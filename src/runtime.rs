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
use crate::ir::{IRCompiler, IREffect, IREvaluator, IRNode};
use crate::modules;
use crate::rule::{self, RuleDecision};
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
    /// If true, run preflight analysis only — return ExecutionPlan without
    /// executing. Agent can inspect capabilities/effects/risk before committing.
    #[serde(default)]
    pub dry_run: bool,
    /// If true, collect per-IR-node ExecutionEvents and return in response.
    #[serde(default)]
    pub trace: bool,
}

fn default_timeout_ms() -> u64 {
    30000
}

#[derive(Debug, Serialize)]
pub struct AgentResponse {
    pub id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<AgentError>,
    pub meta: ResponseMeta,
    /// Preflight plan. Present when `dry_run=true` or attached to normal
    /// responses for agent observability.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub plan: Option<ExecutionPlan>,
    /// Per-node execution trace. Present when `trace=true`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trace: Option<ExecutionTrace>,
    /// Rule layer decision (Phase 2). Present when a rule matched during
    /// preflight or execution. Lets agents see policy decisions.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rule_decision: Option<RuleDecisionInfo>,
}

/// Serializable representation of a RuleDecision for the agent response.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum RuleDecisionInfo {
    Pass,
    Allow,
    Deny { reason: String },
    RateLimit { rate_per_minute: u32, reason: String },
    Confirm { reason: String },
}

impl From<&RuleDecision> for RuleDecisionInfo {
    fn from(d: &RuleDecision) -> Self {
        match d {
            RuleDecision::Pass => RuleDecisionInfo::Pass,
            RuleDecision::Allow => RuleDecisionInfo::Allow,
            RuleDecision::Deny(r) => RuleDecisionInfo::Deny { reason: r.clone() },
            RuleDecision::RateLimit { rate_per_minute, reason } => RuleDecisionInfo::RateLimit {
                rate_per_minute: *rate_per_minute,
                reason: reason.clone(),
            },
            RuleDecision::Confirm(r) => RuleDecisionInfo::Confirm { reason: r.clone() },
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct AgentError {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
    pub recoverable: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ResponseMeta {
    pub elapsed_ms: u64,
    pub agent: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cache_hit: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub budget_used: Option<usize>,
    pub session_age_ms: u64,
}

// ── Observable Execution Engine (Line B Phase 1) ────────────────────
//
// Inspired by InterCode (arXiv:2306.14898): execution feedback must be
// structured observation sufficient for agent self-correction. The v0.3
// runtime was a black box — agents saw only input/output. v0.4 adds:
//   - ExecutionPlan: preflight static analysis (capabilities + effects)
//   - ExecutionEvent: per-IR-node execution record
//   - ExecutionTrace: Vec<ExecutionEvent> returned with the response
//
// dry_run mode returns a plan without executing, letting agents confirm
// safety before side-effecting operations.

/// Risk level estimated from the IR's effect taxonomy.
/// Ordered by severity: Pure < ReadOnly < Mutating < Destructive.
#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum RiskLevel {
    /// Pure computation, no side effects.
    Pure,
    /// Read-only side effects (file read, sys info, proc list).
    ReadOnly,
    /// Mutating side effects (file write, http post).
    Mutating,
    /// Destructive/irreversible (file delete, proc kill).
    Destructive,
}

/// Preflight analysis result. Returned by `dry_run` or attached to normal
/// responses as part of `AgentResponse.plan`.
#[derive(Debug, Clone, Serialize)]
pub struct ExecutionPlan {
    /// Builtin names that will be called (static, ordered by first occurrence).
    pub builtins_called: Vec<String>,
    /// Capability tokens required (deduplicated).
    pub capabilities_required: Vec<String>,
    /// Effect classes touched.
    pub effects: Vec<String>,
    /// Aggregate risk level (highest among effects).
    pub risk_level: RiskLevel,
    /// Estimated side-effect categories.
    pub side_effects: Vec<String>,
    /// Number of IR nodes (rough cost proxy).
    pub node_count: usize,
}

/// A single execution event for tracing. Re-exported from `env.rs` (defined
/// there to avoid a circular dependency, since `ir.rs` needs to push events).
pub use crate::env::ExecutionEvent;

/// Collected execution trace. Returned when `AgentRequest.trace == true`.
pub type ExecutionTrace = Vec<ExecutionEvent>;

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

    fn age_ms(&self) -> u64 {
        self.created_at.elapsed().as_millis() as u64
    }

    fn idle_ms(&self) -> u64 {
        self.last_used_at.lock().unwrap().elapsed().as_millis() as u64
    }
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
            let now_us =
                start.elapsed().as_micros() as u64 + self.started_at.elapsed().as_micros() as u64; // approx monotonic
            let last = session.last_request_at.swap(now_us, Ordering::Relaxed);
            if last > 0 && now_us.saturating_sub(last) < interval_us {
                return AgentResponse {
                    id: req.id,
                    ok: false,
                    value: None,
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
                        cache_hit: None,
                        budget_used: None,
                        session_age_ms: session.age_ms(),
                    },
                    plan: None,
                    trace: None,
                    rule_decision: None,
                };
            }
        }

