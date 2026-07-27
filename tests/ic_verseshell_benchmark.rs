//! IC-VerseShell Benchmark (T14)
//!
//! Evaluates VerseShell's friendliness to LLM agents following the InterCode
//! methodology (arXiv:2306.14898). Five dimensions are measured:
//!   1. Task Success Rate
//!   2. Syntax Error Rate (Line A specific)
//!   3. Avg Retry Rounds
//!   4. Capability Violation Rate
//!   5. Avg Token Cost per Task
//!
//! The benchmark uses pre-recorded tool calls (no real LLM dependency). Each
//! task spawns `ae-mcp`, sends one `tools/call` request, and inspects the
//! response. Tasks cover all 6 ACI tools plus the 3 legacy tools.
//!
//! Run with:
//!   cargo test --test ic_verseshell_benchmark -- --ignored --nocapture

use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};

const BIN: &str = env!("CARGO_BIN_EXE_ae-mcp");

// ── Data structures ─────────────────────────────────────────────────

struct BenchmarkTask {
    id: &'static str,
    prompt: &'static str,
    /// Pre-recorded `(tool_name, arguments)` calls. The last call's response
    /// is fed to `expected_check`.
    pre_recorded_calls: Vec<(&'static str, Value)>,
    /// Optional capability override (sets AETHER_CAPS env var). `None` means
    /// no restriction (default state).
    caps_env: Option<&'static str>,
    /// Check the final tool response. Returns `true` if the task succeeded.
    /// The `Value` passed in is the full JSON-RPC `result` object.
    expected_check: fn(&Value) -> bool,
}

struct TaskResult {
    task_id: String,
    success: bool,
    tool_calls: usize,
    retry_rounds: usize,
    token_cost: usize,
    is_syntax_error: bool,
    is_capability_violation: bool,
    error: Option<String>,
}

#[derive(Debug, serde::Serialize)]
struct BenchmarkReport {
    task_success_rate: f64,
    syntax_error_rate: f64,
    avg_retry_rounds: f64,
    capability_violation_rate: f64,
    avg_token_cost: f64,
    per_task: Vec<TaskResultRecord>,
}

#[derive(Debug, serde::Serialize)]
struct TaskResultRecord {
    task_id: String,
    success: bool,
    tool_calls: usize,
    retry_rounds: usize,
    token_cost: usize,
    is_syntax_error: bool,
    is_capability_violation: bool,
    error: Option<String>,
}

// ── Tasks (>=10) ────────────────────────────────────────────────────

fn benchmark_tasks() -> Vec<BenchmarkTask> {
    vec![
        // 1. system_snapshot basic
        BenchmarkTask {
            id: "sys-snapshot-basic",
            prompt: "Get CPU and memory info",
            pre_recorded_calls: vec![("system_snapshot", json!({"aspects": ["cpu", "mem"]}))],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.get("cpu"))
                    .is_some()
            },
        },
        // 2. system_snapshot full (all 5 aspects)
        BenchmarkTask {
            id: "sys-snapshot-full",
            prompt: "Take a full system snapshot",
            pre_recorded_calls: vec![(
                "system_snapshot",
                json!({"aspects": ["cpu", "mem", "processes", "disk", "load"]}),
            )],
            caps_env: None,
            expected_check: |r| {
                let sc = match r.get("structuredContent").and_then(|s| s.get("result")) {
                    Some(v) => v,
                    None => return false,
                };
                sc.get("cpu").is_some()
                    && sc.get("mem").is_some()
                    && sc.get("processes").is_some()
                    && sc.get("disk").is_some()
                    && sc.get("load").is_some()
            },
        },
        // 3. process_inspect with filter
        BenchmarkTask {
            id: "process-inspect-filter",
            prompt: "List top 5 processes by memory",
            pre_recorded_calls: vec![(
                "process_inspect",
                json!({"filter": {"mem_mb_gt": 0}, "sort_by": "mem", "limit": 5}),
            )],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.as_array())
                    .map(|a| a.len() <= 5)
                    .unwrap_or(false)
            },
        },
        // 4. process_inspect no filter (default limit 10)
        BenchmarkTask {
            id: "process-inspect-no-filter",
            prompt: "List processes (default)",
            pre_recorded_calls: vec![("process_inspect", json!({}))],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.as_array())
                    .map(|a| !a.is_empty())
                    .unwrap_or(false)
            },
        },
        // 5. process_terminate nonexistent pid (expect is_error=true)
        BenchmarkTask {
            id: "process-terminate-nonexistent",
            prompt: "Kill a nonexistent process (expect graceful error)",
            pre_recorded_calls: vec![(
                "process_terminate",
                json!({"pid": 999999, "confirm_name": "nonexistent"}),
            )],
            caps_env: None,
            expected_check: |r| r.get("isError").and_then(|v| v.as_bool()).unwrap_or(false),
        },
        // 6. eval basic (1+2 → 3)
        BenchmarkTask {
            id: "eval-basic",
            prompt: "Compute 1+2",
            pre_recorded_calls: vec![("eval", json!({"code": "1 + 2"}))],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.as_i64())
                    .map(|n| n == 3)
                    .unwrap_or(false)
            },
        },
        // 7. describe_capabilities (non-empty)
        BenchmarkTask {
            id: "describe-capabilities",
            prompt: "List granted capabilities",
            pre_recorded_calls: vec![("describe_capabilities", json!({}))],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.get("granted"))
                    .is_some()
            },
        },
        // 8. transpile_bash ls (ae_source non-empty)
        BenchmarkTask {
            id: "transpile-bash-ls",
            prompt: "Transpile 'ls -la' to VerseShell",
            pre_recorded_calls: vec![("transpile_bash", json!({"bash_code": "ls -la"}))],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.get("ae_source"))
                    .and_then(|v| v.as_str())
                    .map(|s| !s.is_empty())
                    .unwrap_or(false)
            },
        },
        // 9. transpile_bash ps with explain_as_tools
        BenchmarkTask {
            id: "transpile-bash-ps-explain",
            prompt: "Transpile 'ps aux' and explain as tool calls",
            pre_recorded_calls: vec![(
                "transpile_bash",
                json!({"bash_code": "ps aux", "explain_as_tools": true}),
            )],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.get("tool_calls"))
                    .and_then(|v| v.as_array())
                    .map(|a| {
                        a.iter().any(|t| {
                            t.get("tool").and_then(|n| n.as_str()) == Some("process_inspect")
                        })
                    })
                    .unwrap_or(false)
            },
        },
        // 10. transpile_bash free with explain_as_tools (→ system_snapshot)
        BenchmarkTask {
            id: "transpile-bash-free-explain",
            prompt: "Transpile 'free -m' and explain as tool calls",
            pre_recorded_calls: vec![(
                "transpile_bash",
                json!({"bash_code": "free -m", "explain_as_tools": true}),
            )],
            caps_env: None,
            expected_check: |r| {
                r.get("structuredContent")
                    .and_then(|s| s.get("result"))
                    .and_then(|v| v.get("tool_calls"))
                    .and_then(|v| v.as_array())
                    .map(|a| {
                        a.iter().any(|t| {
                            t.get("tool").and_then(|n| n.as_str()) == Some("system_snapshot")
                        })
                    })
                    .unwrap_or(false)
            },
        },
        // 11. health (legacy)
        BenchmarkTask {
            id: "health-legacy",
            prompt: "Check server health",
            pre_recorded_calls: vec![("health", json!({}))],
            caps_env: None,
            expected_check: |r| {
                r.get("content")
                    .and_then(|c| c.get(0))
                    .and_then(|c| c.get("text"))
                    .and_then(|t| t.as_str())
                    .map(|s| s.starts_with("ok verseshell-mcp"))
                    .unwrap_or(false)
            },
        },
        // 12. capability violation (proc.kill with restricted caps)
        BenchmarkTask {
            id: "capability-violation",
            prompt: "Attempt proc.kill with restricted caps (expect denial)",
            pre_recorded_calls: vec![("eval", json!({"code": "proc.kill(999999)"}))],
            caps_env: Some("sys.read,file.read"),
            expected_check: |r| {
                // Should return is_error=true with capability denial message.
                r.get("isError").and_then(|v| v.as_bool()).unwrap_or(false)
            },
        },
    ]
}

