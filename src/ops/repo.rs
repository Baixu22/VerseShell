//! Repo intelligence ops (no LSP in v1).

use super::common::{arg_str, arg_u64, audit, err, now, ok, require_capability};
use crate::operation::{Observation, OperationRequest, OperationSpec};
use crate::safety::{self, Effect};
use serde_json::json;
use std::path::Path;
use std::process::Command;

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "repo.search",
            mcp_name: "repo_search",
            description: "Search workspace text files for a query. Default max_items=50.",
            effect: "repo.search",
            capability: "file.read",
            input_schema: schema_search,
            handler: execute_search,
        },
        OperationSpec {
            name: "repo.changed_files",
            mcp_name: "repo_changed_files",
            description: "List git changed files via status --porcelain.",
            effect: "repo.git",
            capability: "file.read",
            input_schema: schema_empty,
            handler: execute_changed,
        },
        OperationSpec {
            name: "repo.summary",
            mcp_name: "repo_summary",
            description: "Short repo summary: branch, dirty count, top-level entries.",
            effect: "repo.summary",
            capability: "file.read",
            input_schema: schema_empty,
            handler: execute_summary,
        },
    ]
}

fn schema_empty() -> serde_json::Value {
    json!({"type":"object","properties":{}})
}
fn schema_search() -> serde_json::Value {
    json!({
        "type":"object",
        "required":["query"],
        "properties":{
            "query":{"type":"string"},
            "glob":{"type":"string"},
            "context_lines":{"type":"integer","default":2},
            "max_items":{"type":"integer","default":50}
        }
    })
}

fn execute_search(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") { return o; }
    let query = match arg_str(&req.args, "query") {
        Some(q) if !q.is_empty() => q,
        _ => return err(req, "repo", "E_BAD_ARG", "query is required", start),
    };
    let glob = arg_str(&req.args, "glob");
    let context_lines = arg_u64(&req.args, "context_lines", 2).min(10) as usize;
    let max_items = arg_u64(&req.args, "max_items", 50).clamp(1, 500) as usize;
    let root = safety::workspace_root();
    let mut matches = Vec::new();
    let mut scanned = 0u64;
    walk_search(&root, &root, glob.as_deref(), &query, context_lines, max_items, &mut matches, &mut scanned);
    audit("repo.search", Effect::ReadLocal, "allow", &query, json!({"matches": matches.len(), "scanned": scanned}));
    ok(
        req,
        "repo",
        json!({
            "query": query,
            "glob": glob,
            "scanned_files": scanned,
            "match_count": matches.len(),
            "truncated": matches.len() >= max_items,
            "matches": matches
        }),
        &["repo.search"],
        &["file.read"],
        start,
    )
}

fn walk_search(
    root: &Path,
    dir: &Path,
    glob: Option<&str>,
    query: &str,
    context_lines: usize,
    max_items: usize,
    matches: &mut Vec<serde_json::Value>,
    scanned: &mut u64,
) {
    if matches.len() >= max_items {
        return;
    }
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        if matches.len() >= max_items {
            break;
        }
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if name == ".git" || name == "target" || name == "node_modules" || name == ".ae" {
            continue;
        }
        if path.is_dir() {
            walk_search(root, &path, glob, query, context_lines, max_items, matches, scanned);
            continue;
        }
        if let Some(g) = glob {
            if !glob_match(&name, g) && !glob_match(&path.to_string_lossy(), g) {
                continue;
            }
        }
        // Skip likely binary / huge files
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        if meta.len() > 1_000_000 {
            continue;
        }
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(_) => continue,
        };
        *scanned += 1;
        let lines: Vec<&str> = text.lines().collect();
        for (idx, line) in lines.iter().enumerate() {
            if matches.len() >= max_items {
                break;
            }
            if line.contains(query) {
                let from = idx.saturating_sub(context_lines);
                let to = (idx + context_lines + 1).min(lines.len());
                let rel = path
                    .strip_prefix(root)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .replace('\\', "/");
                matches.push(json!({
                    "path": rel,
                    "line": idx + 1,
                    "text": *line,
                    "context": lines[from..to].join("\n")
                }));
            }
        }
    }
}

fn glob_match(name: &str, pattern: &str) -> bool {
    // Minimal glob: supports `*.ext` and substring `*foo*`
    if pattern == "*" {
        return true;
    }
    if let Some(ext) = pattern.strip_prefix("*.") {
        return name.ends_with(&format!(".{ext}")) || name.ends_with(ext);
    }
    if pattern.starts_with('*') && pattern.ends_with('*') && pattern.len() > 2 {
        let mid = &pattern[1..pattern.len() - 1];
        return name.contains(mid);
    }
    if let Some(suf) = pattern.strip_prefix('*') {
        return name.ends_with(suf);
    }
    if let Some(pre) = pattern.strip_suffix('*') {
        return name.starts_with(pre);
    }
    name == pattern || name.contains(pattern)
}

fn execute_changed(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") { return o; }
    let root = safety::workspace_root();
    let output = Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(&root)
        .output();
    match output {
        Ok(out) if out.status.success() => {
            let text = String::from_utf8_lossy(&out.stdout);
            let mut files = Vec::new();
            for line in text.lines() {
                if line.len() < 4 {
                    continue;
                }
                let status = line[..2].trim().to_string();
                let path = line[3..].trim().to_string();
                files.push(json!({"status": status, "path": path}));
            }
            ok(
                req,
                "repo",
                json!({"files": files, "count": files.len()}),
                &["repo.git"],
                &["file.read"],
                start,
            )
        }
        Ok(out) => {
            let err_msg = String::from_utf8_lossy(&out.stderr).trim().to_string();
            err(
                req,
                "repo",
                "E_GIT",
                if err_msg.is_empty() {
                    "git status failed".into()
                } else {
                    err_msg
                },
                start,
            )
        }
        Err(e) => err(req, "repo", "E_GIT", format!("git not available: {e}"), start),
    }
}

fn execute_summary(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") { return o; }
    let root = safety::workspace_root();
    let branch = git_out(&root, &["rev-parse", "--abbrev-ref", "HEAD"]);
    let dirty = git_out(&root, &["status", "--porcelain"])
        .map(|s| s.lines().filter(|l| !l.is_empty()).count())
        .unwrap_or(0);
    let mut top = Vec::new();
    if let Ok(rd) = std::fs::read_dir(&root) {
        for e in rd.flatten().take(40) {
            let name = e.file_name().to_string_lossy().to_string();
            let kind = if e.path().is_dir() { "dir" } else { "file" };
            top.push(json!({"name": name, "kind": kind}));
        }
    }
    ok(
        req,
        "repo",
        json!({
            "workspace": crate::artifact::display_path(&root),
            "branch": branch,
            "dirty_files": dirty,
            "top_level": top
        }),
        &["repo.summary"],
        &["file.read"],
        start,
    )
}

fn git_out(root: &Path, args: &[&str]) -> Option<String> {
    let out = Command::new("git").args(args).current_dir(root).output().ok()?;
    if !out.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
}
