//! Versioned Agent operations and the unified observation envelope.

use crate::artifact::{display_path, ArtifactMetadata, ArtifactStore};
use crate::process_runner::{self, CapturedStream, ExecLimits};
use crate::safety::{self, Effect, GuardCtx, Mode};
use anyhow::{anyhow, Result};
use lazy_static::lazy_static;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub const OBSERVATION_SCHEMA: &str = "verseshell.observation/v1";
pub const DEFAULT_MAX_TOKENS: usize = 4_000;
/// Hard cap for model-visible success summaries (noisy install/build profiles).
pub const SUCCESS_SUMMARY_TOKENS: usize = 120;
/// Max lines retained in a success summary.
pub const SUCCESS_SUMMARY_MAX_LINES: usize = 4;
/// Soft cap for failure windows shown to the model (full log remains in artifact).
pub const FAILURE_WINDOW_TOKENS: usize = 800;
pub const RAW_QUERY_HARD_CAP: usize = 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
pub struct OperationRequest {
    pub id: String,
    #[serde(default = "default_agent")]
    pub agent: String,
    pub op: String,
    #[serde(default = "empty_object")]
    pub args: Value,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default)]
    pub budget: ObservationBudget,
}

fn default_agent() -> String {
    "default".into()
}
fn empty_object() -> Value {
    json!({})
}
fn default_timeout_ms() -> u64 {
    process_runner::DEFAULT_TIMEOUT_MS
}

#[derive(Debug, Clone, Deserialize)]
pub struct ObservationBudget {
    #[serde(default = "default_max_tokens")]
    pub max_tokens: usize,
}

impl Default for ObservationBudget {
    fn default() -> Self {
        Self {
            max_tokens: DEFAULT_MAX_TOKENS,
        }
    }
}

fn default_max_tokens() -> usize {
    DEFAULT_MAX_TOKENS
}

#[derive(Debug, Clone, Serialize)]
pub struct OperationError {
    pub code: String,
    pub message: String,
    pub recoverable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub tool: String,
    pub severity: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SuggestedAction {
    pub op: String,
    pub args: Value,
}

#[derive(Debug, Clone, Serialize)]
pub struct ObservationMeta {
    pub elapsed_ms: u64,
    pub profile: String,
    pub token_estimate: usize,
    pub effects: Vec<String>,
    pub capabilities_used: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Observation {
    pub schema: &'static str,
    pub id: String,
    pub op: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<OperationError>,
    pub diagnostics: Vec<Diagnostic>,
    pub meta: ObservationMeta,
    pub suggested_next: Vec<SuggestedAction>,
}

impl Observation {
    pub fn failure(
        id: &str,
        op: &str,
        profile: &str,
        code: &str,
        message: impl Into<String>,
        recoverable: bool,
    ) -> Self {
        Self {
            schema: OBSERVATION_SCHEMA,
            id: id.into(),
            op: op.into(),
            ok: false,
            data: None,
            error: Some(OperationError {
                code: code.into(),
                message: message.into(),
                recoverable,
                hint: None,
            }),
            diagnostics: Vec::new(),
            meta: ObservationMeta {
                elapsed_ms: 0,
                profile: profile.into(),
                token_estimate: 0,
                effects: Vec::new(),
                capabilities_used: Vec::new(),
            },
            suggested_next: Vec::new(),
        }
    }

    pub fn success(
        id: &str,
        op: &str,
        profile: &str,
        data: Value,
        effects: Vec<String>,
        capabilities_used: Vec<String>,
        elapsed_ms: u64,
        diagnostics: Vec<Diagnostic>,
        suggested_next: Vec<SuggestedAction>,
    ) -> Self {
        let serialized = serde_json::to_string(&data).unwrap_or_default();
        Self {
            schema: OBSERVATION_SCHEMA,
            id: id.into(),
            op: op.into(),
            ok: true,
            data: Some(data),
            error: None,
            diagnostics,
            meta: ObservationMeta {
                elapsed_ms,
                profile: profile.into(),
                token_estimate: crate::builtins::est_token_count(&serialized),
                effects,
                capabilities_used,
            },
            suggested_next,
        }
    }

    pub fn fail_with(
        id: &str,
        op: &str,
        profile: &str,
        code: &str,
        message: impl Into<String>,
        recoverable: bool,
        data: Option<Value>,
        diagnostics: Vec<Diagnostic>,
        suggested_next: Vec<SuggestedAction>,
        hint: Option<String>,
        elapsed_ms: u64,
    ) -> Self {
        let mut obs = Self::failure(id, op, profile, code, message, recoverable);
        obs.data = data;
        obs.diagnostics = diagnostics;
        obs.suggested_next = suggested_next;
        obs.meta.elapsed_ms = elapsed_ms;
        if let Some(h) = hint {
            if let Some(err) = obs.error.as_mut() {
                err.hint = Some(h);
            }
        }
        obs
    }
}

/// Map a [`safety::SafetyError`] into an Observation, preserving `hint` and
/// optional approval token so agents can complete the approve/retry loop.
pub fn safety_error_to_observation(
    req: &OperationRequest,
    profile: &str,
    err: safety::SafetyError,
) -> Observation {
    let hint = if err.hint.is_empty() {
        None
    } else {
        Some(err.hint.clone())
    };
    let data = err.approval.as_ref().map(|a| {
        json!({
            "approval_token": a.token,
            "what": a.what,
            "builtin": a.builtin,
            "reversible": a.reversible,
        })
    });
    let recoverable = !matches!(
        err.code,
        safety::ErrorCode::PolicyDeny | safety::ErrorCode::BudgetExceeded
    );
    Observation::fail_with(
        &req.id,
        &req.op,
        profile,
        err.code.as_str(),
        err.message,
        recoverable,
        data,
        Vec::new(),
        Vec::new(),
        hint,
        0,
    )
}

#[derive(Clone)]
pub struct OperationSpec {
    pub name: &'static str,
    pub mcp_name: &'static str,
    pub description: &'static str,
    pub effect: &'static str,
    pub capability: &'static str,
    pub input_schema: fn() -> Value,
    pub handler: fn(&OperationRequest) -> Observation,
}

#[derive(Default, Clone)]
pub struct OperationRegistry {
    specs: BTreeMap<&'static str, OperationSpec>,
}

impl OperationRegistry {
    pub fn new() -> Self {
        let mut specs = BTreeMap::new();
        for spec in [exec_spec(), result_spec()] {
            specs.insert(spec.name, spec);
        }
        for spec in crate::ops::all_specs() {
            specs.insert(spec.name, spec);
        }
        Self { specs }
    }

