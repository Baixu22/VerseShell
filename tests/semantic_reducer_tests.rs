//! Semantic reducer quality gates (fixtures + diagnostics integrity).

use std::fs;
use std::path::PathBuf;
use verseshell::reducers::{reduce_for_profile, suggested_from_diagnostics};

fn fixture(name: &str) -> String {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.push("tests");
    p.push("fixtures");
    p.push("reducers");
    p.push(name);
    fs::read_to_string(&p).unwrap_or_else(|e| panic!("read {}: {e}", p.display()))
}

#[test]
fn cargo_e0308_fixture() {
    let text = fixture("cargo_e0308.txt");
    let out = reduce_for_profile("cargo", &text, false).expect("cargo reducer");
    assert!(!out.diagnostics.is_empty());
    let d = &out.diagnostics[0];
    assert_eq!(d.code.as_deref(), Some("E0308"));
    assert_eq!(d.path.as_deref(), Some("src/lib.rs"));
    assert_eq!(d.line, Some(88));
    assert_eq!(d.expected.as_deref(), Some("String"));
    assert_eq!(d.found.as_deref(), Some("&str"));
    let summary = out.summary.as_ref().unwrap();
    assert!(summary.contains("E0308") || summary.contains("error"));
    // token budget: summary should be short
    assert!(summary.len() < 400, "summary too long: {summary}");
    let suggested = suggested_from_diagnostics("cargo", &out.diagnostics);
    assert!(
        suggested.iter().any(|s| s.op == "file.view"),
        "expected file.view suggestion"
    );
}

#[test]
fn cargo_ok_fixture() {
    let text = fixture("cargo_ok.txt");
    let out = reduce_for_profile("cargo", &text, true).expect("cargo reducer");
    let summary = out.summary.as_ref().unwrap();
    assert!(
        summary.to_ascii_lowercase().contains("pass")
            || summary.contains("finished")
            || summary.contains("successfully")
            || summary.contains("cargo")
    );
    assert!(summary.len() < 300);
}

#[test]
fn pytest_fail_fixture() {
    let text = fixture("pytest_fail.txt");
    let out = reduce_for_profile("pytest", &text, false).expect("pytest reducer");
    assert!(!out.diagnostics.is_empty());
    let d = &out.diagnostics[0];
    assert!(d.path.as_deref().unwrap_or("").contains("test_math.py"));
    assert_eq!(d.line, Some(10));
    assert!(out.summary.as_ref().unwrap().contains("failed"));
}

#[test]
fn pytest_ok_fixture() {
    let text = fixture("pytest_ok.txt");
    let out = reduce_for_profile("pytest", &text, true).expect("pytest reducer");
    assert!(out.summary.as_ref().unwrap().contains("passed"));
}

#[test]
fn git_status_and_diff_fixtures() {
    let status = fixture("git_status.txt");
    let out = reduce_for_profile("git", &status, true).expect("git");
    assert!(out.summary.as_ref().unwrap().contains("modified"));
    assert!(out.stats.contains_key("modified"));

    let diff = fixture("git_diffstat.txt");
    let out = reduce_for_profile("git", &diff, true).expect("git diff");
    assert!(out.summary.as_ref().unwrap().contains("3"));
}

#[test]
fn npm_fixtures() {
    let ok = fixture("npm_ok.txt");
    let out = reduce_for_profile("npm_install", &ok, true).expect("npm");
    assert!(
        out.summary.as_ref().unwrap().contains("120")
            || out.summary.as_ref().unwrap().contains("added")
    );

    let fail = fixture("npm_fail.txt");
    let out = reduce_for_profile("npm_install", &fail, false).expect("npm fail");
    assert!(!out.diagnostics.is_empty());
    assert!(
        out.summary
            .as_ref()
            .unwrap()
            .to_ascii_lowercase()
            .contains("fail")
            || out.summary.as_ref().unwrap().contains("npm")
    );
}

#[test]
fn match_guard_does_not_require_env_clone_api() {
    // Behavioral regression: match with guards evaluates via with_frame path.
    use verseshell::env::Env;
    use verseshell::eval::eval_program;
    use verseshell::parser::parse_program;
    use verseshell::value::Value;

    let mut env = Env::new();
    // fill env with many vars so a full clone would be expensive / distinct
    for i in 0..200 {
        env.set_var_unchecked(&format!("v{i}"), Value::Int(i));
    }
    let code = r#"
        match 2 {
            x if x > 1 => "yes",
            _ => "no"
        }
    "#;
    let stmts = parse_program(code).expect("parse");
    let result = eval_program(&stmts, &mut env).expect("eval");
    match result {
        Value::Str(s) => assert_eq!(s, "yes"),
        other => panic!("unexpected {other:?}"),
    }
    // outer bindings still present
    assert_eq!(env.get_var("v0"), Some(&Value::Int(0)));
    assert_eq!(env.get_var("v199"), Some(&Value::Int(199)));
}
