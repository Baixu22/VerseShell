//! Reproducible measurement of the compact protocol against JSON (claim C9).
//!
//! Mirrors the two real server paths in `src/server.rs`:
//!   * observation: compact `O <encode_value(...)>` vs `serde_json::to_string(observation)`
//!   * response:    compact `encode_response(&AgentResponse)` vs the JSON `StreamDone` body
//!
//! Inputs are real: one `ops.list` observation executed through the live
//! `OperationRegistry`, one observation per large-noise / noisy-failure reducer
//! fixture, and two response envelopes built from those values.
//!
//! Sizes are reported twice: raw bytes, and the `ceil(len / 4)` token proxy the
//! repo already uses in `tests/token_compression_tests.rs`. Observation payloads
//! are decoded back and compared with the original, so a size win cannot come
//! from losing data. Response lines have no in-tree decoder, so they are not
//! round-trip checked.
//!
//! Usage:
//!     cargo run --example compact_ratio                  # JSON on stdout
//!     cargo run --example compact_ratio -- --out eval/compact_ratio.json

use serde_json::{json, Map, Value as Json};
use std::path::PathBuf;
use verseshell::compact::{decode_value, encode_value};
use verseshell::operation::{Observation, ObservationMeta, OperationRegistry, OperationRequest};
use verseshell::reducers::{reduce_for_profile, ReduceOutput};
use verseshell::runtime::{AgentResponse, ResponseMeta};
use verseshell::value::Value;

struct Fixture {
    name: &'static str,
    profile: &'static str,
    fixture: &'static str,
    success: bool,
}

/// The same corpus `tests/token_compression_tests.rs` uses for large logs.
const FIXTURES: &[Fixture] = &[
    Fixture { name: "cargo_large_noise", profile: "cargo", fixture: "cargo_large_noise.txt", success: false },
    Fixture { name: "npm_large_noise", profile: "npm_install", fixture: "npm_large_noise.txt", success: true },
    Fixture { name: "git_diff_large", profile: "git", fixture: "git_diff_large.txt", success: true },
    Fixture { name: "cargo_fail_noisy", profile: "cargo", fixture: "cargo_fail_noisy.txt", success: false },
];

fn meta(profile: &str) -> ObservationMeta {
    ObservationMeta {
        elapsed_ms: 0,
        profile: profile.into(),
        token_estimate: 0,
        effects: Vec::new(),
        capabilities_used: Vec::new(),
    }
}

fn response_meta() -> ResponseMeta {
    ResponseMeta {
        elapsed_ms: 3,
        agent: "compact-ratio".into(),
        cache_hit: Some(false),
        budget_used: None,
        session_age_ms: 0,
    }
}

fn fixture_path(fixture: &str) -> PathBuf {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    path.push("tests");
    path.push("fixtures");
    path.push("reducers");
    path.push("adversarial");
    path.push(fixture);
    path
}

/// The observation a coding agent would receive for one reduced run.
fn fixture_observation(case: &Fixture, out: &ReduceOutput) -> Observation {
    let mut stats = Map::new();
    for (key, value) in &out.stats {
        stats.insert(key.clone(), value.clone());
    }
    Observation {
        schema: "verseshell.observation/v1",
        id: format!("compact-ratio-{}", case.name),
        op: "exec.run".into(),
        ok: true,
        status: "ok",
        substitutions: Vec::new(),
        blocked_operation: None,
        blocked_target: None,
        data: Some(json!({
            "profile": case.profile,
            "fixture": case.fixture,
            "summary": out.summary,
            "stats": Json::Object(stats),
        })),
        error: None,
        diagnostics: out.diagnostics.clone(),
        meta: meta(case.profile),
        suggested_next: Vec::new(),
    }
}

/// One real observation from the live op registry (`ops.list`, the catalog).
fn registry_observation() -> Observation {
    let request = OperationRequest {
        id: "compact-ratio-ops-list".into(),
        agent: "compact-ratio".into(),
        op: "ops.list".into(),
        args: json!({}),
        timeout_ms: 10_000,
        budget: Default::default(),
    };
    OperationRegistry::new().execute(request)
}

/// Exactly what `src/server.rs::encode_observation` emits in compact mode.
fn compact_observation(observation: &Observation) -> String {
    let value = serde_json::to_value(observation).unwrap_or_default();
    format!("O {}", encode_value(&Value::from_json(&value)))
}

/// Exactly what `src/server.rs` emits in JSON mode (`StreamDone`).
fn json_response(resp: &AgentResponse) -> String {
    let mut map = Map::new();
    map.insert("type".into(), json!("done"));
    map.insert("id".into(), json!(resp.id));
    map.insert("ok".into(), json!(resp.ok));
    if let Some(value) = &resp.value {
        map.insert("value".into(), value.clone());
    }
    if let Some(error) = &resp.error {
        map.insert("error".into(), serde_json::to_value(error).unwrap_or_default());
    }
    map.insert(
        "meta".into(),
        serde_json::to_value(&resp.meta).unwrap_or_default(),
    );
    serde_json::to_string(&Json::Object(map)).expect("serialize stream done")
}

/// `1 token ~= 4 chars`, identical to the convention in the compression tests.
fn rough_token_count(text: &str) -> usize {
    let bytes = text.len();
    if bytes <= 1 {
        bytes
    } else {
        (bytes as f64 * 0.25).ceil() as usize
    }
}

fn savings(reference: usize, measured: usize) -> f64 {
    if reference == 0 {
        return 0.0;
    }
    let ratio = 1.0 - (measured as f64 / reference as f64);
    (ratio * 10000.0).round() / 10000.0
}

