//! Cargo build/check/test/clippy semantic reducer.

use super::{diag, diag_rich, normalize_path, ReduceInput, ReduceOutput};
use regex::Regex;
use serde_json::{json, Value};
use std::sync::OnceLock;

fn re_error_header() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?m)^(error(?:\[(?P<code>E\d+)\])?): (?P<msg>.+)$").unwrap()
    })
}

fn re_warning_header() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?m)^(warning(?:\[(?P<code>[^\]]+)\])?): (?P<msg>.+)$").unwrap()
    })
}

fn re_location() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^\s*-->\s+(?P<path>.+):(?P<line>\d+):(?P<col>\d+)\s*$").unwrap()
    })
}

fn re_expected_found() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?i)expected\s+`(?P<expected>[^`]+)`,\s*found\s+`(?P<found>[^`]+)`").unwrap()
    })
}

fn re_test_result() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"test result:\s+(?P<summary>\w+)\.\s+(?P<passed>\d+)\s+passed;\s+(?P<failed>\d+)\s+failed;\s+(?P<ignored>\d+)\s+ignored",
        )
        .unwrap()
    })
}

fn re_finished() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"Finished\s+`?(?P<profile>\w+)`?\s+.+in\s+(?P<elapsed>[\d.]+s)").unwrap()
    })
}

fn re_help_suggest() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^\s*=\s*help:\s*(?P<help>.+)$").unwrap())
}

