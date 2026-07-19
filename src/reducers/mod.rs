//! Command-aware semantic observation reducers.
//!
//! Profile-specific parsers turn raw tool output into structured
//! `summary` + `diagnostics` + `stats` for verseshell.observation/v1.

mod cargo;
mod git;
mod npm;
mod pytest;

use crate::operation::Diagnostic;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

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

/// Build suggested next actions from diagnostics (minimal rule set).
pub fn suggested_from_diagnostics(profile: &str, diagnostics: &[Diagnostic]) -> Vec<crate::operation::SuggestedAction> {
    use crate::operation::SuggestedAction;
    let mut out = Vec::new();
    for d in diagnostics.iter().take(5) {
        if let (Some(path), Some(line)) = (d.path.as_ref(), d.line) {
            out.push(SuggestedAction {
                op: "file.view".into(),
                args: json!({
                    "path": path,
                    "cursor": line,
                    "window": 40
                }),
            });
            if profile == "pytest" {
                out.push(SuggestedAction {
                    op: "test.run_target".into(),
                    args: json!({
                        "target": path,
                        "framework": "pytest"
                    }),
                });
            }
        }
    }
    // Dedup by op+path
    let mut seen = std::collections::HashSet::new();
    out.retain(|a| {
        let key = format!("{}:{}", a.op, a.args);
        seen.insert(key)
    });
    out
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
}
