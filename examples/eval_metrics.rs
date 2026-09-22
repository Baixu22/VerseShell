//! Machine-checkable eval metrics for claim_gate (task-forest TF-0008).
//!
//! Reads `eval/manifest.json`, runs the real semantic reducers over every
//! fixture/adversarial entry that expects failure, probes the real op
//! registry for E_STALE_HASH / E_AMBIGUOUS structured recovery fields, and
//! prints one JSON document (verseshell.eval-metrics/v1) to stdout.
//!
//! Usage:
//!     cargo run --example eval_metrics            # JSON on stdout
//!     cargo run --example eval_metrics -- --out eval/metrics.json

use serde_json::{json, Value};
use std::io::Write;
use std::path::{Path, PathBuf};
use verseshell::operation::{OperationRegistry, OperationRequest, SuggestedAction};
use verseshell::reducers::{reduce_for_profile, suggested_from_diagnostics, suggested_ops_are_legal};

fn req(op: &str, args: Value) -> OperationRequest {
    OperationRequest {
        id: format!("eval-metrics-{}", op.replace('.', "-")),
        agent: "eval-metrics".into(),
        op: op.into(),
        args,
        timeout_ms: 10_000,
        budget: Default::default(),
    }
}

fn write_text(path: &Path, content: &str) {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).expect("create dir");
    }
    std::fs::write(path, content).expect("write temp file");
}

fn fixture_text(root: &Path, source: &str) -> String {
    std::fs::read_to_string(root.join(source))
        .unwrap_or_else(|e| panic!("manifest source unreadable: {source}: {e}"))
}

/// Every playbook action carries the argument keys its op needs, so an agent
/// can copy it, fill the sketch values, and send it without another doc.
/// An empty playbook is `false`: there is no script to check.
fn playbook_args_complete(actions: &[SuggestedAction]) -> bool {
    if actions.is_empty() {
        return false;
    }
    actions.iter().all(|a| {
        let args = match a.args.as_object() {
            Some(m) if !m.is_empty() => m,
            _ => return false,
        };
        let non_empty = |k: &str| args.get(k).and_then(|v| v.as_str()).is_some_and(|s| !s.is_empty());
        match a.op.as_str() {
            "file.view" | "file.read_range" | "file.hash" => non_empty("path"),
            "file.replace_exact" => non_empty("path") && non_empty("old") && non_empty("new"),
            "file.apply_patch" => non_empty("path") && args.contains_key("patch"),
            "file.edit_range" => non_empty("path"),
            "exec.run" => args.get("argv").and_then(|v| v.as_array()).is_some_and(|a| !a.is_empty()),
            "test.run_target" => non_empty("target"),
            _ => true,
        }
    })
}

/// Repair playbook emitted by the real reducer for one failure fixture.
fn playbook_probe(profile: &str, out: &verseshell::reducers::ReduceOutput) -> Value {
    let actions = suggested_from_diagnostics(profile, &out.diagnostics);
    let ops: Vec<String> = actions.iter().map(|a| a.op.clone()).collect();
    let has_rerun = ops.iter().any(|o| o == "test.run_target" || o == "exec.run");
    json!({
        "suggested_next_ops": ops,
        "suggested_next_count": actions.len(),
        "suggested_next_legal": suggested_ops_are_legal(&actions),
        "suggested_next_has_rerun": has_rerun,
        "suggested_next_arg_keys_ok": playbook_args_complete(&actions),
    })
}

