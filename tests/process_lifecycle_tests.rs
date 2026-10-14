#![cfg(windows)]

use serde_json::{json, Map, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const AGENT: &str = "uas05-agent";
const SESSION: &str = "uas05-session";

struct TestServer {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl TestServer {
    fn start(workspace: &Path) -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_ae"))
            .arg("--serve")
            .args(["--cap", "shell.exec"])
            .env("AETHER_WORKSPACE", workspace)
            .env_remove("AETHER_MODE")
            .env_remove("AETHER_CAPS")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn ae --serve");
        let stdin = child.stdin.take().expect("server stdin");
        let stdout = BufReader::new(child.stdout.take().expect("server stdout"));
        Self {
            child,
            stdin,
            stdout,
            next_id: 1,
        }
    }

    fn request(&mut self, op: &str, args: Value) -> Value {
        let id = format!("lifecycle-{}", self.next_id);
        self.next_id += 1;
        let request = json!({
            "id": id,
            "agent": AGENT,
            "op": op,
            "args": args,
            "timeout_ms": 10_000,
            "budget": {"max_tokens": 4_000}
        });
        writeln!(self.stdin, "{request}").expect("write request");
        self.stdin.flush().expect("flush request");
        let mut line = String::new();
        self.stdout.read_line(&mut line).expect("read response");
        assert!(!line.trim().is_empty(), "server closed before response");
        serde_json::from_str(&line)
            .unwrap_or_else(|error| panic!("invalid server response: {error}; line={line:?}"))
    }

    fn shutdown(mut self) {
        writeln!(self.stdin, "SHUTDOWN").expect("write shutdown");
        self.stdin.flush().expect("flush shutdown");
        drop(self.stdin);
        let output = self.child.wait_with_output().expect("wait for server");
        assert!(
            output.status.success(),
            "server failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    fn crash(mut self) {
        self.child.kill().expect("kill server");
        let _ = self.child.wait();
    }
}

fn workspace() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "verseshell-process-lifecycle-{}",
        uuid::Uuid::new_v4()
    ));
    std::fs::create_dir_all(&path).unwrap();
    path
}

/// Parent environment, minus the Windows hidden entries (`=C:`, `=ExitCode`)
/// that `std::env::vars()` exposes but the `process.start` env contract
/// rejects (and `Command::env` cannot forward): a client must not ship them.
fn full_environment(extra: &[(&str, String)]) -> Value {
    let mut values: Map<String, Value> = std::env::vars()
        .filter(|(key, value)| {
            !key.is_empty() && !key.contains(['=', '\0', '\r', '\n']) && !value.contains('\0')
        })
        .map(|(key, value)| (key, Value::String(value)))
        .collect();
    for (key, value) in extra {
        values.insert((*key).into(), Value::String(value.clone()));
    }
    Value::Object(values)
}

fn owner(data: &Value) -> Value {
    json!({
        "process_id": data["process_id"],
        "runtime_id": data["runtime_id"],
        "agent_id": AGENT,
        "session_id": SESSION
    })
}

fn poll(server: &mut TestServer, data: &Value, cursor: u64, wait_ms: u64) -> Value {
    let mut args = owner(data);
    let object = args.as_object_mut().unwrap();
    object.insert("cursor".into(), json!(cursor));
    object.insert("max_bytes".into(), json!(65_536));
    object.insert("wait_ms".into(), json!(wait_ms));
    server.request("process.poll", args)
}

fn output_text(data: &Value) -> String {
    data["output"]["chunks"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|chunk| chunk["text"].as_str())
        .collect()
}

fn child_pid(output: &str) -> u32 {
    output
        .split("CHILD_PID:")
        .nth(1)
        .and_then(|suffix| suffix.split_whitespace().next())
        .and_then(|pid| pid.parse::<u32>().ok())
        .unwrap_or_else(|| panic!("missing child pid in output={output:?}"))
}

fn await_output_contains(
    server: &mut TestServer,
    start: &Value,
    required: &str,
    timeout: Duration,
) -> String {
    let mut collected = output_text(start);
    let mut cursor = start["output"]["cursor"].as_u64().unwrap_or(0);
    let deadline = Instant::now() + timeout;
    while !collected.contains(required) {
        // Check the deadline BEFORE polling, never after appending the poll result.
        // The old order asserted `Instant::now() < deadline` at the bottom of the
        // body, so a poll that had just delivered `required` still panicked whenever
        // the deadline had passed during that poll - which is exactly how this helper
        // reported `timed out waiting for "two"` while printing an output that
        // already contained "two".
        assert!(
            Instant::now() < deadline,
            "timed out waiting for {required:?}: output={collected:?}"
        );
        let next = poll(server, start, cursor, 1_000);
        assert_eq!(next["ok"], true, "poll response={next}");
        let next_cursor = next["data"]["output"]["cursor"].as_u64().unwrap_or(cursor);
        assert!(next_cursor >= cursor, "cursor rewound: response={next}");
        cursor = next_cursor;
        collected.push_str(&output_text(&next["data"]));
    }
    collected
}

