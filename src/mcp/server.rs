//! MCP stdio server: reads JSON-RPC messages, dispatches to handlers,
//! writes responses with matching framing.
//!
//! T2 refactored: the three legacy tools (`health`, `exec`, `list_commands`)
//! are now registered in a `ToolRegistry` (see `tools::default_tools`) and
//! dispatched through `registry.call`. T3 will add task-oriented ACI tools
//! on top of the same registry.

use std::sync::Arc;

use anyhow::Result;
use serde_json::{json, Value};
use tokio::io::{stdin, stdout, BufReader};

use crate::mcp::protocol::{read_message, write_message, JsonRpcRequest, JsonRpcResponse};
use crate::mcp::registry::ToolRegistry;
use crate::mcp::tools;
use crate::runtime::{RuntimeConfig, SharedRuntime};

/// Run the MCP stdio server until stdin is closed.
///
/// Creates a fresh `SharedRuntime` with default config and a `ToolRegistry`
/// preloaded with all default tools (legacy + ACI). Each `tools/call` is
/// dispatched through the registry — the T5 deadline mechanism ensures
/// timeouts are honored promptly for tools that invoke `runtime.execute`.
pub async fn serve_stdio() -> Result<()> {
    let runtime = Arc::new(SharedRuntime::new(RuntimeConfig::default()));
    serve_stdio_with_runtime(runtime).await
}

/// Run the MCP server with an externally-constructed runtime (used by tests
/// and future embeddings that want to share a runtime across endpoints).
pub async fn serve_stdio_with_runtime(runtime: Arc<SharedRuntime>) -> Result<()> {
    let mut registry = ToolRegistry::new();
    for tool in tools::default_tools() {
        registry.register(tool);
    }

    let stdin = stdin();
    let mut reader = BufReader::new(stdin);
    let mut out = stdout();

    while let Some((body, framing)) = read_message(&mut reader).await? {
        let req: JsonRpcRequest = match serde_json::from_str(&body) {
            Ok(r) => r,
            Err(e) => {
                // Malformed JSON: respond with parse error, id unknown.
                let resp = JsonRpcResponse::error(
                    Value::Null,
                    -32700,
                    format!("parse error: {e}"),
                    None,
                );
                let resp_body = serde_json::to_string(&resp)?;
                write_message(&mut out, &resp_body, framing).await?;
                continue;
            }
        };

        // Notifications (no id) receive no response.
        let is_notification = req.id.is_none();
        let resp = dispatch(&req, &runtime, &registry).await;

        if is_notification {
            continue;
        }

        if let Some(r) = resp {
            let resp_body = serde_json::to_string(&r)?;
            write_message(&mut out, &resp_body, framing).await?;
        }
    }

    Ok(())
}

async fn dispatch(
    req: &JsonRpcRequest,
    runtime: &Arc<SharedRuntime>,
    registry: &ToolRegistry,
) -> Option<JsonRpcResponse> {
    let id = req.id.clone().unwrap_or(Value::Null);
    match req.method.as_str() {
        "initialize" => Some(handle_initialize(id)),
        "notifications/initialized" => None,
        "tools/list" => Some(handle_tools_list(id, registry)),
        "tools/call" => Some(handle_tools_call(id, &req.params, runtime, registry).await),
        _ => Some(JsonRpcResponse::error(
            id,
            -32601,
            format!("method not found: {}", req.method),
            None,
        )),
    }
}

fn handle_initialize(id: Value) -> JsonRpcResponse {
    JsonRpcResponse::ok(
        id,
        json!({
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "ae-mcp",
                "version": env!("CARGO_PKG_VERSION")
            }
        }),
    )
}

fn handle_tools_list(id: Value, registry: &ToolRegistry) -> JsonRpcResponse {
    let tools: Vec<Value> = registry
        .list()
        .iter()
        .map(|s| {
            json!({
                "name": s.name,
                "description": s.description,
                "inputSchema": s.input_schema,
            })
        })
        .collect();
    JsonRpcResponse::ok(id, json!({ "tools": tools }))
}

async fn handle_tools_call(
    id: Value,
    params: &Value,
    runtime: &Arc<SharedRuntime>,
    registry: &ToolRegistry,
) -> JsonRpcResponse {
    let name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let args = params.get("arguments").cloned().unwrap_or(Value::Null);

    match registry.call(name, args, Arc::clone(runtime)).await {
        Ok(Ok(result)) => JsonRpcResponse::ok(
            id,
            serde_json::to_value(&result).unwrap_or_else(|_| json!({})),
        ),
        Ok(Err(rpc_err)) => JsonRpcResponse::error(id, rpc_err.code, rpc_err.message, rpc_err.data),
        Err(rpc_err) => JsonRpcResponse::error(id, rpc_err.code, rpc_err.message, rpc_err.data),
    }
}
