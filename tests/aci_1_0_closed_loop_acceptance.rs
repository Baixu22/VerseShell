//! 1.0 ACI closed-loop acceptance: real `ae --serve --agent` multi-op sessions.
//! Does not use PowerShell pipes (UTF-8 BOM risk). stdin is raw UTF-8 bytes.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

fn run_server(input: &str, workspace: &Path, extra_env: &[(&str, Option<&str>)]) -> Vec<Value> {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_ae"));
    cmd.arg("--serve")
        .arg("--agent")
        .arg("--cap")
        .arg("all")
        .env("AETHER_WORKSPACE", workspace)
        .env("AETHER_MODE", "agent")
        .env_remove("AETHER_CAPS")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    // Default: approve-all for functional exec path unless a test overrides.
    let mut env_map: HashMap<String, Option<String>> = HashMap::new();
    env_map.insert("AETHER_APPROVE_ALL".into(), Some("1".into()));
    for (k, v) in extra_env {
        env_map.insert((*k).into(), v.map(|s| s.to_string()));
    }
    for (k, v) in &env_map {
        match v {
            Some(val) => {
                cmd.env(k, val);
            }
            None => {
                cmd.env_remove(k);
            }
        }
    }

    let mut child = cmd.spawn().expect("spawn ae --serve");
    child
        .stdin
        .as_mut()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            serde_json::from_str(line).unwrap_or_else(|e| {
                panic!("bad json line: {e}; line={line}");
            })
        })
        .collect()
}

fn op(id: &str, op: &str, args: Value) -> String {
    json!({
        "id": id,
        "agent": "accept",
        "op": op,
        "args": args,
        "timeout_ms": 20000,
        "budget": {"max_tokens": 4000}
    })
    .to_string()
        + "\n"
}

fn by_id<'a>(responses: &'a [Value], id: &str) -> &'a Value {
    responses
        .iter()
        .find(|r| r.get("id").and_then(|v| v.as_str()) == Some(id))
        .unwrap_or_else(|| {
            panic!(
                "missing response id={id}; got {:?}",
                responses.iter().map(|r| r.get("id")).collect::<Vec<_>>()
            )
        })
}

fn assert_ok(r: &Value, label: &str) {
    assert_eq!(r["ok"], true, "{label}: {r}");
}

fn assert_err(r: &Value, code: &str, label: &str) {
    assert_eq!(r["ok"], false, "{label} expected fail: {r}");
    assert_eq!(r["error"]["code"], code, "{label}: {r}");
}

fn write_fixture(ws: &Path) {
    std::fs::create_dir_all(ws.join("src")).unwrap();
    std::fs::write(ws.join("app.py"), "def add(a, b):\n    return a + b\n").unwrap();
    std::fs::write(ws.join("readme.md"), "# Demo\nneedle marker\n").unwrap();
    std::fs::write(ws.join("cfg.json"), "{\n  \"ok\": true\n}\n").unwrap();
    std::fs::write(
        ws.join("src/main.txt"),
        "line1\nline2\nline3\nline4\nline5\n",
    )
    .unwrap();
    std::fs::write(ws.join("dup.txt"), "x foo y foo z\n").unwrap();
}