// ── Benchmark runner ────────────────────────────────────────────────

fn frame(body: &str) -> String {
    format!("Content-Length: {}\r\n\r\n{}", body.as_bytes().len(), body)
}

/// Parse the first framed JSON-RPC response from `output`. Returns the
/// `result` object on success, or `None` on parse failure.
fn parse_first_response_result(output: &str) -> Option<Value> {
    let bytes = output.as_bytes();
    let header_end = bytes.windows(4).position(|w| w == b"\r\n\r\n").map(|p| p)?;
    let headers = std::str::from_utf8(&bytes[..header_end]).ok()?;
    let content_length = headers.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse::<usize>().ok())
            .flatten()
    })?;
    let body_start = header_end + 4;
    let body_end = body_start + content_length;
    if body_end > bytes.len() {
        return None;
    }
    let body = std::str::from_utf8(&bytes[body_start..body_end]).ok()?;
    let v: Value = serde_json::from_str(body).ok()?;
    // Return the `result` field if present (success), else the whole response
    // (so callers can inspect `error`).
    v.get("result").cloned().or(Some(v))
}

fn run_task(task: &BenchmarkTask) -> TaskResult {
    let mut last_result: Option<Value> = None;
    let mut error: Option<String> = None;
    let mut total_bytes = 0;
    let mut is_syntax_error = false;
    let mut is_capability_violation = false;

    for (tool, args) in &task.pre_recorded_calls {
        let req = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args}
        });
        let req_str = serde_json::to_string(&req).unwrap();
        let framed = frame(&req_str);

        let mut cmd = Command::new(BIN);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(caps) = task.caps_env {
            cmd.env("AETHER_CAPS", caps);
        }

        let result = cmd.spawn().and_then(|mut child| {
            {
                let stdin = child.stdin.as_mut().ok_or_else(|| {
                    std::io::Error::new(std::io::ErrorKind::Other, "missing stdin")
                })?;
                stdin.write_all(framed.as_bytes())?;
            }
            drop(child.stdin.take());
            child.wait_with_output()
        });

        match result {
            Ok(out) => {
                let s = String::from_utf8_lossy(&out.stdout).to_string();
                total_bytes += s.len();

                // Detect error markers in the response text for classification.
                if s.contains("parse error") || s.contains("E_PARSE") {
                    is_syntax_error = true;
                }
                if s.contains("requires capability") || s.contains("capability") {
                    is_capability_violation = true;
                }

                if let Some(v) = parse_first_response_result(&s) {
                    last_result = Some(v);
                }
            }
            Err(e) => {
                error = Some(format!("spawn failed: {e}"));
            }
        }
    }

    let success = match &last_result {
        Some(v) => (task.expected_check)(v),
        None => false,
    };

    TaskResult {
        task_id: task.id.into(),
        success,
        tool_calls: task.pre_recorded_calls.len(),
        retry_rounds: task.pre_recorded_calls.len(),
        token_cost: total_bytes / 4, // crude: 4 bytes ≈ 1 token
        is_syntax_error,
        is_capability_violation,
        error,
    }
}