    pub fn list(&self) -> Vec<&OperationSpec> {
        self.specs.values().collect()
    }

    pub fn spec(&self, name: &str) -> Option<&OperationSpec> {
        self.specs.get(name)
    }

    pub fn execute(&self, req: OperationRequest) -> Observation {
        let spec = match self.spec(&req.op) {
            Some(spec) => spec,
            None => {
                let suggestions: Vec<&str> = self
                    .specs
                    .keys()
                    .filter(|name| {
                        name.contains(&req.op) || req.op.contains(*name) || {
                            let a = req.op.replace('.', "_");
                            name.replace('.', "_") == a
                        }
                    })
                    .copied()
                    .take(5)
                    .collect();
                let msg = if suggestions.is_empty() {
                    format!("unknown operation: {}", req.op)
                } else {
                    format!(
                        "unknown operation: {}; did you mean {}?",
                        req.op,
                        suggestions.join(", ")
                    )
                };
                return Observation::failure(
                    &req.id,
                    &req.op,
                    "none",
                    "E_OPERATION_UNKNOWN",
                    msg,
                    true,
                )
            }
        };
        (spec.handler)(&req)
    }
}

pub fn exec_input_schema() -> Value {
    json!({
        "type": "object",
        "required": ["argv"],
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "cwd": {"type": "string", "default": "."},
            "profile": {"type": "string", "default": "auto"},
            "artifact": {"type": "string", "enum": ["auto", "always", "never"], "default": "auto"},
            "max_output_bytes": {"type": "integer", "default": 67108864},
            "max_memory_mb": {"type": "integer"},
            "max_processes": {"type": "integer"},
            "timeout_ms": {"type": "integer", "default": 30000},
            "max_tokens": {"type": "integer", "default": 4000}
        }
    })
}

pub fn result_input_schema() -> Value {
    json!({
        "type": "object",
        "required": ["handle", "mode"],
        "properties": {
            "handle": {"type": "string"},
            "mode": {"type": "string", "enum": ["meta", "head", "tail", "slice", "grep", "raw"]},
            "lines": {"type": "integer", "default": 40},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "pattern": {"type": "string"},
            "max_matches": {"type": "integer", "default": 50},
            "max_bytes": {"type": "integer", "default": 65536},
            "max_tokens": {"type": "integer", "default": 4000}
        }
    })
}

fn exec_spec() -> OperationSpec {
    OperationSpec {
        name: "exec.run",
        mcp_name: "exec_run",
        description: "Run a non-interactive argv command and return a bounded, structured observation with artifact handles.",
        effect: "process.spawn",
        capability: "shell.exec",
        input_schema: exec_input_schema,
        handler: execute_run,
    }
}

fn result_spec() -> OperationSpec {
    OperationSpec {
        name: "result.query",
        mcp_name: "result_query",
        description: "Inspect a result artifact by metadata, line window, grep, or explicitly bounded raw bytes.",
        effect: "artifact.read",
        capability: "shell.exec",
        input_schema: result_input_schema,
        handler: execute_result_query,
    }
}

#[derive(Debug, Deserialize)]
struct ExecArgs {
    argv: Vec<String>,
    #[serde(default = "default_cwd")]
    cwd: String,
    #[serde(default = "default_profile")]
    profile: String,
    #[serde(default = "default_artifact")]
    artifact: String,
    #[serde(default = "process_runner::default_max_output_bytes")]
    max_output_bytes: usize,
    #[serde(default)]
    max_memory_mb: Option<usize>,
    #[serde(default)]
    max_processes: Option<u32>,
    #[serde(default)]
    timeout_ms: Option<u64>,
    #[serde(default)]
    max_tokens: Option<usize>,
}

fn default_cwd() -> String {
    ".".into()
}
fn default_profile() -> String {
    "auto".into()
}
fn default_artifact() -> String {
    "auto".into()
}

#[derive(Debug, Deserialize)]
struct ResultArgs {
    handle: String,
    mode: String,
    #[serde(default = "default_lines")]
    lines: usize,
    #[serde(default)]
    start_line: Option<usize>,
    #[serde(default)]
    end_line: Option<usize>,
    #[serde(default)]
    pattern: Option<String>,
    #[serde(default = "default_max_matches")]
    max_matches: usize,
    #[serde(default = "default_query_bytes")]
    max_bytes: usize,
    #[serde(default)]
    max_tokens: Option<usize>,
}

fn default_lines() -> usize {
    40
}
fn default_max_matches() -> usize {
    50
}
fn default_query_bytes() -> usize {
    64 * 1024
}

#[derive(Debug, Clone, Serialize)]
struct StreamObservation {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    text: Option<String>,
    raw_bytes: u64,
    returned_bytes: u64,
    omitted_bytes: u64,
    raw_complete: bool,
    encoding: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    artifact: Option<String>,
}

fn execute_run(req: &OperationRequest) -> Observation {
    let args: ExecArgs = match serde_json::from_value(req.args.clone()) {
        Ok(args) => args,
        Err(e) => {
            return Observation::failure(
                &req.id,
                &req.op,
                "none",
                "E_EXEC_BAD_ARG",
                e.to_string(),
                true,
            )
        }
    };
    if args.argv.is_empty() {
        return Observation::failure(
            &req.id,
            &req.op,
            "none",
            "E_EXEC_BAD_ARG",
            "argv must contain a program",
            true,
        );
    }
    if !matches!(args.artifact.as_str(), "auto" | "always" | "never") {
        return Observation::failure(
            &req.id,
            &req.op,
            "none",
            "E_EXEC_BAD_ARG",
            "artifact must be auto, always, or never",
            true,
        );
    }

    if let crate::capability::CapabilityResult::Deny(reason) =
        crate::capability::check_capability("sh")
    {
        return Observation::failure(&req.id, &req.op, "none", "E_CAPABILITY_DENY", reason, true);
    }

    let cwd = match resolve_cwd(&args.cwd) {
        Ok(cwd) => cwd,
        Err(e) => {
            return Observation::failure(
                &req.id,
                &req.op,
                "none",
                "E_OUTSIDE_WORKSPACE",
                e.to_string(),
                true,
            )
        }
    };
    let command_text = args.argv.join(" ");
    if let Err(e) = safety::guard(GuardCtx {
        builtin: "exec.run",
        effect: Effect::Exec,
        what: "exec",
        targets: vec![command_text],
        blast_radius: json!({"argv": args.argv, "cwd": display_path(&cwd)}),
        reversible: false,
        fs_paths: false,
    }) {
        return safety_error_to_observation(req, "none", e);
    }

    let profile = detect_profile(&args.argv, &args.profile);
    let limits = ExecLimits {
        timeout_ms: args.timeout_ms.unwrap_or(req.timeout_ms),
        max_output_bytes: args.max_output_bytes,
        max_memory_mb: args.max_memory_mb,
        max_processes: args.max_processes,
    };
    let output = match process_runner::run(&args.argv, &cwd, &limits) {
        Ok(output) => output,
        Err(e) => {
            let code = classify_exec_error(&e);
            return Observation::failure(&req.id, &req.op, &profile, code, e.to_string(), true);
        }
    };

    let success = output.exit_code == 0 && !output.timed_out;
    let max_tokens = args.max_tokens.unwrap_or(req.budget.max_tokens).max(64);
    let store = ArtifactStore::new(safety::workspace_root()).ok();
    let stdout = observe_stream(
        &output.stdout,
        "stdout",
        &profile,
        success,
        max_tokens / 2,
        &args.artifact,
        store.as_ref(),
        &req.agent,
    );
    let stderr = observe_stream(
        &output.stderr,
        "stderr",
        &profile,
        success,
        max_tokens / 2,
        &args.artifact,
        store.as_ref(),
        &req.agent,
    );

    let combined = format!(
        "{}\n{}",
        output.stdout.text.as_deref().unwrap_or(""),
        output.stderr.text.as_deref().unwrap_or("")
    );
    let diagnostics = if success {
        extract_warnings(&combined, &profile)
    } else {
        extract_diagnostics(&combined, &profile)
    };
    let _ = safety::audit(
        "exec.run",
        Effect::Exec,
        if success { "completed" } else { "failed" },
        &args.argv.first().cloned().unwrap_or_default(),
        json!({
            "exit_code": output.exit_code,
            "timed_out": output.timed_out,
            "elapsed_ms": output.elapsed_ms,
            "stdout": {"handle": stdout.artifact.clone(), "raw_bytes": stdout.raw_bytes, "status": stdout.status},
            "stderr": {"handle": stderr.artifact.clone(), "raw_bytes": stderr.raw_bytes, "status": stderr.status}
        }),
    );
    let data = json!({
        "argv": args.argv,
        "cwd": display_path(&cwd),
        "exit_code": output.exit_code,
        "timed_out": output.timed_out,
        "stdout": stdout,
        "stderr": stderr
    });
    let serialized = serde_json::to_string(&data).unwrap_or_default();
    let token_estimate = crate::builtins::est_token_count(&serialized);
    let error = if output.timed_out {
        Some(OperationError {
            code: "E_TIMEOUT".into(),
            message: format!("command timed out after {}ms", limits.timeout_ms),
            recoverable: true,
            hint: Some("increase timeout_ms or run a narrower command".into()),
        })
    } else if output.exit_code != 0 {
        Some(OperationError {
            code: "E_PROCESS_EXIT".into(),
            message: format!("process exited with code {}", output.exit_code),
            recoverable: true,
            hint: diagnostics.first().map(|d| d.message.clone()),
        })
    } else {
        None
    };
    let mut suggested_next = Vec::new();
    if !success {
        let pattern = failure_grep_pattern(&profile);
        for stream in [&stdout, &stderr] {
            if let Some(handle) = &stream.artifact {
                suggested_next.push(SuggestedAction {
                    op: "result.query".into(),
                    args: json!({
                        "handle": handle,
                        "mode": "grep",
                        "pattern": pattern,
                        "max_matches": 50
                    }),
                });
            }
        }
    }

    Observation {
        schema: OBSERVATION_SCHEMA,
        id: req.id.clone(),
        op: req.op.clone(),
        ok: success,
        data: Some(data),
        error,
        diagnostics,
        meta: ObservationMeta {
            elapsed_ms: output.elapsed_ms,
            profile,
            token_estimate,
            effects: vec!["process.spawn".into()],
            capabilities_used: vec!["shell.exec".into()],
        },
        suggested_next,
    }
}

fn execute_result_query(req: &OperationRequest) -> Observation {
    if let crate::capability::CapabilityResult::Deny(reason) =
        crate::capability::check_capability("sh")
    {
        return Observation::failure(
            &req.id,
            &req.op,
            "result",
            "E_CAPABILITY_DENY",
            reason,
            true,
        );
    }
    let args: ResultArgs = match serde_json::from_value(req.args.clone()) {
        Ok(args) => args,
        Err(e) => {
            return Observation::failure(
                &req.id,
                &req.op,
                "result",
                "E_RESULT_BAD_ARG",
                e.to_string(),
                true,
            )
        }
    };
    let store = match ArtifactStore::new(safety::workspace_root()) {
        Ok(store) => store,
        Err(e) => {
            return Observation::failure(
                &req.id,
                &req.op,
                "result",
                "E_RESULT_STORE",
                e.to_string(),
                true,
            )
        }
    };
    let (metadata, bytes) = match store.load(&args.handle) {
        Ok(value) => value,
        Err(e) => {
            let text = e.to_string();
            let code = text
                .split(':')
                .next()
                .filter(|s| s.starts_with("E_"))
                .unwrap_or("E_RESULT_READ")
                .to_string();
            return Observation::failure(&req.id, &req.op, "result", &code, text, true);
        }
    };

    let max_tokens = args.max_tokens.unwrap_or(req.budget.max_tokens).max(64);
    let data = match query_artifact(&metadata, &bytes, &args, max_tokens) {
        Ok(data) => data,
        Err(e) => {
            return Observation::failure(
                &req.id,
                &req.op,
                "result",
                "E_RESULT_QUERY",
                e.to_string(),
                true,
            )
        }
    };
    let _ = safety::audit(
        "result.query",
        Effect::ReadLocal,
        "allow",
        &args.handle,
        json!({"mode": args.mode, "max_bytes": args.max_bytes, "max_tokens": max_tokens}),
    );
    let serialized = serde_json::to_string(&data).unwrap_or_default();
    Observation {
        schema: OBSERVATION_SCHEMA,
        id: req.id.clone(),
        op: req.op.clone(),
        ok: true,
        data: Some(data),
        error: None,
        diagnostics: Vec::new(),
        meta: ObservationMeta {
            elapsed_ms: 0,
            profile: "result".into(),
            token_estimate: crate::builtins::est_token_count(&serialized),
            effects: vec!["artifact.read".into()],
            capabilities_used: vec!["shell.exec".into()],
        },
        suggested_next: Vec::new(),
    }
}

fn resolve_cwd(input: &str) -> Result<PathBuf> {
    let resolved = PathBuf::from(safety::resolve_path_str(input));
    let cwd = resolved
        .canonicalize()
        .map_err(|e| anyhow!("cwd '{}' is unavailable: {}", resolved.display(), e))?;
    if (safety::current_mode() == Mode::Agent || std::env::var("AETHER_WORKSPACE").is_ok())
        && !safety::within_workspace(&cwd.to_string_lossy())
    {
        return Err(anyhow!("cwd is outside the configured workspace"));
    }
    Ok(cwd)
}

fn observe_stream(
    stream: &CapturedStream,
    stream_name: &str,
    profile: &str,
    success: bool,
    max_tokens: usize,
    artifact_mode: &str,
    store: Option<&ArtifactStore>,
    agent: &str,
) -> StreamObservation {
    if stream.raw_bytes == 0 {
        let summary = if success {
            Some("completed successfully with no output".into())
        } else {
            Some("command produced no output".into())
        };
        return StreamObservation {
            status: "empty",
            summary,
            text: None,
            raw_bytes: 0,
            returned_bytes: 0,
            omitted_bytes: 0,
            raw_complete: true,
            encoding: stream.encoding.clone(),
            artifact: None,
        };
    }

    // Decode path: strip ANSI + collapse blank runs before any reducer.
    let cleaned = stream
        .text
        .as_deref()
        .map(|t| collapse_blank_lines(&strip_ansi(t)))
        .unwrap_or_default();

    let (status, summary, text) = if stream.binary {
        (
            "binary",
            Some("binary output stored as an artifact".into()),
            None,
        )
    } else if success && is_summary_profile(profile) {
        // Success silence: model sees only a short summary, never the full log.
        let summary = clamp_summary(reduce_success(&cleaned, profile), SUCCESS_SUMMARY_TOKENS);
        ("reduced", Some(summary), None)
    } else if !success {
        // Failure focus: extract error window; full log goes to artifact.
        let budget = max_tokens.min(FAILURE_WINDOW_TOKENS).max(64);
        let window = reduce_failure(&cleaned, profile, budget);
        let (window, over_budget) = head_tail_budget(&window, budget);
        let status = if over_budget || cleaned.len() > window.len() {
            "truncated"
        } else {
            "reduced"
        };
        (status, None, Some(window))
    } else if is_content_truncated_profile(profile) {
        // git status/diff/log: prefer short summary; never dump large bodies.
        if let Some(summary) = reduce_success_optional(&cleaned, profile) {
            let summary = clamp_summary(summary, SUCCESS_SUMMARY_TOKENS);
            ("reduced", Some(summary), None)
        } else {
            let (text, truncated) = head_tail_budget(&cleaned, max_tokens.max(64));
            let status = if truncated || !stream.raw_complete {
                "truncated"
            } else {
                "full"
            };
            (status, None, Some(text))
        }
    } else {
        let (text, truncated) = head_tail_budget(&cleaned, max_tokens.max(64));
        let status = if truncated || !stream.raw_complete {
            "truncated"
        } else {
            "full"
        };
        (status, None, Some(text))
    };

    let returned_bytes = text
        .as_ref()
        .map(|s| s.len() as u64)
        .or_else(|| summary.as_ref().map(|s| s.len() as u64))
        .unwrap_or(0);
    let omitted_bytes = stream.raw_bytes.saturating_sub(returned_bytes);
    let needs_artifact = artifact_mode == "always"
        || (artifact_mode == "auto"
            && (matches!(status, "reduced" | "truncated" | "binary")
                || (!success && stream.raw_bytes > 0)
                || omitted_bytes > 0));
    let artifact = if needs_artifact {
        store.and_then(|store| {
            store
                .store(
                    &stream.bytes,
                    &stream.encoding,
                    stream_name,
                    "exec.run",
                    agent,
                )
                .ok()
                .map(|artifact| artifact.metadata.handle)
        })
    } else {
        None
    };

    StreamObservation {
        status,
        summary,
        text,
        raw_bytes: stream.raw_bytes,
        returned_bytes,
        omitted_bytes,
        raw_complete: stream.raw_complete,
        encoding: stream.encoding.clone(),
        artifact,
    }
}

fn query_artifact(
    metadata: &ArtifactMetadata,
    bytes: &[u8],
    args: &ResultArgs,
    max_tokens: usize,
) -> Result<Value> {
    if args.mode == "meta" {
        return Ok(serde_json::to_value(metadata)?);
    }
    let max_bytes = args.max_bytes.max(1).min(RAW_QUERY_HARD_CAP);
    if args.mode == "raw" {
        let end = bytes.len().min(max_bytes);
        let (text, encoding) = decode_query_text(&bytes[..end], &metadata.encoding);
        let text = strip_ansi(&text);
        let (text, budget_truncated) = head_tail_budget(&text, max_tokens);
        return Ok(json!({
            "handle": metadata.handle,
            "mode": "raw",
            "encoding": encoding,
            "text": text,
            "returned_bytes": end,
            "raw_bytes": metadata.bytes,
            "truncated": end < bytes.len() || budget_truncated
        }));
    }

    let (mut text, encoding) = decode_query_text(bytes, &metadata.encoding);
    text = strip_ansi(&text);
    if safety::current_mode() == Mode::Agent && safety::redaction_enabled() {
        text = safety::redact_str(&text).0;
    }
    let lines: Vec<&str> = text.lines().collect();
    let payload = match args.mode.as_str() {
        "head" => {
            let n = args.lines.max(1);
            let slice = lines.iter().take(n).cloned().collect::<Vec<_>>().join("\n");
            let (slice, truncated) = head_tail_budget(&slice, max_tokens);
            json!({
                "handle": metadata.handle,
                "mode": "head",
                "encoding": encoding,
                "lines": n.min(lines.len()),
                "text": slice,
                "truncated": truncated || lines.len() > n
            })
        }
        "tail" => {
            let n = args.lines.max(1);
            let start = lines.len().saturating_sub(n);
            let slice = lines[start..].join("\n");
            let (slice, truncated) = head_tail_budget(&slice, max_tokens);
            json!({
                "handle": metadata.handle,
                "mode": "tail",
                "encoding": encoding,
                "lines": lines.len() - start,
                "text": slice,
                "truncated": truncated || start > 0
            })
        }
        "slice" => {
            let start = args.start_line.unwrap_or(1).max(1);
            let end = args
                .end_line
                .unwrap_or(start.saturating_add(args.lines.saturating_sub(1)))
                .max(start);
            let from = start.saturating_sub(1);
            let to = end.min(lines.len());
            let slice = if from < lines.len() {
                lines[from..to].join("\n")
            } else {
                String::new()
            };
            let (slice, truncated) = head_tail_budget(&slice, max_tokens);
            json!({
                "handle": metadata.handle,
                "mode": "slice",
                "encoding": encoding,
                "start_line": start,
                "end_line": end,
                "text": slice,
                "truncated": truncated
            })
        }
        "grep" => {
            let pattern = args
                .pattern
                .as_deref()
                .ok_or_else(|| anyhow!("E_RESULT_BAD_ARG: pattern is required for grep"))?;
            let re = Regex::new(pattern)
                .map_err(|e| anyhow!("E_RESULT_BAD_ARG: invalid pattern: {e}"))?;
            let mut matches = Vec::new();
            for (idx, line) in lines.iter().enumerate() {
                if re.is_match(line) {
                    matches.push(json!({"line": idx + 1, "text": *line}));
                    if matches.len() >= args.max_matches.max(1) {
                        break;
                    }
                }
            }
            json!({
                "handle": metadata.handle,
                "mode": "grep",
                "encoding": encoding,
                "pattern": pattern,
                "matches": matches,
                "truncated": matches.len() >= args.max_matches.max(1)
            })
        }
        other => {
            return Err(anyhow!(
                "E_RESULT_BAD_ARG: mode must be meta|head|tail|slice|grep|raw, got {other}"
            ))
        }
    };
    Ok(payload)
}

fn decode_query_text(bytes: &[u8], declared: &str) -> (String, String) {
    if declared.starts_with("windows-oem-") || declared == "utf-8" {
        if let Ok(text) = std::str::from_utf8(bytes) {
            return (text.to_string(), "utf-8".into());
        }
    }
    if let Ok(text) = std::str::from_utf8(bytes) {
        (text.to_string(), "utf-8".into())
    } else {
        (String::from_utf8_lossy(bytes).into_owned(), declared.into())
    }
}

fn head_tail_budget(text: &str, max_tokens: usize) -> (String, bool) {
    if crate::builtins::est_token_count(text) <= max_tokens {
        return (text.to_string(), false);
    }
    let chars: Vec<char> = text.chars().collect();
    let max_chars = max_tokens.saturating_mul(4).max(64);
    let head = max_chars * 2 / 5;
    let tail = max_chars.saturating_sub(head);
    let omitted = chars.len().saturating_sub(head + tail);
    let mut value: String = chars.iter().take(head).collect();
    value.push_str(&format!("\n…({omitted} chars omitted)…\n"));
    value.extend(chars.iter().skip(chars.len().saturating_sub(tail)));
    (value, true)
}

fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut it = s.chars().peekable();
    while let Some(ch) = it.next() {
        if ch == '\u{1b}' {
            if it.peek() == Some(&'[') {
                it.next();
                for c in it.by_ref() {
                    if c.is_ascii_alphabetic() {
                        break;
                    }
                }
                continue;
            }
            // OSC / other ESC sequences: drop until BEL or ST
            if it.peek() == Some(&']') {
                it.next();
                while let Some(c) = it.next() {
                    if c == '\u{7}' {
                        break;
                    }
                    if c == '\u{1b}' && it.peek() == Some(&'\\') {
                        it.next();
                        break;
                    }
                }
                continue;
            }
            continue;
        }
        // Also strip common CSI-less color codes sometimes left as raw
        out.push(ch);
    }
    out
}

