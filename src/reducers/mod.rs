//! Command-aware semantic observation reducers.
//!
//! Profile-specific parsers turn raw tool output into structured
//! `summary` + `diagnostics` + `stats` for verseshell.observation/v1.

mod cargo;
mod git;
mod npm;
mod pytest;

use crate::operation::Diagnostic;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::sync::OnceLock;

/// Input to a semantic reducer.
#[derive(Debug, Clone)]
pub struct ReduceInput<'a> {
    pub profile: &'a str,
    pub text: &'a str,
    pub success: bool,
    pub exit_code: i32,
}

/// Structured reduction result shared by all profiles.
#[derive(Debug, Clone, Default)]
pub struct ReduceOutput {
    pub summary: Option<String>,
    pub diagnostics: Vec<Diagnostic>,
    pub stats: BTreeMap<String, Value>,
}

impl ReduceOutput {
    pub fn stats_json(&self) -> Value {
        let mut map = Map::new();
        for (k, v) in &self.stats {
            map.insert(k.clone(), v.clone());
        }
        Value::Object(map)
    }
}

/// Run the best-matching semantic reducer for `profile`.
/// Returns `None` when no specialized reducer applies (caller falls back).
pub fn reduce_semantic(input: &ReduceInput<'_>) -> Option<ReduceOutput> {
    match input.profile {
        "cargo" => Some(cargo::reduce(input)),
        "pytest" => Some(pytest::reduce(input)),
        "git" => Some(git::reduce(input)),
        "npm_install" => Some(npm::reduce(input)),
        _ => None,
    }
}

/// Convenience for tests and benches: reduce with exit_code derived from success.
pub fn reduce_for_profile(profile: &str, text: &str, success: bool) -> Option<ReduceOutput> {
    reduce_semantic(&ReduceInput {
        profile,
        text,
        success,
        exit_code: if success { 0 } else { 1 },
    })
}

fn re_location_in_message() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(?P<path>[\w./\\-]+\.(?:rs|py|js|mjs|ts|tsx|jsx|go|java|rb|c|h|cpp|hpp|cs|php|swift|kt|toml|json|yaml|yml|ini|cfg|sql|sh|ps1|md|txt))(?::(?P<line>\d+))?",
        )
        .unwrap()
    })
}

/// Recover a failure-site location from a diagnostic message when the profile
/// parser could not structure it: panic locations (`src/engine.rs:42:9`), merge
/// conflicts (`Merge conflict in src/config.rs`), pytest `FAILED file::case`.
///
/// Missing-path failures are excluded on purpose: for `ENOENT` / `no such file`
/// / `not a git repository` the path is precisely what does not exist, so a
/// `file.view` step would fail immediately and is worse than no playbook.
fn recover_location(message: &str) -> Option<(String, Option<u64>)> {
    let lower = message.to_ascii_lowercase();
    if ["enoent", "no such file", "not found", "not a git repository"]
        .iter()
        .any(|needle| lower.contains(needle))
    {
        return None;
    }
    let caps = re_location_in_message().captures(message)?;
    let path = caps.name("path")?.as_str().to_string();
    let line = caps
        .name("line")
        .and_then(|m| m.as_str().parse::<u64>().ok());
    Some((path, line))
}

/// Build a short repair playbook from diagnostics: view → exact edit → rerun.
pub fn suggested_from_diagnostics(
    profile: &str,
    diagnostics: &[Diagnostic],
) -> Vec<crate::operation::SuggestedAction> {
    use crate::operation::SuggestedAction;
    let mut out = Vec::new();
    for d in diagnostics.iter().take(5) {
        // Structured location first; fall back to the message so classes the
        // parser could not anchor still get a usable playbook.
        let located = match d.path.clone() {
            Some(path) => Some((path, d.line)),
            None => recover_location(&d.message),
        };
        let Some((path, line)) = located else {
            continue;
        };
        let mut view_args = serde_json::Map::new();
        view_args.insert("path".into(), json!(path));
        if let Some(line) = line {
            view_args.insert("cursor".into(), json!(line));
            view_args.insert("window".into(), json!(40));
        }
        out.push(SuggestedAction {
            op: "file.view".into(),
            args: Value::Object(view_args),
        });
        // Prefer a concrete replace sketch when we know expected/found or a fix.
        if let Some(fix) = d.suggested_fix.as_ref().filter(|s| !s.trim().is_empty()) {
            out.push(SuggestedAction {
                op: "file.replace_exact".into(),
                args: json!({
                    "path": path.clone(),
                    "old": d.found.clone().unwrap_or_else(|| "<code at failure site>".into()),
                    "new": fix,
                    "expected_hash": "<from file.view hash or content_hash>"
                }),
            });
        } else if let (Some(expected), Some(found)) = (d.expected.as_ref(), d.found.as_ref()) {
            out.push(SuggestedAction {
                op: "file.replace_exact".into(),
                args: json!({
                    "path": path.clone(),
                    "old": found,
                    "new": expected,
                    "expected_hash": "<from file.view hash or content_hash>"
                }),
            });
        }
        match profile {
            "pytest" => out.push(SuggestedAction {
                op: "test.run_target".into(),
                args: json!({
                    "target": path.clone(),
                    "runner": "pytest"
                }),
            }),
            "cargo" => out.push(SuggestedAction {
                op: "exec.run".into(),
                args: json!({
                    "argv": ["cargo", "check"],
                    "profile": "cargo"
                }),
            }),
            "git" => out.push(SuggestedAction {
                op: "exec.run".into(),
                args: json!({
                    "argv": ["git", "status", "--short"],
                    "profile": "git"
                }),
            }),
            _ => {}
        }
    }
    let mut seen = std::collections::HashSet::new();
    out.retain(|a| {
        let key = format!("{}:{}", a.op, a.args);
        seen.insert(key)
    });
    out
}