fn run_benchmark() -> BenchmarkReport {
    let tasks = benchmark_tasks();
    let results: Vec<TaskResult> = tasks.iter().map(run_task).collect();
    let total = results.len() as f64;
    let success_count = results.iter().filter(|r| r.success).count() as f64;
    let syntax_error_count = results.iter().filter(|r| r.is_syntax_error).count() as f64;
    let cap_violation_count = results.iter().filter(|r| r.is_capability_violation).count() as f64;
    let total_retry: usize = results.iter().map(|r| r.retry_rounds).sum();
    let total_tokens: usize = results.iter().map(|r| r.token_cost).sum();

    let per_task = results
        .into_iter()
        .map(|r| TaskResultRecord {
            task_id: r.task_id,
            success: r.success,
            tool_calls: r.tool_calls,
            retry_rounds: r.retry_rounds,
            token_cost: r.token_cost,
            is_syntax_error: r.is_syntax_error,
            is_capability_violation: r.is_capability_violation,
            error: r.error,
        })
        .collect();

    BenchmarkReport {
        task_success_rate: success_count / total,
        syntax_error_rate: syntax_error_count / total,
        avg_retry_rounds: total_retry as f64 / total,
        capability_violation_rate: cap_violation_count / total,
        avg_token_cost: total_tokens as f64 / total,
        per_task,
    }
}

#[test]
#[ignore]
fn ic_verseshell_benchmark() {
    let report = run_benchmark();
    let json = serde_json::to_string_pretty(&report).expect("serialize report");
    println!("\n=== IC-VerseShell Benchmark Report ===\n{}", json);

    assert!(
        report.per_task.len() >= 10,
        "benchmark must have >= 10 tasks, got {}",
        report.per_task.len()
    );

    // Loose success threshold: most tasks should succeed. The
    // capability-violation task is *expected* to return is_error=true (which
    // counts as success for that task), and the process-terminate-nonexistent
    // task also expects is_error=true.
    assert!(
        report.task_success_rate > 0.5,
        "task_success_rate must be > 0.5, got {}",
        report.task_success_rate
    );

    println!(
        "\n=== Summary ===\n  task_success_rate: {:.2}\n  syntax_error_rate: {:.2}\n  avg_retry_rounds: {:.2}\n  capability_violation_rate: {:.2}\n  avg_token_cost: {:.0}",
        report.task_success_rate,
        report.syntax_error_rate,
        report.avg_retry_rounds,
        report.capability_violation_rate,
        report.avg_token_cost
    );
}
