//! Typed lifecycle operations for VerseShell-owned local processes.

use crate::operation::OperationSpec;
use serde_json::{json, Value};

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "process.start",
            mcp_name: "process_start",
            description: "Start an approved argv process owned by this runtime and return its scoped lifecycle identity.",
            effect: "process.spawn",
            capability: "shell.exec",
            input_schema: start_schema,
            handler: crate::process_lifecycle::execute_start,
        },
        OperationSpec {
            name: "process.poll",
            mcp_name: "process_poll",
            description: "Read bounded process output from a monotonic byte cursor and observe lifecycle state.",
            effect: "process.read",
            capability: "shell.exec",
            input_schema: poll_schema,
            handler: crate::process_lifecycle::execute_poll,
        },
        OperationSpec {
            name: "process.write",
            mcp_name: "process_write",
            description: "Write bounded input or EOF to an owned pipe or PTY process.",
            effect: "process.write",
            capability: "shell.exec",
            input_schema: write_schema,
            handler: crate::process_lifecycle::execute_write,
        },
        OperationSpec {
            name: "process.kill",
            mcp_name: "process_kill",
            description: "Idempotently terminate an owned process tree and observe the converged state.",
            effect: "process.kill",
            capability: "shell.exec",
            input_schema: kill_schema,
            handler: crate::process_lifecycle::execute_kill,
        },
        OperationSpec {
            name: "process.list",
            mcp_name: "process_list",
            description: "List lifecycle records scoped to one runtime, agent, session, and workspace.",
            effect: "process.read",
            capability: "shell.exec",
            input_schema: list_schema,
            handler: crate::process_lifecycle::execute_list,
        },
    ]
}

fn owner_properties() -> Value {
    json!({
        "process_id": {"type": "string"},
        "runtime_id": {"type": "string"},
        "agent_id": {"type": "string"},
        "session_id": {"type": "string"}
    })
}

fn start_schema() -> Value {
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["argv", "agent_id", "session_id"],
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "cwd": {"type": "string", "default": "."},
            "agent_id": {"type": "string"},
            "session_id": {"type": "string"},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            "stdin_mode": {"type": "string", "enum": ["null", "pipe"], "default": "null"},
            "stdin": {"type": "string"},
            "stdin_encoding": {"type": "string", "enum": ["utf8", "base64"], "default": "utf8"},
            "stdin_eof": {"type": "boolean", "default": false},
            "pty": {"type": "boolean", "default": false},
            "cols": {"type": "integer", "minimum": 1, "default": 120},
            "rows": {"type": "integer", "minimum": 1, "default": 30},
            "timeout_ms": {"type": "integer", "minimum": 0},
            "max_output_bytes": {"type": "integer", "minimum": 1, "default": 67108864},
            "max_memory_mb": {"type": "integer", "minimum": 1},
            "max_processes": {"type": "integer", "minimum": 1},
            "wait_ms": {"type": "integer", "minimum": 0, "default": 0}
        }
    })
}

fn poll_schema() -> Value {
    let mut properties = owner_properties();
    let object = properties
        .as_object_mut()
        .expect("owner properties are an object");
    object.insert(
        "cursor".into(),
        json!({"type": "integer", "minimum": 0, "default": 0}),
    );
    object.insert(
        "max_bytes".into(),
        json!({"type": "integer", "minimum": 1, "default": 65536}),
    );
    object.insert(
        "wait_ms".into(),
        json!({"type": "integer", "minimum": 0, "default": 0}),
    );
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["process_id", "runtime_id", "agent_id", "session_id"],
        "properties": properties
    })
}

fn write_schema() -> Value {
    let mut properties = owner_properties();
    let object = properties
        .as_object_mut()
        .expect("owner properties are an object");
    object.insert("data".into(), json!({"type": "string", "default": ""}));
    object.insert(
        "encoding".into(),
        json!({"type": "string", "enum": ["utf8", "base64"], "default": "utf8"}),
    );
    object.insert(
        "submit".into(),
        json!({"type": "boolean", "default": false}),
    );
    object.insert("eof".into(), json!({"type": "boolean", "default": false}));
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["process_id", "runtime_id", "agent_id", "session_id"],
        "properties": properties
    })
}

fn kill_schema() -> Value {
    let mut properties = owner_properties();
    let object = properties
        .as_object_mut()
        .expect("owner properties are an object");
    object.insert(
        "reason".into(),
        json!({"type": "string", "default": "manual_cancel"}),
    );
    object.insert(
        "wait_ms".into(),
        json!({"type": "integer", "minimum": 0, "default": 2000}),
    );
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["process_id", "runtime_id", "agent_id", "session_id"],
        "properties": properties
    })
}

fn list_schema() -> Value {
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["runtime_id", "agent_id", "session_id"],
        "properties": {
            "runtime_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "session_id": {"type": "string"},
            "include_terminal": {"type": "boolean", "default": false}
        }
    })
}
