//! MCP tool implementations.
//!
//! T2 migrates the three legacy tools (`health`, `list_commands`, `exec`)
//! from inline server handlers into the `ToolRegistry`. T3 adds the
//! task-oriented ACI tools (`system_snapshot`, `process_inspect`,
//! `process_terminate`, `transpile_bash`, `eval`, `describe_capabilities`)
//! on top of the same registry. T4 injects `agent_hints` into the ACI tool
//! responses. T6 extends `transpile_bash` with `explain_as_tools`.

use std::sync::Arc;

use serde_json::{json, Value};

use crate::capability;
use crate::mcp::registry::{AgentHints, CallToolResult, Content, RpcError, Tool, ToolSchema};
use crate::modules;
use crate::runtime::{AgentRequest, AgentResponse, SharedRuntime};
use crate::value::Value as VmValue;

// Legacy DSL core surface — the ~70 most-used builtins for agent tasks.
const CORE_BUILTINS: &[&str] = &[
    "sys_hostname", "sys_os", "sys_arch", "sys_cpu_info", "sys_mem_info",
    "sys_disk_info", "sys_load_avg", "sys_process_info", "sys_uptime",
    "sys_env_all", "sys_describe",
    "proc_list", "proc_kill", "proc_info", "proc_grep", "proc_spawn",
    "file_ls", "file_read", "file_write", "file_stat", "file_find",
    "file_mkdir", "file_copy", "file_move", "file_remove", "file_exists",
    "file_head", "file_tail", "file_grep", "file_wc",
    "http_get", "http_post",
    "net_ping", "net_interfaces", "net_dns_lookup",
    "shell_exec",
    "str_upper", "str_lower", "str_trim", "str_split", "str_join",
    "str_replace", "str_contains", "str_length", "str_grep",
    "arr_sort", "arr_filter", "arr_map", "arr_reduce",
    "arr_first", "arr_last", "arr_take", "arr_any", "arr_all",
    "arr_unique", "arr_flatten", "arr_range", "arr_keys",
    "math_abs", "math_min", "math_max", "math_sum", "math_mean",
    "json_parse", "json_stringify",
    "win_snapshot", "win_registry_get", "win_env_get",
    "crypto_hash", "crypto_uuid",
    "sort", "where", "map", "reduce", "take", "reverse", "first", "last", "any", "all",
];

/// Box an async closure into the `ToolHandler` signature.
macro_rules! handler {
    ($f:expr) => {{
        Box::new($f)
    }};
}

/// Return all tools that should be registered in the MCP server.
///
/// Includes legacy tools plus the 1.0 OperationRegistry (file/tx/repo/test/exec/result).
pub fn default_tools() -> Vec<Tool> {
    let mut tools = vec![
        // ── Legacy (T1/T2) ──
        health_tool(),
        list_commands_tool(),
        exec_tool(),
        // ── ACI (T3) ──
        system_snapshot_tool(),
        process_inspect_tool(),
        process_terminate_tool(),
        transpile_bash_tool(),
        eval_tool(),
        describe_capabilities_tool(),
    ];
    // ── Typed operations from OperationRegistry (1.0) ──
    // exec_run / result_query keep specialized handlers; all other ops auto-bind.
    tools.push(exec_run_tool());
    tools.push(result_query_tool());
    for spec in crate::operation::OperationRegistry::new().list() {
        if matches!(spec.name, "exec.run" | "result.query") {
            continue;
        }
        tools.push(registry_op_tool(spec));
    }
    tools
}