/// Completeness over error diagnostics for one fixture entry.
fn entry_completeness(entry: &Value, root: &Path) -> Value {
    let id = entry["id"].as_str().unwrap_or("?").to_string();
    let source = entry["source"].as_str().unwrap_or("?").to_string();
    let expect = &entry["expect"];
    let profile = expect["profile"].as_str().unwrap_or("auto").to_string();
    let success = expect["success"].as_bool().unwrap_or(true);
    let diff_class = expect["diff_class"].as_bool().unwrap_or(false);

    if success {
        return json!({
            "id": id, "source": source, "profile": profile,
            "kind": "success_fixture", "diff_class": diff_class,
            "errors": 0, "expected_found_complete": 0,
        });
    }
    let text = fixture_text(root, &source);
    match reduce_for_profile(&profile, &text, success) {
        Some(out) => {
            let errors = out
                .diagnostics
                .iter()
                .filter(|d| d.severity == "error")
                .collect::<Vec<_>>();
            let complete = errors
                .iter()
                .filter(|d| d.expected.is_some() && d.found.is_some())
                .count();
            let playbook = playbook_probe(&profile, &out);
            json!({
                "id": id, "source": source, "profile": profile,
                "kind": "failure_fixture", "reduced": true, "diff_class": diff_class,
                "errors": errors.len(), "expected_found_complete": complete,
                "playbook": playbook,
            })
        }
        None => json!({
            "id": id, "source": source, "profile": profile,
            "kind": "failure_fixture", "reduced": false, "diff_class": diff_class,
            "errors": 0, "expected_found_complete": 0, "playbook": null,
        }),
    }
}