        // ── Fast path: system snapshot cache ──────────────────
        if let Some(snap_resp) = self.try_sys_snapshot(&req, &agent_id) {
            return snap_resp;
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
                        id: req.id,
                        ok: false,
                        value: None,
                        error: Some(AgentError {
                            code,
                            message: msg,
                            hint,
                            recoverable,
                        }),
                        meta: ResponseMeta {
                            elapsed_ms: start.elapsed().as_millis() as u64,
                            agent: agent_id,
                            cache_hit: Some(false),
                            budget_used: None,
                            session_age_ms: 0,
                        },
                        plan: None,
                        trace: None,
                        rule_decision: None,
                    };
                }
            },
        };

        // ── Phase 1: Compile IR + preflight analysis ───────
        // Compile AST → IR once, then reuse for both preflight and execution.
        // The preflight produces an ExecutionPlan (builtins, capabilities,
        // effects, risk level) without side effects.
        let ir_plan = if let Some(ref stmts) = stmts_to_run {
            let compiler = IRCompiler::new(true);
            let ir = compiler.compile_program(stmts);
            let plan = build_execution_plan(&ir);
            Some((ir, plan))
        } else {
            None
        };

        // ── dry_run: return plan without executing ──────────
        // Agent inspects capabilities/effects/risk before committing to
        // side-effecting execution (AgentSpec-inspired safety boundary).
        // Phase 2: also evaluate rules against the plan so the agent can see
        // policy decisions (deny/rate-limit/confirm) before committing.
        if req.dry_run {
            if let Some((_, plan)) = &ir_plan {
                let decision = rule::evaluate_plan(plan, &req.cmd);
                let rule_info: Option<RuleDecisionInfo> = match &decision {
                    RuleDecision::Pass => None,
                    other => Some(RuleDecisionInfo::from(other)),
                };
                return AgentResponse {
                    id: req.id,
                    ok: true,
                    value: None,
                    error: None,
                    meta: ResponseMeta {
                        elapsed_ms: start.elapsed().as_millis() as u64,
                        agent: agent_id,
                        cache_hit: Some(cache_hit),
                        budget_used: None,
                        session_age_ms: 0,
                    },
                    plan: Some(plan.clone()),
                    trace: None,
                    rule_decision: rule_info,
                };
            }
        }

        // ── Phase 2: Pre-execution rule check ──────────────
        // Evaluate the plan against the global RuleSet before executing.
        // Deny → abort with error. Confirm → return error prompting agent
        // to acknowledge. RateLimit → enforced per-builtin during execution
        // (via check_builtin in ir.rs Builtin dispatch, future enhancement).
        // For now, evaluate_plan gives a conservative pre-check.
        if let Some((_, plan)) = &ir_plan {
            let decision = rule::evaluate_plan(plan, &req.cmd);
            match &decision {
                RuleDecision::Deny(reason) => {
                    return AgentResponse {
                        id: req.id,
                        ok: false,
                        value: None,
                        error: Some(AgentError {
                            code: "E_RULE_DENIED".into(),
                            message: reason.clone(),
                            hint: Some("operation blocked by policy rule; adjust rule file or use dry_run to inspect".into()),
                            recoverable: false,
                        }),
                        meta: ResponseMeta {
                            elapsed_ms: start.elapsed().as_millis() as u64,
                            agent: agent_id,
                            cache_hit: Some(cache_hit),
                            budget_used: None,
                            session_age_ms: 0,
                        },
                        plan: Some(plan.clone()),
                        trace: None,
                        rule_decision: Some(RuleDecisionInfo::from(&decision)),
                    };
                }
                RuleDecision::Confirm(reason) => {
                    return AgentResponse {
                        id: req.id,
                        ok: false,
                        value: None,
                        error: Some(AgentError {
                            code: "E_RULE_CONFIRM".into(),
                            message: format!("confirmation required: {}", reason),
                            hint: Some("re-request with explicit acknowledgment that this operation is destructive".into()),
                            recoverable: true,
                        }),
                        meta: ResponseMeta {
                            elapsed_ms: start.elapsed().as_millis() as u64,
                            agent: agent_id,
                            cache_hit: Some(cache_hit),
                            budget_used: None,
                            session_age_ms: 0,
                        },
                        plan: Some(plan.clone()),
                        trace: None,
                        rule_decision: Some(RuleDecisionInfo::from(&decision)),
                    };
                }
                _ => {} // Pass, Allow, RateLimit proceed to execution
            }
        }

        // ── Session lookup + execution ────────────────────────
        let session = self.get_or_create_session(&req.agent);

        let mut env = session.env.lock().unwrap();
        // T5: inject per-request deadline so IR evaluation can abort long-running
        // programs. `timeout_ms == 0` means "no deadline" (preserves prior behavior
        // for callers that explicitly disable timeout).
        env.deadline = if req.timeout_ms > 0 {
            Some(Instant::now() + Duration::from_millis(req.timeout_ms))
        } else {
            None
        };
        // Phase 1: enable per-node trace collection when requested. The trace
        // collector is a Vec that ir.rs::eval pushes ExecutionEvents into.
        env.trace = if req.trace { Some(Vec::new()) } else { None };
        let result = if let Some((ir, _)) = &ir_plan {
            IREvaluator::eval_program(ir, &mut env)
        } else {
            Err(anyhow::anyhow!("internal: no statements to execute"))
        };
        // Extract trace before clearing deadline so the env (returned to session
        // pool) doesn't carry stale state into the next request.
        let trace_data = env.trace.take();
        env.deadline = None;
        drop(env);

        let elapsed_ms = start.elapsed().as_millis() as u64;
        session.touch();
        let session_age_ms = session.age_ms();
        let plan_data = ir_plan.as_ref().map(|(_, p)| p.clone());

        match result {
            Ok(val) => AgentResponse {
                id: req.id,
                ok: true,
                value: Some(val.to_json()),
                error: None,
                meta: ResponseMeta {
                    elapsed_ms,
                    agent: agent_id,
                    cache_hit: Some(cache_hit),
                    budget_used: None,
                    session_age_ms,
                },
                plan: plan_data,
                trace: trace_data,
                rule_decision: None,
            },
            Err(e) => {
                let msg = e.to_string();
                let (code, recoverable) = classify_error_with_hint(&msg);
                let hint = error_hint(&msg, &code);
                AgentResponse {
                    id: req.id,
                    ok: false,
                    value: None,
                    error: Some(AgentError {
                        code,
                        message: msg,
                        hint,
                        recoverable,
                    }),
                    meta: ResponseMeta {
                        elapsed_ms,
                        agent: agent_id,
                        cache_hit: None,
                        budget_used: None,
                        session_age_ms,
                    },
                    plan: plan_data,
                    trace: trace_data,
                    rule_decision: None,
                }
            }
        }
    }

    fn try_sys_snapshot(&self, req: &AgentRequest, agent_id: &str) -> Option<AgentResponse> {
        // Skip the fast path when the agent explicitly requests preflight
        // analysis (dry_run) or execution tracing — these modes need the full
        // IR compilation path to produce plan/trace data.
        if req.dry_run || req.trace {
            return None;
        }
        let cmd = req.cmd.trim();
        let needs = matches!(
            cmd,
            "sys.cpu_info()"
                | "sys.mem_info()"
                | "sys.disk_info()"
                | "sys.load_avg()"
                | "sys.hostname()"
                | "sys.os()"
                | "sys.uptime()"
                | "hw.cpu()"
                | "hw.memory()"
                | "hw.disks()"
                | "proc.list()"
                | "sys.info()"
        );
        if !needs {
            return None;
        }
        if let Some(snap) = self.cache.get_sys_snapshot() {
            let val = match cmd {
                "sys.cpu_info()" | "hw.cpu()" => snap.cpu_info.clone(),
                "sys.mem_info()" | "hw.memory()" => snap.mem_info.clone(),
                "sys.disk_info()" | "hw.disks()" => snap.disk_info.clone(),
                "sys.load_avg()" => snap.load_avg.clone(),
                "sys.hostname()" => Value::Str(snap.hostname.clone()),
                "sys.os()" => Value::Str(snap.os.clone()),
                "sys.uptime()" => Value::Int(System::uptime() as i64),
                "proc.list()" => snap.process_list.clone(),
                "sys.info()" => snap.sys_info.clone(),
                _ => return None,
            };
            Some(AgentResponse {
                id: req.id.clone(),
                ok: true,
                value: Some(val.to_json()),
                error: None,
                meta: ResponseMeta {
                    elapsed_ms: 0,
                    agent: agent_id.to_string(),
                    cache_hit: Some(true),
                    budget_used: None,
                    session_age_ms: 0,
                },
                plan: None,
                trace: None,
                rule_decision: None,
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
            cpu_rec.insert(
                "cores".into(),
                Value::Int(sys.physical_core_count().unwrap_or(1) as i64),
            );
            cpu_rec.insert("mhz".into(), Value::Float(cpu.frequency() as f64));
        }
        let mut mem_rec = std::collections::BTreeMap::new();
        mem_rec.insert("total".into(), Value::Int(sys.total_memory() as i64));
        mem_rec.insert("free".into(), Value::Int(sys.free_memory() as i64));
        mem_rec.insert(
            "available".into(),
            Value::Int(sys.available_memory() as i64),
        );
        let mut disk_arr = Vec::new();
        for disk in disks.list() {
            let mut d = std::collections::BTreeMap::new();
            let total = disk.total_space();
            let avail = disk.available_space();
            let used = total.saturating_sub(avail);
            let pct = if total > 0 {
                (used as f64 / total as f64 * 100.0) as i64
            } else {
                0
            };
            d.insert(
                "filesystem".into(),
                Value::Str(disk.file_system().to_str().unwrap_or("?").to_string()),
            );
            d.insert(
                "mounted_on".into(),
                Value::Str(disk.mount_point().to_str().unwrap_or("?").to_string()),
            );
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

        // Build cached process list from the same System snapshot
        let mut procs = Vec::new();
        for (pid, proc) in sys.processes() {
            let mut rec = std::collections::BTreeMap::new();
            rec.insert("pid".to_string(), Value::Int(pid.as_u32() as i64));
            rec.insert("name".to_string(), Value::Str(proc.name().to_string_lossy().to_string()));
            rec.insert("cpu".to_string(), Value::Float(proc.cpu_usage() as f64));
            rec.insert("mem".to_string(), Value::Int(proc.memory() as i64));
            rec.insert("command".to_string(), Value::Str(
                proc.exe().map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|| proc.name().to_string_lossy().to_string())
            ));
            procs.push(Value::Record(rec));
        }
        procs.sort_by(|a, b| {
            let pid_a = match a { Value::Record(r) => r.get("pid").and_then(|v| if let Value::Int(n) = v { Some(*n) } else { None }).unwrap_or(0), _ => 0 };
            let pid_b = match b { Value::Record(r) => r.get("pid").and_then(|v| if let Value::Int(n) = v { Some(*n) } else { None }).unwrap_or(0), _ => 0 };
            pid_a.cmp(&pid_b)
        });

        // Build cached sys_info with os_name from sysinfo instead of spawning powershell
        let mut sys_info_rec = std::collections::BTreeMap::new();
        sys_info_rec.insert("os".to_string(), Value::Str(std::env::consts::OS.to_string()));
        sys_info_rec.insert("arch".to_string(), Value::Str(std::env::consts::ARCH.to_string()));
        sys_info_rec.insert("family".to_string(), Value::Str(std::env::consts::FAMILY.to_string()));
        // Use sysinfo for OS name (works cross-platform without subprocess)
        sys_info_rec.insert("os_name".to_string(), Value::Str(
            sysinfo::System::name().unwrap_or_else(|| std::env::consts::OS.to_string())
        ));

        cache.put_sys_snapshot(SystemSnapshot {
            cpu_info: Value::Record(cpu_rec),
            mem_info: Value::Record(mem_rec),
            disk_info: Value::Array(disk_arr),
            load_avg: Value::Record(load_rec),
            hostname: sysinfo::System::host_name().unwrap_or_default(),
            os: std::env::consts::OS.to_string(),
            process_list: Value::Array(procs),
            sys_info: Value::Record(sys_info_rec),
            taken_at: Instant::now(),
            ttl: Duration::from_millis(5000),
        });
    }

    pub fn refresh_sys_snapshot(&self) {
        Self::refresh_sys_snapshot_inner(&self.cache);
    }

    fn get_or_create_session(&self, agent_id: &str) -> Arc<AgentSession> {
        {
            let sessions = self.sessions.read().unwrap();
            if let Some(s) = sessions.get(agent_id) {
                return Arc::clone(s);
            }
        }
        let mut sessions = self.sessions.write().unwrap();
        if let Some(s) = sessions.get(agent_id) {
            return Arc::clone(s);
        }
        if sessions.len() >= self.config.max_sessions {
            if let Some(oldest) = sessions.iter().min_by_key(|(_, s)| s.idle_ms()) {
                let id = oldest.0.clone();
                sessions.remove(&id);
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
            ast_hits: cs.ast_hits,
            ast_misses: cs.ast_misses,
            sys_hits: cs.sys_hits,
            sys_misses: cs.sys_misses,
            ast_cache_size: self.cache.ast.read().unwrap().entries.len(),
            uptime_ms: self.started_at.elapsed().as_millis() as u64,
        }
    }

    pub fn session_count(&self) -> usize {
        self.sessions.read().unwrap().len()
    }
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
    if msg.contains("unknown builtin") {
        return ("E_UNKNOWN_BUILTIN".into(), true);
    }
    if msg.contains("timeout") || msg.contains("timed out") {
        return ("E_TIMEOUT".into(), true);
    }
    if msg.contains("rate limit") {
        return ("E_RATE_LIMIT".into(), true);
    }
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
        "E_PARSE" => Some("check syntax: missing parens, quotes, or operator".into()),
        "E_TYPE" => Some("use 'describe' to inspect value types before operating".into()),
        "E_IO" => Some("check that the file path exists and is accessible".into()),
        "E_RATE_LIMIT" => Some("reduce request frequency or increase --rate-limit".into()),
        "E_TIMEOUT" => Some("reduce workload or increase timeout_ms in the request".into()),
        "E_INTERNAL" => Some("this is an unexpected internal error; report if persistent".into()),
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
    if m == 0 {
        return n;
    }
    if n == 0 {
        return m;
    }

    let mut prev: Vec<usize> = (0..=n).collect();
    let mut curr = vec![0usize; n + 1];

    for i in 1..=m {
        curr[0] = i;
        for j in 1..=n {
            let cost = if a_chars[i - 1] == b_chars[j - 1] {
                0
            } else {
                1
            };
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
        Self {
            inner: Arc::new(AgentRuntime::new(config)),
        }
    }

    /// Execute with panic recovery — a panic in one request doesn't crash the server.
    pub fn execute(&self, req: AgentRequest) -> AgentResponse {
        let agent_id = req.agent.clone();
        let req_id = req.id.clone();
        let rt = Arc::clone(&self.inner);
        let req_clone = req; // moved into closure

        let result =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || rt.execute(req_clone)));

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
                        hint: Some(
                            "this is a bug; the request triggered an unrecoverable error".into(),
                        ),
                        recoverable: false,
                    }),
                    meta: ResponseMeta {
                        elapsed_ms: 0,
                        agent: agent_id,
                        cache_hit: None,
                        budget_used: None,
                        session_age_ms: 0,
                    },
                    plan: None,
                    trace: None,
                    rule_decision: None,
                }
            }
        }
    }

    pub fn stats(&self) -> RuntimeStats {
        self.inner.full_stats()
    }

    pub fn gc(&self) -> usize {
        self.inner.gc_idle()
    }

    pub fn refresh_snapshot(&self) {
        self.inner.refresh_sys_snapshot();
    }

    pub fn clone_ref(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
        }
    }
}

