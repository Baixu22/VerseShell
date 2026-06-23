//! Agent runtime: lock-free session pool with per-agent concurrency.
//!
//! Architecture:
//!   - No global Mutex — sessions store `Mutex<Env>` individually
//!   - Session lookup: `RwLock<HashMap<>>` (readers don't block each other)
//!   - Atomic counters for stats (no lock contention)
//!   - `Arc<Env>` template — cloning is O(1) pointer increment
//!   - Panic recovery — one bad request doesn't crash the server
//!   - Rate limiting — per-agent sliding window throttle
//!   - Error suggestions — nearest builtin name for typos

use crate::cache::{GlobalCache, SystemSnapshot};
use crate::env::Env;
use crate::modules;
use crate::value::Value;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use std::time::{Duration, Instant};

// ── JSON-RPC Protocol Types ──────────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct AgentRequest {
    pub id: String,
    pub agent: String,
    pub cmd: String,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default)]
    pub budget: Option<usize>,
}

fn default_timeout_ms() -> u64 { 30000 }

#[derive(Debug, Serialize)]
pub struct AgentResponse {
    pub id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<AgentError>,
    pub meta: ResponseMeta,
}

#[derive(Debug, Serialize)]
pub struct AgentError {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
    pub recoverable: bool,
}

#[derive(Debug, Serialize)]
pub struct ResponseMeta {
    pub elapsed_ms: u64,
    pub agent: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cache_hit: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub budget_used: Option<usize>,
    pub session_age_ms: u64,
}

// ── Session ──────────────────────────────────────────────────────────

struct AgentSession {
    env: Mutex<Env>,
    created_at: Instant,
    last_used_at: Mutex<Instant>,
    request_count: AtomicU64,
    /// Timestamp (ms since epoch) of the last request, for rate limiting.
    last_request_at: AtomicU64,
}

impl AgentSession {
    fn new(template: &Arc<Env>) -> Self {
        Self {
            env: Mutex::new(Env::clone(template)),
            created_at: Instant::now(),
            last_used_at: Mutex::new(Instant::now()),
            request_count: AtomicU64::new(0),
            last_request_at: AtomicU64::new(0),
        }
    }

    fn touch(&self) {
        *self.last_used_at.lock().unwrap() = Instant::now();
        self.request_count.fetch_add(1, Ordering::Relaxed);
    }

    fn age_ms(&self) -> u64 { self.created_at.elapsed().as_millis() as u64 }

    fn idle_ms(&self) -> u64 { self.last_used_at.lock().unwrap().elapsed().as_millis() as u64 }
}

// ── Runtime Config ───────────────────────────────────────────────────

#[derive(Clone)]
pub struct RuntimeConfig {
    pub workspace: Option<PathBuf>,
    pub max_concurrency: usize,
    pub agent_mode: bool,
    pub max_sessions: usize,
    pub session_idle_timeout_ms: u64,
    pub cache_ttl_ms: u64,
    pub max_ast_entries: usize,
    /// Per-agent rate limit in requests per second. 0 = unlimited.
    pub rate_limit: u32,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            workspace: None,
            max_concurrency: 4,
            agent_mode: false,
            max_sessions: 256,
            session_idle_timeout_ms: 30 * 60 * 1000,
            cache_ttl_ms: 5000,
            max_ast_entries: 1024,
            rate_limit: 0,
        }
    }
}

// ── Runtime Stats ────────────────────────────────────────────────────

#[derive(Clone, Serialize)]
pub struct RuntimeStats {
    pub sessions: usize,
    pub total_requests: u64,
    pub ast_hits: u64,
    pub ast_misses: u64,
    pub sys_hits: u64,
    pub sys_misses: u64,
    pub ast_cache_size: usize,
    pub uptime_ms: u64,
}

// ── Lock-Free Agent Runtime ──────────────────────────────────────────

pub struct AgentRuntime {
    pub(crate) config: RuntimeConfig,
    template_env: Arc<Env>,
    sessions: RwLock<HashMap<String, Arc<AgentSession>>>,
    cache: Arc<GlobalCache>,
    started_at: Instant,
    total_requests: AtomicU64,
}

