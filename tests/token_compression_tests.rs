//! Large-noise token compression stress tests.
//! Measures compression_ratio = 1 - agent_tokens / raw_tokens.
//! Target: compression_ratio >= 0.7 for large logs (raw_tokens >= 2000)
//!   AND critical diagnostics preserved.

use std::fs;
use std::path::PathBuf;
use verseshell::reducers::{reduce_for_profile, ReduceOutput};

fn adv_fixture(name: &str) -> String {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p.push("reducers");
    p.push("adversarial");
    p.push(name);
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
}

fn rough_token_count(text: &str) -> usize {
    // 1 token ~ 4 chars for English/ASCII; good enough for compression ratio.
    let byte_len = text.len();
    if byte_len <= 1 {
        byte_len
    } else {
        (byte_len as f64 * 0.25).ceil() as usize
    }
}

fn agent_payload_tokens(out: &ReduceOutput) -> usize {
    let summary_tokens = rough_token_count(out.summary.as_deref().unwrap_or(""));
    let diag_json = serde_json::to_string(&out.diagnostics).unwrap_or_default();
    let diag_tokens = rough_token_count(&diag_json);
    summary_tokens + diag_tokens
}

fn compression_ratio(raw_tokens: usize, agent_tokens: usize) -> f64 {
    if raw_tokens == 0 {
        return 0.0;
    }
    let ratio = 1.0 - (agent_tokens as f64 / raw_tokens as f64);
    (ratio * 10000.0).round() / 10000.0
}

#[test]
fn cargo_large_noise_high_compression() {
    let text = adv_fixture("cargo_large_noise.txt");
    let raw_tokens = rough_token_count(&text);

    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    let agent_tokens = agent_payload_tokens(&out);
    let ratio = compression_ratio(raw_tokens, agent_tokens);

    println!(
        "cargo_large_noise: raw_tokens={} agent_tokens={} ratio={:.4}",
        raw_tokens, agent_tokens, ratio
    );

    // Large log (>=2000 raw_tokens) must compress >= 0.7
    assert!(
        raw_tokens >= 2000,
        "fixture too small ({} tokens); generate larger noise",
        raw_tokens
    );
    assert!(
        ratio >= 0.7,
        "compression ratio {:.4} < 0.7 for {} tokens raw",
        ratio,
        raw_tokens
    );

    // CRITICAL: Must preserve the one real error (E0502 at src/engine.rs:142)
    let errors: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert_eq!(errors.len(), 1, "must find exactly 1 error in noise");
    let d = &errors[0];
    assert_eq!(d.code.as_deref(), Some("E0502"));
    assert_eq!(d.path.as_deref(), Some("src/engine.rs"));
    assert_eq!(d.line, Some(142));
}

#[test]
fn npm_large_noise_high_compression() {
    let text = adv_fixture("npm_large_noise.txt");
    let raw_tokens = rough_token_count(&text);

    let out = reduce_for_profile("npm_install", &text, true).expect("npm reducer");
    let agent_tokens = agent_payload_tokens(&out);
    let ratio = compression_ratio(raw_tokens, agent_tokens);

    println!(
        "npm_large_noise: raw_tokens={} agent_tokens={} ratio={:.4}",
        raw_tokens, agent_tokens, ratio
    );

    assert!(
        raw_tokens >= 2000,
        "fixture too small ({} tokens)",
        raw_tokens
    );
    assert!(ratio >= 0.7, "compression ratio {:.4} < 0.7", ratio);

    // Must extract structured stats from the noise
    assert_eq!(out.stats.get("added"), Some(&serde_json::json!(1024)));
    assert_eq!(
        out.stats.get("vulnerabilities"),
        Some(&serde_json::json!(0))
    );
    // Summary should NOT contain the HTTP fetch noise
    let s = out.summary.as_ref().unwrap();
    assert!(!s.contains("GET 200"), "summary contains HTTP noise");
    assert!(
        !s.contains("registry.npmjs.org"),
        "summary contains registry noise"
    );
}

#[test]
fn git_diff_large_truncates_body() {
    let text = adv_fixture("git_diff_large.txt");
    let raw_tokens = rough_token_count(&text);

    let out = reduce_for_profile("git", &text, true).expect("git reducer");
    let agent_tokens = agent_payload_tokens(&out);
    let ratio = compression_ratio(raw_tokens, agent_tokens);

    println!(
        "git_diff_large: raw_tokens={} agent_tokens={} ratio={:.4}",
        raw_tokens, agent_tokens, ratio
    );

    assert!(raw_tokens >= 2000, "fixture too small");
    assert!(ratio >= 0.7, "compression ratio {:.4} < 0.7", ratio);

    // Must capture diff stat
    assert_eq!(out.stats.get("files_changed"), Some(&serde_json::json!(51)));
    assert_eq!(out.stats.get("insertions"), Some(&serde_json::json!(750)));
    assert_eq!(out.stats.get("deletions"), Some(&serde_json::json!(125)));
}

#[test]
fn compression_must_not_lose_critical_info() {
    // Anti-false-compression: verify that even with high compression,
    // the critical fixable diagnostics are preserved.
    // Use the cargo noisy failure (has noise + 1 real error E0599)
    let text = adv_fixture("cargo_fail_noisy.txt");
    let raw_tokens = rough_token_count(&text);

    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    let agent_tokens = agent_payload_tokens(&out);
    let ratio = compression_ratio(raw_tokens, agent_tokens);
    println!("cargo_fail_noisy: raw={raw_tokens} agent={agent_tokens} ratio={ratio:.4}");

    // Must find the error with path:line
    let errors: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert_eq!(errors.len(), 1);
    let d = &errors[0];
    assert!(d.path.is_some(), "error must have path");
    assert!(d.line.is_some(), "error must have line");
    assert!(d.code.is_some(), "error should have code (E0599)");
}
