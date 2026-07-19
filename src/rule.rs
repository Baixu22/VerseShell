//! AgentSpec Rule Layer (Line B Phase 2).
//!
//! Declarative policy layer that augments the static capability model.
//! While `capability.rs` answers "is this builtin's capability granted?",
//! the rule layer answers richer policy questions:
//!
//!   - "Is this builtin allowed for this agent at this time?"
//!   - "Should this destructive op require interactive confirmation?"
//!   - "Should this network op be rate-limited?"
//!
//! ## Rule evaluation order
//!
//! 1. Static capability check (`capability::check_capability`) — the baseline
//!    allow/deny derived from `--cap` flags or `AETHER_CAPS` env var.
//! 2. Rule layer (this module) — dynamic, configurable policies loaded from
//!    a TOML file via `--rules <path>` or `AETHER_RULES` env var.
//! 3. RBAC approval gating (`safety.rs`) — interactive confirm for destructive
//!    ops when an authorized principal is present.
//!
//! Rules are evaluated in declaration order; first match wins. A rule that
//! matches but has action `Allow` short-circuits further rule evaluation.
//!
//! ## TOML format
//!
//! ```toml
//! [[rule]]
//! name = "deny-rm-rf"
//! match = { builtin = "sh", pattern = ".*rm -rf.*" }
//! action = "deny"
//! reason = "recursive delete is forbidden"
//!
//! [[rule]]
//! name = "limit-http"
//! match = { effect = "NetHttpPost" }
//! action = "rate_limit"
//! rate_per_minute = 10
//!
//! [[rule]]
//! name = "confirm-file-delete"
//! match = { effect = "FileDelete" }
//! action = "confirm"
//! reason = "file deletion is irreversible"
//!
//! [[rule]]
//! name = "allow-sys-read"
//! match = { effect = "SysRead" }
//! action = "allow"
//! ```
//!
//! ## Integration
//!
//! The runtime calls `rule::evaluate(&plan)` during preflight (dry_run) and
//! `rule::check_builtin(name)` before each Builtin IR node executes. Deny
//! results abort execution; rate_limit results enforce a sliding window;
//! confirm results return an error prompting the agent to re-request with
//! explicit confirmation.

use crate::ir::IREffect;
use crate::runtime::{ExecutionPlan, RiskLevel};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::RwLock;

// ── Rule Action ─────────────────────────────────────────────────────

/// Action kind prescribed by a rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionKind {
    /// Explicitly allow the operation; skip remaining rules.
    Allow,
    /// Deny the operation with a reason.
    Deny,
    /// Rate-limit the operation to N calls per minute (sliding window).
    RateLimit,
    /// Require explicit confirmation before proceeding.
    Confirm,
}

/// Action a rule prescribes when its match criteria are met.
/// Serialized as flat fields in TOML: `action = "deny"` + `reason = "..."`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuleAction {
    /// The action kind.
    pub action: ActionKind,
    /// Reason shown to the agent (used by Deny/Confirm/RateLimit).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Rate limit (calls per minute). Only meaningful for `RateLimit`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rate_per_minute: Option<u32>,
}

impl RuleAction {
    pub fn allow() -> Self {
        Self { action: ActionKind::Allow, reason: None, rate_per_minute: None }
    }
    pub fn deny(reason: impl Into<String>) -> Self {
        Self { action: ActionKind::Deny, reason: Some(reason.into()), rate_per_minute: None }
    }
    pub fn confirm(reason: impl Into<String>) -> Self {
        Self { action: ActionKind::Confirm, reason: Some(reason.into()), rate_per_minute: None }
    }
    pub fn rate_limit(rate: u32, reason: impl Into<String>) -> Self {
        Self { action: ActionKind::RateLimit, reason: Some(reason.into()), rate_per_minute: Some(rate) }
    }
}

// ── Rule Match ──────────────────────────────────────────────────────

/// Match criteria for a rule. All specified fields must match (AND logic).
/// Unspecified fields are wildcards (match anything).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuleMatch {
    /// Match by builtin name (exact match, e.g. `"file_write"`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub builtin: Option<String>,
    /// Match by capability token (e.g. `"file.write"`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capability: Option<String>,
    /// Match by IREffect variant name (e.g. `"FileWrite"`, `"NetHttpPost"`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub effect: Option<String>,
    /// Match by RiskLevel (e.g. `"mutating"`, `"destructive"`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub risk: Option<String>,
    /// Regex pattern matched against the original command text.
    /// Used for argument-aware rules (e.g., `".*rm -rf.*"` on `sh`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pattern: Option<String>,
}