// ── Phase 1: Preflight analysis helpers ─────────────────────────────
//
// Walk the IR to collect builtins, effects, and estimate risk — without
// executing anything. Used by `dry_run` and attached to normal responses
// for agent observability.

/// Build an `ExecutionPlan` from compiled IR by walking all nodes and
/// collecting `Builtin` calls with their effects.
fn build_execution_plan(ir: &[IRNode]) -> ExecutionPlan {
    let mut builtins: Vec<(String, IREffect)> = Vec::new();
    let mut node_count: usize = 0;

    for node in ir {
        collect_builtins(node, &mut builtins, &mut node_count);
    }

    // Deduplicate builtins by name (keep first occurrence order).
    let mut seen = std::collections::HashSet::new();
    let builtins_dedup: Vec<String> = builtins
        .iter()
        .map(|(n, _)| n.clone())
        .filter(|n| seen.insert(n.clone()))
        .collect();

    // Deduplicate capabilities.
    let mut caps_seen = std::collections::HashSet::new();
    let capabilities: Vec<String> = builtins
        .iter()
        .filter_map(|(_, e)| effect_to_capability(e))
        .filter(|c| caps_seen.insert(c.to_string()))
        .map(String::from)
        .collect();

    // Deduplicate effects.
    let mut eff_seen = std::collections::HashSet::new();
    let effects: Vec<String> = builtins
        .iter()
        .filter_map(|(_, e)| {
            let s = effect_to_str(e);
            if eff_seen.insert(s.clone()) {
                Some(s)
            } else {
                None
            }
        })
        .collect();

    let risk = compute_risk(&builtins);
    let side_effects = compute_side_effects(&builtins);

    ExecutionPlan {
        builtins_called: builtins_dedup,
        capabilities_required: capabilities,
        effects,
        risk_level: risk,
        side_effects,
        node_count,
    }
}

