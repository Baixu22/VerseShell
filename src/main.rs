use anyhow::{Context, Result};
use std::fs;
use std::io::{self, Read, Write};

use clap::Parser;
use verseshell::{env::Env, eval, modules, parser, runtime, server, transpile};

fn create_env_with_modules() -> Env {
    let mut env = Env::new();
    for (name, module) in modules::all_modules() {
        env.register_module(name, module);
    }
    env
}

#[derive(Parser)]
#[command(name = "ae")]
#[command(about = "VerseShell — Agent Action / Observation Runtime for local systems")]
#[command(version = env!("CARGO_PKG_VERSION"))]
struct Cli {
    /// Bash compatibility mode (transpile bash to aeshell)
    #[arg(long, short = 'b')]
    bash: bool,

    /// Execute a command string
    #[arg(long, short = 'c')]
    command: Option<String>,

    /// Token budget for output: results over N estimated tokens are paged/truncated
    #[arg(long, value_name = "N")]
    budget: Option<usize>,

    /// Agent mode: default-deny dangerous effect classes (gate behind approval)
    #[arg(long)]
    agent: bool,

    /// Workspace root that confines destructive/write operations (the jail)
    #[arg(long, value_name = "DIR")]
    workspace: Option<String>,

    /// Safety policy: "strict" (default) or "permissive" (allow-all in agent mode)
    #[arg(long, value_name = "POLICY")]
    policy: Option<String>,

    /// Deterministic output: render results as canonical, byte-stable JSON
    #[arg(long)]
    deterministic: bool,

    /// Output as JSON (alias for --deterministic)
    #[arg(long)]
    json: bool,

    /// Timeout in seconds for operations (http, shell exec, etc.)
    #[arg(long, value_name = "SECS")]
    timeout: Option<u64>,

    /// Start JSON-RPC server mode (reads stdin, writes stdout)
    #[arg(long)]
    serve: bool,

    /// Max concurrent agent sessions in server mode
    #[arg(long, default_value = "4")]
    max_concurrency: usize,

    /// Transport for server mode (default: stdio)
    #[arg(long, default_value = "stdio")]
    transport: String,

    /// Cache TTL in milliseconds for server mode
    #[arg(long, default_value = "5000")]
    cache_ttl_ms: u64,

    /// Per-agent rate limit in requests/second (0 = unlimited)
    #[arg(long, default_value = "0")]
    rate_limit: u32,

    /// Capability grants (comma-separated): file.read,file.write,net.http.get,all
    #[arg(long, value_name = "CAPS")]
    cap: Option<String>,

    /// Enable work-stealing scheduler (v2.1)
    #[arg(long)]
    scheduler: bool,

    /// Number of scheduler worker threads
    #[arg(long, default_value = "4")]
    scheduler_workers: usize,

    /// CPU budget per agent (max concurrent ops)
    #[arg(long, default_value = "8")]
    cpu_budget: usize,

    /// Output format: json, compact (token-efficient), human (default)
    #[arg(long, default_value = "human")]
    format: String,

    /// Compact output alias (same as --format compact)
    #[arg(long)]
    compact: bool,

    /// Script file to execute
    #[arg(value_name = "FILE")]
    file: Option<String>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    // Common env setup
    if let Some(n) = cli.budget {
        std::env::set_var("AE_TOKEN_BUDGET", n.to_string());
    }
    if cli.agent {
        std::env::set_var("AETHER_MODE", "agent");
    }
    if let Some(ws) = &cli.workspace {
        std::env::set_var("AETHER_WORKSPACE", ws);
    }
    if let Some(p) = &cli.policy {
        std::env::set_var("AETHER_POLICY", p);
    }
    if cli.deterministic || cli.json || cli.format == "json" {
        std::env::set_var("AE_DETERMINISTIC", "1");
    }
    if cli.compact || cli.format == "compact" {
        std::env::set_var("AE_FORMAT", "compact");
    }
    // Phase 4: --timeout is now plumbed through env.deadline (see run_code)
    // instead of the AE_TIMEOUT env var. AE_TIMEOUT is no longer read.
    verseshell::safety::init_rbac_from_env();