// ── Rule ────────────────────────────────────────────────────────────

/// A single policy rule. Fields are inlined (no serde(flatten)) for TOML compat.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rule {
    /// Human-readable name for diagnostics.
    #[serde(default)]
    pub name: String,
    /// Match criteria (TOML sub-table `match = { ... }`).
    #[serde(rename = "match", default)]
    pub r#match: RuleMatch,
    /// Action kind: "allow", "deny", "rate_limit", "confirm".
    pub action: ActionKind,
    /// Reason shown to agent (for deny/confirm/rate_limit).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Rate limit (calls per minute). Only for `rate_limit` action.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rate_per_minute: Option<u32>,
}

impl Rule {
    /// Return a view of this rule's action as a RuleAction struct.
    pub fn action_view(&self) -> RuleAction {
        RuleAction {
            action: self.action.clone(),
            reason: self.reason.clone(),
            rate_per_minute: self.rate_per_minute,
        }
    }
}

impl Rule {
    /// Check if this rule matches the given evaluation context.
    /// All specified match fields must match (AND logic).
    fn matches(
        &self,
        builtin: &str,
        capability: Option<&str>,
        effect: Option<&IREffect>,
        risk: Option<&RiskLevel>,
        cmd: &str,
    ) -> bool {
        let m = &self.r#match;

        if let Some(ref want) = m.builtin {
            if builtin != want {
                return false;
            }
        }
        if let Some(ref want) = m.capability {
            if Some(want.as_str()) != capability {
                return false;
            }
        }
        if let Some(ref want) = m.effect {
            let actual = effect.map(effect_name).unwrap_or("");
            if actual != want {
                return false;
            }
        }
        if let Some(ref want) = m.risk {
            let actual = risk.map(risk_name).unwrap_or("");
            if !risk_matches(actual, want) {
                return false;
            }
        }
        if let Some(ref pat) = m.pattern {
            if let Ok(re) = regex::Regex::new(pat) {
                if !re.is_match(cmd) {
                    return false;
                }
            } else {
                return false;
            }
        }
        true
    }
}

/// Return the string name of an IREffect for rule matching.
fn effect_name(e: &IREffect) -> &'static str {
    use IREffect::*;
    match e {
        Pure => "Pure",
        SysRead => "SysRead",
        FileRead => "FileRead",
        FileWrite => "FileWrite",
        FileDelete => "FileDelete",
        NetHttpGet => "NetHttpGet",
        NetHttpPost => "NetHttpPost",
        NetHttpDelete => "NetHttpDelete",
        ProcList => "ProcList",
        ProcKill => "ProcKill",
        ProcSpawn => "ProcSpawn",
        ShellExec => "ShellExec",
        WinRegistry => "WinRegistry",
        WinService => "WinService",
        CryptoHash => "CryptoHash",
        CryptoRandom => "CryptoRandom",
        DbRead => "DbRead",
        DbWrite => "DbWrite",
        GitRead => "GitRead",
        GitWrite => "GitWrite",
        Combined(_) => "Combined",
    }
}

/// Return the string name of a RiskLevel for rule matching.
fn risk_name(r: &RiskLevel) -> &'static str {
    match r {
        RiskLevel::Pure => "pure",
        RiskLevel::ReadOnly => "read_only",
        RiskLevel::Mutating => "mutating",
        RiskLevel::Destructive => "destructive",
    }
}

/// Check if actual risk matches the requested pattern.
/// Supports exact match and severity-based match (e.g., "mutating" matches
/// "mutating" and "destructive"; "read_only" matches all four).
fn risk_matches(actual: &str, want: &str) -> bool {
    let order = |s: &str| -> u8 {
        match s {
            "pure" => 0,
            "read_only" => 1,
            "mutating" => 2,
            "destructive" => 3,
            _ => 99,
        }
    };
    // Match if actual severity >= requested severity (conservative: a rule
    // targeting "mutating" also applies to "destructive")
    order(actual) >= order(want)
}

