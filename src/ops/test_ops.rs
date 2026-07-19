//! Thin test orchestration ops over exec.run profiles.

use super::common::{arg_str, err, now, ok, require_capability};
use crate::operation::{Observation, ObservationBudget, OperationRegistry, OperationRequest, OperationSpec};
use crate::safety;
use serde_json::json;
use std::sync::Mutex;

lazy_static::lazy_static! {
    static ref LAST_TEST: Mutex<Option<LastTest>> = Mutex::new(None);
}

#[derive(Clone)]
struct LastTest {
    target: String,
    ok: bool,
    summary: String,
    exit_code: i64,
    profile: String,
}

pub fn specs() -> Vec<OperationSpec> {
    vec![
        OperationSpec {
            name: "test.discover",
            mcp_name: "test_discover",
            description: "Detect available test runners (cargo/npm/pytest) in the workspace.",
            effect: "test.discover",
            capability: "file.read",
            input_schema: schema_empty,
            handler: execute_discover,
        },
        OperationSpec {
            name: "test.run_target",
            mcp_name: "test_run_target",
            description: "Run a test target via argv (or auto cargo test / npm test / pytest).",
            effect: "test.run",
            capability: "shell.exec",
            input_schema: schema_run,
            handler: execute_run_target,
        },
        OperationSpec {
            name: "test.summarize_last",
            mcp_name: "test_summarize_last",
            description: "Summarize the last test.run_target result in this process.",
            effect: "test.summary",
            capability: "file.read",
            input_schema: schema_empty,
            handler: execute_summarize_last,
        },
    ]
}

fn schema_empty() -> serde_json::Value {
    json!({"type":"object","properties":{}})
}
fn schema_run() -> serde_json::Value {
    json!({
        "type":"object",
        "properties":{
            "target":{"type":"string","description":"Optional cargo package/test name, pytest node id, or npm script"},
            "runner":{"type":"string","enum":["auto","cargo","npm","pytest"],"default":"auto"},
            "argv":{"type":"array","items":{"type":"string"}},
            "timeout_ms":{"type":"integer","default":120000},
            "max_tokens":{"type":"integer","default":4000}
        }
    })
}

fn execute_discover(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "cat") { return o; }
    let root = safety::workspace_root();
    let mut runners = Vec::new();
    if root.join("Cargo.toml").exists() {
        runners.push(json!({"runner":"cargo","manifest":"Cargo.toml","cmd":["cargo","test"]}));
    }
    if root.join("package.json").exists() {
        runners.push(json!({"runner":"npm","manifest":"package.json","cmd":["npm","test"]}));
    }
    if root.join("pytest.ini").exists()
        || root.join("pyproject.toml").exists()
        || root.join("tests").is_dir()
    {
        runners.push(json!({"runner":"pytest","cmd":["pytest","-q"]}));
    }
    ok(
        req,
        "test",
        json!({"workspace": crate::artifact::display_path(&root), "runners": runners}),
        &["test.discover"],
        &["file.read"],
        start,
    )
}

