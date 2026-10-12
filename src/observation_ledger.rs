//! Per-session observation ledger (ring buffer) for reference context.
//!
//! Stores compact summaries only — never full command output bodies.

use crate::operation::{Diagnostic, Observation};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

const DEFAULT_CAPACITY: usize = 32;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LedgerEntry {
    pub id: String,
    pub op: String,
    pub ok: bool,
    pub profile: String,
    pub elapsed_ms: u64,
    pub token_estimate: usize,
    pub diagnostic_fingerprint: String,
    pub paths: Vec<String>,
    pub summary: Option<String>,
    pub error_code: Option<String>,
}

lazy_static::lazy_static! {
    static ref LEDGERS: Mutex<HashMap<String, VecDeque<LedgerEntry>>> =
        Mutex::new(HashMap::new());
}

fn fingerprint_diagnostics(diags: &[Diagnostic]) -> String {
    use sha2::{Digest, Sha256};
    let mut parts: Vec<String> = diags
        .iter()
        .map(|d| {
            format!(
                "{}|{}|{}|{}|{}",
                d.severity,
                d.code.as_deref().unwrap_or(""),
                d.path.as_deref().unwrap_or(""),
                d.line.unwrap_or(0),
                d.message
            )
        })
        .collect();
    parts.sort();
    let joined = parts.join("\n");
    let hash = Sha256::digest(joined.as_bytes());
    format!("sha256:{}", hex::encode(&hash[..8]))
}

fn paths_from_observation(obs: &Observation) -> Vec<String> {
    let mut paths: Vec<String> = obs
        .diagnostics
        .iter()
        .filter_map(|d| d.path.clone())
        .collect();
    if let Some(data) = &obs.data {
        if let Some(arr) = data.get("paths").and_then(|v| v.as_array()) {
            for v in arr {
                if let Some(s) = v.as_str() {
                    paths.push(s.to_string());
                }
            }
        }
        if let Some(s) = data.get("path").and_then(|v| v.as_str()) {
            paths.push(s.to_string());
        }
    }
    paths.sort();
    paths.dedup();
    paths.truncate(16);
    paths
}

fn summary_from_observation(obs: &Observation) -> Option<String> {
    if let Some(data) = &obs.data {
        if let Some(s) = data
            .get("stdout")
            .and_then(|v| v.get("summary"))
            .and_then(|v| v.as_str())
        {
            return Some(s.chars().take(200).collect());
        }
        if let Some(s) = data.get("summary").and_then(|v| v.as_str()) {
            return Some(s.chars().take(200).collect());
        }
    }
    obs.error
        .as_ref()
        .map(|e| e.message.chars().take(200).collect())
}

/// Record an observation into the agent session ledger.
pub fn record(agent: &str, obs: &Observation) {
    let entry = LedgerEntry {
        id: obs.id.clone(),
        op: obs.op.clone(),
        ok: obs.ok,
        profile: obs.meta.profile.clone(),
        elapsed_ms: obs.meta.elapsed_ms,
        token_estimate: obs.meta.token_estimate,
        diagnostic_fingerprint: fingerprint_diagnostics(&obs.diagnostics),
        paths: paths_from_observation(obs),
        summary: summary_from_observation(obs),
        error_code: obs.error.as_ref().map(|e| e.code.clone()),
    };
    if let Ok(mut map) = LEDGERS.lock() {
        let q = map
            .entry(agent.to_string())
            .or_insert_with(|| VecDeque::with_capacity(DEFAULT_CAPACITY));
        if q.len() >= DEFAULT_CAPACITY {
            q.pop_front();
        }
        q.push_back(entry);
    }
}

/// Recent ledger entries for an agent (newest last).
pub fn recent(agent: &str, limit: usize) -> Vec<LedgerEntry> {
    let limit = limit.clamp(1, DEFAULT_CAPACITY);
    if let Ok(map) = LEDGERS.lock() {
        if let Some(q) = map.get(agent) {
            let skip = q.len().saturating_sub(limit);
            return q.iter().skip(skip).cloned().collect();
        }
    }
    Vec::new()
}

/// Paths that still appear in recent failed diagnostics (reference context).
pub fn open_error_paths(agent: &str) -> Vec<Value> {
    let entries = recent(agent, DEFAULT_CAPACITY);
    let mut path_fp: HashMap<String, String> = HashMap::new();
    for e in &entries {
        if !e.ok {
            for p in &e.paths {
                path_fp.insert(p.clone(), e.diagnostic_fingerprint.clone());
            }
        } else {
            // successful ops on a path clear it
            for p in &e.paths {
                path_fp.remove(p);
            }
        }
    }
    let mut out: Vec<Value> = path_fp
        .into_iter()
        .map(|(path, fingerprint)| {
            json!({
                "path": path,
                "last_error_fingerprint": fingerprint,
                "still_open": true
            })
        })
        .collect();
    out.sort_by(|a, b| {
        a["path"]
            .as_str()
            .unwrap_or("")
            .cmp(b["path"].as_str().unwrap_or(""))
    });
    out
}

/// Clear ledger for tests.
#[cfg(test)]
pub fn clear_agent(agent: &str) {
    if let Ok(mut map) = LEDGERS.lock() {
        map.remove(agent);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::operation::{Observation, ObservationMeta, OBSERVATION_SCHEMA};

    fn sample(id: &str, ok: bool, path: &str) -> Observation {
        Observation {
            schema: OBSERVATION_SCHEMA,
            id: id.into(),
            op: "exec.run".into(),
            ok,
            data: Some(json!({"path": path, "paths": [path], "stdout": {"summary": "x"}})),
            error: None,
            diagnostics: if ok {
                vec![]
            } else {
                vec![crate::operation::Diagnostic {
                    tool: "cargo".into(),
                    severity: "error".into(),
                    message: "boom".into(),
                    path: Some(path.into()),
                    line: Some(1),
                    column: None,
                    code: Some("E0308".into()),
                    expected: None,
                    found: None,
                    suggested_fix: None,
                }]
            },
            meta: ObservationMeta {
                elapsed_ms: 1,
                profile: "cargo".into(),
                token_estimate: 10,
                effects: vec![],
                capabilities_used: vec![],
            },
            suggested_next: vec![],
        }
    }

    #[test]
    fn ring_and_open_paths() {
        clear_agent("ledger-test");
        record("ledger-test", &sample("1", false, "src/a.rs"));
        record("ledger-test", &sample("2", false, "src/b.rs"));
        let open = open_error_paths("ledger-test");
        assert_eq!(open.len(), 2);
        record("ledger-test", &sample("3", true, "src/a.rs"));
        let open = open_error_paths("ledger-test");
        assert_eq!(open.len(), 1);
        assert_eq!(open[0]["path"], "src/b.rs");
    }
}
