//! File ACI operations: view, edit, hash, remove (with trash).

use super::common::{
    arg_bool, arg_str, arg_u64, audit, check_expected_hash, content_hash_str, err, err_data,
    guard_delete, guard_read, guard_write, now, numbered_lines, ok, read_text_file,
    require_capability, resolve_workspace_path, write_text_file,
};
use super::trash;
use crate::operation::{Diagnostic, Observation, OperationRequest, OperationSpec, SuggestedAction};
use crate::safety::{self, Effect, Mode};
use crate::tx;
use serde_json::{json, Value};
use std::path::Path;

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "file.read_range",
            mcp_name: "file_read_range",
            description:
                "Read a line range from a file with content hash. Default hard cap 500 lines.",
            effect: "fs.read",
            capability: "file.read",
            input_schema: schema_read_range,
            handler: execute_read_range,
        },
        OperationSpec {
            name: "file.view",
            mcp_name: "file_view",
            description:
                "View a window of lines around a cursor with total_lines and content hash.",
            effect: "fs.read",
            capability: "file.read",
            input_schema: schema_view,
            handler: execute_view,
        },
        OperationSpec {
            name: "file.hash",
            mcp_name: "file_hash",
            description:
                "Return sha256 content hash of a file for expected_hash optimistic concurrency.",
            effect: "fs.read",
            capability: "file.read",
            input_schema: schema_path_only,
            handler: execute_hash,
        },
        OperationSpec {
            name: "file.replace_exact",
            mcp_name: "file_replace_exact",
            description:
                "Replace exactly one unique occurrence of old with new. Optional expected_hash.",
            effect: "fs.write",
            capability: "file.write",
            input_schema: schema_replace,
            handler: execute_replace_exact,
        },
        OperationSpec {
            name: "file.apply_patch",
            mcp_name: "file_apply_patch",
            description: "Apply ordered find/replace patches. Optional expected_hash.",
            effect: "fs.write",
            capability: "file.write",
            input_schema: schema_patch,
            handler: execute_apply_patch,
        },
        OperationSpec {
            name: "file.edit_range",
            mcp_name: "file_edit_range",
            description:
                "Replace a line range with replacement text. Optional expected_hash and check.",
            effect: "fs.write",
            capability: "file.write",
            input_schema: schema_edit_range,
            handler: execute_edit_range,
        },
        OperationSpec {
            name: "file.diff",
            mcp_name: "file_diff",
            description:
                "Unified-style line diff between file content and provided new_text (or empty).",
            effect: "fs.read",
            capability: "file.read",
            input_schema: schema_diff,
            handler: execute_diff,
        },
        OperationSpec {
            name: "file.write",
            mcp_name: "file_write",
            description: "Create or overwrite a file. Returns path and content_hash.",
            effect: "fs.write",
            capability: "file.write",
            input_schema: schema_write,
            handler: execute_write,
        },
        OperationSpec {
            name: "file.remove",
            mcp_name: "file_remove",
            description: "Remove a path. In agent mode moves to trash and returns restore_token.",
            effect: "fs.delete",
            capability: "file.delete",
            input_schema: schema_remove,
            handler: execute_remove,
        },
    ]
}

