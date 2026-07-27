//! Adversarial stress tests for semantic reducers.
//! Each profile tested: cargo, pytest, git, npm_install.
//! Each gets: success, 2+ failure variants, noisy, malformed.
//! Assertions: diagnostics completeness, summary bounds, body collapse,
//! suggested_next correctness, no false compression.

use std::fs;
use std::path::PathBuf;
use verseshell::reducers::{reduce_for_profile, suggested_from_diagnostics};

fn adv_fixture(name: &str) -> String {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p.push("reducers");
    // If name starts with "../", resolve relative to adversarial/ dir (go up one)
    if name.starts_with("../") {
        p.push(&name[3..]);
    } else {
        p.push("adversarial");
        p.push(name);
    }
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
}

// ── cargo ────────────────────────────────────────────────────

#[test]
fn cargo_adv_success() {
    let text = adv_fixture("../cargo_ok.txt"); // reuse base
    let out = reduce_for_profile("cargo", &text, true).expect("cargo reducer");
    let summary = out.summary.as_ref().unwrap();
    assert!(summary.len() < 300);
    assert!(
        summary.contains("finished") || summary.contains("completed") || summary.contains("cargo")
    );
}

#[test]
fn cargo_adv_fail_e0308() {
    let text = adv_fixture("../cargo_e0308.txt"); // reuse base
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    assert!(!out.diagnostics.is_empty());
    let d = &out.diagnostics[0];
    assert_eq!(d.code.as_deref(), Some("E0308"));
    assert_eq!(d.path.as_deref(), Some("src/lib.rs"));
    assert_eq!(d.line, Some(88));
    assert_eq!(d.expected.as_deref(), Some("String"));
    assert_eq!(d.found.as_deref(), Some("&str"));
    assert!(out.summary.as_ref().unwrap().contains("E0308"));
    // suggested_next must recommend file.view
    let suggested = suggested_from_diagnostics("cargo", &out.diagnostics);
    assert!(
        suggested.iter().any(|s| s.op == "file.view"),
        "expected file.view in suggested_next"
    );
}

#[test]
fn cargo_adv_fail_multi_error() {
    let text = adv_fixture("cargo_fail_multi_error.txt");
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    // Should have at least 2 error diagnostics (E0308, E0277)
    let errs: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert!(errs.len() >= 2, "expected >=2 errors, got {}", errs.len());
    // First error should be E0308 with path:line
    let first = &errs[0];
    assert!(first.code.as_deref().unwrap_or("").starts_with("E"));
    assert!(first.path.is_some(), "first error must have path");
    assert!(first.line.is_some(), "first error must have line");
    // Summary should mention E0308 or heading error
    assert!(out.summary.as_ref().unwrap().contains("error"));
}

#[test]
fn cargo_adv_fail_noisy() {
    let text = adv_fixture("cargo_fail_noisy.txt");
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    // Must find the one real error (E0599: no method `render`)
    let errors: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert_eq!(
        errors.len(),
        1,
        "should find exactly 1 error in noise (E0599), got: {:?}",
        errors.iter().map(|d| &d.message).collect::<Vec<_>>()
    );
    let d = &errors[0];
    assert_eq!(d.code.as_deref(), Some("E0599"));
    assert!(d.path.as_deref().unwrap_or("").contains("server.rs"));
    assert_eq!(d.line, Some(100));
    // Summary must be bounded
    assert!(
        out.summary.as_ref().unwrap().len() < 600,
        "summary too long for noisy cargo"
    );
}

#[test]
fn cargo_adv_fail_panic() {
    let text = adv_fixture("cargo_fail_panic.txt");
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    // Cargo reducer fallback catches panic lines (no structured error header)
    // Must produce at least one diagnostic
    assert!(
        !out.diagnostics.is_empty(),
        "panic log should produce at least 1 diagnostic"
    );
    // Summary is bounded
    if let Some(ref s) = out.summary {
        assert!(s.len() < 500, "panic summary too long");
    }
}

#[test]
fn cargo_adv_fail_malformed() {
    let text = adv_fixture("cargo_fail_malformed.txt");
    // Malformed cargo output (broken lines, backslash path)
    // Should not panic; diagnostics may be partial but summary must exist
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    // The header regex may or may not match the broken "error[E0308]" line
    // but we must not crash and must produce a summary
    assert!(
        out.summary.is_some(),
        "must produce summary even for malformed"
    );
}

// ── pytest ───────────────────────────────────────────────────

#[test]
fn pytest_adv_success() {
    let text = adv_fixture("../pytest_ok.txt"); // reuse base
    let out = reduce_for_profile("pytest", &text, true).expect("pytest reducer");
    assert!(out.summary.as_ref().unwrap().contains("passed"));
}

#[test]
fn pytest_adv_fail() {
    let text = adv_fixture("../pytest_fail.txt"); // reuse base
    let out = reduce_for_profile("pytest", &text, false).expect("pytest reducer");
    assert!(!out.diagnostics.is_empty());
    let d = &out.diagnostics[0];
    assert!(d.path.as_deref().unwrap_or("").contains("test_math.py"));
    assert_eq!(d.line, Some(10));
}