// ── RuleSet ─────────────────────────────────────────────────────────

/// A collection of rules evaluated in order. First match wins.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuleSet {
    /// Rules. TOML key is `[[rule]]` (singular array-of-tables).
    #[serde(default, rename = "rule")]
    pub rules: Vec<Rule>,
}

impl RuleSet {
    /// Load a RuleSet from a TOML string.
    pub fn from_toml_str(s: &str) -> Result<Self, String> {
        toml::from_str(s).map_err(|e| format!("rule parse error: {}", e))
    }

    /// Load a RuleSet from a TOML file.
    pub fn from_file(path: &std::path::Path) -> Result<Self, String> {
        let content = std::fs::read_to_string(path)
            .map_err(|e| format!("cannot read rules file '{}': {}", path.display(), e))?;
        Self::from_toml_str(&content)
    }

    /// Evaluate rules against the given context. Returns the first matching
    /// rule's action, or `None` if no rule matches.
    pub fn evaluate(
        &self,
        builtin: &str,
        capability: Option<&str>,
        effect: Option<&IREffect>,
        risk: Option<&RiskLevel>,
        cmd: &str,
    ) -> Option<RuleAction> {
        for rule in &self.rules {
            if rule.matches(builtin, capability, effect, risk, cmd) {
                return Some(rule.action_view());
            }
        }
        None
    }

    /// Evaluate rules against an ExecutionPlan (preflight mode).
    /// Returns the most restrictive action among all matched builtins.
    /// - If any builtin matches a `Deny` rule → Deny
    /// - Else if any matches `Confirm` → Confirm
    /// - Else if any matches `RateLimit` → RateLimit (lowest rate)
    /// - Else if any matches `Allow` → Allow
    /// - Else None (no rules apply)
    pub fn evaluate_plan(&self, plan: &ExecutionPlan, cmd: &str) -> Option<RuleAction> {
        let mut result: Option<RuleAction> = None;
        for builtin in &plan.builtins_called {
            // Derive effect from plan.effects (string form)
            let effect = plan
                .effects
                .iter()
                .find_map(|e| parse_effect(e))
                .or_else(|| {
                    // Fallback: derive from builtin name via IREffect::for_builtin
                    Some(IREffect::for_builtin(builtin))
                });
            // Derive capability from plan.capabilities_required
            let cap = plan
                .capabilities_required
                .iter()
                .find(|c| c.contains('.'))
                .map(|s| s.as_str());
            // Derive risk from plan.risk_level
            let risk = Some(&plan.risk_level);

            if let Some(action) = self.evaluate(builtin, cap, effect.as_ref(), risk, cmd) {
                match action.action {
                    ActionKind::Deny => {
                        // Deny is terminal — return immediately
                        return Some(action);
                    }
                    ActionKind::Confirm => {
                        if result.is_none() {
                            result = Some(action);
                        }
                    }
                    ActionKind::RateLimit => {
                        match &result {
                            None => result = Some(action),
                            Some(RuleAction { action: ActionKind::RateLimit, rate_per_minute: Some(existing), .. }) => {
                                // Take the lower rate (more restrictive)
                                if let Some(new) = action.rate_per_minute {
                                    if new < *existing {
                                        result = Some(action);
                                    }
                                }
                            }
                            _ => {} // Confirm takes precedence over RateLimit
                        }
                    }
                    ActionKind::Allow => {
                        if result.is_none() {
                            result = Some(action);
                        }
                    }
                }
            }
        }
        result
    }

    /// Returns true if the ruleset has no rules.
    pub fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }
}

/// Parse an IREffect from its string name.
fn parse_effect(s: &str) -> Option<IREffect> {
    use IREffect::*;
    Some(match s {
        "Pure" => Pure,
        "SysRead" => SysRead,
        "FileRead" => FileRead,
        "FileWrite" => FileWrite,
        "FileDelete" => FileDelete,
        "NetHttpGet" => NetHttpGet,
        "NetHttpPost" => NetHttpPost,
        "NetHttpDelete" => NetHttpDelete,
        "ProcList" => ProcList,
        "ProcKill" => ProcKill,
        "ProcSpawn" => ProcSpawn,
        "ShellExec" => ShellExec,
        "WinRegistry" => WinRegistry,
        "WinService" => WinService,
        "CryptoHash" => CryptoHash,
        "CryptoRandom" => CryptoRandom,
        "DbRead" => DbRead,
        "DbWrite" => DbWrite,
        "GitRead" => GitRead,
        "GitWrite" => GitWrite,
        _ => return None,
    })
}