fn schema_path_only() -> Value {
    json!({"type":"object","required":["path"],"properties":{"path":{"type":"string"}}})
}
fn schema_read_range() -> Value {
    json!({
        "type":"object","required":["path","start_line","end_line"],
        "properties":{
            "path":{"type":"string"},
            "start_line":{"type":"integer","minimum":1},
            "end_line":{"type":"integer","minimum":1},
            "max_lines":{"type":"integer","default":500}
        }
    })
}
fn schema_view() -> Value {
    json!({
        "type":"object","required":["path"],
        "properties":{
            "path":{"type":"string"},
            "cursor":{"type":"integer","default":1},
            "window":{"type":"integer","default":80}
        }
    })
}
fn schema_replace() -> Value {
    json!({
        "type":"object","required":["path","old","new"],
        "properties":{
            "path":{"type":"string"},
            "old":{"type":"string"},
            "new":{"type":"string"},
            "expected_hash":{"type":"string"}
        }
    })
}
fn schema_patch() -> Value {
    json!({
        "type":"object","required":["path","patches"],
        "properties":{
            "path":{"type":"string"},
            "expected_hash":{"type":"string"},
            "patches":{"type":"array","items":{"type":"object","properties":{
                "old":{"type":"string"},"new":{"type":"string"},
                "find":{"type":"string"},"replace":{"type":"string"}
            }}}
        }
    })
}
fn schema_edit_range() -> Value {
    json!({
        "type":"object","required":["path","start_line","end_line","replacement"],
        "properties":{
            "path":{"type":"string"},
            "start_line":{"type":"integer","minimum":1},
            "end_line":{"type":"integer","minimum":1},
            "replacement":{"type":"string"},
            "expected_hash":{"type":"string"},
            "check":{"type":"boolean","default":false}
        }
    })
}
fn schema_diff() -> Value {
    json!({
        "type":"object","required":["path"],
        "properties":{
            "path":{"type":"string"},
            "new_text":{"type":"string"},
            "max_lines":{"type":"integer","default":200}
        }
    })
}
fn schema_write() -> Value {
    json!({
        "type":"object","required":["path","content"],
        "properties":{
            "path":{"type":"string"},
            "content":{"type":"string"}
        }
    })
}
fn schema_remove() -> Value {
    json!({
        "type":"object","required":["path"],
        "properties":{
            "path":{"type":"string"},
            "hard":{"type":"boolean","default":false,"description":"Force hard delete even in agent mode"}
        }
    })
}

fn execute_read_range(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let start_line = arg_u64(&req.args, "start_line", 1).max(1) as usize;
    let end_line =
        arg_u64(&req.args, "end_line", start_line as u64).max(start_line as u64) as usize;
    let max_lines = arg_u64(&req.args, "max_lines", 500).clamp(1, 2000) as usize;
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_read(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    let hash = content_hash_str(&text);
    let all: Vec<&str> = text.lines().collect();
    let total = all.len();
    let from = start_line.saturating_sub(1).min(total);
    let mut to = end_line.min(total);
    if to.saturating_sub(from) > max_lines {
        to = from + max_lines;
    }
    let slice = &all[from..to];
    audit(
        "file.read_range",
        Effect::ReadLocal,
        "allow",
        &path,
        json!({"start": start_line, "end": end_line}),
    );
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "start_line": from + 1,
            "end_line": to,
            "total_lines": total,
            "content_hash": hash,
            "truncated": to < end_line.min(total) || (end_line.saturating_sub(start_line) + 1) > max_lines,
            "lines": numbered_lines(slice, from + 1)
        }),
        &["fs.read"],
        &["file.read"],
        start,
    )
}

fn execute_view(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let cursor = arg_u64(&req.args, "cursor", 1).max(1) as usize;
    let window = arg_u64(&req.args, "window", 80).clamp(1, 500) as usize;
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_read(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    let hash = content_hash_str(&text);
    let all: Vec<&str> = text.lines().collect();
    let half = window / 2;
    let mut from = cursor.saturating_sub(1).saturating_sub(half);
    if from >= all.len() && !all.is_empty() {
        from = all.len().saturating_sub(window);
    }
    let to = (from + window).min(all.len());
    let slice = if all.is_empty() {
        &[][..]
    } else {
        &all[from..to]
    };
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "cursor": cursor,
            "window": window,
            "start_line": if all.is_empty() { 0 } else { from + 1 },
            "end_line": to,
            "total_lines": all.len(),
            "content_hash": hash,
            "lines": numbered_lines(slice, if all.is_empty() { 0 } else { from + 1 })
        }),
        &["fs.read"],
        &["file.read"],
        start,
    )
}

fn execute_hash(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_read(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let bytes = match std::fs::read(&resolved) {
        Ok(b) => b,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e.to_string(), start),
    };
    let hash = super::common::content_hash(&bytes);
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "content_hash": hash,
            "bytes": bytes.len()
        }),
        &["fs.read"],
        &["file.read"],
        start,
    )
}

