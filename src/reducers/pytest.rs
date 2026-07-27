//! Pytest semantic reducer.

use super::{diag, normalize_path, ReduceInput, ReduceOutput};
use regex::Regex;
use serde_json::json;
use std::sync::OnceLock;

fn re_failed_header() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^_{5,}\s+(?P<node>.+?)\s+_{5,}\s*$").unwrap())
}

fn re_file_line() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^(?P<path>[^:\s].*?\.py):(?P<line>\d+):(?P<rest>.*)$").unwrap())
}

fn re_assert() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^\s*assert\s+(?P<body>.+)$").unwrap())
}

fn re_e_line() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^E\s+(?P<body>.+)$").unwrap())
}

fn re_summary() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(?P<failed>\d+)\s+failed(?:,\s+(?P<passed>\d+)\s+passed)?(?:,\s+(?P<skipped>\d+)\s+skipped)?",
        )
        .unwrap()
    })
}

fn re_passed_only() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?P<passed>\d+)\s+passed").unwrap())
}

pub fn reduce(input: &ReduceInput<'_>) -> ReduceOutput {
    let text = input.text;
    let lines: Vec<&str> = text.lines().collect();
    let mut diagnostics = Vec::new();
    let mut i = 0usize;

    while i < lines.len() {
        if let Some(caps) = re_failed_header().captures(lines[i]) {
            let node = caps
                .name("node")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_default();
            let mut path = None;
            let mut line_no = None;
            let mut message = format!("FAILED {node}");
            let mut assert_line = None;

            let mut j = i + 1;
            while j < lines.len() && j < i + 80 {
                let l = lines[j];
                if re_failed_header().is_match(l)
                    || l.starts_with("=====")
                    || l.starts_with("-----") && l.contains("short test")
                {
                    break;
                }
                if let Some(fc) = re_file_line().captures(l) {
                    path = fc.name("path").map(|m| normalize_path(m.as_str().trim()));
                    line_no = fc.name("line").and_then(|m| m.as_str().parse().ok());
                }
                if let Some(a) = re_assert().captures(l) {
                    assert_line = a.name("body").map(|m| m.as_str().trim().to_string());
                }
                if let Some(e) = re_e_line().captures(l) {
                    let body = e.name("body").map(|m| m.as_str().trim()).unwrap_or("");
                    if !body.is_empty() {
                        message = body.to_string();
                    }
                }
                j += 1;
            }

            if let Some(a) = assert_line {
                if message.starts_with("FAILED") {
                    message = format!("assert {a}");
                }
            }

            diagnostics.push(diag("pytest", "error", message, path, line_no, None));
            // stash node in stats later via message prefix if needed
            if diagnostics.len() >= 20 {
                break;
            }
            i = j;
            continue;
        }
        i += 1;
    }

    // Fallback: FAILED test_name lines
    if diagnostics.is_empty() {
        for line in lines {
            let t = line.trim();
            if t.starts_with("FAILED ") {
                diagnostics.push(diag("pytest", "error", t, None, None, None));
            }
            if diagnostics.len() >= 20 {
                break;
            }
        }
    }

    let mut stats = std::collections::BTreeMap::new();
    let mut failed = 0u64;
    let mut passed = 0u64;
    let mut skipped = 0u64;
    if let Some(caps) = re_summary().captures(text) {
        failed = caps
            .name("failed")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        passed = caps
            .name("passed")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        skipped = caps
            .name("skipped")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
    } else if let Some(caps) = re_passed_only().captures(text) {
        passed = caps
            .name("passed")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
    }
    if failed == 0 && !input.success {
        failed = diagnostics.len() as u64;
    }
    stats.insert("failed".into(), json!(failed));
    stats.insert("passed".into(), json!(passed));
    stats.insert("skipped".into(), json!(skipped));
    stats.insert("errors".into(), json!(diagnostics.len()));

    let summary = if !input.success || failed > 0 {
        let first = diagnostics
            .first()
            .map(|d| {
                let loc = match (&d.path, d.line) {
                    (Some(p), Some(l)) => format!(" ({p}:{l})"),
                    _ => String::new(),
                };
                format!("{}{loc}", d.message)
            })
            .unwrap_or_else(|| "pytest failed".into());
        Some(format!(
            "pytest: {failed} failed, {passed} passed, {skipped} skipped; {first}"
        ))
    } else {
        Some(format!("pytest: {passed} passed, {skipped} skipped"))
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
    fn parses_failed_assert() {
        let text = r#"
=========================== FAILURES ===========================
___________________________ test_add ___________________________
tests/test_math.py:10: in test_add
    assert add(1, 1) == 3
E   assert 2 == 3
=========================== short test summary info ============================
FAILED tests/test_math.py::test_add - assert 2 == 3
======================== 1 failed, 2 passed in 0.05s ========================
"#;
        let out = reduce(&ReduceInput {
            profile: "pytest",
            text,
            success: false,
            exit_code: 1,
        });
        assert!(!out.diagnostics.is_empty());
        let d = &out.diagnostics[0];
        assert!(d.path.as_deref().unwrap_or("").contains("test_math.py"));
        assert_eq!(d.line, Some(10));
        assert!(out.summary.as_ref().unwrap().contains("failed"));
    }
}