fn registry_op_tool(spec: &crate::operation::OperationSpec) -> Tool {
    let op_name = spec.name.to_string();
    let mcp_name = spec.mcp_name.to_string();
    let description = spec.description.to_string();
    let input_schema = (spec.input_schema)();
    Tool {
        schema: ToolSchema {
            name: mcp_name,
            description,
            input_schema,
        },
        handler: handler!({
            move |args: Value, _runtime: Arc<SharedRuntime>| {
                let op_name = op_name.clone();
                Box::pin(async move {
                    let timeout_ms = args
                        .get("timeout_ms")
                        .and_then(Value::as_u64)
                        .unwrap_or(30_000);
                    let max_tokens = args
                        .get("max_tokens")
                        .and_then(Value::as_u64)
                        .unwrap_or(4_000) as usize;
                    let request = crate::operation::OperationRequest {
                        id: format!("mcp-{}", uuid::Uuid::new_v4()),
                        agent: format!("mcp-{}", op_name.replace('.', "-")),
                        op: op_name,
                        args,
                        timeout_ms,
                        budget: crate::operation::ObservationBudget { max_tokens },
                    };
                    let observation = tokio::task::spawn_blocking(move || {
                        crate::operation::OperationRegistry::new().execute(request)
                    })
                    .await
                    .map_err(|error| {
                        RpcError::new(-1, format!("operation worker failed: {error}"))
                    })?;
                    Ok(observation_tool_result(observation))
                })
            }
        }),
    }
}

fn observation_tool_result(observation: crate::operation::Observation) -> CallToolResult {
    let value = serde_json::to_value(&observation).unwrap_or(Value::Null);
    let text = observation
        .data
        .as_ref()
        .and_then(|data| data.get("stdout"))
        .and_then(|stdout| stdout.get("summary").or_else(|| stdout.get("text")))
        .and_then(Value::as_str)
        .or_else(|| observation.error.as_ref().map(|error| error.message.as_str()))
        .unwrap_or(if observation.ok { "operation completed" } else { "operation failed" })
        .to_string();
    CallToolResult {
        content: vec![Content::Text { text }],
        structured_content: Some(value),
        is_error: !observation.ok,
    }
}

fn exec_run_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "exec_run".into(),
            description: "Preferred 1.0 execution interface. Runs an argv command and returns a bounded structured observation with result artifact handles.".into(),
            input_schema: crate::operation::exec_input_schema(),
        },
        handler: handler!({
            move |args: Value, _runtime: Arc<SharedRuntime>| {
                Box::pin(async move {
                    let timeout_ms = args.get("timeout_ms").and_then(Value::as_u64).unwrap_or(30_000);
                    let max_tokens = args.get("max_tokens").and_then(Value::as_u64).unwrap_or(4_000) as usize;
                    let request = crate::operation::OperationRequest {
                        id: format!("mcp-{}", uuid::Uuid::new_v4()),
                        agent: "mcp-exec-run".into(),
                        op: "exec.run".into(),
                        args,
                        timeout_ms,
                        budget: crate::operation::ObservationBudget { max_tokens },
                    };
                    let observation = tokio::task::spawn_blocking(move || {
                        crate::operation::OperationRegistry::new().execute(request)
                    })
                    .await
                    .map_err(|error| RpcError::new(-1, format!("operation worker failed: {error}")))?;
                    Ok(observation_tool_result(observation))
                })
            }
        }),
    }
}

fn result_query_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "result_query".into(),
            description: "Query a result:// artifact by metadata, head, tail, slice, grep, or explicitly bounded raw bytes.".into(),
            input_schema: crate::operation::result_input_schema(),
        },
        handler: handler!({
            move |args: Value, _runtime: Arc<SharedRuntime>| {
                Box::pin(async move {
                    let max_tokens = args.get("max_tokens").and_then(Value::as_u64).unwrap_or(4_000) as usize;
                    let request = crate::operation::OperationRequest {
                        id: format!("mcp-{}", uuid::Uuid::new_v4()),
                        agent: "mcp-result-query".into(),
                        op: "result.query".into(),
                        args,
                        timeout_ms: 30_000,
                        budget: crate::operation::ObservationBudget { max_tokens },
                    };
                    let observation = tokio::task::spawn_blocking(move || {
                        crate::operation::OperationRegistry::new().execute(request)
                    })
                    .await
                    .map_err(|error| RpcError::new(-1, format!("operation worker failed: {error}")))?;
                    Ok(observation_tool_result(observation))
                })
            }
        }),
    }
}

