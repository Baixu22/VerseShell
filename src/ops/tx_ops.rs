//! Transaction typed operations wrapping crate::tx and trash restore.

use super::common::{arg_str, audit, err, now, ok, require_capability};
use super::trash;
use crate::operation::{Observation, OperationRequest, OperationSpec};
use crate::safety::Effect;
use crate::tx;
use serde_json::json;

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "tx.begin",
            mcp_name: "tx_begin",
            description: "Begin a filesystem transaction. Nested begins are supported.",
            effect: "tx.begin",
            capability: "file.write",
            input_schema: schema_empty,
            handler: execute_begin,
        },
        OperationSpec {
            name: "tx.commit",
            mcp_name: "tx_commit",
            description: "Commit the innermost filesystem transaction frame.",
            effect: "tx.commit",
            capability: "file.write",
            input_schema: schema_empty,
            handler: execute_commit,
        },
        OperationSpec {
            name: "tx.rollback",
            mcp_name: "tx_rollback",
            description: "Roll back the innermost filesystem transaction frame.",
            effect: "tx.rollback",
            capability: "file.write",
            input_schema: schema_empty,
            handler: execute_rollback,
        },
        OperationSpec {
            name: "tx.status",
            mcp_name: "tx_status",
            description: "Report whether a filesystem transaction is active.",
            effect: "tx.status",
            capability: "file.read",
            input_schema: schema_empty,
            handler: execute_status,
        },
        OperationSpec {
            name: "tx.restore",
            mcp_name: "tx_restore",
            description: "Restore a trash:// token produced by agent-mode file.remove.",
            effect: "tx.restore",
            capability: "file.write",
            input_schema: schema_restore,
            handler: execute_restore,
        },
        OperationSpec {
            name: "ops.list",
            mcp_name: "ops_list",
            description: "List registered typed operations (name, mcp_name, effect, description).",
            effect: "meta",
            capability: "meta",
            input_schema: schema_empty,
            handler: execute_ops_list,
        },
    ]
}

fn schema_empty() -> serde_json::Value {
    json!({"type":"object","properties":{}})
}
fn schema_restore() -> serde_json::Value {
    json!({
        "type":"object",
        "required":["restore_token"],
        "properties":{"restore_token":{"type":"string"}}
    })
}

fn execute_begin(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") { return o; }
    match tx::begin() {
        Ok(id) => {
            audit("tx.begin", Effect::WriteLocal, "allow", &id, json!({"depth": tx::depth()}));
            ok(
                req,
                "tx",
                json!({"tx_id": id, "depth": tx::depth(), "active": true}),
                &["tx.begin"],
                &["file.write"],
                start,
            )
        }
        Err(e) => err(req, "tx", "E_TX", e.to_string(), start),
    }
}

fn execute_commit(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") { return o; }
    match tx::commit() {
        Ok(ops) => {
            audit("tx.commit", Effect::WriteLocal, "allow", "tx", json!({"ops": ops}));
            ok(
                req,
                "tx",
                json!({"committed_ops": ops, "active": tx::is_active(), "depth": tx::depth()}),
                &["tx.commit"],
                &["file.write"],
                start,
            )
        }
        Err(e) => err(req, "tx", "E_TX", e.to_string(), start),
    }
}

fn execute_rollback(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") { return o; }
    match tx::rollback() {
        Ok(n) => {
            audit("tx.rollback", Effect::WriteLocal, "allow", "tx", json!({"restored": n}));
            ok(
                req,
                "tx",
                json!({"restored_paths": n, "active": tx::is_active(), "depth": tx::depth()}),
                &["tx.rollback"],
                &["file.write"],
                start,
            )
        }
        Err(e) => err(req, "tx", "E_TX", e.to_string(), start),
    }
}

fn execute_status(req: &OperationRequest) -> Observation {
    let start = now();
    let status = tx::status();
    ok(
        req,
        "tx",
        json!({
            "active": tx::is_active(),
            "depth": tx::depth(),
            "tx_id": status.as_ref().map(|s| s.0.clone()),
            "ops": status.map(|s| s.1).unwrap_or(0)
        }),
        &["tx.status"],
        &["file.read"],
        start,
    )
}

fn execute_restore(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "file_write") { return o; }
    let token = match arg_str(&req.args, "restore_token") {
        Some(t) => t,
        None => return err(req, "tx", "E_BAD_ARG", "restore_token is required", start),
    };
    match trash::restore(&token) {
        Ok(path) => ok(
            req,
            "tx",
            json!({
                "restored": true,
                "path": crate::artifact::display_path(&path),
                "restore_token": token
            }),
            &["tx.restore"],
            &["file.write"],
            start,
        ),
        Err(e) => err(req, "tx", "E_RESTORE", e, start),
    }
}

fn execute_ops_list(req: &OperationRequest) -> Observation {
    let start = now();
    let registry = crate::operation::OperationRegistry::new();
    let ops: Vec<serde_json::Value> = registry
        .list()
        .into_iter()
        .map(|s| {
            json!({
                "name": s.name,
                "mcp_name": s.mcp_name,
                "effect": s.effect,
                "capability": s.capability,
                "description": s.description
            })
        })
        .collect();
    ok(
        req,
        "meta",
        json!({"operations": ops, "count": ops.len()}),
        &["meta"],
        &["meta"],
        start,
    )
}