/// Recursively walk an IR node, collecting Builtin calls and counting nodes.
fn collect_builtins(
    node: &IRNode,
    out: &mut Vec<(String, IREffect)>,
    count: &mut usize,
) {
    *count += 1;
    match node {
        IRNode::Builtin(name, args, effect) => {
            out.push((name.clone(), effect.clone()));
            for arg in args {
                collect_builtins(arg, out, count);
            }
        }
        IRNode::Array(items) => {
            for item in items {
                collect_builtins(item, out, count);
            }
        }
        IRNode::Record(map) => {
            for v in map.values() {
                collect_builtins(v, out, count);
            }
        }
        IRNode::Let(_, val, body) => {
            collect_builtins(val, out, count);
            collect_builtins(body, out, count);
        }
        IRNode::Binary(a, _, b) => {
            collect_builtins(a, out, count);
            collect_builtins(b, out, count);
        }
        IRNode::Unary(_, a) => {
            collect_builtins(a, out, count);
        }
        IRNode::If(c, t, e) => {
            collect_builtins(c, out, count);
            collect_builtins(t, out, count);
            collect_builtins(e, out, count);
        }
        IRNode::Match(scrutinee, arms) => {
            collect_builtins(scrutinee, out, count);
            for arm in arms {
                if let Some(g) = &arm.guard {
                    collect_builtins(g, out, count);
                }
                collect_builtins(&arm.body, out, count);
            }
        }
        IRNode::Try(body, _, catch) => {
            collect_builtins(body, out, count);
            collect_builtins(catch, out, count);
        }
        IRNode::Throw(inner) => {
            collect_builtins(inner, out, count);
        }
        IRNode::Call(callee, args) => {
            collect_builtins(callee, out, count);
            for arg in args {
                collect_builtins(arg, out, count);
            }
        }
        IRNode::Pipeline(stages) => {
            for s in stages {
                collect_builtins(s, out, count);
            }
        }
        IRNode::Reduce(_, _, init) => {
            collect_builtins(init, out, count);
        }
        IRNode::Take(n) => {
            collect_builtins(n, out, count);
        }
        IRNode::FusedMapMap(a, b) | IRNode::FusedMapFilter(a, b) | IRNode::FusedFilterMap(a, b) => {
            collect_builtins(a, out, count);
            collect_builtins(b, out, count);
        }
        IRNode::MemberAccess(obj, _) => {
            collect_builtins(obj, out, count);
        }
        IRNode::Annotate(_, _, inner) => {
            collect_builtins(inner, out, count);
        }
        // Leaf nodes or AST-Expr-bearing nodes (Lambda/Map/Filter/Sort carry
        // `Box<Expr>` which is AST, not IR — no builtins to collect there).
        IRNode::Unit | IRNode::Bool(_) | IRNode::Int(_) | IRNode::Float(_)
        | IRNode::Str(_) | IRNode::Var(_) | IRNode::Lambda(_, _)
        | IRNode::Map(_, _) | IRNode::Filter(_, _) | IRNode::Sort(_)
        | IRNode::Error(_, _) => {}
    }
}