impl AgentRuntime {
    pub fn new(config: RuntimeConfig) -> Self {
        if config.agent_mode {
            std::env::set_var("AETHER_MODE", "agent");
        }
        if let Some(ref ws) = config.workspace {
            std::env::set_var("AETHER_WORKSPACE", ws.to_string_lossy().as_ref());
        }
        crate::safety::init_rbac_from_env();

        let mut template_env = Env::new();
        for (name, module) in modules::all_modules() {
            template_env.register_module(name, module);
        }
        let template_env = Arc::new(template_env);

        let cache = GlobalCache::new(config.max_ast_entries, config.cache_ttl_ms);
        Self::refresh_sys_snapshot_inner(&cache);

        Self {
            template_env,
            sessions: RwLock::new(HashMap::new()),
            cache,
            config,
            started_at: Instant::now(),
            total_requests: AtomicU64::new(0),
        }
    }

    /// Execute a request. No global lock — only the per-session Mutex<Env> is held.
    pub fn execute(&self, req: AgentRequest) -> AgentResponse {
        self.total_requests.fetch_add(1, Ordering::Relaxed);
        self.cache.inc_requests();
        let start = Instant::now();
        let agent_id = req.agent.clone();

        // ── Rate limit check ─────────────────────────────────
        if self.config.rate_limit > 0 {
            let session = self.get_or_create_session(&req.agent);
            let interval_us = 1_000_000u64 / self.config.rate_limit as u64;
            let now_us = start.elapsed().as_micros() as u64
                + self.started_at.elapsed().as_micros() as u64; // approx monotonic
            let last = session.last_request_at.swap(now_us, Ordering::Relaxed);
            if last > 0 && now_us.saturating_sub(last) < interval_us {
                return AgentResponse {
                    id: req.id, ok: false, value: None,
                    error: Some(AgentError {
                        code: "E_RATE_LIMIT".into(),
                        message: format!(
                            "rate limit exceeded: {} req/s (agent: {})",
                            self.config.rate_limit, agent_id
                        ),
                        hint: Some("reduce request frequency or increase --rate-limit".into()),
                        recoverable: true,
                    }),
                    meta: ResponseMeta {
                        elapsed_ms: start.elapsed().as_millis() as u64,
                        agent: agent_id,
                        cache_hit: None, budget_used: None, session_age_ms: session.age_ms(),
                    },
                };
            }
        }

        // ── Fast path: system snapshot cache ──────────────────
        if let Some(snap_resp) = self.try_sys_snapshot(&req, &agent_id) {
            return snap_resp;
        }

        // ── V2 Capability check ───────────────────────────────
        // Check capability for any builtin call in the command
        if let Some(builtin_name) = extract_builtin_name(&req.cmd) {
            match crate::capability::check_capability(&builtin_name) {
                crate::capability::CapabilityResult::Deny(reason) => {
                    return AgentResponse {
                        id: req.id, ok: false, value: None,
                        error: Some(AgentError {
                            code: "E_CAPABILITY_DENY".into(),
                            message: format!("capability denied: {}", reason),
                            hint: Some("request the required capability with --cap <name>".into()),
                            recoverable: true,
                        }),
                        meta: ResponseMeta {
                            elapsed_ms: start.elapsed().as_millis() as u64,
                            agent: agent_id, cache_hit: None, budget_used: None, session_age_ms: 0,
                        },
                    };
                }
                _ => {} // Allow
            }
        }

        // ── AST cache ────────────────────────────────────────
        let cached_ast = self.cache.get_ast(&req.cmd);
        let cache_hit = cached_ast.is_some();

        let stmts_to_run = match cached_ast {
            Some(stmts) => Some(stmts),
            None => match crate::parser::parse_program(&req.cmd) {
                Ok(stmts) => {
                    self.cache.put_ast(req.cmd.clone(), stmts.clone());
                    Some(Arc::new(stmts))
                }
                Err(e) => {
                    let msg = e.to_string();
                    let (code, recoverable) = classify_error_with_hint(&msg);
                    let hint = error_hint(&msg, &code);
                    return AgentResponse {
                        id: req.id, ok: false, value: None,
                        error: Some(AgentError { code, message: msg, hint, recoverable }),
                        meta: ResponseMeta {
                            elapsed_ms: start.elapsed().as_millis() as u64,
                            agent: agent_id, cache_hit: Some(false),
                            budget_used: None, session_age_ms: 0,
                        },
                    };
                }
            },
        };

        // ── Session lookup + execution ────────────────────────
        let session = self.get_or_create_session(&req.agent);

        let mut env = session.env.lock().unwrap();
        let result = if let Some(ref stmts) = stmts_to_run {
            crate::repl::run_eval_stmts(&mut env, stmts)
        } else {
            Err(anyhow::anyhow!("internal: no statements to execute"))
        };
        drop(env);

        let elapsed_ms = start.elapsed().as_millis() as u64;
        session.touch();
        let session_age_ms = session.age_ms();

        match result {
            Ok(val) => AgentResponse {
                id: req.id, ok: true,
                value: Some(val.to_json()), error: None,
                meta: ResponseMeta { elapsed_ms, agent: agent_id, cache_hit: Some(cache_hit), budget_used: None, session_age_ms },
            },
            Err(e) => {
                let msg = e.to_string();
                let (code, recoverable) = classify_error_with_hint(&msg);
                let hint = error_hint(&msg, &code);
                AgentResponse {
                    id: req.id, ok: false, value: None,
                    error: Some(AgentError { code, message: msg, hint, recoverable }),
                    meta: ResponseMeta { elapsed_ms, agent: agent_id, cache_hit: None, budget_used: None, session_age_ms },
                }
            }
        }
    }

