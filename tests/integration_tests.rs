//! Core integration tests for aeshell.
//!
//! Run with: cargo test

use std::process::Command;

fn ae_path() -> String {
    env!("CARGO_BIN_EXE_ae").to_string()
}

fn run(cmd: &str) -> String {
    let output = Command::new(ae_path())
        .args(["-c", cmd])
        .output()
        .expect("failed to execute ae");
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

fn run_json(cmd: &str) -> String {
    let output = Command::new(ae_path())
        .args(["--json", "-c", cmd])
        .output()
        .expect("failed to execute ae");
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

fn run_err(cmd: &str) -> String {
    let output = Command::new(ae_path())
        .args(["-c", cmd])
        .output()
        .expect("failed to execute ae");
    String::from_utf8_lossy(&output.stderr).trim().to_string()
}

// ==================== Core Language ====================

#[test]
fn test_literals() {
    assert_eq!(run("42"), "42");
    assert!(run("3.14").starts_with("3.1")); // float formatting varies
    assert_eq!(run("true"), "true");
    assert_eq!(run("\"hello\""), "hello");
    assert_eq!(run("null"), "null");
}

#[test]
fn test_arithmetic() {
    assert_eq!(run("1 + 2"), "3");
    assert_eq!(run("5 - 3"), "2");
    assert_eq!(run("3 * 4"), "12");
    assert_eq!(run("10 / 2"), "5.0");
    assert_eq!(run("10 % 3"), "1");
    assert_eq!(run("2 ^ 3"), "8");
}

#[test]
fn test_comparisons() {
    assert_eq!(run("1 < 2"), "true");
    assert_eq!(run("1 > 2"), "false");
    assert_eq!(run("1 == 1"), "true");
    assert_eq!(run("1 != 2"), "true");
    assert_eq!(run("1 <= 1"), "true");
    assert_eq!(run("2 >= 1"), "true");
}

#[test]
fn test_bool_ops() {
    assert_eq!(run("true && true"), "true");
    assert_eq!(run("true && false"), "false");
    assert_eq!(run("true || false"), "true");
    assert_eq!(run("!true"), "false");
}

#[test]
fn test_variables() {
    assert_eq!(run("let x = 42; x"), "42");
    assert_eq!(run("let x = 10; let y = 20; x + y"), "30");
}

#[test]
fn test_string_interpolation() {
    assert_eq!(run("let name = \"world\"; \"hello ${name}\""), "hello world");
    assert_eq!(run("\"1+1=${1+1}\""), "1+1=2");
}

#[test]
fn test_lambda() {
    assert_eq!(run("let add = fn(x, y) => x + y; add(3, 4)"), "7");
    assert_eq!(run("(fn(x) => x * 2)(5)"), "10");
}

#[test]
fn test_match() {
    assert_eq!(run("match 2 { 1 => \"one\", 2 => \"two\", _ => \"other\" }"), "two");
    assert_eq!(run("match 99 { 1 => \"one\", _ => \"many\" }"), "many");
}

#[test]
fn test_try_catch() {
    assert!(run("try { json.parse(\"bad\") } catch e { \"ok\" }").contains("ok"));
    assert_eq!(run("try { 42 } catch e { \"err\" }"), "42");
}

// ==================== Arrays & Pipelines ====================

#[test]
fn test_array_literal() {
    assert_eq!(run("[1, 2, 3]"), "[1, 2, 3]");
}

#[test]
fn test_record_literal() {
    assert_eq!(run("{a: 1, b: \"x\"}"), "{a: 1, b: x}");
}

#[test]
fn test_pipeline_map() {
    assert_eq!(run("let f = fn(x) => x * 2; [1,2,3] | map f"), "[2, 4, 6]");
}

#[test]
fn test_pipeline_where() {
    assert_eq!(run("[1,2,3,4,5] | where fn(x) => x > 3"), "[4, 5]");
}

#[test]
fn test_pipeline_sort() {
    assert_eq!(run("[3,1,4,1,5] | sort"), "[1, 1, 3, 4, 5]");
}

#[test]
fn test_pipeline_reduce() {
    assert_eq!(run("let f = fn(acc,x) => acc + x; [1,2,3,4] | reduce f 0"), "10");
}

#[test]
fn test_pipeline_take() {
    assert_eq!(run("[1,2,3,4,5] | take 3"), "[1, 2, 3]");
}

#[test]
fn test_pipeline_chain() {
    assert_eq!(
        run("let a = [5,2,4,1,3]; a | sort | where fn(x) => x > 2 | map fn(x) => x * 10"),
        "[30, 40, 50]"
    );
}

#[test]
fn test_first_last() {
    assert_eq!(run("first([10,20,30])"), "10");
    assert_eq!(run("last([10,20,30])"), "30");
}

#[test]
fn test_any_all() {
    assert_eq!(run("any([false,true,false])"), "true");
    assert_eq!(run("all([true,true,false])"), "false");
    assert_eq!(run("let f = fn(x) => x > 1; all([2,3,4])"), "true");
}

#[test]
fn test_concat() {
    assert_eq!(run("concat([1,2], [3,4])"), "[1, 2, 3, 4]");
}

#[test]
fn test_in() {
    assert_eq!(run("in(2, [1,2,3])"), "true");
    assert_eq!(run("in(99, [1,2,3])"), "false");
}

// ==================== System Info ====================

#[test]
fn test_sys_hostname() {
    assert!(!run("sys.hostname()").is_empty());
}

#[test]
fn test_sys_os() {
    let os = run("sys.os()");
    assert!(os == "windows" || os == "linux" || os == "macos");
}

#[test]
fn test_sys_arch() {
    assert!(!run("sys.arch()").is_empty());
}

#[test]
fn test_sys_cpu_info() {
    let info = run("sys.cpu_info()");
    assert!(info.contains("cores") || info.contains("mhz") || info.contains("name"));
}

#[test]
fn test_sys_mem_info() {
    let info = run("sys.mem_info()");
    assert!(info.contains("total"));
}

#[test]
fn test_sys_uptime() {
    assert!(!run("sys.uptime()").is_empty());
}

// ==================== Math ====================

#[test]
fn test_math_abs() {
    assert_eq!(run("math.abs(-5)"), "5");
    assert_eq!(run("math.abs(3)"), "3");
}

#[test]
fn test_math_min_max() {
    assert_eq!(run("math.min(3, 7)"), "3");
    assert_eq!(run("math.max(3, 7)"), "7");
}

#[test]
fn test_math_round() {
    assert_eq!(run("math.round(3.7)"), "4");
    assert_eq!(run("math.floor(3.7)"), "3");
    assert_eq!(run("math.ceil(3.2)"), "4");
}

#[test]
fn test_math_sqrt_pow() {
    assert!(run("math.sqrt(16)").contains("4")); // may return 4.0
    assert_eq!(run("math.pow(2, 8)"), "256");
}

#[test]
fn test_math_sum_mean() {
    assert_eq!(run("math.sum([1,2,3,4,5])"), "15");
    assert_eq!(run("math.mean([1,2,3,4,5])"), "3.0");
}

// ==================== String ====================

#[test]
fn test_str_upper_lower() {
    assert_eq!(run("str.upper(\"hello\")"), "HELLO");
    assert_eq!(run("str.lower(\"WORLD\")"), "world");
}

#[test]
fn test_str_trim() {
    assert_eq!(run("str.trim(\"  x  \")"), "x");
}

#[test]
fn test_str_contains() {
    assert_eq!(run("str.contains(\"hello\", \"ell\")"), "true");
    assert_eq!(run("str.contains(\"hello\", \"xyz\")"), "false");
}

#[test]
fn test_str_join() {
    assert_eq!(run("str.join(\", \", [\"a\",\"b\",\"c\"])"), "a, b, c");
    assert_eq!(run("str.join([\"x\",\"y\"], \"-\")"), "x-y");
}

#[test]
fn test_str_length() {
    assert_eq!(run("str.length(\"hello\")"), "5");
}

// ==================== File System ====================

#[test]
fn test_file_exists() {
    assert_eq!(run("file.exists(\"Cargo.toml\")"), "{exists: true, is_dir: false, is_file: true, path: Cargo.toml}");
}

#[test]
fn test_fs_stat() {
    let stat = run("fs.stat(\".\")");
    assert!(stat.contains("is_dir") && stat.contains("true"));
}

// ==================== Crypto ====================

#[test]
fn test_crypto_hash() {
    let hash = run("crypto.hash(\"hello\", \"sha256\")");
    assert_eq!(hash.len(), 64); // SHA-256 hex is 64 chars
}

#[test]
fn test_crypto_uuid() {
    let uuid = run("crypto.uuid()");
    assert_eq!(uuid.len(), 36); // UUID is 36 chars
}

#[test]
fn test_crypto_random() {
    let bytes = run("crypto.random_bytes(8)");
    assert_eq!(bytes.len(), 16); // 8 bytes = 16 hex chars
}

// ==================== JSON ====================

#[test]
fn test_json_parse() {
    let result = run("json.parse(\"[1,2,3]\")");
    assert_eq!(result, "[1, 2, 3]");
}

#[test]
fn test_json_stringify() {
    assert_eq!(run("json.stringify({a: 1, b: 2})"), "{\"a\":1,\"b\":2}");
}

// ==================== JSON Output Mode ====================

#[test]
fn test_json_output_mode() {
    let result = run_json("sys.hostname()");
    assert!(result.starts_with("\"") || result.starts_with("{") || result.contains(":"));
    // Should be valid JSON
    serde_json::from_str::<serde_json::Value>(&result).expect("not valid JSON");
}

#[test]
fn test_json_compound() {
    let result = run_json("{host: sys.hostname(), os: sys.os()}");
    let v: serde_json::Value = serde_json::from_str(&result).expect("not valid JSON");
    assert!(v["host"].is_string());
    assert!(v["os"].is_string());
}

// ==================== Error Handling ====================

#[test]
fn test_error_recovery() {
    assert_eq!(run("try { json.parse(\"bad\") } catch e { 42 }"), "42");
}

#[test]
fn test_structured_error() {
    let stderr = run_err("json.parse(\"bad\")");  // This should produce an error
    assert!(!stderr.is_empty(), "expected error output for json.parse of bad input");
}

// ==================== Type Introspection ====================

#[test]
fn test_describe() {
    let desc = run("[1,2,3] | describe");
    assert!(desc.contains("array"));
    let desc = run("{a:1} | describe");
    assert!(desc.contains("record"));
}

// ==================== Safety ====================

#[test]
fn test_agent_mode_refuses_dangerous() {
    let output = Command::new(ae_path())
        .args(["--agent", "-c", "sh(\"rm -rf /\")"])
        .output()
        .expect("failed");
    let stderr = String::from_utf8_lossy(&output.stderr);
    // Should output structured error in agent mode
    assert!(stderr.contains("error") || stderr.contains("code") || !output.status.success());
}