    // Agent, server, and explicitly capability-scoped invocations must start
    // fail-closed. Preserve the historical permissive behavior only for the
    // interactive human CLI with no capability configuration.
    if let Some(ref caps) = cli.cap {
        std::env::set_var("AETHER_CAPS", caps);
    }
    if cli.serve {
        std::env::set_var("AE_MAX_CONCURRENCY", cli.max_concurrency.to_string());
    }
    if cli.serve || cli.agent || cli.cap.is_some() {
        verseshell::capability::init_caps(cli.cap.as_deref());
    } else {
        verseshell::capability::init_caps_legacy(None);
    }

    // ── Server mode ──────────────────────────────────────────
    if cli.serve {
        let workspace = cli.workspace.map(|w| std::path::PathBuf::from(w));
        let transport = match cli.transport.as_str() {
            "stdio" => server::Transport::Stdio,
            other => {
                eprintln!("unsupported transport: {} (use 'stdio')", other);
                std::process::exit(1);
            }
        };
        let rt_config = runtime::RuntimeConfig {
            workspace,
            max_concurrency: cli.max_concurrency,
            agent_mode: cli.agent,
            cache_ttl_ms: cli.cache_ttl_ms,
            rate_limit: cli.rate_limit,
            ..Default::default()
        };
        let srv_config = server::ServerConfig {
            transport,
            runtime_config: rt_config,
            num_workers: cli.scheduler_workers,
            cpu_budget_per_agent: cli.cpu_budget,
            mem_budget_per_agent: 64 * 1024 * 1024, // 64MB default
            enable_scheduler: cli.scheduler,
        };
        return server::run_server(srv_config);
    }

    // ── Bash stdin mode ─────────────────────────────────────
    if cli.bash && cli.file.is_none() && cli.command.is_none() {
        let mut buf = String::new();
        io::stdin().read_to_string(&mut buf)?;
        let code =
            transpile::bash::transpile_bash_to_ae(&buf).context("bash→ae transpile failed")?;
        return run_code(&code, cli.timeout);
    }

    // ── -c/--command flag ──────────────────────────────────
    if let Some(cmd) = cli.command {
        let code = if cli.bash {
            transpile::bash::transpile_bash_to_ae(&cmd).context("bash→ae transpile failed")?
        } else {
            cmd
        };
        return run_code(&code, cli.timeout);
    }

    // ── File execution or REPL ─────────────────────────────
    match cli.file {
        Some(file) => run_file(&file, cli.bash, cli.timeout)?,
        None => repl_shell(cli.timeout)?,
    }

    Ok(())
}

fn run_file(path: &str, bash_mode: bool, timeout: Option<u64>) -> Result<()> {
    let mut code = fs::read_to_string(path).with_context(|| format!("failed to read {}", path))?;

    let is_bash = bash_mode || path.to_lowercase().ends_with(".sh");

    if is_bash {
        code = transpile::bash::transpile_bash_to_ae(&code)
            .with_context(|| format!("bash→ae transpile failed for {}", path))?;
    }

    run_code(&code, timeout)
}

fn run_code(code: &str, timeout: Option<u64>) -> Result<()> {
    let mut env = create_env_with_modules();
    // Phase 4: plumb --timeout into env.deadline (replaces AE_TIMEOUT env var)
    if let Some(secs) = timeout {
        env.deadline = Some(std::time::Instant::now() + std::time::Duration::from_secs(secs));
    }
    let exit_code = verseshell::repl::run_one(&mut env, code)?;
    if exit_code != 0 {
        std::process::exit(exit_code);
    }
    Ok(())
}

fn repl_shell(timeout: Option<u64>) -> Result<()> {
    let mut env = create_env_with_modules();
    // Phase 4: plumb --timeout into env.deadline (replaces AE_TIMEOUT env var)
    if let Some(secs) = timeout {
        env.deadline = Some(std::time::Instant::now() + std::time::Duration::from_secs(secs));
    }
    let mut line = String::new();

    println!("ae REPL — type 'exit', 'quit', or Ctrl-D to exit");
    loop {
        line.clear();
        print!("ae> ");
        io::stdout().flush().ok();
        if io::stdin().read_line(&mut line)? == 0 {
            println!();
            break;
        }
        let src = line.trim();
        if src.is_empty() {
            continue;
        }
        if src == "exit" || src == "quit" {
            break;
        }
        match parser::parse_program(src) {
            Ok(stmts) => match eval::eval_program(&stmts, &mut env) {
                Ok(val) => println!("{:?}", val),
                Err(e) => eprintln!("eval error: {e}"),
            },
            Err(e) => eprintln!("parse error: {e}"),
        }
    }
    Ok(())
}