/// Convert an IREffect to a human-readable string.
fn effect_to_str(e: &IREffect) -> String {
    match e {
        IREffect::Pure => "pure".into(),
        IREffect::SysRead => "sys_read".into(),
        IREffect::FileRead => "file_read".into(),
        IREffect::FileWrite => "file_write".into(),
        IREffect::FileDelete => "file_delete".into(),
        IREffect::NetHttpGet => "net_http_get".into(),
        IREffect::NetHttpPost => "net_http_post".into(),
        IREffect::NetHttpDelete => "net_http_delete".into(),
        IREffect::ProcList => "proc_list".into(),
        IREffect::ProcKill => "proc_kill".into(),
        IREffect::ProcSpawn => "proc_spawn".into(),
        IREffect::ShellExec => "shell_exec".into(),
        IREffect::WinRegistry => "win_registry".into(),
        IREffect::WinService => "win_service".into(),
        IREffect::CryptoHash => "crypto_hash".into(),
        IREffect::CryptoRandom => "crypto_random".into(),
        IREffect::DbRead => "db_read".into(),
        IREffect::DbWrite => "db_write".into(),
        IREffect::GitRead => "git_read".into(),
        IREffect::GitWrite => "git_write".into(),
        IREffect::Combined(effects) => {
            let parts: Vec<String> = effects.iter().map(effect_to_str).collect();
            format!("combined({})", parts.join(","))
        }
    }
}