fn execute_replace_exact(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let old = match arg_str(&req.args, "old") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "old is required", start),
    };
    let new = match arg_str(&req.args, "new") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "new is required", start),
    };
    let expected = arg_str(&req.args, "expected_hash");
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_write(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    if let Err(e) = check_expected_hash(&text, expected.as_deref()) {
        return err(req, "file", "E_STALE_HASH", e, start);
    }
    let count = text.matches(&old).count();
    if count == 0 {
        return err(
            req,
            "file",
            "E_NOT_FOUND",
            "old text not found in file",
            start,
        );
    }
    if count > 1 {
        return err(
            req,
            "file",
            "E_AMBIGUOUS",
            format!("old text matches {count} times; must be unique"),
            start,
        );
    }
    let updated = text.replacen(&old, &new, 1);
    tx::snapshot(&resolved.to_string_lossy());
    if let Err(e) = write_text_file(&resolved, &updated) {
        return err(req, "file", "E_WRITE", e, start);
    }
    let new_hash = content_hash_str(&updated);
    audit(
        "file.replace_exact",
        Effect::WriteLocal,
        "completed",
        &path,
        json!({"content_hash": new_hash}),
    );
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "applied": true,
            "replacements": 1,
            "content_hash": new_hash
        }),
        &["fs.write"],
        &["file.write"],
        start,
    )
}