    fn try_sys_snapshot(&self, req: &AgentRequest, agent_id: &str) -> Option<AgentResponse> {
        let cmd = req.cmd.trim();
        let needs = matches!(cmd, "sys.cpu_info()"|"sys.mem_info()"|"sys.disk_info()"|"sys.load_avg()"|"sys.hostname()"|"sys.os()"|"sys.uptime()"|"hw.cpu()"|"hw.memory()"|"hw.disks()");
        if !needs { return None; }
        if let Some(snap) = self.cache.get_sys_snapshot() {
            let val = match cmd {
                "sys.cpu_info()"|"hw.cpu()" => snap.cpu_info.clone(),
                "sys.mem_info()"|"hw.memory()" => snap.mem_info.clone(),
                "sys.disk_info()"|"hw.disks()" => snap.disk_info.clone(),
                "sys.load_avg()" => snap.load_avg.clone(),
                "sys.hostname()" => Value::Str(snap.hostname.clone()),
                "sys.os()" => Value::Str(snap.os.clone()),
                "sys.uptime()" => Value::Int(System::uptime() as i64),
                _ => return None,
            };
            Some(AgentResponse {
                id: req.id.clone(), ok: true, value: Some(val.to_json()), error: None,
                meta: ResponseMeta { elapsed_ms: 0, agent: agent_id.to_string(), cache_hit: Some(true), budget_used: None, session_age_ms: 0 },
            })
        } else {
            Self::refresh_sys_snapshot_inner(&self.cache);
            None
        }
    }

    fn refresh_sys_snapshot_inner(cache: &GlobalCache) {
        let sys = sysinfo::System::new_all();
        let disks = sysinfo::Disks::new_with_refreshed_list();
        let mut cpu_rec = std::collections::BTreeMap::new();
        let cpus = sys.cpus();
        if let Some(cpu) = cpus.first() {
            cpu_rec.insert("name".into(), Value::Str(cpu.brand().to_string()));
            cpu_rec.insert("cores".into(), Value::Int(sys.physical_core_count().unwrap_or(1) as i64));
            cpu_rec.insert("mhz".into(), Value::Float(cpu.frequency() as f64));
        }
        let mut mem_rec = std::collections::BTreeMap::new();
        mem_rec.insert("total".into(), Value::Int(sys.total_memory() as i64));
        mem_rec.insert("free".into(), Value::Int(sys.free_memory() as i64));
        mem_rec.insert("available".into(), Value::Int(sys.available_memory() as i64));
        let mut disk_arr = Vec::new();
        for disk in disks.list() {
            let mut d = std::collections::BTreeMap::new();
            let total = disk.total_space(); let avail = disk.available_space(); let used = total.saturating_sub(avail);
            let pct = if total > 0 { (used as f64 / total as f64 * 100.0) as i64 } else { 0 };
            d.insert("filesystem".into(), Value::Str(disk.file_system().to_str().unwrap_or("?").to_string()));
            d.insert("mounted_on".into(), Value::Str(disk.mount_point().to_str().unwrap_or("?").to_string()));
            d.insert("size".into(), Value::Int(total as i64));
            d.insert("used".into(), Value::Int(used as i64));
            d.insert("available".into(), Value::Int(avail as i64));
            d.insert("use_percent".into(), Value::Str(format!("{}%", pct)));
            disk_arr.push(Value::Record(d));
        }
        let load = sysinfo::System::load_average();
        let mut load_rec = std::collections::BTreeMap::new();
        load_rec.insert("1min".into(), Value::Float(load.one as f64));
        load_rec.insert("5min".into(), Value::Float(load.five as f64));
        load_rec.insert("15min".into(), Value::Float(load.fifteen as f64));
        cache.put_sys_snapshot(SystemSnapshot {
            cpu_info: Value::Record(cpu_rec), mem_info: Value::Record(mem_rec),
            disk_info: Value::Array(disk_arr), load_avg: Value::Record(load_rec),
            hostname: sysinfo::System::host_name().unwrap_or_default(),
            os: std::env::consts::OS.to_string(), taken_at: Instant::now(),
            ttl: Duration::from_millis(5000),
        });
    }