/// Map an IREffect to the capability token it requires (if any).
fn effect_to_capability(e: &IREffect) -> Option<&'static str> {
    match e {
        IREffect::Pure => None,
        IREffect::SysRead => Some("sys.read"),
        IREffect::FileRead => Some("file.read"),
        IREffect::FileWrite => Some("file.write"),
        IREffect::FileDelete => Some("file.delete"),
        IREffect::NetHttpGet => Some("net.http.get"),
        IREffect::NetHttpPost => Some("net.http.post"),
        IREffect::NetHttpDelete => Some("net.http.delete"),
        IREffect::ProcList => Some("proc.list"),
        IREffect::ProcKill => Some("proc.kill"),
        IREffect::ProcSpawn => Some("proc.spawn"),
        IREffect::ShellExec => Some("shell.exec"),
        IREffect::WinRegistry => Some("win.registry"),
        IREffect::WinService => Some("win.service"),
        IREffect::CryptoHash => Some("crypto.hash"),
        IREffect::CryptoRandom => Some("crypto.random"),
        IREffect::DbRead => Some("db.read"),
        IREffect::DbWrite => Some("db.write"),
        IREffect::GitRead => Some("git.read"),
        IREffect::GitWrite => Some("git.write"),
        IREffect::Combined(_) => None, // complex, individual caps handled per-builtin
    }
}

