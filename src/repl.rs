use anyhow::Result;

use crate::{
    ast::Stmt, builtins, env::Env, ir::{IRCompiler, IREvaluator}, parser,
    safety::{self, Mode, SafetyError},
};

/// Run a snippet of AetherShell code once and return the exit code.
pub fn run_one(env: &mut Env, code: &str) -> Result<i32> {
    // v3: Use unified IR evaluation path
    let compiler = IRCompiler::new(true); // optimize=true
    let stmts = parser::parse_program(code)?;
    let ir = compiler.compile_program(&stmts);
    match IREvaluator::eval_program(&ir, env) {
        Ok(v) => {
            print_result(&v);
            Ok(0)
        }
        Err(e) => {
            print_eval_error(&e);
            Ok(1)
        }
    }
}

/// Run a snippet of AetherShell code and return the raw Value (v3 IR path).
pub fn run_eval(env: &mut Env, code: &str) -> anyhow::Result<crate::value::Value> {
    let stmts = parser::parse_program(code)?;
    let compiler = IRCompiler::new(true);
    let ir = compiler.compile_program(&stmts);
    IREvaluator::eval_program(&ir, env)
}

/// Run pre-parsed statements (v3 IR path).
pub fn run_eval_stmts(env: &mut Env, stmts: &[Stmt]) -> anyhow::Result<crate::value::Value> {
    let compiler = IRCompiler::new(true);
    let ir = compiler.compile_program(stmts);
    IREvaluator::eval_program(&ir, env)
}

/// Print a value in the most compact, agent-friendly form available.
fn print_result(val: &crate::value::Value) {
    let budget = std::env::var("AE_TOKEN_BUDGET")
        .ok()
        .and_then(|s| s.parse::<usize>().ok());

    // Deterministic (byte-stable canonical JSON) output
    let deterministic = std::env::var("AE_DETERMINISTIC")
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    if deterministic {
        if let Some(out) = builtins::render_canonical(val) {
            println!("{}", out);
            return;
        }
    }

    // Agent mode: compact AECON rendering with secret redaction
    if safety::current_mode() == Mode::Agent {
        if let Some(out) = builtins::render_agent(val, budget) {
            println!("{}", out);
            return;
        }
    }

    // Human path: clean render (no Debug type tags like Str(), Int())
    match budget {
        None => println!("{}", render_value_clean(val)),
        Some(max) => {
            let out = builtins::budget_value(val, max, 0);
            println!("{}", out);
        }
    }
}

fn render_value_clean(val: &crate::value::Value) -> String {
    use crate::value::Value;
    match val {
        Value::Null => "null".to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Int(n) => n.to_string(),
        Value::Float(f) => {
            if *f == f.trunc() && f.is_finite() {
                format!("{:.1}", f)
            } else {
                f.to_string()
            }
        }
        Value::Str(s) => s.clone(),
        Value::Uri(s) => s.clone(),
        Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(render_value_clean).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Record(map) => {
            let inner: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("{}: {}", k, render_value_clean(v)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
        Value::Lambda(_) => "<lambda>".to_string(),
        Value::AsyncLambda(_) => "<async lambda>".to_string(),
        Value::Future(_) => "<future>".to_string(),
        Value::Error(msg) => format!("<error: {}>", msg),
        Value::Builtin(b) => format!("<builtin: {}>", b.name),
        Value::Table(_) => "<table>".to_string(),
    }
}

/// Render an uncaught evaluation error.
///
/// In agent/deterministic mode, outputs structured JSON for machine parsing.
/// In human REPL mode, outputs readable prose.
fn print_eval_error(e: &anyhow::Error) {
    let is_agent = safety::current_mode() == Mode::Agent;
    let is_deterministic = std::env::var("AE_DETERMINISTIC")
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    if is_agent || is_deterministic {
        let error_json = if let Some(se) = e.downcast_ref::<SafetyError>() {
            format!("{}", se.to_json())
        } else {
            format!(
                "{{\"error\":{{\"code\":\"EVAL_ERROR\",\"message\":\"{}\"}}}}",
                e.to_string().replace('\\', "\\\\").replace('"', "\\\"")
            )
        };
        eprintln!("{}", error_json);
        return;
    }

    if let Some(se) = e.downcast_ref::<SafetyError>() {
        let code = se.code.as_str();
        eprintln!("error[{code}]: {}", se.message);
        if !se.hint.is_empty() {
            eprintln!("  hint: {}", se.hint);
        }
        if let Some(a) = &se.approval {
            eprintln!(
                "  approve: re-run with AETHER_APPROVE={}  (or call approve(\"{}\"))",
                a.token, a.token
            );
        }
    } else {
        eprintln!("error: {e}");
    }
}

/// Parse and evaluate one line of code.
pub fn eval_line(env: &mut Env, code: &str) -> Result<crate::value::Value> {
    let stmts = parser::parse_program(code)?;
    crate::eval::eval_program(&stmts, env)
}