fn collapse_blank_lines(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut blank_run = 0usize;
    for line in s.lines() {
        if line.trim().is_empty() {
            blank_run += 1;
            if blank_run <= 1 {
                out.push('\n');
            }
        } else {
            blank_run = 0;
            out.push_str(line);
            out.push('\n');
        }
    }
    // Preserve whether original ended with newline roughly by trimming one trailing
    // newline if input had content; keep deterministic form.
    if out.ends_with('\n') && !s.ends_with('\n') {
        out.pop();
    }
    out
}

fn clamp_summary(summary: String, max_tokens: usize) -> String {
    let lines: Vec<&str> = summary
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .take(SUCCESS_SUMMARY_MAX_LINES)
        .collect();
    let joined = lines.join("; ");
    if crate::builtins::est_token_count(&joined) <= max_tokens {
        return joined;
    }
    let (truncated, _) = head_tail_budget(&joined, max_tokens);
    truncated
}

fn detect_profile(argv: &[String], requested: &str) -> String {
    if requested != "auto" {
        return requested.to_ascii_lowercase();
    }
    let program = Path::new(&argv[0])
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(&argv[0])
        .to_ascii_lowercase();
    let subcommand = argv
        .get(1)
        .map(|s| s.to_ascii_lowercase())
        .unwrap_or_default();
    match program.as_str() {
        "npm" | "npm.cmd" | "pnpm" | "yarn" | "bun"
            if matches!(subcommand.as_str(), "install" | "i" | "add" | "ci" | "update") =>
        {
            "npm_install".into()
        }
        "cargo" if matches!(subcommand.as_str(), "build" | "check" | "test" | "clippy") => {
            "cargo".into()
        }
        "pip" | "pip3" | "uv" | "poetry"
            if matches!(subcommand.as_str(), "install" | "add" | "sync") =>
        {
            "python_install".into()
        }
        "pytest" => "pytest".into(),
        "dotnet" | "msbuild" => "msbuild".into(),
        "git" | "git.exe" => "git".into(),
        _ => "generic".into(),
    }
}