fn await_process_gone(pid: u32) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while process_exists(pid) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert!(
        !process_exists(pid),
        "process {pid} survived lifecycle cleanup"
    );
}

fn await_terminal(server: &mut TestServer, start: &Value) -> Value {
    let mut cursor = start["output"]["cursor"].as_u64().unwrap_or(0);
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let response = poll(server, start, cursor, 1_000);
        assert_eq!(response["ok"], true, "poll response={response}");
        cursor = response["data"]["output"]["cursor"]
            .as_u64()
            .unwrap_or(cursor);
        let state = response["data"]["state"].as_str().unwrap_or("");
        if matches!(state, "exited" | "killed" | "lost") {
            return response["data"].clone();
        }
        assert!(
            Instant::now() < deadline,
            "process did not terminate: {response}"
        );
    }
}

#[test]
fn direct_argv_environment_pathext_and_pipe_stdin_roundtrip() {
    let workspace = workspace();
    let shim = workspace.join("uas-echo.cmd");
    std::fs::write(&shim, "@echo off\r\necho SHIM:%~1:%UAS_VALUE%\r\n").unwrap();
    let path = format!(
        "{};{}",
        workspace.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    let env = full_environment(&[
        ("PATH", path),
        ("PATHEXT", ".COM;.EXE;.BAT;.CMD".into()),
        ("UAS_VALUE", "env-ok".into()),
    ]);
    let mut server = TestServer::start(&workspace);

    let shim_start = server.request(
        "process.start",
        json!({
            "argv": ["uas-echo", "two words"],
            "cwd": ".",
            "agent_id": AGENT,
            "session_id": SESSION,
            "env": env,
            "wait_ms": 5_000,
            "timeout_ms": 5_000
        }),
    );
    assert_eq!(shim_start["ok"], true, "shim response={shim_start}");
    let shim_data = await_terminal(&mut server, &shim_start["data"]);
    let shim_output = output_text(&shim_start["data"]) + &output_text(&shim_data);
    assert!(
        shim_output.contains("SHIM:two words:env-ok"),
        "output={shim_output:?}"
    );
    assert!(shim_data["interpreter"].as_str().is_some());

    let stdin_start = server.request(
        "process.start",
        json!({
            "argv": [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-Command",
                "$value=[Console]::In.ReadToEnd();[Console]::Out.Write('STDIN:'+$value)"
            ],
            "cwd": ".",
            "agent_id": AGENT,
            "session_id": SESSION,
            "env": full_environment(&[]),
            "stdin_mode": "pipe",
            "wait_ms": 100,
            "timeout_ms": 5_000
        }),
    );
    assert_eq!(stdin_start["ok"], true, "stdin response={stdin_start}");
    let mut stdin_write_args = owner(&stdin_start["data"]);
    stdin_write_args["data"] = json!("hello world");
    stdin_write_args["encoding"] = json!("utf8");
    stdin_write_args["submit"] = json!(true);
    let stdin_write = server.request("process.write", stdin_write_args);
    assert_eq!(stdin_write["ok"], true, "stdin write={stdin_write}");
    assert_eq!(stdin_write["data"]["written_bytes"], 12);
    let mut stdin_eof_args = owner(&stdin_start["data"]);
    stdin_eof_args["eof"] = json!(true);
    let stdin_eof = server.request("process.write", stdin_eof_args);
    assert_eq!(stdin_eof["ok"], true, "stdin EOF={stdin_eof}");
    let stdin_output = await_output_contains(
        &mut server,
        &stdin_start["data"],
        "STDIN:hello world",
        Duration::from_secs(5),
    );
    let stdin_data = await_terminal(&mut server, &stdin_start["data"]);
    assert!(
        stdin_output.contains("STDIN:hello world"),
        "output={stdin_output:?}"
    );
    assert_eq!(stdin_data["exit_code"], 0);

    server.shutdown();
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn cursor_owner_kill_timeout_and_retention_are_explicit() {
    let workspace = workspace();
    let mut server = TestServer::start(&workspace);
    let start = server.request(
        "process.start",
        json!({
            "argv": [
                "powershell.exe", "-NoLogo", "-NoProfile", "-Command",
                "$child=Start-Process powershell.exe -ArgumentList '-NoLogo','-NoProfile','-Command','Start-Sleep -Seconds 30' -PassThru;[Console]::Out.WriteLine('CHILD_PID:'+$child.Id);[Console]::Out.WriteLine('one');Start-Sleep -Milliseconds 350;[Console]::Out.WriteLine('two');Start-Sleep -Seconds 30"
            ],
            "agent_id": AGENT,
            "session_id": SESSION,
            "stdin_mode": "pipe",
            "wait_ms": 150,
            "timeout_ms": 30_000
        }),
    );
    assert_eq!(start["ok"], true, "start response={start}");
    let combined =
        await_output_contains(&mut server, &start["data"], "two", Duration::from_secs(5));
    assert!(
        combined.contains("one") && combined.contains("two"),
        "output={combined:?}"
    );
    let parent_pid = start["data"]["pid"].as_u64().unwrap() as u32;
    let killed_child_pid = child_pid(&combined);
    assert!(
        process_exists(parent_pid),
        "parent exited before kill proof"
    );
    assert!(
        process_exists(killed_child_pid),
        "child exited before kill proof"
    );

    let mut wrong_owner = owner(&start["data"]);
    wrong_owner["session_id"] = json!("wrong-session");
    let denied = server.request("process.poll", wrong_owner);
    assert_eq!(
        denied["error"]["code"], "E_PROCESS_OWNER",
        "response={denied}"
    );

    let mut kill_args = owner(&start["data"]);
    kill_args["reason"] = json!("agent_abort");
    kill_args["wait_ms"] = json!(5_000);
    let killed = server.request("process.kill", kill_args);
    assert_eq!(killed["ok"], true, "kill response={killed}");
    assert_eq!(killed["data"]["state"], "killed");
    assert_eq!(killed["data"]["termination_reason"], "agent_abort");
    await_process_gone(parent_pid);
    await_process_gone(killed_child_pid);

    let mut repeated_kill_args = owner(&start["data"]);
    repeated_kill_args["reason"] = json!("second_kill_must_not_replace_reason");
    repeated_kill_args["wait_ms"] = json!(0);
    let repeated_kill = server.request("process.kill", repeated_kill_args);
    assert_eq!(
        repeated_kill["ok"], true,
        "repeated kill response={repeated_kill}"
    );
    assert_eq!(repeated_kill["data"]["state"], "killed");
    assert_eq!(repeated_kill["data"]["termination_reason"], "agent_abort");

    let timeout = server.request(
        "process.start",
        json!({
            "argv": [
                "powershell.exe", "-NoLogo", "-NoProfile", "-Command",
                "$child=Start-Process powershell.exe -ArgumentList '-NoLogo','-NoProfile','-Command','Start-Sleep -Seconds 30' -PassThru;[Console]::Out.WriteLine('CHILD_PID:'+$child.Id);Start-Sleep -Seconds 30"
            ],
            "agent_id": AGENT,
            "session_id": SESSION,
            "timeout_ms": 1_500,
            "wait_ms": 2_500
        }),
    );
    assert_eq!(timeout["ok"], true, "timeout response={timeout}");
    let timeout_output = await_output_contains(
        &mut server,
        &timeout["data"],
        "CHILD_PID:",
        Duration::from_secs(5),
    );
    let timeout_data = await_terminal(&mut server, &timeout["data"]);
    assert_eq!(timeout_data["state"], "killed");
    assert_eq!(timeout_data["timed_out"], true);
    assert_eq!(timeout_data["termination_reason"], "timeout");
    let timeout_child_pid = child_pid(&timeout_output);
    await_process_gone(timeout["data"]["pid"].as_u64().unwrap() as u32);
    await_process_gone(timeout_child_pid);

    let truncated = server.request(
        "process.start",
        json!({
            "argv": [
                "powershell.exe", "-NoLogo", "-NoProfile", "-Command",
                "[Console]::Out.Write('abcdefghijklmnopqrstuvwxyz0123456789')"
            ],
            "agent_id": AGENT,
            "session_id": SESSION,
            "max_output_bytes": 12,
            "wait_ms": 2_000,
            "timeout_ms": 5_000
        }),
    );
    assert_eq!(truncated["ok"], true, "truncated response={truncated}");
    let truncated_terminal = await_terminal(&mut server, &truncated["data"]);
    let truncated_poll = poll(&mut server, &truncated_terminal, 0, 0);
    assert_eq!(
        truncated_poll["ok"], true,
        "truncated poll={truncated_poll}"
    );
    let truncated_data = &truncated_poll["data"];
    assert_eq!(truncated_data["output"]["truncated"], true);
    assert!(truncated_data["output"]["lost_bytes"].as_u64().unwrap() > 0);
    assert!(truncated_data["artifacts"]
        .as_array()
        .is_some_and(|items| !items.is_empty()));

    server.shutdown();
    let _ = std::fs::remove_dir_all(workspace);
}

#[test]
fn conpty_and_restart_reconciliation_do_not_orphan_or_respawn() {
    let workspace = workspace();
    let mut server = TestServer::start(&workspace);
    let pty = server.request(
        "process.start",
        json!({
            "argv": ["cmd.exe", "/D", "/S", "/C", "echo PTY_OK"],
            "agent_id": AGENT,
            "session_id": SESSION,
            "stdin_mode": "pipe",
            "pty": true,
            "cols": 100,
            "rows": 24,
            "wait_ms": 5_000,
            "timeout_ms": 5_000
        }),
    );
    assert_eq!(pty["ok"], true, "PTY response={pty}");
    let pty_data = await_terminal(&mut server, &pty["data"]);
    let pty_all = poll(&mut server, &pty_data, 0, 0);
    assert_eq!(pty_all["ok"], true, "PTY poll={pty_all}");
    let pty_output = output_text(&pty_all["data"]);
    assert!(pty_output.contains("PTY_OK"), "PTY output={pty_output:?}");
    assert_eq!(pty_data["mode"], "pty");

    let interactive_pty = server.request(
        "process.start",
        json!({
            "argv": ["cmd.exe", "/D", "/Q"],
            "agent_id": AGENT,
            "session_id": SESSION,
            "stdin_mode": "pipe",
            "pty": true,
            "cols": 100,
            "rows": 24,
            "wait_ms": 100,
            "timeout_ms": 5_000
        }),
    );
    assert_eq!(
        interactive_pty["ok"], true,
        "interactive PTY response={interactive_pty}"
    );
    let mut pty_input_args = owner(&interactive_pty["data"]);
    pty_input_args["data"] = json!("echo PTY_INPUT");
    pty_input_args["submit"] = json!(true);
    let pty_input = server.request("process.write", pty_input_args);
    assert_eq!(pty_input["ok"], true, "PTY input={pty_input}");
    let mut pty_exit_args = owner(&interactive_pty["data"]);
    pty_exit_args["data"] = json!("exit");
    pty_exit_args["submit"] = json!(true);
    let pty_exit = server.request("process.write", pty_exit_args);
    assert_eq!(pty_exit["ok"], true, "PTY exit={pty_exit}");
    let interactive_terminal = await_terminal(&mut server, &interactive_pty["data"]);
    let interactive_all = poll(&mut server, &interactive_terminal, 0, 0);
    assert_eq!(
        interactive_all["ok"], true,
        "interactive PTY poll={interactive_all}"
    );
    assert!(
        output_text(&interactive_all["data"]).contains("PTY_INPUT"),
        "interactive PTY output={interactive_all}"
    );

    let running = server.request(
        "process.start",
        json!({
            "argv": [
                "powershell.exe", "-NoLogo", "-NoProfile", "-Command",
                "$child=Start-Process powershell.exe -ArgumentList '-NoLogo','-NoProfile','-Command','Start-Sleep -Seconds 30' -PassThru;[Console]::Out.WriteLine('CHILD_PID:'+$child.Id);Start-Sleep -Seconds 30"
            ],
            "agent_id": AGENT,
            "session_id": SESSION,
            "wait_ms": 500,
            "timeout_ms": 30_000
        }),
    );
    assert_eq!(running["ok"], true, "running response={running}");
    assert_eq!(running["data"]["state"], "running");
    let process_id = running["data"]["process_id"].as_str().unwrap().to_string();
    let runtime_id = running["data"]["runtime_id"].as_str().unwrap().to_string();
    let pid = running["data"]["pid"].as_u64().unwrap() as u32;
    let crash_output = await_output_contains(
        &mut server,
        &running["data"],
        "CHILD_PID:",
        Duration::from_secs(5),
    );
    let crash_child_pid = child_pid(&crash_output);
    server.crash();

    await_process_gone(pid);
    await_process_gone(crash_child_pid);

    let mut restarted = TestServer::start(&workspace);
    let reconciled = restarted.request(
        "process.list",
        json!({
            "runtime_id": runtime_id,
            "agent_id": AGENT,
            "session_id": SESSION,
            "include_terminal": true
        }),
    );
    assert_eq!(reconciled["ok"], true, "list response={reconciled}");
    let records = reconciled["data"]["processes"].as_array().unwrap();
    let record = records
        .iter()
        .find(|record| record["process_id"] == process_id)
        .expect("reconciled lifecycle record");
    assert_eq!(record["state"], "lost");
    assert_eq!(
        record["termination_reason"],
        "runtime_restart_unrecoverable"
    );

    restarted.shutdown();
    let _ = std::fs::remove_dir_all(workspace);
}

fn process_exists(pid: u32) -> bool {
    Command::new("powershell.exe")
        .args([
            "-NoLogo",
            "-NoProfile",
            "-Command",
            &format!("if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}"),
        ])
        .status()
        .is_ok_and(|status| status.success())
}