fn execute_apply_patch(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let patches = match req.args.get("patches").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return err(req, "file", "E_BAD_ARG", "patches array is required", start),
    };
    let expected = arg_str(&req.args, "expected_hash");
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_write(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let mut text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    if let Err(e) = check_expected_hash(&text, expected.as_deref()) {
        return err(req, "file", "E_STALE_HASH", e, start);
    }
    let mut applied = Vec::new();
    let mut failed = Vec::new();
    for (i, patch) in patches.iter().enumerate() {
        let old = patch
            .get("old")
            .or_else(|| patch.get("find"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let new = patch
            .get("new")
            .or_else(|| patch.get("replace"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if old.is_empty() {
            failed.push(json!({"index": i, "error": "missing old/find"}));
            continue;
        }
        if text.contains(old) {
            let count = text.matches(old).count();
            text = text.replace(old, new);
            applied.push(json!({"index": i, "count": count}));
        } else {
            failed.push(json!({"index": i, "error": "not found"}));
        }
    }
    if failed.is_empty() {
        tx::snapshot(&resolved.to_string_lossy());
        if let Err(e) = write_text_file(&resolved, &text) {
            return err(req, "file", "E_WRITE", e, start);
        }
    }
    let new_hash = content_hash_str(&text);
    let success = failed.is_empty();
    if success {
        audit(
            "file.apply_patch",
            Effect::WriteLocal,
            "completed",
            &path,
            json!({"applied": applied.len()}),
        );
        ok(
            req,
            "file",
            json!({
                "path": crate::artifact::display_path(&resolved),
                "applied": true,
                "patches_applied": applied,
                "patches_failed": failed,
                "content_hash": new_hash
            }),
            &["fs.write"],
            &["file.write"],
            start,
        )
    } else {
        err_data(
            req,
            "file",
            "E_PATCH_FAILED",
            "one or more patches failed; file not modified",
            json!({
                "path": crate::artifact::display_path(&resolved),
                "applied": false,
                "patches_applied": applied,
                "patches_failed": failed,
                "content_hash": content_hash_str(&read_text_file(&resolved).unwrap_or_default())
            }),
            Vec::new(),
            Vec::new(),
            start,
        )
    }
}

fn execute_edit_range(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let start_line = arg_u64(&req.args, "start_line", 1).max(1) as usize;
    let end_line =
        arg_u64(&req.args, "end_line", start_line as u64).max(start_line as u64) as usize;
    let replacement = arg_str(&req.args, "replacement").unwrap_or_default();
    let expected = arg_str(&req.args, "expected_hash");
    let check = arg_bool(&req.args, "check", false);
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_write(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    if let Err(e) = check_expected_hash(&text, expected.as_deref()) {
        return err(req, "file", "E_STALE_HASH", e, start);
    }
    let lines: Vec<String> = text.lines().map(|s| s.to_string()).collect();
    let total = lines.len();
    if start_line > total + 1 {
        return err(
            req,
            "file",
            "E_BAD_ARG",
            format!("start_line {start_line} beyond end of file ({total} lines)"),
            start,
        );
    }
    let from = start_line.saturating_sub(1).min(total);
    let to = end_line.min(total);
    let repl_lines: Vec<String> = if replacement.is_empty() {
        Vec::new()
    } else {
        replacement.lines().map(|s| s.to_string()).collect()
    };
    let mut new_lines = Vec::new();
    new_lines.extend_from_slice(&lines[..from]);
    new_lines.extend(repl_lines);
    if to < lines.len() {
        new_lines.extend_from_slice(&lines[to..]);
    }
    let mut updated = new_lines.join("\n");
    if text.ends_with('\n') && !updated.ends_with('\n') {
        updated.push('\n');
    }

    if check {
        if let Some(diag) = lint_check(&resolved, &updated) {
            return err_data(
                req,
                "file",
                "E_LINT_FAILED",
                "edit would introduce syntax/check errors",
                json!({
                    "path": crate::artifact::display_path(&resolved),
                    "applied": false,
                    "content_hash": content_hash_str(&text)
                }),
                vec![diag],
                vec![SuggestedAction {
                    op: "file.read_range".into(),
                    args: json!({
                        "path": path,
                        "start_line": start_line.saturating_sub(5).max(1),
                        "end_line": end_line + 5
                    }),
                }],
                start,
            );
        }
    }

    tx::snapshot(&resolved.to_string_lossy());
    if let Err(e) = write_text_file(&resolved, &updated) {
        return err(req, "file", "E_WRITE", e, start);
    }
    let new_hash = content_hash_str(&updated);
    audit(
        "file.edit_range",
        Effect::WriteLocal,
        "completed",
        &path,
        json!({"content_hash": new_hash}),
    );
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "applied": true,
            "start_line": start_line,
            "end_line": end_line,
            "content_hash": new_hash
        }),
        &["fs.write"],
        &["file.write"],
        start,
    )
}

fn lint_check(path: &Path, content: &str) -> Option<Diagnostic> {
    let ext = path.extension().and_then(|s| s.to_str()).unwrap_or("");
    match ext {
        "py" => {
            // Best-effort: python -m py_compile via temp file
            let tmp = path.with_extension("ae_lint.py");
            if std::fs::write(&tmp, content).is_err() {
                return None;
            }
            let out = std::process::Command::new("python")
                .args(["-m", "py_compile"])
                .arg(&tmp)
                .output();
            let _ = std::fs::remove_file(&tmp);
            let _ = std::fs::remove_file(tmp.with_extension("pyc"));
            match out {
                Ok(o) if !o.status.success() => {
                    let msg = String::from_utf8_lossy(&o.stderr).trim().to_string();
                    Some(Diagnostic {
                        tool: "py_compile".into(),
                        severity: "error".into(),
                        message: if msg.is_empty() {
                            "python syntax error".into()
                        } else {
                            msg
                        },
                        path: Some(crate::artifact::display_path(path)),
                        line: None,
                        column: None,
                        code: None,
                        expected: None,
                        found: None,
                        suggested_fix: None,
                    })
                }
                _ => None,
            }
        }
        "json" => match serde_json::from_str::<Value>(content) {
            Ok(_) => None,
            Err(e) => Some(Diagnostic {
                tool: "json".into(),
                severity: "error".into(),
                message: e.to_string(),
                path: Some(crate::artifact::display_path(path)),
                line: None,
                column: None,
                code: None,
                expected: None,
                found: None,
                suggested_fix: None,
            }),
        },
        _ => None,
    }
}

fn execute_diff(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let new_text = arg_str(&req.args, "new_text").unwrap_or_default();
    let max_lines = arg_u64(&req.args, "max_lines", 200).clamp(1, 2000) as usize;
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_read(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    let old_text = match read_text_file(&resolved) {
        Ok(t) => t,
        Err(e) => return err(req, "file", "E_NOT_FOUND", e, start),
    };
    let old_lines: Vec<&str> = old_text.lines().collect();
    let new_lines: Vec<&str> = new_text.lines().collect();
    let mut diff_lines = Vec::new();
    let max_i = old_lines.len().max(new_lines.len());
    for i in 0..max_i {
        let o = old_lines.get(i).copied();
        let n = new_lines.get(i).copied();
        match (o, n) {
            (Some(a), Some(b)) if a == b => {
                diff_lines.push(format!(" {a}"));
            }
            (Some(a), Some(b)) => {
                diff_lines.push(format!("-{a}"));
                diff_lines.push(format!("+{b}"));
            }
            (Some(a), None) => diff_lines.push(format!("-{a}")),
            (None, Some(b)) => diff_lines.push(format!("+{b}")),
            (None, None) => {}
        }
        if diff_lines.len() >= max_lines {
            break;
        }
    }
    let truncated = diff_lines.len() >= max_lines && max_i > max_lines;
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "content_hash": content_hash_str(&old_text),
            "truncated": truncated,
            "diff": diff_lines
        }),
        &["fs.read"],
        &["file.read"],
        start,
    )
}