    pub fn refresh_sys_snapshot(&self) { Self::refresh_sys_snapshot_inner(&self.cache); }

    fn get_or_create_session(&self, agent_id: &str) -> Arc<AgentSession> {
        {
            let sessions = self.sessions.read().unwrap();
            if let Some(s) = sessions.get(agent_id) { return Arc::clone(s); }
        }
        let mut sessions = self.sessions.write().unwrap();
        if let Some(s) = sessions.get(agent_id) { return Arc::clone(s); }
        if sessions.len() >= self.config.max_sessions {
            if let Some(oldest) = sessions.iter().min_by_key(|(_, s)| s.idle_ms()) {
                let id = oldest.0.clone(); sessions.remove(&id);
            }
        }
        let session = Arc::new(AgentSession::new(&self.template_env));
        sessions.insert(agent_id.to_string(), Arc::clone(&session));
        session
    }

    pub fn gc_idle(&self) -> usize {
        let timeout = Duration::from_millis(self.config.session_idle_timeout_ms);
        let mut sessions = self.sessions.write().unwrap();
        let before = sessions.len();
        sessions.retain(|_, s| s.idle_ms() < timeout.as_millis() as u64);
        before - sessions.len()
    }

    pub fn full_stats(&self) -> RuntimeStats {
        let cs = self.cache.stats.read().unwrap();
        RuntimeStats {
            sessions: self.sessions.read().unwrap().len(),
            total_requests: self.total_requests.load(Ordering::Relaxed),
            ast_hits: cs.ast_hits, ast_misses: cs.ast_misses,
            sys_hits: cs.sys_hits, sys_misses: cs.sys_misses,
            ast_cache_size: self.cache.ast.read().unwrap().entries.len(),
            uptime_ms: self.started_at.elapsed().as_millis() as u64,
        }
    }

    pub fn session_count(&self) -> usize { self.sessions.read().unwrap().len() }
}

/// Extract the primary builtin name from a command string for capability checking.
fn extract_builtin_name(cmd: &str) -> Option<String> {
    let cmd = cmd.trim();
    if cmd.is_empty() { return None; }

    // Strip leading 'let ... = ' for assignment patterns
    let cmd = if let Some(rest) = cmd.strip_prefix("let ") {
        rest.splitn(2, '=').nth(1).map(|s| s.trim()).unwrap_or(cmd)
    } else { cmd };

    // Find the first function call pattern: name(...) or module.name(...)
    if let Some(paren_pos) = cmd.find('(') {
        let prefix = &cmd[..paren_pos].trim();
        // Get the last dot-separated component as the builtin name
        let name = prefix.rsplit('.').next().unwrap_or(prefix);
        return Some(name.to_string());
    }

    // Check for pipeline: ... | builtin_name
    if let Some(pipe_pos) = cmd.rfind('|') {
        let after_pipe = cmd[pipe_pos + 1..].trim();
        let name = after_pipe.split(|c: char| c.is_whitespace() || c == '(')
            .next()
            .unwrap_or("");
        if !name.is_empty() { return Some(name.to_string()); }
    }

    // Direct identifier (no parens, no pipes): "sort"
    let first_word = cmd.split(|c: char| c.is_whitespace()).next().unwrap_or("");
    if !first_word.is_empty() && first_word.chars().all(|c| c.is_alphanumeric() || c == '_') {
        return Some(first_word.to_string());
    }

    None
}

// ── Error Classification + Hint Generation ──────────────────────────

fn classify_error_with_hint(msg: &str) -> (String, bool) {
    if msg.contains("parse error") || msg.contains("expected") || msg.contains("unexpected token") {
        return ("E_PARSE".into(), true);
    }
    if msg.contains("BAD_ARG") || msg.contains("type") {
        return ("E_TYPE".into(), true);
    }
    if msg.contains("file") || msg.contains("path") || msg.contains("not found") {
        return ("E_IO".into(), true);
    }
    if msg.contains("unknown builtin") { return ("E_UNKNOWN_BUILTIN".into(), true); }
    if msg.contains("timeout") || msg.contains("timed out") { return ("E_TIMEOUT".into(), true); }
    if msg.contains("rate limit") { return ("E_RATE_LIMIT".into(), true); }
    ("E_INTERNAL".into(), false)
}