// ── Shared execution helper (T3) ─────────────────────────────────────

/// Execute VerseShell code via `SharedRuntime` with the two-layer timeout
/// strategy (T5 inner deadline + outer tokio timeout on a detached thread).
///
/// All ACI tools that need to run VerseShell code go through this helper
/// so they automatically inherit the T5 deadline mechanism and T13
/// capability check (both enforced inside `runtime.execute`).
///
/// `agent_label` is stored in `AgentRequest.agent` for telemetry.
async fn execute_via_runtime(
    runtime: Arc<SharedRuntime>,
    code: String,
    timeout_ms: u64,
    agent_label: &str,
) -> Result<CallToolResult, RpcError> {
    let code_bytes = code.as_bytes().len();
    let req = AgentRequest {
        id: format!("mcp-{}", uuid::Uuid::new_v4()),
        agent: agent_label.to_string(),
        cmd: code,
        timeout_ms,
        budget: None,
        dry_run: false,
        trace: false,
    };

    // Two-layer timeout strategy (see T1 server.rs for full rationale):
    //   - Inner (T5 deadline inside runtime.execute): aborts CPU-bound loops.
    //   - Outer (tokio::time::timeout around a detached OS thread): aborts
    //     blocking operations (sleep, sync I/O) that don't check env.deadline.
    //
    // We use std::thread::spawn (not tokio::task::spawn_blocking) so that on
    // timeout the orphaned thread does not block process exit — the tokio
    // runtime would otherwise wait for spawn_blocking tasks to finish.
    let (tx, rx) = tokio::sync::oneshot::channel::<AgentResponse>();
    let runtime_clone = Arc::clone(&runtime);
    std::thread::spawn(move || {
        let resp = runtime_clone.execute(req);
        let _ = tx.send(resp); // receiver may be gone on timeout — ignore error
    });

    let exec_result = if timeout_ms > 0 {
        match tokio::time::timeout(
            std::time::Duration::from_millis(timeout_ms),
            rx,
        )
        .await
        {
            Ok(inner) => inner,
            Err(_elapsed) => {
                // Outer timeout fired. Return RPC error per mcp_stdio_tests
                // contract: message "timed out after {N}ms", data.codeLength
                // set, no source echo.
                return Err(RpcError::new(
                    -1,
                    format!("timed out after {}ms", timeout_ms),
                )
                .with_data(json!({ "codeLength": code_bytes })));
            }
        }
    } else {
        rx.await
    };

    let resp = match exec_result {
        Ok(r) => r,
        Err(_recv_err) => {
            return Err(RpcError::new(
                -1,
                "internal error: executor thread terminated without result",
            ));
        }
    };

    if resp.ok {
        let value = resp.value.unwrap_or(Value::Null);
        Ok(CallToolResult {
            content: vec![Content::Text {
                text: v_to_text(&value),
            }],
            structured_content: Some(value),
            is_error: false,
        })
    } else {
        let err = resp.error;
        let code_str = err
            .as_ref()
            .map(|e| e.code.as_str())
            .unwrap_or("E_INTERNAL");
        let msg = err
            .as_ref()
            .map(|e| e.message.clone())
            .unwrap_or_default();

        if code_str == "E_TIMEOUT" {
            // Inner T5 deadline fired (CPU-bound timeout). Same contract as
            // outer timeout: RPC error with codeLength, no source echo.
            let reported_ms = if timeout_ms > 0 { timeout_ms } else { 30000 };
            return Err(RpcError::new(
                -1,
                format!("timed out after {}ms", reported_ms),
            )
            .with_data(json!({ "codeLength": code_bytes })));
        }

        // Other errors: return as soft-error result so the agent sees the
        // message in content[0].text and can self-correct.
        Ok(CallToolResult::error_text(format!("{}: {}", code_str, msg)))
    }
}

/// Render a `serde_json::Value` (as produced by `AgentResponse.value`) into a
/// display string suitable for the `text` content of a tool result.
fn v_to_text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        _ => serde_json::to_string_pretty(v).unwrap_or_else(|_| v.to_string()),
    }
}