fn main() {
    // Explicit capability allow-list + workspace jail so ops run like the
    // agent surface does (registry calls fail closed otherwise).
    verseshell::capability::init_caps(Some("all"));
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let ws = std::env::temp_dir().join(format!(
        "verseshell-eval-metrics-{}",
        uuid::Uuid::new_v4().simple()
    ));
    std::env::set_var("AETHER_WORKSPACE", &ws);
    std::fs::create_dir_all(&ws).expect("create temp workspace");

    let manifest_path = root.join("eval/manifest.json");
    let manifest: Value = serde_json::from_str(
        &std::fs::read_to_string(&manifest_path)
            .unwrap_or_else(|e| panic!("read {}: {e}", manifest_path.display())),
    )
    .expect("parse eval/manifest.json");

    // ── 1) Diagnostic expected/found completeness over manifest fixtures ──
    let mut per_entry = Vec::new();
    let mut total_errors = 0usize;
    let mut complete_errors = 0usize;
    // diff_class subset: fixtures whose tool output actually contains an
    // expected/found pair (pytest assert `==`, cargo E0308 mismatch). Other
    // failure classes (git fatal, npm ENOENT, panics) have no pair to extract
    // and are reported but excluded from the C3 rate.
    let mut diff_total = 0usize;
    let mut diff_complete = 0usize;
    for entry in manifest["entries"].as_array().expect("manifest.entries") {
        let kind = entry["kind"].as_str().unwrap_or("");
        if !matches!(kind, "reducer_fixture" | "adversarial_fixture") {
            continue;
        }
        let row = entry_completeness(entry, &root);
        total_errors += row["errors"].as_u64().unwrap_or(0) as usize;
        complete_errors += row["expected_found_complete"].as_u64().unwrap_or(0) as usize;
        if row["diff_class"].as_bool().unwrap_or(false) {
            diff_total += row["errors"].as_u64().unwrap_or(0) as usize;
            diff_complete += row["expected_found_complete"].as_u64().unwrap_or(0) as usize;
        }
        per_entry.push(row);
    }
    let completeness_rate = if total_errors == 0 {
        1.0
    } else {
        complete_errors as f64 / total_errors as f64
    };
    let diff_class_rate = if diff_total == 0 {
        1.0
    } else {
        diff_complete as f64 / diff_total as f64
    };

    // ── 2) One-step recovery probes through the real registry ──
    let registry = OperationRegistry::new();

    // stale hash: view → replace with wrong hash → structured data + retry
    write_text(&ws.join("probe_stale.txt"), "alpha\nbeta\ngamma\n");
    let view = registry.execute(
        req("file.view", json!({"path": "probe_stale.txt", "cursor": 1, "window": 10})),
    );
    assert!(view.ok, "file.view must succeed for the stale-hash probe");
    let stale = registry.execute(req(
        "file.replace_exact",
        json!({
            "path": "probe_stale.txt",
            "old": "beta",
            "new": "BETA",
            "expected_hash": "sha256:deadbeef"
        }),
    ));
    let stale_code = stale.error.as_ref().map(|e| e.code.clone()).unwrap_or_default();
    let stale_data = stale.data.clone().unwrap_or(json!({}));
    let has_actual = stale_data["actual_hash"].is_string();
    let has_expected = stale_data["expected_hash"].is_string();
    // One-step retry: take the failure's own suggested_next and resend it.
    let retry_ok = if stale.suggested_next.is_empty() {
        false
    } else {
        let retry = registry.execute(req(
            "file.replace_exact",
            stale.suggested_next[0].args.clone(),
        ));
        retry.ok
    };

    // ambiguous: three identical lines → matches[] with line/offset/snippet
    write_text(&ws.join("probe_ambiguous.txt"), "beta\nkeep\nbeta\nkeep\nbeta\n");
    let amb = registry.execute(req(
        "file.replace_exact",
        json!({"path": "probe_ambiguous.txt", "old": "beta", "new": "BETA"}),
    ));
    let amb_code = amb.error.as_ref().map(|e| e.code.clone()).unwrap_or_default();
    let amb_data = amb.data.clone().unwrap_or(json!({}));
    let matches = amb_data["matches"].as_array().cloned().unwrap_or_default();
    let matches_structured = !matches.is_empty()
        && matches.iter().all(|m| {
            m["line"].is_u64() && m["offset"].is_u64() && m["snippet"].is_string()
        });
    let widen_ok = {
        let widened = registry.execute(req(
            "file.replace_exact",
            json!({"path": "probe_ambiguous.txt", "old": "beta\nkeep\nbeta", "new": "BETA\nkeep\nBETA"}),
        ));
        widened.ok
    };

    let metrics = json!({
        "schema": "verseshell.eval-metrics/v1",
        "generator": "examples/eval_metrics.rs",
        "manifest": "eval/manifest.json",
        "reducer_diagnostic_completeness": {
            "scope": "error diagnostics produced by failure entries in eval/manifest.json (reducer_fixture + adversarial_fixture); complete = expected AND found both present",
            "complete": complete_errors,
            "total": total_errors,
            "rate": completeness_rate,
            "diff_class": {
                "scope": "entries tagged expect.diff_class=true in eval/manifest.json (pytest assert `==`, cargo E0308 mismatch) — the failure classes whose output contains an expected/found pair",
                "complete": diff_complete,
                "total": diff_total,
                "rate": diff_class_rate,
            },
            "per_entry": per_entry,
        },
        "recovery_probes": {
            "stale_hash": {
                "source": "src/ops/file.rs replace_exact E_STALE_HASH",
                "error_code": stale_code,
                "data_actual_hash_present": has_actual,
                "data_expected_hash_present": has_expected,
                "one_step_retry_from_suggested_next_ok": retry_ok,
            },
            "ambiguous": {
                "source": "src/ops/file.rs replace_exact E_AMBIGUOUS",
                "error_code": amb_code,
                "match_count": amb_data["match_count"].clone(),
                "matches_structured_line_offset_snippet": matches_structured,
                "widen_old_retry_ok": widen_ok,
            }
        }
    });

    let out_path = std::env::args()
        .position(|a| a == "--out")
        .and_then(|i| std::env::args().nth(i + 1));
    match out_path {
        Some(p) => {
            std::fs::write(&p, serde_json::to_vec_pretty(&metrics).unwrap()).expect("write metrics");
            eprintln!("metrics written: {p}");
        }
        None => {
            let stdout = std::io::stdout();
            let mut lock = stdout.lock();
            writeln!(lock, "{}", serde_json::to_string_pretty(&metrics).unwrap())
                .expect("write stdout");
        }
    }

    let _ = std::fs::remove_dir_all(&ws);
}
