//! Git status/diff/log semantic reducer — short summaries only.

use super::{ReduceInput, ReduceOutput};
use regex::Regex;
use serde_json::json;
use std::sync::OnceLock;

fn re_branch() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?m)^On branch\s+(?P<branch>\S+)").unwrap())
}

fn re_diff_stat() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(?P<files>\d+)\s+files? changed(?:,\s+(?P<ins>\d+)\s+insertions?\(\+\))?(?:,\s+(?P<del>\d+)\s+deletions?\(-\))?",
        )
        .unwrap()
    })
}

fn re_commit() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?m)^commit\s+(?P<hash>[0-9a-f]{7,40})").unwrap())
}

fn count_status_lines(text: &str) -> (u64, u64, u64, u64) {
    let mut modified = 0u64;
    let mut added = 0u64;
    let mut deleted = 0u64;
    let mut untracked = 0u64;
    for line in text.lines() {
        let t = line.trim_end();
        if t.is_empty() || t.starts_with("On branch") || t.starts_with("Your branch") {
            continue;
        }
        if t.starts_with("Changes") || t.starts_with("Untracked") || t.starts_with("no changes") {
            continue;
        }
        // porcelain: XY path
        if t.len() >= 3 && t.as_bytes()[2] == b' ' {
            let x = t.as_bytes()[0] as char;
            let y = t.as_bytes()[1] as char;
            match (x, y) {
                ('?', '?') => untracked += 1,
                ('A', _) | (_, 'A') => added += 1,
                ('D', _) | (_, 'D') => deleted += 1,
                ('M', _) | (_, 'M') | ('R', _) | (_, 'R') => modified += 1,
                _ => modified += 1,
            }
            continue;
        }
        // human status
        let lower = t.to_ascii_lowercase();
        if lower.contains("modified:") {
            modified += 1;
        } else if lower.contains("new file:") {
            added += 1;
        } else if lower.contains("deleted:") {
            deleted += 1;
        } else if t.starts_with('\t') && !t.contains(':') {
            untracked += 1;
        }
    }
    (modified, added, deleted, untracked)
}

pub fn reduce(input: &ReduceInput<'_>) -> ReduceOutput {
    let text = input.text;
    let mut stats = std::collections::BTreeMap::new();
    let mut diagnostics = Vec::new();

    if !input.success {
        for line in text.lines() {
            let t = line.trim();
            if t.starts_with("fatal:") || t.starts_with("error:") || t.contains("CONFLICT") {
                diagnostics.push(super::diag("git", "error", t, None, None, None));
            }
            if diagnostics.len() >= 10 {
                break;
            }
        }
    }

    let mut branch = None;
    if let Some(caps) = re_branch().captures(text) {
        branch = caps.name("branch").map(|m| m.as_str().to_string());
        if let Some(ref b) = branch {
            stats.insert("branch".into(), json!(b));
        }
    }

    let (modified, added, deleted, untracked) = count_status_lines(text);
    let total_status = modified + added + deleted + untracked;
    if total_status > 0 {
        stats.insert("modified".into(), json!(modified));
        stats.insert("added".into(), json!(added));
        stats.insert("deleted".into(), json!(deleted));
        stats.insert("untracked".into(), json!(untracked));
        stats.insert("changed_files".into(), json!(total_status));
    }

    if let Some(caps) = re_diff_stat().captures(text) {
        let files: u64 = caps
            .name("files")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        let ins: u64 = caps
            .name("ins")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        let del: u64 = caps
            .name("del")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        stats.insert("files_changed".into(), json!(files));
        stats.insert("insertions".into(), json!(ins));
        stats.insert("deletions".into(), json!(del));
    }

    let commits: Vec<String> = re_commit()
        .captures_iter(text)
        .filter_map(|c| c.name("hash").map(|m| m.as_str()[..7.min(m.as_str().len())].to_string()))
        .take(5)
        .collect();
    if !commits.is_empty() {
        stats.insert("recent_commits".into(), json!(commits.len()));
        stats.insert("commit_hashes".into(), json!(commits));
    }

    let summary = if !input.success {
        let msg = diagnostics
            .first()
            .map(|d| d.message.clone())
            .unwrap_or_else(|| "git command failed".into());
        Some(format!("git error: {msg}"))
    } else if stats.contains_key("files_changed") {
        Some(format!(
            "git: {} file(s) changed, +{}, -{}",
            stats.get("files_changed").unwrap(),
            stats.get("insertions").cloned().unwrap_or(json!(0)),
            stats.get("deletions").cloned().unwrap_or(json!(0))
        ))
    } else if total_status > 0 {
        let b = branch.as_deref().unwrap_or("?");
        Some(format!(
            "git status on {b}: {modified} modified, {added} added, {deleted} deleted, {untracked} untracked"
        ))
    } else if !commits.is_empty() {
        Some(format!("git log: {} recent commit(s)", commits.len()))
    } else if let Some(b) = branch {
        Some(format!("git: on branch {b}, clean working tree"))
    } else {
        Some("git: completed".into())
    };

    ReduceOutput {
        summary,
        diagnostics,
        stats,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summarizes_status() {
        let text = r#"On branch main
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
	modified:   src/lib.rs
	modified:   README.md
Untracked files:
	tmp.txt
"#;
        let out = reduce(&ReduceInput {
            profile: "git",
            text,
            success: true,
            exit_code: 0,
        });
        assert!(out.summary.as_ref().unwrap().contains("modified"));
        assert_eq!(out.stats.get("modified"), Some(&json!(2)));
    }

    #[test]
    fn summarizes_diff_stat() {
        let text = " 3 files changed, 40 insertions(+), 2 deletions(-)\n";
        let out = reduce(&ReduceInput {
            profile: "git",
            text,
            success: true,
            exit_code: 0,
        });
        assert!(out.summary.as_ref().unwrap().contains("3"));
    }
}
