use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn run_mcp(input: &str) -> String {
    let mut child = Command::new(env!("CARGO_BIN_EXE_ae-mcp"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn ae-mcp");

    {
        let stdin = child.stdin.as_mut().expect("missing child stdin");
        stdin
            .write_all(input.as_bytes())
            .expect("failed to write MCP input");
    }
    drop(child.stdin.take());

    let output = child.wait_with_output().expect("failed to wait for ae-mcp");
    assert!(
        output.status.success(),
        "ae-mcp failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).to_string()
}

fn frame(body: &str) -> String {
    format!("Content-Length: {}\r\n\r\n{}", body.as_bytes().len(), body)
}

fn parse_json_lines(output: &str) -> Vec<Value> {
    output
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("invalid JSON line response"))
        .collect()
}

fn parse_framed(output: &str) -> Vec<Value> {
    let bytes = output.as_bytes();
    let mut offset = 0;
    let mut responses = Vec::new();

    while offset < bytes.len() {
        if bytes[offset..].iter().all(|b| b.is_ascii_whitespace()) {
            break;
        }

        let header_end = bytes[offset..]
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .expect("missing MCP header terminator")
            + offset;
        let headers = std::str::from_utf8(&bytes[offset..header_end]).expect("headers not UTF-8");
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())
                    .flatten()
            })
            .expect("missing Content-Length header");
        let body_start = header_end + 4;
        let body_end = body_start + content_length;
        let body = std::str::from_utf8(&bytes[body_start..body_end]).expect("body not UTF-8");
        responses.push(serde_json::from_str(body).expect("invalid framed JSON response"));
        offset = body_end;
    }

    responses
}

#[test]
fn json_line_list_commands_reports_callable_functions() {
    let input = concat!(
        "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"list_commands\",\"arguments\":{}}}\n"
    );

    let responses = parse_json_lines(&run_mcp(input));
    let text = responses[0]["result"]["content"][0]["text"]
        .as_str()
        .expect("missing list_commands text");

    assert!(text.contains("sys.hostname -> sys_hostname"));
    assert!(text.contains("file.read -> cat"));
    assert!(text.contains("shell.exec -> sh"));
}

#[test]
fn content_length_framing_supports_initialize_and_tools_list() {
    let initialize = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"0\"}}}";
    let initialized =
        "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\",\"params\":{}}";
    let tools_list = "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}";

    let output = run_mcp(&format!(
        "{}{}{}",
        frame(initialize),
        frame(initialized),
        frame(tools_list)
    ));
    let responses = parse_framed(&output);

    assert_eq!(responses.len(), 2);
    assert_eq!(responses[0]["result"]["serverInfo"]["name"], "ae-mcp");

    let tool_names: Vec<&str> = responses[1]["result"]["tools"]
        .as_array()
        .expect("tools should be an array")
        .iter()
        .filter_map(|tool| tool["name"].as_str())
        .collect();
    assert!(tool_names.contains(&"health"));
    assert!(tool_names.contains(&"exec"));
    assert!(tool_names.contains(&"list_commands"));
    assert!(tool_names.contains(&"exec_run"));
    assert!(tool_names.contains(&"result_query"));
}

#[test]
fn exec_run_returns_observation_structured_content() {
    #[cfg(windows)]
    let argv = serde_json::json!(["cmd", "/C", "echo hello"]);
    #[cfg(not(windows))]
    let argv = serde_json::json!(["sh", "-c", "echo hello"]);
    let body = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "exec_run", "arguments": {"argv": argv, "cwd": "."}}
    });
    let responses = parse_json_lines(&run_mcp(&(body.to_string() + "\n")));
    let result = &responses[0]["result"];
    assert_eq!(result["isError"], false);
    assert_eq!(result["structuredContent"]["schema"], "verseshell.observation/v1");
    assert_eq!(result["structuredContent"]["data"]["exit_code"], 0);
}

#[test]
fn exec_timeout_returns_promptly_without_echoing_source() {
    let input = concat!(
        "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"exec\",\"arguments\":{\"code\":\"sleep(5)\",\"timeout_ms\":50}}}\n"
    );
    let started = Instant::now();
    let responses = parse_json_lines(&run_mcp(input));

    assert!(
        started.elapsed() < Duration::from_secs(2),
        "timeout response was not prompt"
    );

    let error = &responses[0]["error"];
    assert!(error["message"]
        .as_str()
        .expect("missing error message")
        .contains("timed out after 50ms"));
    assert_eq!(error["data"]["codeLength"], 8);
    assert!(error["data"].get("code").is_none());
}
