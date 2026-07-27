//! Runtime discovery operations.
//!
//! This module intentionally exposes only read-only discovery. Approval state
//! is process-global, so grant/revoke remain unavailable over the model-facing
//! JSONL transport until a separately authenticated host-control channel exists.

use super::common::{now, ok};
use crate::artifact::{display_path, DEFAULT_MAX_TOTAL_BYTES, DEFAULT_TTL};
use crate::operation::{
    OperationRegistry, OperationRequest, OperationSpec, OBSERVATION_SCHEMA,
    OPERATION_CATALOG_SCHEMA, SERVER_PROTOCOL,
};
use crate::{capability, safety};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const HANDSHAKE_FEATURES: &[&str] = &["typed_operations", "result_artifacts", "legacy_cmd"];

/// The host binds a named, immutable policy profile to a subprocess through
/// these inherited environment values. The model-facing JSONL transport has no
/// operation that can mutate them. This is deliberately an identity assertion,
/// not a policy-control API: strict enforcement remains owned by `--policy`.
const POLICY_PROFILE_ID_ENV: &str = "VERSESHELL_POLICY_PROFILE_ID";
const POLICY_PROFILE_DIGEST_ENV: &str = "VERSESHELL_POLICY_PROFILE_DIGEST";

fn policy_profile_binding() -> Value {
    let id = std::env::var(POLICY_PROFILE_ID_ENV).ok();
    let digest = std::env::var(POLICY_PROFILE_DIGEST_ENV).ok();
    match (id, digest) {
        (Some(id), Some(digest)) if !id.trim().is_empty() && is_sha256_digest(&digest) => {
            json!({ "id": id, "digest": digest })
        }
        _ => Value::Null,
    }
}

fn is_sha256_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

pub fn specs() -> Vec<OperationSpec> {
    vec![OperationSpec {
        name: "runtime.handshake",
        mcp_name: "runtime_handshake",
        description: "Return the authoritative typed ACI runtime handshake and ordered operation catalog identity.",
        effect: "meta",
        capability: "meta",
        input_schema: schema_empty,
        handler: execute_handshake,
    }]
}

fn schema_empty() -> Value {
    json!({"type":"object","additionalProperties":false,"properties":{}})
}

fn execute_handshake(req: &OperationRequest) -> crate::operation::Observation {
    let start = now();
    let registry = OperationRegistry::new();
    let root = safety::workspace_root();
    let canonical = root.canonicalize().unwrap_or(root);
    let mut normalized = display_path(&canonical);
    if cfg!(windows) {
        normalized = normalized.to_ascii_lowercase();
    }
    let workspace_id = format!(
        "ws_sha256_{}",
        hex::encode(Sha256::digest(normalized.as_bytes()))
    );
    let policy_mode = match safety::current_mode() {
        safety::Mode::Human => "human",
        safety::Mode::Agent => {
            if std::env::var("AETHER_POLICY").ok().as_deref() == Some("permissive") {
                "agent_permissive"
            } else {
                "agent_strict"
            }
        }
    };
    let catalog = registry.catalog();
    let max_concurrency = std::env::var("AE_MAX_CONCURRENCY")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(4);
    let data = json!({
        "crate_version": env!("CARGO_PKG_VERSION"),
        "runtime_version": env!("CARGO_PKG_VERSION"),
        "server_protocol": SERVER_PROTOCOL,
        "observation_schema": OBSERVATION_SCHEMA,
        "operation_catalog_schema": OPERATION_CATALOG_SCHEMA,
        "workspace": {
            "id": workspace_id,
            "canonical": true
        },
        "capabilities": {
            "mode": capability::current_mode_str(),
            "granted": capability::current_capabilities()
        },
        "policy_mode": policy_mode,
        "policy_profile": policy_profile_binding(),
        "artifact_defaults": {
            "ttl_seconds": DEFAULT_TTL.as_secs(),
            "max_total_bytes": DEFAULT_MAX_TOTAL_BYTES
        },
        "max_concurrency": max_concurrency,
        "operation_catalog": {
            "digest": registry.catalog_digest(),
            "count": catalog.len()
        },
        "features": HANDSHAKE_FEATURES
    });
    ok(req, "runtime", data, &["meta"], &["meta"], start)
}
