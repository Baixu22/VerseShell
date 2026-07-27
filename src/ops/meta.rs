//! Meta ops for session observation ledger (reference context).

use super::common::{arg_str, arg_u64, audit, now, ok};
use crate::observation_ledger;
use crate::operation::{Observation, OperationRequest, OperationSpec};
use crate::safety::Effect;
use serde_json::json;

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "ops.observation_recent",
            mcp_name: "ops_observation_recent",
            description:
                "Return recent observation summaries for this agent session (reference context).",
            effect: "meta",
            capability: "meta",
            input_schema: schema_recent,
            handler: execute_recent,
        },
        OperationSpec {
            name: "ops.observation_open_errors",
            mcp_name: "ops_observation_open_errors",
            description:
                "Paths with unresolved error diagnostics in the session observation ledger.",
            effect: "meta",
            capability: "meta",
            input_schema: schema_empty,
            handler: execute_open_errors,
        },
    ]
}

fn schema_empty() -> serde_json::Value {
    json!({"type":"object","properties":{
        "agent":{"type":"string"}
    }})
}

fn schema_recent() -> serde_json::Value {
    json!({
        "type":"object",
        "properties":{
            "limit":{"type":"integer","default":16},
            "agent":{"type":"string"}
        }
    })
}

fn execute_recent(req: &OperationRequest) -> Observation {
    let start = now();
    let limit = arg_u64(&req.args, "limit", 16) as usize;
    let agent = arg_str(&req.args, "agent").unwrap_or_else(|| req.agent.clone());
    let entries = observation_ledger::recent(&agent, limit);
    audit(
        "ops.observation_recent",
        Effect::ReadLocal,
        "allow",
        &agent,
        json!({"count": entries.len()}),
    );
    ok(
        req,
        "meta",
        json!({"agent": agent, "entries": entries, "count": entries.len()}),
        &["meta"],
        &["meta"],
        start,
    )
}

fn execute_open_errors(req: &OperationRequest) -> Observation {
    let start = now();
    let agent = arg_str(&req.args, "agent").unwrap_or_else(|| req.agent.clone());
    let open = observation_ledger::open_error_paths(&agent);
    audit(
        "ops.observation_open_errors",
        Effect::ReadLocal,
        "allow",
        &agent,
        json!({"count": open.len()}),
    );
    ok(
        req,
        "meta",
        json!({"agent": agent, "open_errors": open, "count": open.len()}),
        &["meta"],
        &["meta"],
        start,
    )
}