/// T4: take a successful `CallToolResult` from `execute_via_runtime` and
/// repackage it with `agent_hints`. If the input result is an error, it is
/// returned unchanged (errors don't get proactive hints — they already have
/// reactive hints via `AgentError.hint`).
fn with_hints(result: CallToolResult, hints: AgentHints) -> CallToolResult {
    if result.is_error {
        return result;
    }
    // Extract the structured value. If `execute_via_runtime` succeeded but
    // produced no structured_content (e.g. value was Null), use Null.
    let value = result.structured_content.unwrap_or(Value::Null);
    CallToolResult::structured_with_hints(value, hints)
}

// ── health (legacy) ─────────────────────────────────────────────────

fn health_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "health".into(),
            description: "Return server health and version.".into(),
            input_schema: json!({"type": "object", "properties": {}}),
        },
        handler: handler!({
            move |_args: Value, _runtime: Arc<SharedRuntime>| {
                Box::pin(async move {
                    Ok(CallToolResult::text(format!(
                        "ok verseshell-mcp {}",
                        env!("CARGO_PKG_VERSION")
                    )))
                })
            }
        }),
    }
}

// ── list_commands (legacy) ──────────────────────────────────────────

fn list_commands_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "list_commands".into(),
            description:
                "List available VerseShell commands and their builtin aliases (module.fn -> builtin_name)."
                    .into(),
            input_schema: json!({"type": "object", "properties": {
                "core": {"type": "boolean", "default": false, "description": "If true, list only the ~70 most-used agent builtins."}
            }}),
        },
        handler: handler!({
            move |args: Value, _runtime: Arc<SharedRuntime>| {
                Box::pin(async move {
                    let core_only = args.get("core").and_then(|v| v.as_bool()).unwrap_or(false);
                    Ok(CallToolResult::text(build_list_commands_text(core_only)))
                })
            }
        }),
    }
}

/// Build the `list_commands` output by walking the module registry.
/// Format: one mapping per line, `module.fn_name -> builtin_name`.
fn build_list_commands_text(core_only: bool) -> String {
    let core_set: std::collections::HashSet<&str> = CORE_BUILTINS.iter().copied().collect();
    let mut lines = Vec::new();
    for (module_name, module_value) in modules::all_modules() {
        if let VmValue::Record(map) = module_value {
            for (fn_name, val) in map.iter() {
                if let VmValue::Builtin(b) = val {
                    let is_core = core_set.contains(b.name.as_str());
                    if core_only && !is_core {
                        continue;
                    }
                    let tag = if is_core { " [core]" } else { "" };
                    lines.push(format!("{}.{} -> {}{}", module_name, fn_name, b.name, tag));
                }
            }
        }
    }
    lines.sort();
    lines.join("\n")
}

// ── exec (legacy) ───────────────────────────────────────────────────

fn exec_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "exec".into(),
            description: "Execute a VerseShell program and return its value. Supports a timeout_ms parameter; on timeout returns a JSON-RPC error with codeLength (no source echo).".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "VerseShell source to execute"},
                    "timeout_ms": {"type": "integer", "description": "Per-request timeout in milliseconds. 0 = use default 30s.", "default": 0}
                },
                "required": ["code"]
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { exec_handler(args, runtime).await })
            }
        }),
    }
}

async fn exec_handler(args: Value, runtime: Arc<SharedRuntime>) -> Result<CallToolResult, RpcError> {
    let code = args
        .get("code")
        .and_then(|v| v.as_str())
        .ok_or_else(|| RpcError::new(-32602, "missing required argument: code"))?
        .to_string();
    let timeout_ms = args
        .get("timeout_ms")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    execute_via_runtime(runtime, code, timeout_ms, "mcp-exec").await
}

// ── system_snapshot (ACI) ───────────────────────────────────────────

