//! npm/pnpm/yarn install semantic reducer.

use super::{diag, ReduceInput, ReduceOutput};
use regex::Regex;
use serde_json::json;
use std::sync::OnceLock;

fn re_added() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?P<added>\d+)\s+packages?\s+added|(?P<added2>added)\s+(?P<n>\d+)\s+packages?").unwrap()
    })
}

fn re_npm_done() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"added\s+(?P<added>\d+),?\s*removed\s+(?P<removed>\d+),?\s*changed\s+(?P<changed>\d+).+in\s+(?P<elapsed>[\d.]+s)",
        )
        .unwrap()
    })
}

fn re_audited() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"found\s+(?P<count>\d+)\s+vulnerabilit").unwrap()
    })
}

fn re_packages_in() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?P<n>\d+)\s+packages?\s+in\s+(?P<elapsed>[\d.]+s)").unwrap()
    })
}


fn re_added_packages() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"added\s+(?P<n>\d+)\s+packages?").unwrap())
}

fn re_peer() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?i)peer\s+dep").unwrap())
}

pub fn reduce(input: &ReduceInput<'_>) -> ReduceOutput {
    let text = input.text;
    let mut stats = std::collections::BTreeMap::new();
    let mut diagnostics = Vec::new();

    if let Some(caps) = re_npm_done().captures(text) {
        if let Some(a) = caps.name("added").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("added".into(), json!(a));
        }
        if let Some(r) = caps.name("removed").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("removed".into(), json!(r));
        }
        if let Some(c) = caps.name("changed").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("changed".into(), json!(c));
        }
        if let Some(e) = caps.name("elapsed") {
            stats.insert("elapsed".into(), json!(e.as_str()));
        }
    } else if let Some(caps) = re_packages_in().captures(text) {
        if let Some(n) = caps.name("n").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("packages".into(), json!(n));
        }
        if let Some(e) = caps.name("elapsed") {
            stats.insert("elapsed".into(), json!(e.as_str()));
        }
    } else if let Some(caps) = re_added_packages().captures(text) {
        if let Some(n) = caps.name("n").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("added".into(), json!(n));
            stats.insert("packages".into(), json!(n));
        }
    }

    if let Some(caps) = re_audited().captures(text) {
        if let Some(c) = caps.name("count").and_then(|m| m.as_str().parse::<u64>().ok()) {
            stats.insert("vulnerabilities".into(), json!(c));
            if c > 0 {
                diagnostics.push(diag(
                    "npm",
                    "warning",
                    format!("{c} vulnerabilities found"),
                    None,
                    None,
                    None,
                ));
            }
        }
    }

    let peer_lines: Vec<&str> = text
        .lines()
        .filter(|l| re_peer().is_match(l))
        .take(5)
        .collect();
    if !peer_lines.is_empty() {
        stats.insert("peer_dep_issues".into(), json!(peer_lines.len()));
        for l in peer_lines {
            diagnostics.push(diag(
                "npm",
                "warning",
                l.trim(),
                None,
                None,
                None,
            ));
        }
    }

    if !input.success {
        for line in text.lines() {
            let t = line.trim();
            let lower = t.to_ascii_lowercase();
            if lower.contains("npm error")
                || lower.contains("err!")
                || lower.contains("error ")
                || lower.contains("failed")
            {
                if t.len() > 8 {
                    diagnostics.push(diag("npm", "error", t, None, None, None));
                }
            }
            if diagnostics.iter().filter(|d| d.severity == "error").count() >= 15 {
                break;
            }
        }
    }

    let summary = if !input.success {
        let first = diagnostics
            .iter()
            .find(|d| d.severity == "error")
            .map(|d| d.message.clone())
            .unwrap_or_else(|| "npm install failed".into());
        Some(format!("npm install failed: {first}"))
    } else if stats.contains_key("added") {
        let added = stats.get("added").unwrap();
        // Prefer agent-friendly classic phrase when remove/change unknown
        if !stats.contains_key("removed") && !stats.contains_key("changed") {
            Some(format!(
                "added {} packages{}",
                added,
                stats
                    .get("vulnerabilities")
                    .map(|v| format!(", found {v} vulnerabilities"))
                    .unwrap_or_default()
            ))
        } else {
            Some(format!(
                "npm: added {}, removed {}, changed {}{}",
                added,
                stats.get("removed").cloned().unwrap_or(json!(0)),
                stats.get("changed").cloned().unwrap_or(json!(0)),
                stats
                    .get("vulnerabilities")
                    .map(|v| format!(", {v} vulnerabilities"))
                    .unwrap_or_default()
            ))
        }
    } else if let Some(p) = stats.get("packages") {
        Some(format!(
            "npm: {} packages{}",
            p,
            stats
                .get("elapsed")
                .map(|e| format!(" in {e}"))
                .unwrap_or_default()
        ))
    } else {
        Some("npm install completed".into())
    };

    // Cap diagnostics
    diagnostics.truncate(20);

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
    fn summarizes_success() {
        let text = r#"
npm warn deprecated foo@1.0.0
added 120, removed 2, changed 5 packages in 4.2s
found 0 vulnerabilities
"#;
        let out = reduce(&ReduceInput {
            profile: "npm_install",
            text,
            success: true,
            exit_code: 0,
        });
        assert!(out.summary.as_ref().unwrap().contains("added 120"));
        assert_eq!(out.stats.get("vulnerabilities"), Some(&json!(0)));
    }
}