// ── Evaluation Result ───────────────────────────────────────────────

/// Outcome of rule evaluation for a single builtin call.
#[derive(Debug, Clone, PartialEq)]
pub enum RuleDecision {
    /// No rule matched; defer to capability check.
    Pass,
    /// Rule explicitly allows the call.
    Allow,
    /// Rule denies the call. Agent sees this reason.
    Deny(String),
    /// Rule rate-limits the call. Returns (rate_per_minute, reason).
    /// Caller must enforce the sliding window.
    RateLimit { rate_per_minute: u32, reason: String },
    /// Rule requires confirmation. Agent must re-request with confirm flag.
    Confirm(String),
}

impl RuleAction {
    /// Convert to a RuleDecision.
    pub fn to_decision(&self) -> RuleDecision {
        match self.action {
            ActionKind::Allow => RuleDecision::Allow,
            ActionKind::Deny => RuleDecision::Deny(self.reason.clone().unwrap_or_default()),
            ActionKind::RateLimit => RuleDecision::RateLimit {
                rate_per_minute: self.rate_per_minute.unwrap_or(0),
                reason: self.reason.clone().unwrap_or_default(),
            },
            ActionKind::Confirm => RuleDecision::Confirm(self.reason.clone().unwrap_or_default()),
        }
    }
}

// ── Rate Limiter ────────────────────────────────────────────────────

/// Sliding-window rate limiter for rule enforcement.
/// Tracks call timestamps per builtin name.
#[derive(Debug, Default)]
pub struct RateLimiter {
    /// builtin_name → Vec of timestamps (ms since epoch) in the last minute.
    windows: HashMap<String, Vec<u64>>,
}

impl RateLimiter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Check if a call to `builtin` is allowed under the rate limit.
    /// If allowed, records the timestamp. If denied, returns false.
    pub fn check_and_record(&mut self, builtin: &str, rate_per_minute: u32, now_ms: u64) -> bool {
        let window = self.windows.entry(builtin.to_string()).or_default();
        // Evict timestamps older than 60 seconds
        let cutoff = now_ms.saturating_sub(60_000);
        window.retain(|&t| t >= cutoff);
        if window.len() >= rate_per_minute as usize {
            return false;
        }
        window.push(now_ms);
        true
    }

    /// Reset the rate limiter state (for testing).
    pub fn reset(&mut self) {
        self.windows.clear();
    }
}

// ── Global Rule State ───────────────────────────────────────────────

lazy_static::lazy_static! {
    static ref GLOBAL_RULES: RwLock<RuleSet> = RwLock::new(RuleSet::default());
    static ref GLOBAL_LIMITER: RwLock<RateLimiter> = RwLock::new(RateLimiter::new());
}

/// Initialize the global RuleSet from a TOML file path.
/// Called once at startup from `--rules <path>` CLI flag or `AETHER_RULES` env var.
/// If the path doesn't exist or parsing fails, logs a warning and uses empty ruleset.
pub fn init_rules(path: Option<&std::path::Path>) {
    let path = path
        .map(|p| p.to_path_buf())
        .or_else(|| std::env::var("AETHER_RULES").ok().map(std::path::PathBuf::from));

    if let Some(ref p) = path {
        match RuleSet::from_file(p) {
            Ok(rs) => {
                eprintln!("[rule] loaded {} rules from {}", rs.rules.len(), p.display());
                *GLOBAL_RULES.write().unwrap() = rs;
            }
            Err(e) => {
                eprintln!("[rule] warning: failed to load rules from {}: {}", p.display(), e);
            }
        }
    }
}

/// Initialize the global RuleSet from a TOML string (for testing and programmatic use).
pub fn init_rules_from_str(toml_str: &str) -> Result<(), String> {
    let rs = RuleSet::from_toml_str(toml_str)?;
    *GLOBAL_RULES.write().unwrap() = rs;
    Ok(())
}

/// Clear all rules and reset the rate limiter (for testing).
pub fn clear_rules() {
    *GLOBAL_RULES.write().unwrap() = RuleSet::default();
    GLOBAL_LIMITER.write().unwrap().reset();
}