fn is_summary_profile(profile: &str) -> bool {
    matches!(
        profile,
        "npm_install" | "cargo" | "python_install" | "pytest" | "msbuild"
    )
}

fn is_content_truncated_profile(profile: &str) -> bool {
    matches!(profile, "git")
}

fn failure_grep_pattern(profile: &str) -> &'static str {
    match profile {
        "npm_install" => r"npm error|ERR!|error|failed",
        "cargo" => r"error\[|error:|failed|panic",
        "python_install" => r"ERROR|Error|failed|No matching",
        "pytest" => r"FAILED|ERROR|Error|assert",
        "msbuild" => r"error |Build FAILED|FAILED",
        "git" => r"fatal:|error:|conflict|failed",
        _ => r"error|failed|panic|fatal",
    }
}

fn reduce_success(text: &str, profile: &str) -> String {
    reduce_success_optional(text, profile).unwrap_or_else(|| {
        format!("{} completed successfully", profile.replace('_', " "))
    })
}

fn reduce_success_optional(text: &str, profile: &str) -> Option<String> {
    let needles: &[&str] = match profile {
        "npm_install" => &[
            "added ",
            "removed ",
            "changed ",
            "packages in",
            "audited ",
            "found 0 vulnerabilit",
            "found 1 vulnerabilit",
            "vulnerabilities",
        ],
        "cargo" => &["Finished", "test result:"],
        "python_install" => &["Successfully installed", "Installed", "Resolved"],
        "pytest" => &[" passed", " failed", " skipped", "warnings summary", "====="],
        "msbuild" => &[
            "Build succeeded",
            "Build FAILED",
            " Warning(s)",
            " Error(s)",
        ],
        "git" => &[
            "file changed",
            "files changed",
            "insertions",
            "deletions",
            "On branch",
            "Your branch",
            "nothing to commit",
            "Changes not staged",
            "Changes to be committed",
            "Untracked files",
        ],
        _ => &[],
    };
    if needles.is_empty() {
        return None;
    }

    // Prefer last matching lines (final summary), skip progress noise.
    let mut lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .filter(|line| {
            let lower = line.to_ascii_lowercase();
            // Drop known progress noise even if it accidentally matches a needle.
            if lower.contains("reify")
                || lower.contains("\r")
                || lower.starts_with("compiling ")
                || lower.starts_with("downloading ")
                || lower.starts_with("fetching ")
            {
                return false;
            }
            needles.iter().any(|needle| {
                line.contains(needle) || lower.contains(&needle.to_ascii_lowercase())
            })
        })
        .collect();
    lines.dedup();
    if lines.is_empty() {
        return None;
    }
    let kept: Vec<&str> = lines
        .into_iter()
        .rev()
        .take(SUCCESS_SUMMARY_MAX_LINES)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    Some(kept.join("; "))
}