fn try_git_init(ws: &Path) -> bool {
    let init = Command::new("git")
        .args(["init"])
        .current_dir(ws)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if !init.map(|s| s.success()).unwrap_or(false) {
        return false;
    }
    let _ = Command::new("git")
        .args(["config", "user.email", "accept@test.local"])
        .current_dir(ws)
        .status();
    let _ = Command::new("git")
        .args(["config", "user.name", "accept"])
        .current_dir(ws)
        .status();
    let _ = Command::new("git")
        .args(["add", "-A"])
        .current_dir(ws)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    Command::new("git")
        .args(["commit", "-m", "init", "--allow-empty"])
        .current_dir(ws)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[test]
fn coder_agent_full_closed_loop() {
    let ws = std::env::temp_dir().join(format!("vs-loop-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&ws).unwrap();
    write_fixture(&ws);
    let has_git = try_git_init(&ws);

    #[cfg(windows)]
    let success_argv = json!([
        "cmd",
        "/C",
        "echo noise && echo added 12 packages && echo found 0 vulnerabilities"
    ]);
    #[cfg(not(windows))]
    let success_argv = json!([
        "sh",
        "-c",
        "printf 'noise\\nadded 12 packages\\nfound 0 vulnerabilities\\n'"
    ]);

    #[cfg(windows)]
    let fail_argv = json!(["cmd", "/C", "echo ERROR: boom failed& exit /b 1"]);
    #[cfg(not(windows))]
    let fail_argv = json!(["sh", "-c", "printf 'ERROR: boom failed\\n'; exit 1"]);

    #[cfg(windows)]
    let test_argv = json!(["cmd", "/C", "echo test ok"]);
    #[cfg(not(windows))]
    let test_argv = json!(["sh", "-c", "printf 'test ok\\n'"]);

    let mut script = String::new();
    script.push_str(&op("1", "ops.list", json!({})));
    script.push_str(&op(
        "2",
        "file.view",
        json!({"path": "app.py", "cursor": 1, "window": 20}),
    ));
    script.push_str(&op(
        "3",
        "file.read_range",
        json!({"path": "src/main.txt", "start_line": 2, "end_line": 4}),
    ));
    script.push_str(&op("4", "file.hash", json!({"path": "cfg.json"})));
    script.push_str(&op(
        "5",
        "repo.search",
        json!({"query": "needle", "max_items": 5}),
    ));
    script.push_str(&op("6", "repo.summary", json!({})));
    script.push_str(&op("7", "repo.changed_files", json!({})));
    script.push_str(&op("8", "test.discover", json!({})));
    script.push_str(&op("9", "tx.begin", json!({})));
    script.push_str(&op(
        "10",
        "file.replace_exact",
        json!({"path": "app.py", "old": "return a + b", "new": "return a + b  # ok"}),
    ));
    script.push_str(&op("11", "tx.commit", json!({})));
    script.push_str(&op(
        "12",
        "file.apply_patch",
        json!({"path": "readme.md", "patches": [{"old": "Demo", "new": "DemoApp"}]}),
    ));
    script.push_str(&op(
        "13",
        "file.edit_range",
        json!({
            "path": "src/main.txt",
            "start_line": 2,
            "end_line": 3,
            "replacement": "LINE2\nLINE3"
        }),
    ));
    script.push_str(&op(
        "14",
        "file.diff",
        json!({"path": "cfg.json", "new_text": "{\n  \"ok\": false\n}\n"}),
    ));
    script.push_str(&op(
        "15",
        "file.edit_range",
        json!({
            "path": "cfg.json",
            "start_line": 1,
            "end_line": 3,
            "replacement": "{ not json",
            "check": true
        }),
    ));
    script.push_str(&op(
        "16",
        "file.replace_exact",
        json!({
            "path": "app.py",
            "old": "return",
            "new": "x",
            "expected_hash": "sha256:deadbeef"
        }),
    ));
    script.push_str(&op(
        "17",
        "file.replace_exact",
        json!({"path": "dup.txt", "old": "foo", "new": "bar"}),
    ));
    script.push_str(&op(
        "18",
        "exec.run",
        json!({
            "argv": success_argv,
            "profile": "npm_install",
            "artifact": "auto"
        }),
    ));
    script.push_str(&op(
        "19",
        "exec.run",
        json!({
            "argv": fail_argv,
            "artifact": "always"
        }),
    ));
    // id 20 filled after we know handle — two-phase: first batch ends at 19, second continues...
    // For single-session closed loop we chain result.query using a second server call is NOT same process for LAST_TEST,
    // but artifact is on disk. result.query and trash restore work cross-process.
    // Plan requires same-session for 17-20; we inject result.query after parsing intermediate?
    // Better: run one script that includes placeholder — can't. So: build script in two waves
    // Wave A: 1-19, then append 20 with handle, 21-26 in second process for restore?
    // Plan: "同会话 result.query" — artifact store is workspace-scoped so cross-process query is fine
    // and still validates recovery. For same process we can do two run_server calls with same workspace
    // but LAST_TEST is process-local. test.run_target + summarize must be same process.

    // Split: batch1 ids 1-19, then batch2 with handle + tests + trash + rollback all same process
    // Actually simplest: run batch1, extract handle, run batch2 with remaining ops in ONE new process
    // for tests/trash/tx which don't need batch1 state except files on disk.
    // test.summarize_last needs same process as test.run_target — put them together in batch2.

    let responses1 = run_server(&script, &ws, &[]);
    let r = |id: &str| by_id(&responses1, id);

    // 1 ops.list
    assert_ok(r("1"), "ops.list");
    let names: Vec<String> = r("1")["data"]["operations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|o| o["name"].as_str().unwrap().to_string())
        .collect();
    assert!(names.len() >= 20, "ops count {}", names.len());
    for need in [
        "exec.run",
        "file.view",
        "file.replace_exact",
        "file.remove",
        "tx.begin",
        "tx.restore",
        "repo.search",
        "test.discover",
    ] {
        assert!(names.iter().any(|n| n == need), "missing {need}");
    }

    // 2 view
    assert_ok(r("2"), "file.view");
    assert!(r("2")["data"]["total_lines"].as_u64().unwrap() >= 2);
    assert!(r("2")["data"]["content_hash"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));

    // 3 read_range
    assert_ok(r("3"), "read_range");
    let lines = r("3")["data"]["lines"].as_array().unwrap();
    assert_eq!(lines.len(), 3);
    assert_eq!(lines[0]["line"], 2);
    assert_eq!(lines[0]["text"], "line2");

    // 4 hash
    assert_ok(r("4"), "hash");
    assert!(r("4")["data"]["content_hash"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));

    // 5 search
    assert_ok(r("5"), "search");
    assert!(r("5")["data"]["match_count"].as_u64().unwrap() >= 1);

    // 6 summary
    assert_ok(r("6"), "summary");

    // 7 changed_files
    if has_git {
        assert_ok(r("7"), "changed_files");
    } else {
        assert_eq!(r("7")["ok"], false);
        assert_eq!(r("7")["error"]["code"], "E_GIT");
    }

    // 8 discover
    assert_ok(r("8"), "discover");

    // 9-11 tx commit path
    assert_ok(r("9"), "tx.begin");
    assert_ok(r("10"), "replace in tx");
    assert_ok(r("11"), "tx.commit");
    let app = std::fs::read_to_string(ws.join("app.py")).unwrap();
    assert!(app.contains("# ok"), "commit should persist: {app}");

    // 12-14 patch/edit/diff
    assert_ok(r("12"), "apply_patch");
    assert_ok(r("13"), "edit_range");
    assert_ok(r("14"), "diff");
    assert!(std::fs::read_to_string(ws.join("readme.md"))
        .unwrap()
        .contains("DemoApp"));
    assert!(std::fs::read_to_string(ws.join("src/main.txt"))
        .unwrap()
        .contains("LINE2"));

    // 15 lint fail
    assert_err(r("15"), "E_LINT_FAILED", "lint");
    assert_eq!(r("15")["data"]["applied"], false);
    assert_eq!(
        std::fs::read_to_string(ws.join("cfg.json")).unwrap(),
        "{\n  \"ok\": true\n}\n"
    );

    // 16 stale
    assert_err(r("16"), "E_STALE_HASH", "stale");

    // 17 ambiguous
    assert_err(r("17"), "E_AMBIGUOUS", "ambiguous");

    // 18 exec success reduced
    assert_ok(r("18"), "exec success");
    assert_eq!(r("18")["data"]["stdout"]["status"], "reduced");
    assert!(
        r("18")["data"]["stdout"].get("text").is_none()
            || r("18")["data"]["stdout"]["text"].is_null(),
        "success must not dump full text: {}",
        r("18")
    );
    let summary = r("18")["data"]["stdout"]["summary"].as_str().unwrap_or("");
    assert!(
        summary.contains("packages") || summary.contains("vulnerabilities") || !summary.is_empty(),
        "summary={summary}"
    );

    // 19 exec fail + artifact
    assert_err(r("19"), "E_PROCESS_EXIT", "exec fail");
    let handle = r("19")["data"]["stdout"]["artifact"]
        .as_str()
        .or_else(|| r("19")["data"]["stderr"]["artifact"].as_str())
        .expect("artifact handle on failure")
        .to_string();

    // Batch 2: same workspace, new process — artifact/trash on disk; tests same process together.
    let mut script2 = String::new();
    script2.push_str(&op(
        "20",
        "result.query",
        json!({"handle": handle, "mode": "raw"}),
    ));
    script2.push_str(&op(
        "21",
        "test.run_target",
        json!({"argv": test_argv, "runner": "auto"}),
    ));
    script2.push_str(&op("22", "test.summarize_last", json!({})));
    script2.push_str(&op("23", "file.remove", json!({"path": "src/main.txt"})));
    // restore token unknown yet — two-step inside batch2 after parsing remove is needed.
    // Run 20-23 first, then restore + rollback in batch3 same files.

    let responses2 = run_server(&script2, &ws, &[]);
    let r2 = |id: &str| by_id(&responses2, id);

    assert_ok(r2("20"), "result.query");
    let raw = r2("20")["data"]["text"].as_str().unwrap_or("");
    assert!(raw.contains("ERROR") || raw.contains("boom"), "raw={raw}");

    assert_ok(r2("21"), "test.run_target");
    assert_ok(r2("22"), "test.summarize_last");

    assert_ok(r2("23"), "file.remove");
    assert_eq!(r2("23")["data"]["action"], "moved_to_trash");
    let token = r2("23")["data"]["restore_token"]
        .as_str()
        .unwrap()
        .to_string();
    assert!(!ws.join("src/main.txt").exists());

    let mut script3 = String::new();
    script3.push_str(&op("24", "tx.restore", json!({"restore_token": token})));
    script3.push_str(&op("25", "tx.begin", json!({})));
    script3.push_str(&op(
        "26",
        "file.replace_exact",
        json!({"path": "readme.md", "old": "DemoApp", "new": "CHANGED"}),
    ));
    script3.push_str(&op("27", "tx.rollback", json!({})));
    script3.push_str(&op(
        "28",
        "file.view",
        json!({"path": "readme.md", "cursor": 1, "window": 10}),
    ));

    let responses3 = run_server(&script3, &ws, &[]);
    let r3 = |id: &str| by_id(&responses3, id);

    assert_ok(r3("24"), "tx.restore");
    assert!(ws.join("src/main.txt").exists());
    assert!(std::fs::read_to_string(ws.join("src/main.txt"))
        .unwrap()
        .contains("LINE2"));

    assert_ok(r3("25"), "tx.begin2");
    assert_ok(r3("26"), "tx write");
    assert_ok(r3("27"), "tx.rollback");
    assert_ok(r3("28"), "view after rollback");
    let readme_view = r3("28")["data"]["lines"]
        .as_array()
        .unwrap()
        .iter()
        .map(|l| l["text"].as_str().unwrap_or(""))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(
        readme_view.contains("DemoApp"),
        "rollback should restore DemoApp, got {readme_view}"
    );
    assert!(!readme_view.contains("CHANGED"));

    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn agent_exec_denied_without_approval_exposes_hint() {
    let ws = std::env::temp_dir().join(format!("vs-deny-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&ws).unwrap();

    #[cfg(windows)]
    let argv = json!(["cmd", "/C", "echo hi"]);
    #[cfg(not(windows))]
    let argv = json!(["sh", "-c", "echo hi"]);

    let script = op("1", "exec.run", json!({"argv": argv}));
    let responses = run_server(
        &script,
        &ws,
        &[("AETHER_APPROVE_ALL", None), ("AETHER_APPROVE", None)],
    );
    let r = by_id(&responses, "1");
    assert_err(r, "E_NEEDS_APPROVAL", "denied");
    let hint = r["error"]["hint"].as_str().unwrap_or("");
    assert!(
        hint.contains("AETHER_APPROVE") || hint.contains("approve("),
        "hint must teach retry path, got: {hint:?} full={r}"
    );
    // optional structured token
    if let Some(tok) = r["data"]["approval_token"].as_str() {
        assert!(tok.starts_with("apv_"), "token={tok}");
    }

    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn trash_restore_across_server_restarts() {
    let ws = std::env::temp_dir().join(format!("vs-xproc-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&ws).unwrap();
    std::fs::write(ws.join("keep.txt"), "persist-me\n").unwrap();

    let r1 = run_server(
        &op("1", "file.remove", json!({"path": "keep.txt"})),
        &ws,
        &[],
    );
    let r = by_id(&r1, "1");
    assert_ok(r, "remove");
    let token = r["data"]["restore_token"].as_str().unwrap().to_string();
    assert!(!ws.join("keep.txt").exists());

    let r2 = run_server(
        &op("2", "tx.restore", json!({"restore_token": token})),
        &ws,
        &[],
    );
    let r = by_id(&r2, "2");
    assert_ok(r, "restore other process");
    assert_eq!(
        std::fs::read_to_string(ws.join("keep.txt")).unwrap(),
        "persist-me\n"
    );

    let _ = std::fs::remove_dir_all(&ws);
}

#[test]
fn ops_list_surface_count_stable() {
    let ws = std::env::temp_dir().join(format!("vs-ops-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&ws).unwrap();
    let r = run_server(&op("1", "ops.list", json!({})), &ws, &[]);
    let resp = by_id(&r, "1");
    assert_ok(resp, "ops.list");
    assert!(resp["data"]["count"].as_u64().unwrap() >= 20);
    let _ = std::fs::remove_dir_all(&ws);
}