/// Check a builtin call against the global RuleSet.
/// Returns a RuleDecision indicating whether to allow, deny, rate-limit, or confirm.
pub fn check_builtin(
    builtin: &str,
    capability: Option<&str>,
    effect: Option<&IREffect>,
    risk: Option<&RiskLevel>,
    cmd: &str,
) -> RuleDecision {
    let rules = GLOBAL_RULES.read().unwrap();
    if rules.is_empty() {
        return RuleDecision::Pass;
    }
    match rules.evaluate(builtin, capability, effect, risk, cmd) {
        None => RuleDecision::Pass,
        Some(action) => {
            // For rate-limited calls, check the sliding window before deciding
            if action.action == ActionKind::RateLimit {
                if let Some(rate) = action.rate_per_minute {
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_millis() as u64)
                        .unwrap_or(0);
                    let mut limiter = GLOBAL_LIMITER.write().unwrap();
                    if !limiter.check_and_record(builtin, rate, now_ms) {
                        return RuleDecision::Deny(format!(
                            "rate limit exceeded: {} calls/min for '{}'",
                            rate, builtin
                        ));
                    }
                }
            }
            action.to_decision()
        }
    }
}

/// Evaluate an ExecutionPlan against the global RuleSet (preflight mode).
/// Returns the most restrictive RuleDecision among all matched builtins.
pub fn evaluate_plan(plan: &ExecutionPlan, cmd: &str) -> RuleDecision {
    let rules = GLOBAL_RULES.read().unwrap();
    if rules.is_empty() {
        return RuleDecision::Pass;
    }
    match rules.evaluate_plan(plan, cmd) {
        None => RuleDecision::Pass,
        Some(action) => action.to_decision(),
    }
}

/// Return the number of rules currently loaded.
pub fn rule_count() -> usize {
    GLOBAL_RULES.read().unwrap().rules.len()
}

