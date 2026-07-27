//! T6: translate bash source into equivalent MCP tool calls.
//!
//! Strategy (v1):
//! 1. Call `transpile_bash_to_ae` to get the VerseShell source.
//! 2. Scan the transpiled `ae_src` for known builtin names and map them to
//!    task-oriented ACI tools (`system_snapshot`, `process_inspect`, etc.).
//! 3. If no mapping matches, fall back to `eval` with the transpiled
//!    `ae_src` (NOT the bash original — bash original would fail to parse
//!    as VerseShell).
//!
//! v2 (deferred to v0.5) will parse the `ae_src` AST and extract arguments
//! to populate the tool call arguments more precisely. v1 only matches on
//! builtin name presence and emits conservative default arguments.

use serde_json::{json, Value};

/// One equivalent MCP tool call derived from a bash snippet.
#[derive(Debug, Clone)]
pub struct ToolCall {
    pub tool: String,
    pub arguments: Value,
    pub rationale: String,
}

/// Translate a bash snippet into a list of equivalent MCP tool calls.
///
/// v1 returns at most one tool call (the first matching mapping). v2 may
/// return multiple calls for compound bash commands (e.g. pipelines).
pub fn explain_as_tools(bash_src: &str) -> anyhow::Result<Vec<ToolCall>> {
    let ae_src = crate::transpile::bash::transpile_bash_to_ae(bash_src)?;

    // Mapping table: patterns in the transpiled ae_src → ACI tool name.
    // IMPORTANT: patterns match VerseShell builtin/module names, NOT bash
    // command names. `transpile_bash_to_ae("ps aux")` outputs `proc.list()`
    // (not `sys.process_info()`), so we must match on `proc.list` here.
    let mappings: &[(&str, &str)] = &[
        // System info builtins → system_snapshot
        ("sys.cpu_info", "system_snapshot"),
        ("sys.mem_info", "system_snapshot"),
        ("sys.process_info", "system_snapshot"),
        ("sys.disk_info", "system_snapshot"),
        ("sys.load_avg", "system_snapshot"),
        ("sys.info", "system_snapshot"),
        ("sys.hostname", "system_snapshot"),
        ("sys.os", "system_snapshot"),
        ("sys.arch", "system_snapshot"),
        ("sys.uptime", "system_snapshot"),
        ("sys.uname", "system_snapshot"),
        ("sys.whoami", "system_snapshot"),
        ("sys.disk_usage", "system_snapshot"),
        ("sys.env", "system_snapshot"),
        // Process listing builtins → process_inspect
        ("proc.list", "process_inspect"),
        ("proc.info", "process_inspect"),
        ("proc.grep", "process_inspect"),
        ("proc.children", "process_inspect"),
        // Process kill → process_terminate
        ("proc.kill", "process_terminate"),
        ("proc.killall", "process_terminate"),
        ("proc.pkill", "process_terminate"),
    ];

    let matched_tool: Option<&str> = mappings
        .iter()
        .find(|(pattern, _)| ae_src.contains(*pattern))
        .map(|(_, tool)| *tool);

    let calls = match matched_tool {
        Some("system_snapshot") => vec![ToolCall {
            tool: "system_snapshot".into(),
            arguments: json!({"aspects": ["cpu", "mem", "processes"]}),
            rationale: format!(
                "bash code maps to system info builtins; ae_source: {}",
                ae_src
            ),
        }],
        Some("process_inspect") => vec![ToolCall {
            tool: "process_inspect".into(),
            arguments: json!({"limit": 20}),
            rationale: format!(
                "bash code maps to process listing builtins; ae_source: {}",
                ae_src
            ),
        }],
        Some("process_terminate") => vec![ToolCall {
            tool: "process_terminate".into(),
            arguments: json!({}),
            rationale: format!("bash code maps to process kill; ae_source: {}", ae_src),
        }],
        _ => {
            // Fallback: use eval with the transpiled ae_src (not bash_src!).
            vec![ToolCall {
                tool: "eval".into(),
                arguments: json!({"code": ae_src}),
                rationale: "bash code has no direct ACI mapping; fallback to eval with transpiled ae_source".into(),
            }]
        }
    };

    Ok(calls)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explain_ls_falls_back_to_eval() {
        // `ls` is not in the ACI mapping table → fallback to eval.
        let calls = explain_as_tools("ls -la").unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].tool, "eval");
        // arguments.code must be the transpiled ae_src, not the bash original.
        let code = calls[0].arguments.get("code").unwrap().as_str().unwrap();
        assert!(!code.is_empty());
        assert!(code != "ls -la", "fallback must pass ae_src, not bash_src");
    }

    #[test]
    fn explain_ps_aux_maps_to_process_inspect() {
        // `ps` transpiles to `proc.list` (see bash.rs map_builtin).
        let calls = explain_as_tools("ps aux").unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].tool, "process_inspect");
    }

    #[test]
    fn explain_free_maps_to_system_snapshot() {
        // `free` transpiles to `sys.mem_info`.
        let calls = explain_as_tools("free -m").unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].tool, "system_snapshot");
    }

    #[test]
    fn explain_kill_maps_to_process_terminate() {
        // `kill` transpiles to `proc.kill`.
        let calls = explain_as_tools("kill 1234").unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].tool, "process_terminate");
    }
}
