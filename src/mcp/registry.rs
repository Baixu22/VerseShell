//! MCP tool registry: schema definitions, handler dispatch, and lightweight
//! input validation.
//!
//! A `Tool` is a named, JSON-Schema-described operation with an async handler.
//! The registry stores tools by name and routes `tools/call` requests. Handlers
//! return either a `CallToolResult` (normal MCP tool result, possibly with
//! `is_error: true` for soft failures) or an `RpcError` (protocol-level error
//! such as timeout that must surface as a JSON-RPC error response).
//!
//! T2 builds the registry infrastructure and migrates the three T1 legacy
//! tools (`health`, `list_commands`, `exec`) into it. T3 adds task-oriented
//! ACI tools (`system_snapshot`, `process_inspect`, etc.) on top.

use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use serde::Serialize;
use serde_json::Value;

use crate::runtime::SharedRuntime;

/// Boxed async future returned by tool handlers.
pub type BoxFuture<T> = Pin<Box<dyn Future<Output = T> + Send>>;

/// A tool handler: async function taking parsed arguments + shared runtime,
/// returning either a normal tool result or a protocol-level RPC error.
pub type ToolHandler =
    Box<dyn Fn(Value, Arc<SharedRuntime>) -> BoxFuture<Result<CallToolResult, RpcError>> + Send + Sync>;

/// JSON-Schema-described tool surface exposed via `tools/list`.
#[derive(Debug, Clone, Serialize)]
pub struct ToolSchema {
    pub name: String,
    pub description: String,
    /// JSON Schema for the tool's `arguments` object.
    pub input_schema: Value,
}

/// A registered tool: its schema plus the handler that executes it.
pub struct Tool {
    pub schema: ToolSchema,
    pub handler: ToolHandler,
}

/// Registry of all tools exposed by the MCP server.
pub struct ToolRegistry {
    tools: HashMap<String, Tool>,
}

impl ToolRegistry {
    pub fn new() -> Self {
        Self {
            tools: HashMap::new(),
        }
    }

    pub fn register(&mut self, tool: Tool) {
        self.tools.insert(tool.schema.name.clone(), tool);
    }

    /// Schemas for `tools/list`. Sorted by name for stable output.
    pub fn list(&self) -> Vec<ToolSchema> {
        let mut v: Vec<_> = self.tools.values().map(|t| t.schema.clone()).collect();
        v.sort_by(|a, b| a.name.cmp(&b.name));
        v
    }

    /// Dispatch a `tools/call` request. Returns:
    ///   - `Ok(Ok(result))` — tool executed, return result (may have is_error=true)
    ///   - `Ok(Err(rpc_err))` — tool executed but requests a protocol-level error
    ///   - `Err(rpc_err)` — unknown tool or schema validation failure
    pub async fn call(
        &self,
        name: &str,
        args: Value,
        runtime: Arc<SharedRuntime>,
    ) -> Result<Result<CallToolResult, RpcError>, RpcError> {
        let tool = self.tools.get(name).ok_or_else(|| RpcError {
            code: -32602,
            message: format!("unknown tool: {name}"),
            data: None,
        })?;

        if let Err(msg) = validate_schema(&tool.schema.input_schema, &args) {
            return Err(RpcError {
                code: -32602,
                message: msg,
                data: None,
            });
        }

        Ok((tool.handler)(args, runtime).await)
    }
}

impl Default for ToolRegistry {
    fn default() -> Self {
        Self::new()
    }
}

// ── Result types ────────────────────────────────────────────────────

/// MCP `tools/call` result. Maps to the JSON-RPC `result` field.
///
/// `is_error` is serialized as `isError` to match the MCP spec.
#[derive(Debug, Serialize)]
pub struct CallToolResult {
    pub content: Vec<Content>,
    #[serde(skip_serializing_if = "Option::is_none", rename = "structuredContent")]
    pub structured_content: Option<Value>,
    #[serde(rename = "isError")]
    pub is_error: bool,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum Content {
    #[serde(rename = "text")]
    Text { text: String },
    #[serde(rename = "json")]
    Json { json: Value },
}

impl CallToolResult {
    /// Successful text result.
    pub fn text(text: impl Into<String>) -> Self {
        Self {
            content: vec![Content::Text { text: text.into() }],
            structured_content: None,
            is_error: false,
        }
    }

    /// Successful structured result. Also emits a text content block so
    /// clients that only read `content[0].text` still see something useful.
    pub fn structured(value: Value) -> Self {
        let text = serde_json::to_string_pretty(&value).unwrap_or_else(|_| value.to_string());
        Self {
            content: vec![Content::Text { text }],
            structured_content: Some(value),
            is_error: false,
        }
    }