/// Extract a failure-focused window from noisy tool output.
/// Full log remains in the artifact; this is model-visible only.
fn reduce_failure(text: &str, profile: &str, max_tokens: usize) -> String {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return "command failed with no output".into();
    }

    let mut interesting: Vec<usize> = Vec::new();
    for (idx, line) in lines.iter().enumerate() {
        if is_failure_line(line, profile) {
            interesting.push(idx);
        }
    }

    if interesting.is_empty() {
        // Fallback: last ~40 lines often hold the real error.
        let start = lines.len().saturating_sub(40);
        let window = lines[start..].join("\n");
        return clamp_to_tokens(window, max_tokens);
    }

    // Expand each hit with a small context window and merge overlaps.
    let ctx = match profile {
        "npm_install" => 2,
        "cargo" => 3,
        "pytest" => 4,
        _ => 2,
    };
    let mut ranges: Vec<(usize, usize)> = interesting
        .into_iter()
        .map(|i| (i.saturating_sub(ctx), (i + ctx + 1).min(lines.len())))
        .collect();
    ranges.sort_by_key(|r| r.0);
    let mut merged: Vec<(usize, usize)> = Vec::new();
    for (s, e) in ranges {
        if let Some(last) = merged.last_mut() {
            if s <= last.1 {
                last.1 = last.1.max(e);
                continue;
            }
        }
        merged.push((s, e));
    }

    // Prefer the last merged ranges (errors usually appear late).
    merged.reverse();
    let mut selected: Vec<(usize, usize)> = Vec::new();
    let mut total_lines = 0usize;
    for range in merged {
        let len = range.1 - range.0;
        if total_lines > 0 && total_lines + len > 60 {
            break;
        }
        selected.push(range);
        total_lines += len;
    }
    selected.reverse();

    let mut parts: Vec<String> = Vec::new();
    for (s, e) in selected {
        parts.push(lines[s..e].join("\n"));
    }
    let window = parts.join("\n…\n");
    clamp_to_tokens(window, max_tokens)
}