fn system_snapshot_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "system_snapshot".into(),
            description: "Take a one-shot snapshot of system dimensions (cpu, mem, processes, disk, load). Avoids multiple round-trips for common system inspection tasks.".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "aspects": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["cpu","mem","processes","disk","load"]},
                        "default": ["cpu","mem","processes"],
                        "description": "Dimensions to include in the snapshot."
                    }
                }
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { system_snapshot_handler(args, runtime).await })
            }
        }),
    }
}

async fn system_snapshot_handler(
    args: Value,
    runtime: Arc<SharedRuntime>,
) -> Result<CallToolResult, RpcError> {
    let aspects: Vec<String> = args
        .get("aspects")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_else(|| {
            vec!["cpu".into(), "mem".into(), "processes".into()]
        });

    let mut fields: Vec<String> = Vec::new();
    for aspect in &aspects {
        let expr = match aspect.as_str() {
            "cpu" => "cpu: sys.cpu_info()",
            "mem" => "mem: sys.mem_info()",
            "processes" => "processes: proc.list()",
            "disk" => "disk: sys.disk_info()",
            "load" => "load: sys.load_avg()",
            other => {
                return Ok(CallToolResult::error_text(format!(
                    "unknown aspect: {other}. Valid: cpu, mem, processes, disk, load"
                )));
            }
        };
        fields.push(expr.into());
    }

    // Build a VerseShell record literal: { cpu: sys.cpu_info(), mem: sys.mem_info(), ... }
    let code = format!("{{ {} }}", fields.join(", "));
    let result = execute_via_runtime(runtime, code, 0, "mcp-snapshot").await?;
    let hints = AgentHints {
        next_actions: vec!["process_inspect".into(), "describe_capabilities".into()],
        warnings: vec![],
        reversible: true,
        undo_tool: None,
    };
    Ok(with_hints(result, hints))
}

// ── process_inspect (ACI) ───────────────────────────────────────────

fn process_inspect_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "process_inspect".into(),
            description: "Query processes with optional filter, sort, and limit. Returns a structured process list, avoiding the need for the agent to compose nested arr.where/arr.sort expressions.".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "object",
                        "properties": {
                            "mem_mb_gt": {"type": "number", "description": "Keep processes with mem_mb greater than this."},
                            "name_contains": {"type": "string", "description": "Keep processes whose name contains this substring."},
                            "pid_lt": {"type": "integer", "description": "Keep processes with pid less than this."}
                        }
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["cpu","mem","pid"],
                        "default": "mem",
                        "description": "Sort key. Descending order."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of processes to return."
                    }
                }
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { process_inspect_handler(args, runtime).await })
            }
        }),
    }
}

async fn process_inspect_handler(
    args: Value,
    runtime: Arc<SharedRuntime>,
) -> Result<CallToolResult, RpcError> {
    let filter = args.get("filter").cloned().unwrap_or(Value::Null);
    let sort_by = args
        .get("sort_by")
        .and_then(|v| v.as_str())
        .unwrap_or("mem");
    let limit = args
        .get("limit")
        .and_then(|v| v.as_u64())
        .unwrap_or(10)
        .min(1000) as usize;

    // Build nested `where` calls to avoid depending on a boolean `and` operator.
    // We start from proc.list() and layer filters.
    // Note: proc.list() returns `mem` in bytes (not `mem_mb`), so the
    // `mem_mb_gt` parameter is converted to bytes before comparison.
    // Note: use flat builtin names (`where`, `sort`, `take`) not `arr.X` —
    // the `arr` module only exports a subset of array functions.
    let mut current = "proc.list()".to_string();

    if let Some(mem_mb_gt) = filter.get("mem_mb_gt").and_then(|v| v.as_f64()) {
        let mem_bytes = (mem_mb_gt * 1048576.0) as u64;
        current = format!(
            "where({}, fn(p) => p.mem > {})",
            current, mem_bytes
        );
    }
    if let Some(pid_lt) = filter.get("pid_lt").and_then(|v| v.as_i64()) {
        current = format!(
            "where({}, fn(p) => p.pid < {})",
            current, pid_lt
        );
    }
    if let Some(name_contains) = filter.get("name_contains").and_then(|v| v.as_str()) {
        // Escape double quotes in the needle.
        let escaped = name_contains.replace('\\', "\\\\").replace('"', "\\\"");
        current = format!(
            "where({}, fn(p) => str.contains(p.name, \"{}\"))",
            current, escaped
        );
    }

    // Sort descending by the chosen key.
    let sort_key = match sort_by {
        "cpu" => "cpu",
        "mem" => "mem",
        "pid" => "pid",
        other => {
            return Ok(CallToolResult::error_text(format!(
                "unknown sort_by: {other}. Valid: cpu, mem, pid"
            )));
        }
    };
    current = format!(
        "sort({}, fn(a, b) => a.{} > b.{})",
        current, sort_key, sort_key
    );

    // Apply limit.
    let code = format!("take({}, {})", current, limit);
    let result = execute_via_runtime(runtime, code, 0, "mcp-procinspect").await?;
    let hints = AgentHints {
        next_actions: vec!["process_terminate".into(), "system_snapshot".into()],
        warnings: vec!["killing system processes may be unsafe".into()],
        reversible: true,
        undo_tool: None,
    };
    Ok(with_hints(result, hints))
}