#[test]
fn pytest_adv_fail_multi() {
    let text = adv_fixture("pytest_fail_multi.txt");
    let out = reduce_for_profile("pytest", &text, false).expect("pytest reducer");
    // Two failures: test_parse_empty (line 25) and test_format_output (line 42)
    assert!(
        out.diagnostics.len() >= 2,
        "expected >=2 diagnostics, got {}",
        out.diagnostics.len()
    );
    // First failure should have path+line from the first FAILURES block
    let first = &out.diagnostics[0];
    assert!(
        first
            .path
            .as_deref()
            .unwrap_or("")
            .contains("test_parser.py"),
        "first diag path expected test_parser.py, got {:?}",
        first.path
    );
    assert_eq!(first.line, Some(25));
    // Suggested actions for pytest should include file.view AND test.run_target
    let suggested = suggested_from_diagnostics("pytest", &out.diagnostics);
    assert!(
        suggested.iter().any(|s| s.op == "file.view"),
        "expected file.view in suggested"
    );
    assert!(
        suggested.iter().any(|s| s.op == "test.run_target"),
        "expected test.run_target for pytest failures"
    );
}

#[test]
fn pytest_adv_ok_noisy() {
    let text = adv_fixture("pytest_ok_noisy.txt");
    let out = reduce_for_profile("pytest", &text, true).expect("pytest reducer");
    // Should parse 12 passed, not get confused by ANSI
    assert!(out.summary.as_ref().unwrap().contains("12"));
    assert!(out
        .stats
        .get("passed")
        .map_or(false, |v| v.as_u64() == Some(12)));
    // No false error diagnostics on success
    assert!(out.diagnostics.is_empty());
    assert!(out.summary.as_ref().unwrap().len() < 400);
}

#[test]
fn pytest_adv_fail_no_header() {
    let text = adv_fixture("pytest_fail_no_header.txt");
    let out = reduce_for_profile("pytest", &text, false).expect("pytest reducer");
    // No ____________ FAILURES ____________ header, but has FAILED lines
    // Fallback captures FAILED lines as diagnostics
    assert!(
        !out.diagnostics.is_empty(),
        "fallback should capture FAILED lines"
    );
}

// ── git ──────────────────────────────────────────────────────

#[test]
fn git_adv_success_status() {
    let text = adv_fixture("../git_status.txt");
    let out = reduce_for_profile("git", &text, true).expect("git reducer");
    assert!(out.summary.as_ref().unwrap().contains("modified"));
    assert_eq!(out.stats.get("modified"), Some(&serde_json::json!(2)));
    assert_eq!(out.stats.get("untracked"), Some(&serde_json::json!(1)));
}

#[test]
fn git_adv_success_mixed() {
    let text = adv_fixture("git_status_mixed.txt");
    let out = reduce_for_profile("git", &text, true).expect("git reducer");
    // staged: 1 new file + 1 modified; unstaged: 1 modified + 1 deleted; untracked: 2
    assert_eq!(out.stats.get("modified"), Some(&serde_json::json!(2)));
    assert_eq!(out.stats.get("added"), Some(&serde_json::json!(1)));
    assert_eq!(out.stats.get("deleted"), Some(&serde_json::json!(1)));
    assert_eq!(out.stats.get("untracked"), Some(&serde_json::json!(2)));
    assert!(out.summary.as_ref().unwrap().contains("master"));
}

#[test]
fn git_adv_fail_not_repo() {
    let text = adv_fixture("git_fail_not_repo.txt");
    let out = reduce_for_profile("git", &text, false).expect("git reducer");
    // Should produce error diagnostic with fatal: message
    assert!(!out.diagnostics.is_empty());
    let d = &out.diagnostics[0];
    assert!(d.message.contains("fatal:"));
    assert!(out.summary.as_ref().unwrap().contains("error"));
    // No file.view suggestion since no path
    let suggested = suggested_from_diagnostics("git", &out.diagnostics);
    assert!(
        suggested.is_empty(),
        "fatal: not a git repo should not suggest file.view"
    );
}

#[test]
fn git_adv_fail_conflict() {
    let text = adv_fixture("git_fail_conflict.txt");
    let out = reduce_for_profile("git", &text, false).expect("git reducer");
    // CONFLICT lines should produce diagnostics
    assert!(!out.diagnostics.is_empty());
    let has_conflict = out
        .diagnostics
        .iter()
        .any(|d| d.message.contains("CONFLICT"));
    assert!(has_conflict, "should detect CONFLICT lines");
}

// ── npm_install ──────────────────────────────────────────────

#[test]
fn npm_adv_success() {
    let text = adv_fixture("../npm_ok.txt");
    let out = reduce_for_profile("npm_install", &text, true).expect("npm reducer");
    assert!(out.summary.as_ref().unwrap().contains("added"));
    assert_eq!(
        out.stats.get("vulnerabilities"),
        Some(&serde_json::json!(0))
    );
}