fn is_failure_line(line: &str, profile: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    let generic = lower.contains("error")
        || lower.contains("failed")
        || lower.contains("panic")
        || lower.contains("fatal")
        || lower.contains("exception")
        || lower.contains("traceback");
    match profile {
        "npm_install" => {
            lower.contains("npm error")
                || lower.contains("err!")
                || lower.contains("errno")
                || generic
        }
        "cargo" => {
            lower.contains("error[")
                || lower.starts_with("error:")
                || lower.contains("could not compile")
                || lower.contains("panic")
                || generic
        }
        "python_install" => {
            lower.contains("error:")
                || lower.contains("no matching distribution")
                || lower.contains("failed")
                || generic
        }
        "pytest" => {
            lower.contains("failed")
                || lower.contains("error")
                || lower.contains("assert")
                || line.contains("E ")
                || generic
        }
        "msbuild" => {
            lower.contains("error ")
                || lower.contains("build failed")
                || lower.contains("fatal error")
                || generic
        }
        "git" => {
            lower.contains("fatal:")
                || lower.contains("error:")
                || lower.contains("conflict")
                || lower.contains("failed")
                || generic
        }
        _ => generic,
    }
}

fn clamp_to_tokens(text: String, max_tokens: usize) -> String {
    if crate::builtins::est_token_count(&text) <= max_tokens {
        text
    } else {
        head_tail_budget(&text, max_tokens).0
    }
}