/// Compute aggregate risk level from the effects of all builtins.
fn compute_risk(builtins: &[(String, IREffect)]) -> RiskLevel {
    let mut risk = RiskLevel::Pure;
    for (_, e) in builtins {
        let r = effect_to_risk(e);
        if r > risk {
            risk = r;
        }
    }
    risk
}

fn effect_to_risk(e: &IREffect) -> RiskLevel {
    match e {
        IREffect::Pure => RiskLevel::Pure,
        IREffect::SysRead | IREffect::FileRead | IREffect::ProcList
        | IREffect::WinRegistry | IREffect::WinService | IREffect::CryptoHash
        | IREffect::CryptoRandom | IREffect::DbRead | IREffect::GitRead
        | IREffect::NetHttpGet => RiskLevel::ReadOnly,
        IREffect::FileWrite | IREffect::NetHttpPost | IREffect::ProcSpawn
        | IREffect::DbWrite | IREffect::GitWrite => RiskLevel::Mutating,
        IREffect::FileDelete | IREffect::NetHttpDelete | IREffect::ProcKill
        | IREffect::ShellExec => RiskLevel::Destructive,
        IREffect::Combined(effects) => {
            let mut r = RiskLevel::Pure;
            for e in effects {
                let er = effect_to_risk(e);
                if er > r {
                    r = er;
                }
            }
            r
        }
    }
}

/// Produce side-effect category labels from effects.
fn compute_side_effects(builtins: &[(String, IREffect)]) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for (_, e) in builtins {
        let cats = effect_side_effect_categories(e);
        for c in cats {
            if seen.insert(c.to_string()) {
                out.push(c.to_string());
            }
        }
    }
    out
}