/// Ops allowed in `suggested_next` by the 1.0 ACI surface (docs/1.0-aci.md).
pub const SUGGESTED_OP_ALLOWLIST: &[&str] = &[
    "file.view",
    "file.read_range",
    "file.hash",
    "file.replace_exact",
    "file.apply_patch",
    "file.edit_range",
    "file.diff",
    "file.write",
    "file.remove",
    "tx.begin",
    "tx.commit",
    "tx.rollback",
    "tx.restore",
    "result.query",
    "exec.run",
    "test.run_target",
    "test.summarize_last",
    "repo.search",
    "repo.changed_files",
    "repo.summary",
];

/// True when every suggested op is on the 1.0 ACI whitelist.
pub fn suggested_ops_are_legal(actions: &[crate::operation::SuggestedAction]) -> bool {
    actions
        .iter()
        .all(|a| SUGGESTED_OP_ALLOWLIST.contains(&a.op.as_str()))
}

/// Machine-checkable expected/found completeness rate over error diagnostics.
/// Returns `(complete, total, rate)` where complete counts diagnostics that
/// carry both `expected` and `found`. Used by claim_gate (C3).
pub fn expected_found_completeness(diagnostics: &[Diagnostic]) -> (usize, usize, f64) {
    let errors: Vec<&Diagnostic> = diagnostics.iter().filter(|d| d.severity == "error").collect();
    let total = errors.len();
    if total == 0 {
        return (0, 0, 1.0);
    }
    let complete = errors
        .iter()
        .filter(|d| d.expected.is_some() && d.found.is_some())
        .count();
    (complete, total, complete as f64 / total as f64)
}

pub(crate) fn diag(
    tool: &str,
    severity: &str,
    message: impl Into<String>,
    path: Option<String>,
    line: Option<u64>,
    column: Option<u64>,
) -> Diagnostic {
    Diagnostic {
        tool: tool.into(),
        severity: severity.into(),
        message: message.into(),
        path,
        line,
        column,
        code: None,
        expected: None,
        found: None,
        suggested_fix: None,
    }
}

pub(crate) fn diag_rich(
    tool: &str,
    severity: &str,
    message: impl Into<String>,
    path: Option<String>,
    line: Option<u64>,
    column: Option<u64>,
    code: Option<String>,
    expected: Option<String>,
    found: Option<String>,
    suggested_fix: Option<String>,
) -> Diagnostic {
    Diagnostic {
        tool: tool.into(),
        severity: severity.into(),
        message: message.into(),
        path,
        line,
        column,
        code,
        expected,
        found,
        suggested_fix,
    }
}

pub(crate) fn normalize_path(p: &str) -> String {
    p.replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_profile_returns_none() {
        assert!(reduce_for_profile("generic", "hello", true).is_none());
    }

    #[test]
    fn suggested_ops_are_legal_on_whitelist() {
        let actions = suggested_from_diagnostics(
            "cargo",
            &[diag_rich(
                "cargo",
                "error",
                "mismatched types",
                Some("src/lib.rs".into()),
                Some(88),
                None,
                Some("E0308".into()),
                Some("String".into()),
                Some("&str".into()),
                Some(".to_string()".into()),
            )],
        );
        assert!(!actions.is_empty());
        assert!(suggested_ops_are_legal(&actions));
    }

    #[test]
    fn suggested_args_match_op_input_schemas() {
        // TF-0004: an agent must be able to copy a suggested step, fill the
        // placeholders, and send it. Every arg key must exist in the op's real
        // input schema, and every schema-required key must be present.
        let registry = crate::operation::OperationRegistry::new();
        let cases = [
            ("cargo", "cargo check failure"),
            ("pytest", "assert 3 == 4"),
        ];
        for (profile, message) in cases {
            let diags = vec![diag_rich(
                profile,
                "error",
                message,
                Some("src/lib.rs".into()),
                Some(10),
                None,
                None,
                Some("expected value".into()),
                Some("found value".into()),
                None,
            )];
            let actions = suggested_from_diagnostics(profile, &diags);
            assert!(!actions.is_empty());
            for action in &actions {
                let spec = registry
                    .spec(&action.op)
                    .unwrap_or_else(|| panic!("suggested op {} not in registry", action.op));
                let schema = (spec.input_schema)();
                let props = schema
                    .get("properties")
                    .and_then(|p| p.as_object())
                    .unwrap_or_else(|| panic!("op {} schema has no properties", action.op));
                let args = action.args.as_object().expect("args must be an object");
                for key in args.keys() {
                    assert!(
                        props.contains_key(key),
                        "{profile} suggested {} uses unknown arg key {key} (schema: {:?})",
                        action.op,
                        props.keys().collect::<Vec<_>>()
                    );
                }
                if let Some(required) = schema.get("required").and_then(|r| r.as_array()) {
                    for key in required.iter().filter_map(|v| v.as_str()) {
                        assert!(
                            args.contains_key(key),
                            "{profile} suggested {} misses required arg {key}",
                            action.op
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn expected_found_completeness_rate() {
        let diags = vec![
            diag_rich(
                "cargo",
                "error",
                "a",
                None,
                None,
                None,
                None,
                Some("1".into()),
                Some("2".into()),
                None,
            ),
            diag_rich(
                "cargo",
                "error",
                "b",
                None,
                None,
                None,
                None,
                None,
                Some("x".into()),
                None,
            ),
        ];
        let (complete, total, rate) = expected_found_completeness(&diags);
        assert_eq!(complete, 1);
        assert_eq!(total, 2);
        assert!((rate - 0.5).abs() < f64::EPSILON);
    }
}