/// Generate a hint string for an error based on its code and message.
fn error_hint(msg: &str, code: &str) -> Option<String> {
    match code {
        "E_UNKNOWN_BUILTIN" => {
            // Extract the builtin name from the message: "unknown builtin: mat_abs"
            if let Some(name) = msg.strip_prefix("unknown builtin: ") {
                return Some(nearest_builtin(name));
            }
            None
        }
        "E_PARSE" => {
            Some("check syntax: missing parens, quotes, or operator".into())
        }
        "E_TYPE" => {
            Some("use 'describe' to inspect value types before operating".into())
        }
        "E_IO" => {
            Some("check that the file path exists and is accessible".into())
        }
        "E_RATE_LIMIT" => {
            Some("reduce request frequency or increase --rate-limit".into())
        }
        "E_INTERNAL" => {
            Some("this is an unexpected internal error; report if persistent".into())
        }
        _ => None,
    }
}

/// Find the closest builtin name to the given input using Levenshtein distance.
fn nearest_builtin(input: &str) -> String {
    // Lazily load known builtin names from BUILTIN_LOOKUP
    let names: Vec<&str> = crate::builtins::BUILTIN_LOOKUP.keys().copied().collect();
    if names.is_empty() {
        return "no suggestions available".into();
    }

    let input_lower = input.to_lowercase();
    let mut best: Option<(&str, usize)> = None;

    for name in &names {
        let dist = levenshtein(&input_lower, &name.to_lowercase());
        if dist <= 5 && (best.is_none() || dist < best.unwrap().1) {
            best = Some((name, dist));
        }
    }

    match best {
        Some((name, dist)) if dist <= 3 => format!("did you mean '{}'? (distance {})", name, dist),
        Some((name, _)) => format!("closest match: '{}'", name),
        None => format!("no similar builtin found for '{}'", input),
    }
}

fn levenshtein(a: &str, b: &str) -> usize {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let m = a_chars.len();
    let n = b_chars.len();
    if m == 0 { return n; }
    if n == 0 { return m; }

    let mut prev: Vec<usize> = (0..=n).collect();
    let mut curr = vec![0usize; n + 1];

    for i in 1..=m {
        curr[0] = i;
        for j in 1..=n {
            let cost = if a_chars[i - 1] == b_chars[j - 1] { 0 } else { 1 };
            curr[j] = (prev[j] + 1).min(curr[j - 1] + 1).min(prev[j - 1] + cost);
        }
        std::mem::swap(&mut prev, &mut curr);
    }
    prev[n]
}

// ── Panic-Resilient Thread-Safe Runtime Handle ───────────────────────

use sysinfo::System;

pub struct SharedRuntime {
    inner: Arc<AgentRuntime>,
}

impl SharedRuntime {
    pub fn new(config: RuntimeConfig) -> Self {
        Self { inner: Arc::new(AgentRuntime::new(config)) }
    }

    /// Execute with panic recovery — a panic in one request doesn't crash the server.
    pub fn execute(&self, req: AgentRequest) -> AgentResponse {
        let agent_id = req.agent.clone();
        let req_id = req.id.clone();
        let rt = Arc::clone(&self.inner);
        let req_clone = req; // moved into closure

        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
            rt.execute(req_clone)
        }));

        match result {
            Ok(resp) => resp,
            Err(panic_info) => {
                let msg = if let Some(s) = panic_info.downcast_ref::<String>() {
                    s.clone()
                } else if let Some(s) = panic_info.downcast_ref::<&str>() {
                    s.to_string()
                } else {
                    "unknown panic".to_string()
                };
                AgentResponse {
                    id: req_id,
                    ok: false,
                    value: None,
                    error: Some(AgentError {
                        code: "E_PANIC".into(),
                        message: format!("internal server error: {}", msg),
                        hint: Some("this is a bug; the request triggered an unrecoverable error".into()),
                        recoverable: false,
                    }),
                    meta: ResponseMeta {
                        elapsed_ms: 0,
                        agent: agent_id,
                        cache_hit: None,
                        budget_used: None,
                        session_age_ms: 0,
                    },
                }
            }
        }
    }

    pub fn stats(&self) -> RuntimeStats { self.inner.full_stats() }

    pub fn gc(&self) -> usize { self.inner.gc_idle() }

    pub fn refresh_snapshot(&self) { self.inner.refresh_sys_snapshot(); }

    pub fn clone_ref(&self) -> Self { Self { inner: Arc::clone(&self.inner) } }
}