fn effect_side_effect_categories(e: &IREffect) -> Vec<&'static str> {
    match e {
        IREffect::Pure => vec![],
        IREffect::SysRead | IREffect::FileRead | IREffect::ProcList
        | IREffect::WinRegistry | IREffect::WinService | IREffect::CryptoHash
        | IREffect::CryptoRandom | IREffect::DbRead | IREffect::GitRead => vec!["reads"],
        IREffect::FileWrite | IREffect::DbWrite | IREffect::GitWrite => vec!["writes"],
        IREffect::NetHttpPost | IREffect::NetHttpDelete | IREffect::NetHttpGet => vec!["network"],
        IREffect::ProcSpawn => vec!["process"],
        IREffect::ProcKill => vec!["process", "destructive"],
        IREffect::ShellExec => vec!["process", "network", "writes", "destructive"],
        IREffect::FileDelete => vec!["writes", "destructive"],
        IREffect::Combined(effects) => {
            let mut out = Vec::new();
            for e in effects {
                out.extend(effect_side_effect_categories(e));
            }
            out
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exec_req(cmd: &str, dry_run: bool, trace: bool) -> AgentRequest {
        AgentRequest {
            id: "test".into(),
            agent: "test-agent".into(),
            cmd: cmd.into(),
            timeout_ms: 0,
            budget: None,
            dry_run,
            trace,
        }
    }

    #[test]
    fn dry_run_returns_plan_without_executing() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        let resp = rt.execute(exec_req("1 + 2", true, false));

        // dry_run must succeed without executing
        assert!(resp.ok, "dry_run should succeed");
        assert!(resp.value.is_none(), "dry_run should not return a value");
        assert!(resp.plan.is_some(), "dry_run must return a plan");

        let plan = resp.plan.unwrap();
        assert!(plan.node_count > 0, "plan should have nodes");
        assert_eq!(plan.risk_level, RiskLevel::Pure, "1+2 is pure");
        assert!(plan.builtins_called.is_empty(), "1+2 has no builtins");
    }

    #[test]
    fn dry_run_detects_readonly_risk() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        // sys.cpu_info is a read-only sys call
        let resp = rt.execute(exec_req("sys.cpu_info()", true, false));

        assert!(resp.ok);
        let plan = resp.plan.unwrap();
        assert_eq!(plan.risk_level, RiskLevel::ReadOnly);
        assert!(plan.builtins_called.iter().any(|b| b.contains("cpu")));
        assert!(plan.capabilities_required.contains(&"sys.read".to_string()));
        assert!(plan.side_effects.contains(&"reads".to_string()));
    }

    #[test]
    fn dry_run_detects_mutating_risk() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        // file.write is a mutating op — use dry_run so we don't actually write
        let resp = rt.execute(exec_req("file.write(\"/tmp/_dry_run_test\", \"x\")", true, false));

        assert!(resp.ok);
        let plan = resp.plan.unwrap();
        assert_eq!(plan.risk_level, RiskLevel::Mutating);
        assert!(plan.capabilities_required.contains(&"file.write".to_string()));
        assert!(plan.side_effects.contains(&"writes".to_string()));
    }

    #[test]
    fn trace_collects_events() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        let resp = rt.execute(exec_req("1 + 2 * 3", false, true));

        assert!(resp.ok);
        let trace = resp.trace.expect("trace should be collected");
        assert!(!trace.is_empty(), "trace should have at least one event");

        // Every event should have a node_type
        for ev in &trace {
            assert!(!ev.node_type.is_empty());
            assert!(ev.ok, "all events in 1+2*3 should succeed");
        }
    }

    #[test]
    fn trace_labels_builtins() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        // sys.os() compiles to a Builtin node
        let resp = rt.execute(exec_req("sys.os()", false, true));

        assert!(resp.ok);
        let trace = resp.trace.expect("trace should be collected");
        let has_builtin = trace.iter().any(|ev| {
            ev.node_type == "Builtin" && ev.builtin_name.is_some()
        });
        assert!(has_builtin, "trace should contain at least one Builtin event");
    }

    #[test]
    fn normal_execution_attaches_plan() {
        let rt = AgentRuntime::new(RuntimeConfig::default());
        // Non-dry-run execution should also attach plan for observability
        let resp = rt.execute(exec_req("1 + 2", false, false));

        assert!(resp.ok);
        assert!(resp.plan.is_some(), "plan should be attached to normal responses");
        assert!(resp.trace.is_none(), "trace should be None when trace=false");
    }
}