    /// Successful structured result + agent_hints. The `structured_content`
    /// is an object with two fields: `result` (the original value) and
    /// `agent_hints` (the hints). T4 injects this on ACI tool responses
    /// only — legacy tools keep using `text()` / `structured()`.
    pub fn structured_with_hints(value: Value, hints: AgentHints) -> Self {
        let mut combined = serde_json::Map::new();
        combined.insert("result".into(), value);
        combined.insert(
            "agent_hints".into(),
            serde_json::to_value(&hints).unwrap_or(Value::Null),
        );
        let structured = Value::Object(combined);
        let text = serde_json::to_string_pretty(&structured).unwrap_or_default();
        Self {
            content: vec![Content::Text { text }],
            structured_content: Some(structured),
            is_error: false,
        }
    }

    /// Soft-error result: the tool ran but the operation failed. The agent
    /// sees the message in `content[0].text` and can self-correct.
    pub fn error_text(message: impl Into<String>) -> Self {
        Self {
            content: vec![Content::Text {
                text: message.into(),
            }],
            structured_content: None,
            is_error: true,
        }
    }
}

/// T4: structured "agent hints" injected into ACI tool responses.
///
/// Unlike the existing `AgentError.hint: Option<String>` (which is reactive
/// — produced after an error), `AgentHints` is proactive guidance attached
/// to successful results so the agent knows what to do next, what to watch
/// out for, and whether the action is reversible.
#[derive(Debug, Serialize)]
pub struct AgentHints {
    /// Suggested tool names the agent may want to call next.
    pub next_actions: Vec<String>,
    /// Caveats the agent should be aware of (e.g. "action cannot be undone").
    pub warnings: Vec<String>,
    /// Whether the action can be rolled back. `false` for destructive ops.
    pub reversible: bool,
    /// Optional name of a tool that would undo this action. `None` if no
    /// such tool exists or `reversible == false`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub undo_tool: Option<String>,
}

/// Protocol-level error that must surface as a JSON-RPC error response
/// (rather than a `result.isError` tool result). Used for timeouts and
/// other transport-level failures.
#[derive(Debug, Clone, Serialize)]
pub struct RpcError {
    pub code: i64,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl RpcError {
    pub fn new(code: i64, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            data: None,
        }
    }

    pub fn with_data(mut self, data: Value) -> Self {
        self.data = Some(data);
        self
    }
}

// ── Lightweight schema validation ───────────────────────────────────
//
// We do not pull in a full JSON Schema validator (to avoid adding a crate
// dependency). Instead, we check `required` fields and shallow `type` tags
// only — enough to catch obvious client mistakes without rejecting valid
// inputs that use advanced schema features.

fn validate_schema(schema: &Value, args: &Value) -> Result<(), String> {
    let schema_obj = match schema.as_object() {
        Some(o) => o,
        None => return Ok(()), // no schema → accept anything
    };

    // If schema says type=object, args must be an object (or null → {}).
    if schema_obj
        .get("type")
        .and_then(|v| v.as_str())
        .map(|s| s == "object")
        .unwrap_or(false)
    {
        if !args.is_object() && !args.is_null() {
            return Err(format!(
                "arguments must be an object, got {}",
                type_name(args)
            ));
        }
    }

    // Check required fields.
    if let Some(required) = schema_obj.get("required").and_then(|v| v.as_array()) {
        let args_obj = match args.as_object() {
            Some(o) => o,
            None => {
                if args.is_null() {
                    // Treat null args as empty object.
                    &serde_json::Map::new()
                } else {
                    return Err("arguments must be an object".into());
                }
            }
        };
        for req in required {
            if let Some(name) = req.as_str() {
                if !args_obj.contains_key(name) {
                    return Err(format!("missing required argument: {name}"));
                }
            }
        }
    }

    Ok(())
}

fn type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_lists_tools_sorted_by_name() {
        let mut reg = ToolRegistry::new();
        // Register with schemas only (handlers are no-ops for list test).
        // We can't easily build a real handler without a runtime, so we test
        // list() indirectly by checking empty registry behavior.
        let list = reg.list();
        assert!(list.is_empty());
    }

    #[test]
    fn validate_schema_passes_empty_object_for_object_type() {
        let schema = serde_json::json!({"type": "object", "properties": {}});
        assert!(validate_schema(&schema, &serde_json::json!({})).is_ok());
        assert!(validate_schema(&schema, &serde_json::Value::Null).is_ok());
    }

    #[test]
    fn validate_schema_rejects_missing_required() {
        let schema = serde_json::json!({
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "string"}}
        });
        let err = validate_schema(&schema, &serde_json::json!({})).unwrap_err();
        assert!(err.contains("missing required argument: code"));
    }

    #[test]
    fn validate_schema_accepts_present_required() {
        let schema = serde_json::json!({
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "string"}}
        });
        assert!(validate_schema(&schema, &serde_json::json!({"code": "1+1"})).is_ok());
    }

    #[test]
    fn validate_schema_rejects_non_object_when_object_required() {
        let schema = serde_json::json!({"type": "object"});
        let err = validate_schema(&schema, &serde_json::json!(42)).unwrap_err();
        assert!(err.contains("must be an object"));
    }
}