// ── process_terminate (ACI) ─────────────────────────────────────────

fn process_terminate_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "process_terminate".into(),
            description: "Terminate a process by PID with optional name confirmation. If confirm_name is provided, the call aborts (is_error=true) when the actual process name does not match — preventing accidental kills of system processes.".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID to terminate."},
                    "confirm_name": {"type": "string", "description": "Expected process name. If provided and the actual name differs, the call aborts with is_error=true."},
                    "signal": {"type": "string", "default": "SIGTERM", "description": "Signal name (advisory; VerseShell proc.kill uses platform default)."}
                },
                "required": ["pid"]
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { process_terminate_handler(args, runtime).await })
            }
        }),
    }
}

async fn process_terminate_handler(
    args: Value,
    runtime: Arc<SharedRuntime>,
) -> Result<CallToolResult, RpcError> {
    let pid = args
        .get("pid")
        .and_then(|v| v.as_i64())
        .ok_or_else(|| RpcError::new(-32602, "missing required argument: pid"))?;
    let confirm_name = args.get("confirm_name").and_then(|v| v.as_str());

    // Step 1: inspect the process first (if confirm_name provided or for telemetry).
    // We use proc.info(pid) which returns a record or null.
    let inspect_code = format!("proc.info({})", pid);
    let inspect_result = execute_via_runtime(
        Arc::clone(&runtime),
        inspect_code,
        0,
        "mcp-procterminate-inspect",
    )
    .await?;

    // If inspection returned an error (e.g. capability denied or pid doesn't exist),
    // surface it directly.
    if inspect_result.is_error {
        return Ok(CallToolResult::error_text(format!(
            "process_terminate: process {} not found or inspect failed: {}",
            pid,
            inspect_result
                .content
                .first()
                .map(|c| match c {
                    Content::Text { text } => text.clone(),
                    Content::Json { json } => json.to_string(),
                })
                .unwrap_or_default()
        )));
    }

    // Extract the structured process info.
    let proc_info = inspect_result
        .structured_content
        .clone()
        .unwrap_or(Value::Null);

    // Step 2: if confirm_name is provided, verify the process name matches.
    if let Some(expected) = confirm_name {
        let actual_name = proc_info
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if actual_name != expected {
            return Ok(CallToolResult::error_text(format!(
                "process_terminate: name mismatch — expected {:?}, got {:?}. Aborting to prevent accidental kill.",
                expected, actual_name
            )));
        }
    }

    // Step 3: kill the process.
    let kill_code = format!("proc.kill({})", pid);
    let kill_result =
        execute_via_runtime(Arc::clone(&runtime), kill_code, 0, "mcp-procterminate-kill").await?;

    if kill_result.is_error {
        return Ok(kill_result);
    }

    // Step 4: return structured result with previous_state and agent_hints.
    let result = json!({
        "success": true,
        "pid": pid,
        "previous_state": proc_info,
        "signal": args.get("signal").and_then(|v| v.as_str()).unwrap_or("SIGTERM"),
    });
    let hints = AgentHints {
        next_actions: vec!["system_snapshot".into()],
        warnings: vec!["action cannot be undone".into()],
        reversible: false,
        undo_tool: None,
    };
    Ok(CallToolResult::structured_with_hints(result, hints))
}

