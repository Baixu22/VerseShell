use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

fn run_server(input: &str, workspace: &Path) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_ae"))
        .arg("--serve")
        .arg("--agent")
        .arg("--cap")
        .arg("all")
        .env("AETHER_WORKSPACE", workspace)
        .env("AETHER_MODE", "agent")
        .env_remove("AETHER_CAPS")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
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
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn op(id: &str, op: &str, args: Value) -> String {
    json!({
        "id": id,
        "agent": "test",
        "op": op,
        "args": args,
        "timeout_ms": 10000,
        "budget": {"max_tokens": 4000}
    })
    .to_string()
        + "\n"
}

#[test]
fn file_view_replace_and_stale_hash() {
    let workspace = std::env::temp_dir().join(format!("vs-1-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let file = workspace.join("sample.txt");
    std::fs::write(&file, "alpha\nbeta\ngamma\n").unwrap();

    let view = op(
        "1",
        "file.view",
        json!({"path": "sample.txt", "cursor": 2, "window": 10}),
    );
    let r = run_server(&view, &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    assert_eq!(r["data"]["total_lines"], 3);
    let hash = r["data"]["content_hash"].as_str().unwrap().to_string();

    let bad = op(
        "2",
        "file.replace_exact",
        json!({
            "path": "sample.txt",
            "old": "beta",
            "new": "BETA",
            "expected_hash": "sha256:deadbeef"
        }),
    );
    let r2 = run_server(&bad, &workspace).remove(0);
    assert_eq!(r2["ok"], false);
    assert_eq!(r2["error"]["code"], "E_STALE_HASH");
    // TF-0005: structured hash fields for one-step retry
    assert!(
        r2["data"]["actual_hash"].is_string(),
        "E_STALE_HASH must expose actual_hash: {r2}"
    );
    assert!(
        r2["data"]["expected_hash"].is_string(),
        "E_STALE_HASH must expose expected_hash: {r2}"
    );
    // TF-0005: suggested_next carries one-step retry with actual_hash filled in
    let retry_next = r2["suggested_next"].as_array().cloned().unwrap_or_default();
    assert!(!retry_next.is_empty(), "E_STALE_HASH must expose suggested_next: {r2}");
    let first = &retry_next[0];
    assert_eq!(first["op"], "file.replace_exact");
    assert_eq!(first["args"]["expected_hash"], r2["data"]["actual_hash"]);
    // One-step retry using actual_hash from the failure — no file.view required.
    let retry_args = first["args"].clone();
    let r_retry = run_server(&op("2b", "file.replace_exact", retry_args), &workspace).remove(0);
    assert_eq!(r_retry["ok"], true, "one-step retry with actual_hash must succeed: {r_retry}");
    assert_eq!(r_retry["data"]["applied"], true);
    let content = std::fs::read_to_string(&file).unwrap();
    assert!(content.contains("BETA"));
    assert!(!content.contains("beta"));

    // Restore for the subsequent expected_hash=hash path.
    std::fs::write(&file, "alpha\nbeta\ngamma\n").unwrap();

    let good = op(
        "3",
        "file.replace_exact",
        json!({
            "path": "sample.txt",
            "old": "beta",
            "new": "BETA",
            "expected_hash": hash
        }),
    );
    let r3 = run_server(&good, &workspace).remove(0);
    assert_eq!(r3["ok"], true, "{r3}");
    assert_eq!(r3["data"]["applied"], true);
    let content = std::fs::read_to_string(&file).unwrap();
    assert!(content.contains("BETA"));
    assert!(!content.contains("beta"));

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn file_read_many_reads_several_files_with_hashes() {
    let workspace = std::env::temp_dir().join(format!("vs-rm-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(workspace.join("src")).unwrap();
    std::fs::write(workspace.join("a.txt"), "alpha\nbeta\n").unwrap();
    std::fs::write(workspace.join("src/b.txt"), "one\ntwo\nthree\n").unwrap();

    let req = op(
        "1",
        "file.read_many",
        json!({"paths": ["a.txt", "src/b.txt"], "window": 10}),
    );
    let r = run_server(&req, &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    assert_eq!(r["data"]["count"], 2);
    assert_eq!(r["data"]["errors"], 0);
    let files = r["data"]["files"].as_array().unwrap();
    assert_eq!(files[0]["path"], "a.txt");
    assert_eq!(files[0]["total_lines"], 2);
    assert_eq!(files[0]["start_line"], 1);
    assert!(files[0]["content_hash"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));
    assert_eq!(files[1]["path"], "src/b.txt");
    assert_eq!(files[1]["total_lines"], 3);

    // A missing entry is reported per file instead of failing the batch.
    let partial = op(
        "2",
        "file.read_many",
        json!({"paths": ["a.txt", "missing.txt"]}),
    );
    let r2 = run_server(&partial, &workspace).remove(0);
    assert_eq!(r2["ok"], true, "{r2}");
    assert_eq!(r2["data"]["errors"], 1);
    assert!(r2["data"]["files"][1]["error"].is_string());

    // An empty list is a bad argument, not an empty success.
    let empty = op("3", "file.read_many", json!({"paths": []}));
    let r3 = run_server(&empty, &workspace).remove(0);
    assert_eq!(r3["ok"], false);
    assert_eq!(r3["error"]["code"], "E_BAD_ARG");

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn file_replace_exact_ambiguous_match() {
    let workspace = std::env::temp_dir().join(format!("vs-1a-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    std::fs::write(workspace.join("dup.txt"), "x foo y foo z\n").unwrap();

    let r = run_server(
        &op(
            "1",
            "file.replace_exact",
            json!({"path": "dup.txt", "old": "foo", "new": "bar"}),
        ),
        &workspace,
    )
    .remove(0);
    assert_eq!(r["ok"], false, "{r}");
    assert_eq!(r["error"]["code"], "E_AMBIGUOUS");
    // TF-0005: ambiguous match must expose occurrence count + candidates for one-step recovery
    assert!(
        r["data"]["match_count"].is_number() || r["data"]["occurrences"].is_number(),
        "E_AMBIGUOUS must expose match_count/occurrences: {r}"
    );
    let matches = r["data"]["matches"].as_array().expect("matches[] required");
    assert!(matches.len() >= 2, "expected >=2 matches: {matches:?}");
    for m in matches {
        assert!(m["line"].is_number(), "match.line required: {m}");
        assert!(m["offset"].is_number(), "match.offset required: {m}");
        assert!(m["snippet"].is_string(), "match.snippet required: {m}");
    }
    assert!(
        !r["suggested_next"].as_array().cloned().unwrap_or_default().is_empty(),
        "E_AMBIGUOUS must expose suggested_next: {r}"
    );
    assert_eq!(
        std::fs::read_to_string(workspace.join("dup.txt")).unwrap(),
        "x foo y foo z\n"
    );

    // TF-0005: one-step retry by widening old — no file.view required.
    let retry = run_server(
        &op(
            "2",
            "file.replace_exact",
            json!({"path": "dup.txt", "old": "x foo y", "new": "x bar y"}),
        ),
        &workspace,
    )
    .remove(0);
    assert_eq!(retry["ok"], true, "widened old should retry in one step: {retry}");
    assert_eq!(
        std::fs::read_to_string(workspace.join("dup.txt")).unwrap(),
        "x bar y foo z\n"
    );

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn file_path_outside_workspace_rejected() {
    let workspace = std::env::temp_dir().join(format!("vs-1w-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();

    let outside = std::env::temp_dir().join(format!("vs-outside-{}", uuid::Uuid::new_v4()));
    std::fs::write(&outside, "secret\n").unwrap();
    let outside_s = outside.to_string_lossy().to_string();

    let r = run_server(
        &op("1", "file.view", json!({"path": outside_s})),
        &workspace,
    )
    .remove(0);
    assert_eq!(r["ok"], false, "{r}");
    let code = r["error"]["code"].as_str().unwrap_or("");
    assert!(
        code == "E_OUTSIDE_WORKSPACE" || code == "E_POLICY" || code == "E_NOT_FOUND",
        "unexpected code {code}: {r}"
    );

    let _ = std::fs::remove_file(outside);
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn file_edit_range_check_rejects_invalid_json() {
    let workspace = std::env::temp_dir().join(format!("vs-1e-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let file = workspace.join("cfg.json");
    std::fs::write(&file, "{\n  \"ok\": true\n}\n").unwrap();

    let r = run_server(
        &op(
            "1",
            "file.edit_range",
            json!({
                "path": "cfg.json",
                "start_line": 1,
                "end_line": 3,
                "replacement": "{ not json",
                "check": true
            }),
        ),
        &workspace,
    )
    .remove(0);
    assert_eq!(r["ok"], false, "{r}");
    assert_eq!(r["error"]["code"], "E_LINT_FAILED");
    assert_eq!(r["data"]["applied"], false);
    assert_eq!(
        std::fs::read_to_string(&file).unwrap(),
        "{\n  \"ok\": true\n}\n"
    );

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn file_remove_trash_and_restore() {
    let workspace = std::env::temp_dir().join(format!("vs-1t-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let file = workspace.join("doomed.txt");
    std::fs::write(&file, "save me").unwrap();

    let rm = op("1", "file.remove", json!({"path": "doomed.txt"}));
    let r = run_server(&rm, &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    assert_eq!(r["data"]["action"], "moved_to_trash");
    let token = r["data"]["restore_token"].as_str().unwrap().to_string();
    assert!(!file.exists());

    let restore = op("2", "tx.restore", json!({"restore_token": token}));
    let r2 = run_server(&restore, &workspace).remove(0);
    assert_eq!(r2["ok"], true, "{r2}");
    assert!(file.exists());
    assert_eq!(std::fs::read_to_string(&file).unwrap(), "save me");

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn tx_begin_write_rollback() {
    let workspace = std::env::temp_dir().join(format!("vs-1x-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let file = workspace.join("tx.txt");
    std::fs::write(&file, "original").unwrap();

    let script = op("1", "tx.begin", json!({}))
        + &op(
            "2",
            "file.replace_exact",
            json!({"path": "tx.txt", "old": "original", "new": "changed"}),
        )
        + &op("3", "tx.rollback", json!({}));
    let responses = run_server(&script, &workspace);
    assert_eq!(responses[0]["ok"], true, "{}", responses[0]);
    assert_eq!(responses[1]["ok"], true, "{}", responses[1]);
    assert_eq!(responses[2]["ok"], true, "{}", responses[2]);
    assert_eq!(std::fs::read_to_string(&file).unwrap(), "original");

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn repo_search_respects_max_items() {
    let workspace = std::env::temp_dir().join(format!("vs-1r-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    for i in 0..5 {
        std::fs::write(
            workspace.join(format!("f{i}.txt")),
            format!("needle line {i}\n"),
        )
        .unwrap();
    }
    let req = op(
        "1",
        "repo.search",
        json!({"query": "needle", "max_items": 2}),
    );
    let r = run_server(&req, &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    assert_eq!(r["data"]["match_count"], 2);
    assert_eq!(r["data"]["truncated"], true);

    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn ops_list_includes_1_0_surface() {
    let workspace = std::env::temp_dir().join(format!("vs-1o-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let r = run_server(&op("1", "ops.list", json!({})), &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    let names: Vec<String> = r["data"]["operations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|o| o["name"].as_str().unwrap().to_string())
        .collect();
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
        assert!(
            names.iter().any(|n| n == need),
            "missing {need} in {names:?}"
        );
    }
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn test_discover_finds_cargo() {
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf();
    let r = run_server(&op("1", "test.discover", json!({})), &workspace).remove(0);
    assert_eq!(r["ok"], true, "{r}");
    let runners = r["data"]["runners"].as_array().unwrap();
    assert!(
        runners.iter().any(|x| x["runner"] == "cargo"),
        "expected cargo runner: {runners:?}"
    );
}