fn case_json(
    name: &str,
    source: &str,
    json_text: &str,
    compact_text: &str,
    roundtrip_ok: Option<bool>,
) -> Json {
    let json_bytes = json_text.len();
    let compact_bytes = compact_text.len();
    let json_tokens = rough_token_count(json_text);
    let compact_tokens = rough_token_count(compact_text);
    json!({
        "name": name,
        "source": source,
        "json_bytes": json_bytes,
        "compact_bytes": compact_bytes,
        "byte_savings": savings(json_bytes, compact_bytes),
        "json_tokens": json_tokens,
        "compact_tokens": compact_tokens,
        "token_savings": savings(json_tokens, compact_tokens),
        "roundtrip_ok": roundtrip_ok,
    })
}

fn aggregate(cases: &[Json]) -> Json {
    let total = |key: &str| -> usize {
        cases
            .iter()
            .map(|c| c[key].as_u64().unwrap_or(0) as usize)
            .sum()
    };
    let json_bytes = total("json_bytes");
    let compact_bytes = total("compact_bytes");
    let json_tokens = total("json_tokens");
    let compact_tokens = total("compact_tokens");
    let byte_savings = savings(json_bytes, compact_bytes);
    let token_savings = savings(json_tokens, compact_tokens);
    let worst_case_savings = cases
        .iter()
        .map(|c| {
            c["byte_savings"]
                .as_f64()
                .unwrap_or(0.0)
                .min(c["token_savings"].as_f64().unwrap_or(0.0))
        })
        .fold(f64::MAX, f64::min);
    json!({
        "case_count": cases.len(),
        "json_bytes": json_bytes,
        "compact_bytes": compact_bytes,
        "byte_savings": byte_savings,
        "json_tokens": json_tokens,
        "compact_tokens": compact_tokens,
        "token_savings": token_savings,
        "worst_case_savings": (worst_case_savings * 10000.0).round() / 10000.0,
        "headline_savings": byte_savings.min(token_savings).min(worst_case_savings),
    })
}

fn main() {
    let mut out_path: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--out" {
            out_path = args.next().map(PathBuf::from);
        }
    }

    // ── observation path ──
    let mut observations: Vec<Json> = Vec::new();
    let mut observation_values: Vec<(String, String, Observation)> = vec![(
        "ops_list_catalog".to_string(),
        "src/operation.rs (OperationRegistry::ops.list)".to_string(),
        registry_observation(),
    )];
    for case in FIXTURES {
        let path = fixture_path(case.fixture);
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
        let reduced = reduce_for_profile(case.profile, &text, case.success)
            .unwrap_or_else(|| panic!("no reducer output for profile {}", case.profile));
        observation_values.push((
            case.name.to_string(),
            format!("tests/fixtures/reducers/adversarial/{}", case.fixture),
            fixture_observation(case, &reduced),
        ));
    }
    for (name, source, observation) in &observation_values {
        let json_text = serde_json::to_string(observation).expect("serialize observation");
        let compact = compact_observation(observation);
        let roundtrip_ok = compact
            .strip_prefix("O ")
            .and_then(|body| decode_value(body).ok())
            .is_some_and(|decoded| {
                decoded == Value::from_json(&serde_json::to_value(observation).unwrap_or_default())
            });
        observations.push(case_json(name, source, &json_text, &compact, Some(roundtrip_ok)));
    }

    // ── response envelope path ──
    let mut responses: Vec<Json> = Vec::new();
    let small_value = json!({
        "path": "src/main.rs",
        "hash": "sha256:2f8a1c9d4b7e6f0a3c5d8e1b4a7f2c9d6e3b0a8f5c2d9e6b3a0f7c4d1e8b5a2f",
        "lines": 1234,
    });
    let big_value = serde_json::to_value(&observation_values[0].2).unwrap_or_default();
    for (name, value) in [("response_small_hash", small_value), ("response_ops_list", big_value)] {
        let resp = AgentResponse {
            id: format!("compact-ratio-{name}"),
            ok: true,
            value: Some(value),
            error: None,
            meta: response_meta(),
            plan: None,
            trace: None,
            rule_decision: None,
        };
        let json_text = json_response(&resp);
        let compact = verseshell::compact::encode_response(&resp);
        responses.push(case_json(name, "src/server.rs (StreamDone vs encode_response)", &json_text, &compact, None));
    }

    let observation_aggregate = aggregate(&observations);
    let response_aggregate = aggregate(&responses);
    let all_cases: Vec<Json> = observations.iter().chain(responses.iter()).cloned().collect();
    let overall = aggregate(&all_cases);

    let report = json!({
        "schema": "verseshell.compact-ratio/v1",
        "method": {
            "observation_json": "serde_json::to_string(observation) — JSON-mode server path",
            "observation_compact": "format!(\"O {}\", compact::encode_value(Value::from_json(to_value(observation)))) — compact-mode server path",
            "response_json": "the StreamDone body src/server.rs serializes in JSON mode",
            "response_compact": "compact::encode_response(&AgentResponse)",
            "token_proxy": "ceil(bytes / 4), same convention as tests/token_compression_tests.rs",
            "headline": "min(byte_savings, token_savings, worst per-case savings) — the conservative side",
            "roundtrip": "observation compact bodies are decoded back with compact::decode_value and compared with the original; response lines have no in-tree decoder and are not round-trip checked",
        },
        "families": [
            {"kind": "observation", "aggregate": observation_aggregate, "cases": observations},
            {"kind": "response", "aggregate": response_aggregate, "cases": responses},
        ],
        "overall": overall,
    });

    let text = serde_json::to_string_pretty(&report).expect("serialize report");
    if let Some(path) = out_path {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).expect("create output dir");
        }
        std::fs::write(&path, format!("{text}\n")).expect("write report");
        println!("wrote {}", path.display());
    } else {
        println!("{text}");
    }
}