fn execute_run_target(req: &OperationRequest) -> Observation {
    let start = now();
    if let Err(o) = require_capability(req, "sh") { return o; }
    let runner = arg_str(&req.args, "runner").unwrap_or_else(|| "auto".into());
    let target = arg_str(&req.args, "target");
    let timeout_ms = req
        .args
        .get("timeout_ms")
        .and_then(|v| v.as_u64())
        .unwrap_or(req.timeout_ms.max(30_000));
    let max_tokens = req
        .args
        .get("max_tokens")
        .and_then(|v| v.as_u64())
        .unwrap_or(req.budget.max_tokens as u64) as usize;

    let argv: Vec<String> = if let Some(arr) = req.args.get("argv").and_then(|v| v.as_array()) {
        arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect()
    } else {
        build_argv(&runner, target.as_deref())
    };
    if argv.is_empty() {
        return err(req, "test", "E_BAD_ARG", "could not determine test argv", start);
    }

    let exec_req = OperationRequest {
        id: format!("{}-exec", req.id),
        agent: req.agent.clone(),
        op: "exec.run".into(),
        args: json!({
            "argv": argv,
            "cwd": ".",
            "profile": "auto",
            "artifact": "auto",
            "timeout_ms": timeout_ms,
            "max_tokens": max_tokens
        }),
        timeout_ms,
        budget: ObservationBudget { max_tokens },
    };
    let obs = OperationRegistry::new().execute(exec_req);

    let summary = obs
        .data
        .as_ref()
        .and_then(|d| d.get("stdout"))
        .and_then(|s| s.get("summary").or_else(|| s.get("text")))
        .and_then(|v| v.as_str())
        .or_else(|| {
            obs.data
                .as_ref()
                .and_then(|d| d.get("stderr"))
                .and_then(|s| s.get("summary").or_else(|| s.get("text")))
                .and_then(|v| v.as_str())
        })
        .unwrap_or(if obs.ok { "tests passed" } else { "tests failed" })
        .to_string();
    let exit_code = obs
        .data
        .as_ref()
        .and_then(|d| d.get("exit_code"))
        .and_then(|v| v.as_i64())
        .unwrap_or(if obs.ok { 0 } else { 1 });
    let profile = obs.meta.profile.clone();
    if let Ok(mut g) = LAST_TEST.lock() {
        *g = Some(LastTest {
            target: target.unwrap_or_else(|| argv.join(" ")),
            ok: obs.ok,
            summary: summary.clone(),
            exit_code,
            profile: profile.clone(),
        });
    }

    // Return a test-shaped observation, embedding exec observation data.
    if obs.ok {
        ok(
            req,
            "test",
            json!({
                "ok": true,
                "exit_code": exit_code,
                "summary": summary,
                "profile": profile,
                "exec": obs.data
            }),
            &["test.run"],
            &["shell.exec"],
            start,
        )
    } else {
        crate::operation::Observation::fail_with(
            &req.id,
            &req.op,
            "test",
            obs.error.as_ref().map(|e| e.code.as_str()).unwrap_or("E_TEST_FAILED"),
            obs.error.as_ref().map(|e| e.message.clone()).unwrap_or_else(|| "tests failed".into()),
            true,
            Some(json!({
                "ok": false,
                "exit_code": exit_code,
                "summary": summary,
                "profile": profile,
                "exec": obs.data,
                "approval_token": obs.data.as_ref().and_then(|d| d.get("approval_token")).cloned()
            })),
            obs.diagnostics.clone(),
            obs.suggested_next.clone(),
            obs.error.as_ref().and_then(|e| e.hint.clone()),
            super::common::elapsed_ms(start),
        )
    }
}

fn build_argv(runner: &str, target: Option<&str>) -> Vec<String> {
    let root = safety::workspace_root();
    let auto = if runner == "auto" {
        if root.join("Cargo.toml").exists() {
            "cargo"
        } else if root.join("package.json").exists() {
            "npm"
        } else {
            "pytest"
        }
    } else {
        runner
    };
    match auto {
        "cargo" => {
            let mut v = vec!["cargo".into(), "test".into()];
            if let Some(t) = target {
                if !t.is_empty() {
                    v.push(t.into());
                }
            }
            v.push("--".into());
            v.push("--nocapture".into());
            v
        }
        "npm" => {
            if let Some(t) = target {
                if !t.is_empty() && t != "test" {
                    return vec!["npm".into(), "run".into(), t.into()];
                }
            }
            vec!["npm".into(), "test".into()]
        }
        "pytest" => {
            let mut v = vec!["pytest".into(), "-q".into()];
            if let Some(t) = target {
                if !t.is_empty() {
                    v.push(t.into());
                }
            }
            v
        }
        _ => Vec::new(),
    }
}

fn execute_summarize_last(req: &OperationRequest) -> Observation {
    let start = now();
    match LAST_TEST.lock().ok().and_then(|g| g.clone()) {
        Some(last) => ok(
            req,
            "test",
            json!({
                "target": last.target,
                "ok": last.ok,
                "exit_code": last.exit_code,
                "summary": last.summary,
                "profile": last.profile
            }),
            &["test.summary"],
            &["file.read"],
            start,
        ),
        None => err(req, "test", "E_NO_LAST_TEST", "no prior test.run_target in this process", start),
    }
}