// ── transpile_bash (ACI, extended by T6) ────────────────────────────

fn transpile_bash_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "transpile_bash".into(),
            description: "Transpile a bash command into equivalent VerseShell source. Optionally also return equivalent MCP tool calls (explain_as_tools=true) so the agent can use task-oriented ACI tools directly without learning VerseShell syntax.".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "bash_code": {"type": "string", "description": "Bash source code to transpile."},
                    "explain_as_tools": {"type": "boolean", "default": false, "description": "If true, also return equivalent MCP tool calls in structured_content.tool_calls."}
                },
                "required": ["bash_code"]
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { transpile_bash_handler(args, runtime).await })
            }
        }),
    }
}

async fn transpile_bash_handler(
    args: Value,
    _runtime: Arc<SharedRuntime>,
) -> Result<CallToolResult, RpcError> {
    let bash_code = args
        .get("bash_code")
        .and_then(|v| v.as_str())
        .ok_or_else(|| RpcError::new(-32602, "missing required argument: bash_code"))?;
    let explain = args
        .get("explain_as_tools")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let ae_src = match crate::transpile::bash::transpile_bash_to_ae(bash_code) {
        Ok(s) => s,
        Err(e) => {
            return Ok(CallToolResult::error_text(format!(
                "transpile failed: {e}"
            )));
        }
    };

    let mut result = serde_json::Map::new();
    result.insert("ae_source".into(), Value::String(ae_src.clone()));
    result.insert("fallback_used".into(), Value::Bool(false));

    if explain {
        match crate::transpile::explain::explain_as_tools(bash_code) {
            Ok(calls) => {
                let tool_calls: Vec<Value> = calls
                    .iter()
                    .map(|c| {
                        json!({
                            "tool": c.tool,
                            "arguments": c.arguments,
                            "rationale": c.rationale,
                        })
                    })
                    .collect();
                result.insert("tool_calls".into(), Value::Array(tool_calls));
            }
            Err(e) => {
                result.insert(
                    "tool_calls_error".into(),
                    Value::String(e.to_string()),
                );
            }
        }
    }

    let hints = AgentHints {
        next_actions: vec!["eval".into()],
        warnings: vec![],
        reversible: true,
        undo_tool: None,
    };
    Ok(CallToolResult::structured_with_hints(
        Value::Object(result),
        hints,
    ))
}

// ── eval (ACI) ──────────────────────────────────────────────────────

fn eval_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "eval".into(),
            description: "Execute VerseShell source code directly. For advanced agents that can compose VerseShell expressions; prefer task-oriented ACI tools (system_snapshot, process_inspect, etc.) when they fit the task.".into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "VerseShell source to execute."},
                    "timeout_ms": {"type": "integer", "default": 0, "description": "Per-request timeout in milliseconds. 0 = use default 30s."}
                },
                "required": ["code"]
            }),
        },
        handler: handler!({
            move |args: Value, runtime: Arc<SharedRuntime>| {
                Box::pin(async move { eval_handler(args, runtime).await })
            }
        }),
    }
}

async fn eval_handler(args: Value, runtime: Arc<SharedRuntime>) -> Result<CallToolResult, RpcError> {
    let code = args
        .get("code")
        .and_then(|v| v.as_str())
        .ok_or_else(|| RpcError::new(-32602, "missing required argument: code"))?
        .to_string();
    let timeout_ms = args
        .get("timeout_ms")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let result = execute_via_runtime(runtime, code, timeout_ms, "mcp-eval").await?;
    let hints = AgentHints {
        next_actions: vec!["describe_capabilities".into(), "system_snapshot".into()],
        warnings: vec!["eval bypasses ACI abstractions; prefer task-oriented tools".into()],
        reversible: false,
        undo_tool: None,
    };
    Ok(with_hints(result, hints))
}