// ── Tests ───────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::runtime::ExecutionPlan;
    use std::sync::Mutex;

    // Tests in this module share global state (GLOBAL_RULES / GLOBAL_LIMITER).
    // Acquire this lock at the start of each test to serialize them, even
    // when the test runner uses parallel threads.
    static TEST_LOCK: Mutex<()> = Mutex::new(());

    fn lock() -> std::sync::MutexGuard<'static, ()> {
        // poison-safe: if a previous test panicked while holding the lock,
        // recover so subsequent tests can still run.
        TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn mk_plan(builtins: Vec<&str>, caps: Vec<&str>, effects: Vec<&str>, risk: RiskLevel) -> ExecutionPlan {
        ExecutionPlan {
            builtins_called: builtins.into_iter().map(String::from).collect(),
            capabilities_required: caps.into_iter().map(String::from).collect(),
            effects: effects.into_iter().map(String::from).collect(),
            risk_level: risk,
            side_effects: vec![],
            node_count: 1,
        }
    }

    #[test]
    fn deny_rule_blocks_execution() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "no-shell"
            match = { builtin = "sh" }
            action = "deny"
            reason = "shell execution forbidden"
            "#,
        ).unwrap();

        let decision = check_builtin("sh", None, Some(&IREffect::ShellExec), Some(&RiskLevel::Mutating), "");
        match decision {
            RuleDecision::Deny(reason) => assert!(reason.contains("shell execution forbidden")),
            other => panic!("expected Deny, got {:?}", other),
        }
    }

    #[test]
    fn allow_rule_lets_execution_through() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "allow-sys-read"
            match = { effect = "SysRead" }
            action = "allow"
            "#,
        ).unwrap();

        let decision = check_builtin("sys_cpu_info", Some("sys.read"), Some(&IREffect::SysRead), Some(&RiskLevel::ReadOnly), "");
        assert_eq!(decision, RuleDecision::Allow);
    }

    #[test]
    fn rate_limit_enforces_window() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "limit-http"
            match = { effect = "NetHttpPost" }
            action = "rate_limit"
            rate_per_minute = 2
            "#,
        ).unwrap();

        // First two calls should be allowed
        let d1 = check_builtin("web_post", None, Some(&IREffect::NetHttpPost), Some(&RiskLevel::Mutating), "");
        let d2 = check_builtin("web_post", None, Some(&IREffect::NetHttpPost), Some(&RiskLevel::Mutating), "");
        assert!(matches!(d1, RuleDecision::RateLimit { .. }));
        assert!(matches!(d2, RuleDecision::RateLimit { .. }));

        // Third call should be denied (rate exceeded)
        let d3 = check_builtin("web_post", None, Some(&IREffect::NetHttpPost), Some(&RiskLevel::Mutating), "");
        match d3 {
            RuleDecision::Deny(reason) => assert!(reason.contains("rate limit exceeded")),
            other => panic!("expected Deny on 3rd call, got {:?}", other),
        }
    }

    #[test]
    fn confirm_rule_returns_confirm_decision() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "confirm-delete"
            match = { effect = "FileDelete" }
            action = "confirm"
            reason = "file deletion is irreversible"
            "#,
        ).unwrap();

        let decision = check_builtin("file_delete_lines", None, Some(&IREffect::FileDelete), Some(&RiskLevel::Destructive), "");
        match decision {
            RuleDecision::Confirm(reason) => assert!(reason.contains("irreversible")),
            other => panic!("expected Confirm, got {:?}", other),
        }
    }

    #[test]
    fn dry_run_plan_evaluates_deny() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "no-write"
            match = { effect = "FileWrite" }
            action = "deny"
            reason = "writes blocked by policy"
            "#,
        ).unwrap();

        let plan = mk_plan(vec!["file_write"], vec!["file.write"], vec!["FileWrite"], RiskLevel::Mutating);
        let decision = evaluate_plan(&plan, "file.write(\"/tmp/x\", \"data\")");
        match decision {
            RuleDecision::Deny(reason) => assert!(reason.contains("writes blocked by policy")),
            other => panic!("expected Deny, got {:?}", other),
        }
    }

    #[test]
    fn pattern_match_blocks_rm_rf() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "deny-rm-rf"
            match = { builtin = "sh", pattern = ".*rm -rf.*" }
            action = "deny"
            reason = "recursive delete forbidden"
            "#,
        ).unwrap();

        let decision = check_builtin("sh", None, Some(&IREffect::ShellExec), Some(&RiskLevel::Mutating), "rm -rf /");
        assert!(matches!(decision, RuleDecision::Deny(_)));

        // Non-matching command should pass
        let decision2 = check_builtin("sh", None, Some(&IREffect::ShellExec), Some(&RiskLevel::Mutating), "ls -la");
        assert_eq!(decision2, RuleDecision::Pass);
    }

    #[test]
    fn risk_level_matches_severity() {
        let _g = lock();
        clear_rules();
        init_rules_from_str(
            r#"
            [[rule]]
            name = "confirm-destructive"
            match = { risk = "destructive" }
            action = "confirm"
            reason = "destructive op needs confirmation"
            "#,
        ).unwrap();

        // Destructive should match
        let d1 = check_builtin("file_delete_lines", None, Some(&IREffect::FileDelete), Some(&RiskLevel::Destructive), "");
        assert!(matches!(d1, RuleDecision::Confirm(_)));

        // Mutating should NOT match (destructive > mutating, but rule targets destructive only)
        let d2 = check_builtin("file_write", None, Some(&IREffect::FileWrite), Some(&RiskLevel::Mutating), "");
        assert_eq!(d2, RuleDecision::Pass);
    }

    #[test]
    fn empty_ruleset_passes_everything() {
        let _g = lock();
        clear_rules();
        let decision = check_builtin("file_write", Some("file.write"), Some(&IREffect::FileWrite), Some(&RiskLevel::Mutating), "");
        assert_eq!(decision, RuleDecision::Pass);
    }

    #[test]
    fn toml_loads_multiple_rules() {
        let _g = lock();
        clear_rules();
        let toml = r#"
            [[rule]]
            name = "rule-1"
            match = { effect = "FileDelete" }
            action = "deny"
            reason = "no deletes"

            [[rule]]
            name = "rule-2"
            match = { effect = "SysRead" }
            action = "allow"

            [[rule]]
            name = "rule-3"
            match = { effect = "NetHttpPost" }
            action = "rate_limit"
            rate_per_minute = 5
            "#;
        let rs = RuleSet::from_toml_str(toml).unwrap();
        assert_eq!(rs.rules.len(), 3);
    }
}