fn extract_warnings(text: &str, profile: &str) -> Vec<Diagnostic> {
    let cleaned = strip_ansi(text);
    cleaned
        .lines()
        .filter(|line| line.to_ascii_lowercase().contains("warning"))
        .take(20)
        .map(|line| Diagnostic {
            tool: profile.into(),
            severity: "warning".into(),
            message: line.trim().into(),
            path: None,
            line: None,
            column: None,
        })
        .collect()
}

fn extract_diagnostics(text: &str, profile: &str) -> Vec<Diagnostic> {
    lazy_static! {
        static ref LOCATION: Regex = Regex::new(
            r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<column>\d+))?:\s*(?P<severity>error|warning|fatal)?[:\s]*(?P<message>.+)$"
        )
        .unwrap();
    }
    let cleaned = strip_ansi(text);
    let mut diagnostics = Vec::new();
    for line in cleaned.lines() {
        if !is_failure_line(line, profile) {
            continue;
        }
        if let Some(caps) = LOCATION.captures(line) {
            diagnostics.push(Diagnostic {
                tool: profile.into(),
                severity: caps
                    .name("severity")
                    .map(|v| v.as_str())
                    .unwrap_or("error")
                    .into(),
                message: caps
                    .name("message")
                    .map(|v| v.as_str())
                    .unwrap_or(line)
                    .trim()
                    .into(),
                path: caps.name("path").map(|v| v.as_str().replace('\\', "/")),
                line: caps.name("line").and_then(|v| v.as_str().parse().ok()),
                column: caps.name("column").and_then(|v| v.as_str().parse().ok()),
            });
        } else {
            diagnostics.push(Diagnostic {
                tool: profile.into(),
                severity: "error".into(),
                message: line.trim().into(),
                path: None,
                line: None,
                column: None,
            });
        }
        if diagnostics.len() >= 30 {
            break;
        }
    }
    diagnostics
}