#[test]
fn npm_adv_success_noisy() {
    let text = adv_fixture("npm_ok_noisy.txt");
    let out = reduce_for_profile("npm_install", &text, true).expect("npm reducer");
    // Should extract only structured data, not the deprecation noise
    assert_eq!(out.stats.get("added"), Some(&serde_json::json!(512)));
    assert_eq!(
        out.stats.get("vulnerabilities"),
        Some(&serde_json::json!(3))
    );
    // Summary must be bounded
    assert!(
        out.summary.as_ref().unwrap().len() < 300,
        "noisy npm summary too long"
    );
    // Should NOT contain the raw deprecation noise in summary
    let s = out.summary.as_ref().unwrap();
    assert!(
        !s.contains("deprecated"),
        "summary should not include deprecation noise"
    );
}

#[test]
fn npm_adv_fail_eresolve() {
    let text = adv_fixture("../npm_fail.txt");
    let out = reduce_for_profile("npm_install", &text, false).expect("npm reducer");
    assert!(!out.diagnostics.is_empty());
    assert!(out
        .summary
        .as_ref()
        .unwrap()
        .to_ascii_lowercase()
        .contains("fail"));
}

#[test]
fn npm_adv_fail_enoent() {
    let text = adv_fixture("npm_fail_enoent.txt");
    let out = reduce_for_profile("npm_install", &text, false).expect("npm reducer");
    // Should capture ENOENT error
    let errors: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert!(!errors.is_empty(), "should capture ENOENT");
    let msg = errors[0].message.to_ascii_lowercase();
    assert!(msg.contains("enoent") || msg.contains("no such file"));
    // No false file.view — npm errors don't have path:line
    let suggested = suggested_from_diagnostics("npm_install", &out.diagnostics);
    assert!(
        suggested.is_empty(),
        "npm ENOENT should not suggest file.view"
    );
}

#[test]
fn npm_adv_fail_network() {
    let text = adv_fixture("npm_fail_network.txt");
    let out = reduce_for_profile("npm_install", &text, false).expect("npm reducer");
    // Should capture ETIMEDOUT / 503 errors
    let errors: Vec<_> = out
        .diagnostics
        .iter()
        .filter(|d| d.severity == "error")
        .collect();
    assert!(!errors.is_empty(), "should capture network error");
    let lower = out.summary.as_ref().unwrap().to_ascii_lowercase();
    assert!(lower.contains("fail"), "summary should indicate failure");
}

// ── Summary bounds and invariants ────────────────────────────

#[test]
fn all_failure_summaries_are_bounded() {
    // Every failure fixture must produce a summary ≤ 500 chars
    let cases: Vec<(&str, &str, bool)> = vec![
        ("cargo", "../cargo_e0308.txt", false),
        ("cargo", "cargo_fail_multi_error.txt", false),
        ("cargo", "cargo_fail_noisy.txt", false),
        ("cargo", "cargo_fail_panic.txt", false),
        ("cargo", "cargo_fail_malformed.txt", false),
        ("pytest", "../pytest_fail.txt", false),
        ("pytest", "pytest_fail_multi.txt", false),
        ("pytest", "pytest_fail_no_header.txt", false),
        ("git", "git_fail_not_repo.txt", false),
        ("git", "git_fail_conflict.txt", false),
        ("npm_install", "../npm_fail.txt", false),
        ("npm_install", "npm_fail_enoent.txt", false),
        ("npm_install", "npm_fail_network.txt", false),
    ];
    for (profile, fixture_name, success) in &cases {
        let text = adv_fixture(fixture_name);
        let out =
            reduce_for_profile(profile, &text, *success).expect(&format!("{profile} reducer"));
        if let Some(ref s) = out.summary {
            assert!(
                s.len() <= 500,
                "{profile}/{fixture_name} summary {} chars exceeds 500: {s}",
                s.len()
            );
        }
    }
}

#[test]
fn success_produces_no_error_diagnostics() {
    // On success, diagnostics should only contain warnings, not errors
    let cases: Vec<(&str, &str)> = vec![
        ("cargo", "../cargo_ok.txt"),
        ("pytest", "../pytest_ok.txt"),
        ("npm_install", "../npm_ok.txt"),
        ("npm_install", "npm_ok_noisy.txt"),
        ("git", "../git_status.txt"),
        ("git", "git_status_mixed.txt"),
    ];
    for (profile, fixture_name) in &cases {
        let text = adv_fixture(fixture_name);
        let out = reduce_for_profile(profile, &text, true).expect(profile);
        let errs: Vec<_> = out
            .diagnostics
            .iter()
            .filter(|d| d.severity == "error")
            .collect();
        assert!(
            errs.is_empty(),
            "{profile}/{fixture_name} has {} error diagnostics on success",
            errs.len()
        );
    }
}
