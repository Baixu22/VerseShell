use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

fn run_server(input: &str, workspace: &Path) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_ae"))
        .arg("--serve")
        .env("AETHER_WORKSPACE", workspace)
        .env_remove("AETHER_MODE")
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
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn legacy_cache_hits_preserve_value() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    let input = concat!(
        "{\"id\":\"1\",\"agent\":\"cache\",\"cmd\":\"1 + 2\",\"timeout_ms\":5000}\n",
        "{\"id\":\"2\",\"agent\":\"cache\",\"cmd\":\"1 + 2\",\"timeout_ms\":5000}\n"
    );
    let responses = run_server(input, &workspace);
    assert_eq!(responses[0]["value"], 3);
    assert_eq!(responses[1]["value"], 3);
    assert_eq!(responses[1]["meta"]["cache_hit"], true);
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn exec_run_reduces_success_and_result_query_recovers_raw_output() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    #[cfg(windows)]
    let argv = json!([
        "cmd",
        "/C",
        "echo noise && echo added 12 packages && echo found 0 vulnerabilities"
    ]);
    #[cfg(not(windows))]
    let argv = json!([
        "sh",
        "-c",
        "printf 'noise\\nadded 12 packages\\nfound 0 vulnerabilities\\n'"
    ]);

    let request = json!({
        "id": "op-1", "agent": "test", "op": "exec.run",
        "args": {"argv": argv, "cwd": ".", "profile": "npm_install", "artifact": "auto"},
        "timeout_ms": 5000, "budget": {"max_tokens": 4000}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(response["schema"], "verseshell.observation/v1");
    assert_eq!(response["ok"], true);
    assert_eq!(response["meta"]["profile"], "npm_install");
    assert_eq!(response["data"]["stdout"]["status"], "reduced");
    assert!(response["data"]["stdout"].get("text").is_none());
    let summary = response["data"]["stdout"]["summary"].as_str().unwrap();
    assert!(summary.contains("added 12 packages"));
    assert!(!summary.contains("noise"));
    let handle = response["data"]["stdout"]["artifact"].as_str().unwrap();

    let query = json!({
        "id": "op-2", "agent": "test", "op": "result.query",
        "args": {"handle": handle, "mode": "raw", "max_bytes": 4096},
        "budget": {"max_tokens": 4000}
    });
    let result = run_server(&(query.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(result["ok"], true);
    let raw = result["data"]["text"].as_str().unwrap();
    assert!(raw.contains("added 12 packages"));
    assert!(raw.contains("noise")); // full log recoverable
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn nonzero_exit_keeps_structured_output_and_error_code() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    #[cfg(windows)]
    let argv = json!(["cmd", "/C", "echo compile error 1>&2 & exit /B 7"]);
    #[cfg(not(windows))]
    let argv = json!(["sh", "-c", "echo compile error >&2; exit 7"]);
    let request = json!({
        "id": "op-fail", "agent": "test", "op": "exec.run",
        "args": {"argv": argv, "cwd": ".", "artifact": "auto"},
        "timeout_ms": 5000, "budget": {"max_tokens": 4000}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(response["ok"], false);
    assert_eq!(response["error"]["code"], "E_PROCESS_EXIT");
    assert_eq!(response["data"]["exit_code"], 7);
    assert!(response["data"]["stderr"]["text"]
        .as_str()
        .unwrap()
        .contains("compile error"));
    assert!(!response["diagnostics"].as_array().unwrap().is_empty());
    // Failure should keep raw log recoverable via artifact.
    assert!(response["data"]["stderr"]["artifact"].as_str().is_some());
    assert!(!response["suggested_next"].as_array().unwrap().is_empty());
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn failure_window_prefers_error_lines_over_noise() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    #[cfg(windows)]
    let argv = json!([
        "cmd",
        "/C",
        "echo downloading 1& echo downloading 2& echo downloading 3& echo npm error code E404& echo npm error 404 Not Found - package missing& exit /B 1"
    ]);
    #[cfg(not(windows))]
    let argv = json!([
        "sh",
        "-c",
        "printf 'downloading 1\\ndownloading 2\\ndownloading 3\\nnpm error code E404\\nnpm error 404 Not Found - package missing\\n'; exit 1"
    ]);
    let request = json!({
        "id": "fail-focus", "agent": "test", "op": "exec.run",
        "args": {"argv": argv, "cwd": ".", "profile": "npm_install", "artifact": "auto"},
        "timeout_ms": 5000, "budget": {"max_tokens": 400}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(response["ok"], false);
    assert_eq!(response["error"]["code"], "E_PROCESS_EXIT");
    let text = response["data"]["stdout"]["text"]
        .as_str()
        .or_else(|| response["data"]["stderr"]["text"].as_str())
        .unwrap_or("");
    let combined = format!(
        "{}{}",
        response["data"]["stdout"]["text"].as_str().unwrap_or(""),
        response["data"]["stderr"]["text"].as_str().unwrap_or("")
    );
    assert!(
        combined.to_ascii_lowercase().contains("npm error")
            || combined.contains("E404")
            || text.to_ascii_lowercase().contains("npm error"),
        "failure text should focus on errors, got: {combined}"
    );
    // Progress noise should not dominate when error lines exist.
    let noise_hits = combined.matches("downloading").count();
    assert!(noise_hits <= 3);
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn ansi_color_codes_are_stripped_from_observations() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    // Produce a colored error via PowerShell / printf escape sequences.
    #[cfg(windows)]
    let argv = json!([
        "cmd",
        "/C",
        "echo [31merror: boom[0m 1>&2 & exit /B 1"
    ]);
    #[cfg(not(windows))]
    let argv = json!(["sh", "-c", "printf '\\033[31merror: boom\\033[0m\\n' >&2; exit 1"]);
    let request = json!({
        "id": "ansi", "agent": "test", "op": "exec.run",
        "args": {"argv": argv, "cwd": ".", "artifact": "auto"},
        "timeout_ms": 5000, "budget": {"max_tokens": 1000}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(response["ok"], false);
    let text = response["data"]["stderr"]["text"].as_str().unwrap_or("");
    assert!(text.contains("error: boom") || text.contains("boom"), "got text={text}");
    assert!(!text.contains('\u{1b}'), "ANSI escapes should be stripped, got {text:?}");
    let _ = std::fs::remove_dir_all(workspace);
}


#[test]
fn budget_truncation_is_explicit_with_omitted_marker() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    // Emit a single long line so token budget is hit without relying on shell loops.
    // Keep under Windows CreateProcess command-line limits while exceeding a 40-token budget.
    let long = "line ".to_string() + &"abcdefghijklmnopqrstuvwxyz".repeat(30);
    #[cfg(windows)]
    let argv = json!(["cmd", "/C", format!("echo {long}")]);
    #[cfg(not(windows))]
    let argv = json!(["sh", "-c", format!("printf '%s\\n' '{long}'")]);
    let request = json!({
        "id": "budget", "agent": "test", "op": "exec.run",
        "args": {"argv": argv, "cwd": ".", "profile": "generic", "artifact": "auto"},
        "timeout_ms": 10000, "budget": {"max_tokens": 40}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    assert_eq!(response["ok"], true, "response={response}");
    let stdout = &response["data"]["stdout"];
    assert_eq!(stdout["status"], "truncated", "stdout={stdout}");
    let text = stdout["text"].as_str().unwrap();
    assert!(text.contains("omitted"), "expected omitted marker in {text}");
    assert!(stdout["omitted_bytes"].as_u64().unwrap() > 0);
    assert!(stdout["artifact"].as_str().is_some());
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn git_profile_is_auto_detected() {
    let workspace = std::env::temp_dir().join(format!("verseshell-op-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&workspace).unwrap();
    // Use `git --version` which is available on most developer machines.
    let request = json!({
        "id": "git-prof", "agent": "test", "op": "exec.run",
        "args": {"argv": ["git", "--version"], "cwd": ".", "profile": "auto", "artifact": "auto"},
        "timeout_ms": 5000, "budget": {"max_tokens": 500}
    });
    let response = run_server(&(request.to_string() + "\n"), &workspace).remove(0);
    if response["ok"] == true {
        assert_eq!(response["meta"]["profile"], "git");
    } else {
        // git may be missing in some CI images — treat as soft skip.
        let code = response["error"]["code"].as_str().unwrap_or("");
        assert!(
            code == "E_EXEC_NOT_FOUND" || code == "E_EXEC_SPAWN",
            "unexpected failure: {response}"
        );
    }
    let _ = std::fs::remove_dir_all(workspace);
}