fn execute_write(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "write") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let content = match arg_str(&req.args, "content") {
        Some(c) => c.to_string(),
        None => return err(req, "file", "E_BAD_ARG", "content is required", start),
    };
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if let Err(e) = guard_write(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    if let Err(e) = write_text_file(&resolved, &content) {
        return err(req, "file", "E_WRITE_FAILED", e, start);
    }
    let hash = content_hash_str(&content);
    audit(
        "file.write",
        Effect::WriteLocal,
        "allow",
        &path,
        json!({"bytes": content.len()}),
    );
    ok(
        req,
        "file",
        json!({
            "path": crate::artifact::display_path(&resolved),
            "content_hash": hash,
            "bytes_written": content.len()
        }),
        &["fs.write"],
        &["file.write"],
        start,
    )
}

fn execute_remove(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "rm") {
        return o;
    }
    let path = match arg_str(&req.args, "path") {
        Some(p) => p,
        None => return err(req, "file", "E_BAD_ARG", "path is required", start),
    };
    let hard = arg_bool(&req.args, "hard", false);
    let resolved = match resolve_workspace_path(&path) {
        Ok(p) => p,
        Err(e) => return err(req, "file", "E_OUTSIDE_WORKSPACE", e, start),
    };
    if !resolved.exists() {
        return err(
            req,
            "file",
            "E_NOT_FOUND",
            format!("path not found: {path}"),
            start,
        );
    }
    let use_trash = !hard && safety::current_mode() == Mode::Agent;
    // Trash is reversible -> WriteLocal; hard delete is Destructive (may need approval).
    if use_trash {
        if let Err(e) = guard_write(&resolved.to_string_lossy()) {
            return err(req, "file", "E_POLICY", e, start);
        }
    } else if let Err(e) = guard_delete(&resolved.to_string_lossy()) {
        return err(req, "file", "E_POLICY", e, start);
    }
    if use_trash {
        match trash::move_to_trash(&resolved) {
            Ok(token) => {
                audit(
                    "file.remove",
                    Effect::WriteLocal,
                    "moved_to_trash",
                    &path,
                    json!({"restore_token": token, "tx_id": tx::status().map(|s| s.0)}),
                );
                ok(
                    req,
                    "file",
                    json!({
                        "path": crate::artifact::display_path(&resolved),
                        "action": "moved_to_trash",
                        "restore_token": token
                    }),
                    &["fs.delete"],
                    &["file.delete"],
                    start,
                )
            }
            Err(e) => err(req, "file", "E_TRASH", e, start),
        }
    } else {
        tx::snapshot(&resolved.to_string_lossy());
        let result = if resolved.is_dir() {
            std::fs::remove_dir_all(&resolved)
        } else {
            std::fs::remove_file(&resolved)
        };
        match result {
            Ok(()) => {
                audit(
                    "file.remove",
                    Effect::Destructive,
                    "deleted",
                    &path,
                    json!({}),
                );
                ok(
                    req,
                    "file",
                    json!({
                        "path": crate::artifact::display_path(&resolved),
                        "action": "deleted"
                    }),
                    &["fs.delete"],
                    &["file.delete"],
                    start,
                )
            }
            Err(e) => err(req, "file", "E_DELETE", e.to_string(), start),
        }
    }
}