pub fn reduce(input: &ReduceInput<'_>) -> ReduceOutput {
    let text = input.text;
    let lines: Vec<&str> = text.lines().collect();
    let mut diagnostics = Vec::new();
    let mut i = 0usize;
    while i < lines.len() {
        let line = lines[i];
        let err_caps = re_error_header().captures(line);
        let warn_caps = if err_caps.is_none() {
            re_warning_header().captures(line)
        } else {
            None
        };
        let severity = if err_caps.is_some() { "error" } else { "warning" };
        if let Some(caps) = err_caps.or(warn_caps) {
            let code = caps.name("code").map(|m| m.as_str().to_string());
            let mut message = caps
                .name("msg")
                .map(|m| m.as_str().trim().to_string())
                .unwrap_or_else(|| line.trim().to_string());
            // Skip meta-messages that are not real diagnostics
            let lower_msg = message.to_ascii_lowercase();
            if lower_msg.contains("aborting due to")
                || lower_msg.contains("could not compile")
            {
                i += 1;
                continue;
            }
            let mut path = None;
            let mut line_no = None;
            let mut col = None;
            let mut expected = None;
            let mut found = None;
            let mut suggested_fix = None;

            // Scan following lines for location / expected / help
            let mut j = i + 1;
            while j < lines.len() && j < i + 40 {
                let l = lines[j];
                if re_error_header().is_match(l) || re_warning_header().is_match(l) {
                    break;
                }
                if let Some(loc) = re_location().captures(l) {
                    path = loc
                        .name("path")
                        .map(|m| normalize_path(m.as_str().trim()));
                    line_no = loc.name("line").and_then(|m| m.as_str().parse().ok());
                    col = loc.name("col").and_then(|m| m.as_str().parse().ok());
                }
                if let Some(ef) = re_expected_found().captures(l) {
                    expected = ef.name("expected").map(|m| m.as_str().to_string());
                    found = ef.name("found").map(|m| m.as_str().to_string());
                    if message.len() < 8 {
                        message = format!(
                            "expected `{}`, found `{}`",
                            expected.as_deref().unwrap_or("?"),
                            found.as_deref().unwrap_or("?")
                        );
                    }
                }
                // also check message line itself for expected/found
                if expected.is_none() {
                    if let Some(ef) = re_expected_found().captures(line) {
                        expected = ef.name("expected").map(|m| m.as_str().to_string());
                        found = ef.name("found").map(|m| m.as_str().to_string());
                    }
                }
                if let Some(h) = re_help_suggest().captures(l) {
                    let help = h.name("help").map(|m| m.as_str().trim().to_string());
                    // common pattern: consider using `.to_string()`
                    if let Some(ref help_s) = help {
                        if help_s.contains('`') {
                            if let Some(start) = help_s.find('`') {
                                if let Some(end) = help_s[start + 1..].find('`') {
                                    suggested_fix =
                                        Some(help_s[start + 1..start + 1 + end].to_string());
                                }
                            }
                        }
                    }
                }
                j += 1;
            }

            diagnostics.push(diag_rich(
                "cargo",
                severity,
                message,
                path,
                line_no,
                col,
                code,
                expected,
                found,
                suggested_fix,
            ));
            if diagnostics.len() >= 30 && severity == "warning" {
                // Stop collecting warnings but continue scanning for errors
            }
            i = j;
            continue;
        }
        i += 1;
    }

    let mut stats = std::collections::BTreeMap::new();
    let errors = diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .count();
    let warnings = diagnostics
        .iter()
        .filter(|d| d.severity == "warning")
        .count();
    stats.insert("errors".into(), json!(errors));
    stats.insert("warnings".into(), json!(warnings));

    if let Some(caps) = re_test_result().captures(text) {
        let passed: u64 = caps
            .name("passed")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        let failed: u64 = caps
            .name("failed")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        let ignored: u64 = caps
            .name("ignored")
            .and_then(|m| m.as_str().parse().ok())
            .unwrap_or(0);
        stats.insert("tests_passed".into(), json!(passed));
        stats.insert("tests_failed".into(), json!(failed));
        stats.insert("tests_ignored".into(), json!(ignored));
        if let Some(s) = caps.name("summary") {
            stats.insert("test_result".into(), json!(s.as_str()));
        }
    }
    if let Some(caps) = re_finished().captures(text) {
        if let Some(elapsed) = caps.name("elapsed") {
            stats.insert("elapsed".into(), json!(elapsed.as_str()));
        }
        if let Some(profile) = caps.name("profile") {
            stats.insert("cargo_profile".into(), json!(profile.as_str()));
        }
    }

    let summary = if !input.success || errors > 0 {
        let first = diagnostics
            .iter()
            .find(|d| d.severity == "error")
            .map(|d| {
                let loc = match (&d.path, d.line) {
                    (Some(p), Some(l)) => format!(" at {p}:{l}"),
                    _ => String::new(),
                };
                format!(
                    "{}{}",
                    d.code
                        .as_ref()
                        .map(|c| format!("{c}: "))
                        .unwrap_or_default(),
                    d.message
                ) + &loc
            })
            .unwrap_or_else(|| "cargo failed".into());
        Some(format!("cargo: {errors} error(s), {warnings} warning(s); {first}"))
    } else if let (Some(Value::Number(p)), Some(Value::Number(f))) =
        (stats.get("tests_passed"), stats.get("tests_failed"))
    {
        Some(format!(
            "cargo test: {} passed, {} failed, {} ignored",
            p, f,
            stats
                .get("tests_ignored")
                .cloned()
                .unwrap_or(json!(0))
        ))
    } else if let Some(Value::String(elapsed)) = stats.get("elapsed") {
        Some(format!(
            "cargo finished ok ({} warning(s)) in {}",
            warnings, elapsed
        ))
    } else {
        Some(format!("cargo completed successfully ({} warning(s))", warnings))
    };

    // Keep only errors on failure for model focus; include warnings on success.
    if !input.success {
        diagnostics.retain(|d| d.severity == "error");
        if diagnostics.is_empty() {
            // fallback: first non-empty error-ish line
            for line in lines.iter().rev().take(80) {
                let t = line.trim();
                if t.is_empty() {
                    continue;
                }
                if t.contains("error") || t.contains("FAILED") || t.contains("panic") {
                    diagnostics.push(diag("cargo", "error", t, None, None, None));
                    break;
                }
            }
        }
    } else {
        diagnostics.retain(|d| d.severity == "warning");
        diagnostics.truncate(20);
    }

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
    fn parses_e0308_block() {
        let text = r#"
error[E0308]: mismatched types
  --> src/lib.rs:88:17
   |
88 |     let x: String = "hi";
   |             ------   ^^^^ expected `String`, found `&str`
   |
   = help: try using `.to_string()`
"#;
        let out = reduce(&ReduceInput {
            profile: "cargo",
            text,
            success: false,
            exit_code: 101,
        });
        assert_eq!(out.diagnostics.len(), 1);
        let d = &out.diagnostics[0];
        assert_eq!(d.code.as_deref(), Some("E0308"));
        assert_eq!(d.path.as_deref(), Some("src/lib.rs"));
        assert_eq!(d.line, Some(88));
        assert_eq!(d.expected.as_deref(), Some("String"));
        assert_eq!(d.found.as_deref(), Some("&str"));
        assert!(out.summary.as_ref().unwrap().contains("E0308"));
    }
}