// ── describe_capabilities (ACI) ─────────────────────────────────────

fn describe_capabilities_tool() -> Tool {
    Tool {
        schema: ToolSchema {
            name: "describe_capabilities".into(),
            description: "Return the list of capabilities currently granted to this MCP server. Agents should call this before invoking tools that may be capability-gated (e.g. process_terminate, file writes) to avoid unnecessary denials.".into(),
            input_schema: json!({"type": "object", "properties": {}}),
        },
        handler: handler!({
            move |_args: Value, _runtime: Arc<SharedRuntime>| {
                Box::pin(async move {
                    let granted = capability::current_capabilities();
                    let mode = capability::current_mode_str();
                    let is_empty = capability::caps_is_empty();
                    let result = json!({
                        "granted": granted,
                        "mode": mode,
                        "count": granted.len(),
                        "unrestricted": is_empty,
                        "note": if is_empty {
                            "No capability restrictions set — all builtins allowed."
                        } else {
                            "Capability restrictions active. Builtins not covered by granted caps will be denied."
                        }
                    });
                    let hints = AgentHints {
                        next_actions: vec!["system_snapshot".into(), "process_inspect".into()],
                        warnings: vec![],
                        reversible: true,
                        undo_tool: None,
                    };
                    Ok(CallToolResult::structured_with_hints(result, hints))
                })
            }
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_tools_returns_expected_tools() {
        let tools = default_tools();
        let names: Vec<&str> = tools.iter().map(|t| t.schema.name.as_str()).collect();
        assert!(names.contains(&"system_snapshot"));
        assert!(names.contains(&"process_inspect"));
        assert!(names.contains(&"process_terminate"));
        assert!(names.contains(&"transpile_bash"));
        assert!(names.contains(&"eval"));
        assert!(names.contains(&"describe_capabilities"));
        assert!(names.contains(&"exec_run"));
        assert!(names.contains(&"result_query"));
        // 1.0 ACI surface auto-registered from OperationRegistry
        assert!(names.contains(&"file_view"));
        assert!(names.contains(&"file_replace_exact"));
        assert!(names.contains(&"tx_begin"));
        assert!(names.contains(&"repo_search"));
        assert!(names.contains(&"test_discover"));
        assert!(names.contains(&"ops_list"));
        assert!(tools.len() >= 20, "expected legacy + full 1.0 op surface, got {}", tools.len());
    }

    #[test]
    fn system_snapshot_rejects_unknown_aspect() {
        // We can't easily run the handler without a runtime, but we can at
        // least verify the schema declares the allowed enum values.
        let tools = default_tools();
        let snap = tools
            .iter()
            .find(|t| t.schema.name == "system_snapshot")
            .unwrap();
        let aspects_schema = snap.schema.input_schema
            .get("properties")
            .and_then(|p| p.get("aspects"))
            .and_then(|a| a.get("items"))
            .and_then(|i| i.get("enum"))
            .unwrap();
        let allowed: Vec<String> = aspects_schema
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(allowed, vec!["cpu", "mem", "processes", "disk", "load"]);
    }

    #[test]
    fn process_inspect_schema_has_filter_and_sort() {
        let tools = default_tools();
        let inspect = tools
            .iter()
            .find(|t| t.schema.name == "process_inspect")
            .unwrap();
        let props = inspect.schema.input_schema.get("properties").unwrap();
        assert!(props.get("filter").is_some());
        assert!(props.get("sort_by").is_some());
        assert!(props.get("limit").is_some());
    }

    #[test]
    fn transpile_bash_schema_supports_explain_flag() {
        let tools = default_tools();
        let t = tools
            .iter()
            .find(|t| t.schema.name == "transpile_bash")
            .unwrap();
        let props = t.schema.input_schema.get("properties").unwrap();
        assert!(props.get("bash_code").is_some());
        assert!(props.get("explain_as_tools").is_some());
    }
}