fn classify_exec_error(error: &anyhow::Error) -> &'static str {
    let msg = error.to_string();
    if msg.contains("E_EXEC_BAD_ARG") {
        "E_EXEC_BAD_ARG"
    } else if msg.contains("E_LIMIT_UNSUPPORTED") {
        "E_LIMIT_UNSUPPORTED"
    } else if msg.contains("cannot find")
        || msg.contains("The system cannot find")
        || msg.contains("not found")
        || msg.contains("os error 2")
    {
        "E_EXEC_NOT_FOUND"
    } else {
        "E_EXEC_SPAWN"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_noisy_and_content_profiles() {
        assert_eq!(
            detect_profile(&["npm".into(), "install".into()], "auto"),
            "npm_install"
        );
        assert_eq!(
            detect_profile(&["git".into(), "diff".into()], "auto"),
            "git"
        );
        assert_eq!(
            detect_profile(&["cargo".into(), "test".into()], "auto"),
            "cargo"
        );
    }

    #[test]
    fn npm_success_is_summary_only() {
        let summary = reduce_success(
            "noise\nadded 12 packages in 3s\naudited 13 packages\nfound 0 vulnerabilities\nreify:progress",
            "npm_install",
        );
        assert!(summary.contains("added 12 packages"));
        assert!(summary.contains("0 vulnerabilities") || summary.contains("audited"));
        assert!(!summary.contains("noise"));
        assert!(!summary.contains("reify"));
        assert!(crate::builtins::est_token_count(&summary) <= SUCCESS_SUMMARY_TOKENS);
        assert!(summary.lines().count() <= SUCCESS_SUMMARY_MAX_LINES);
    }

    #[test]
    fn cargo_success_drops_compiling_noise() {
        let summary = reduce_success(
            "   Compiling foo v0.1.0\n   Compiling bar v0.1.0\n    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1.23s\n",
            "cargo",
        );
        assert!(summary.contains("Finished"));
        assert!(!summary.to_ascii_lowercase().contains("compiling"));
        assert!(crate::builtins::est_token_count(&summary) <= SUCCESS_SUMMARY_TOKENS);
    }

    #[test]
    fn failure_window_keeps_error_not_noise() {
        let mut log = String::new();
        for i in 0..100 {
            log.push_str(&format!("downloading package {i}\n"));
        }
        log.push_str("src/main.rs:10:5: error: expected `;`\n");
        log.push_str("could not compile `demo` due to previous error\n");
        let window = reduce_failure(&log, "cargo", 400);
        assert!(window.contains("expected"));
        assert!(window.contains("could not compile") || window.contains("error"));
        assert!(!window.contains("downloading package 0"));
        assert!(crate::builtins::est_token_count(&window) <= 400);
    }

    #[test]
    fn npm_failure_captures_err_block() {
        let log = "npm warn deprecated foo@1.0.0\n\
                   npm error code ERESOLVE\n\
                   npm error ERESOLVE unable to resolve dependency tree\n\
                   npm error\n\
                   npm error Fix the upstream dependency conflict\n";
        let window = reduce_failure(log, "npm_install", 300);
        assert!(window.to_ascii_lowercase().contains("eresolve") || window.contains("npm error"));
        assert!(!window.contains("deprecated") || window.contains("npm error"));
    }

    #[test]
    fn strip_ansi_removes_color_codes() {
        let colored = "\u{1b}[31merror\u{1b}[0m: boom";
        assert_eq!(strip_ansi(colored), "error: boom");
    }

    #[test]
    fn head_tail_is_explicitly_truncated() {
        let input = "x".repeat(20_000);
        let (value, truncated) = head_tail_budget(&input, 100);
        assert!(truncated);
        assert!(value.contains("omitted"));
    }

    #[test]
    fn observe_stream_success_has_no_full_text() {
        let stream = CapturedStream {
            bytes: b"noise\nadded 3 packages\nfound 0 vulnerabilities\n".to_vec(),
            raw_bytes: 48,
            raw_complete: true,
            encoding: "utf-8".into(),
            binary: false,
            text: Some("noise\nadded 3 packages\nfound 0 vulnerabilities\n".into()),
        };
        let obs = observe_stream(
            &stream,
            "stdout",
            "npm_install",
            true,
            2000,
            "auto",
            None,
            "test",
        );
        assert_eq!(obs.status, "reduced");
        assert!(obs.text.is_none());
        assert!(obs.summary.as_ref().unwrap().contains("added 3 packages"));
        assert!(!obs.summary.as_ref().unwrap().contains("noise"));
    }

    #[test]
    fn observe_stream_failure_focuses_errors() {
        let mut body = "installing...\n".repeat(50);
        body.push_str("\u{1b}[31mnpm error code E404\u{1b}[0m\nnpm error 404 Not Found\n");
        let stream = CapturedStream {
            bytes: body.as_bytes().to_vec(),
            raw_bytes: body.len() as u64,
            raw_complete: true,
            encoding: "utf-8".into(),
            binary: false,
            text: Some(body.clone()),
        };
        let obs = observe_stream(
            &stream,
            "stderr",
            "npm_install",
            false,
            400,
            "auto",
            None,
            "test",
        );
        assert!(matches!(obs.status, "truncated" | "reduced"));
        let text = obs.text.unwrap();
        assert!(text.to_ascii_lowercase().contains("npm error") || text.contains("E404"));
        assert!(!text.contains("\u{1b}["));
        assert!(text.len() < body.len());
    }
}
