//! Shared helpers for typed Agent operations.

use crate::operation::{Diagnostic, Observation, OperationRequest, SuggestedAction};
use crate::safety::{self, Effect, GuardCtx, Mode};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::time::Instant;

pub fn now() -> Instant {
    Instant::now()
}

pub fn elapsed_ms(start: Instant) -> u64 {
    start.elapsed().as_millis() as u64
}

pub fn content_hash(bytes: &[u8]) -> String {
    format!("sha256:{}", hex::encode(Sha256::digest(bytes)))
}

pub fn content_hash_str(text: &str) -> String {
    content_hash(text.as_bytes())
}

pub fn require_capability(req: &OperationRequest, builtin: &str) -> Result<(), Observation> {
    if let crate::capability::CapabilityResult::Deny(reason) =
        crate::capability::check_capability(builtin)
    {
        return Err(Observation::failure(
            &req.id,
            &req.op,
            "none",
            "E_CAPABILITY_DENY",
            reason,
            true,
        ));
    }
    Ok(())
}

pub fn resolve_workspace_path(path: &str) -> Result<PathBuf, String> {
    let resolved = safety::resolve_path_str(path);
    let pb = PathBuf::from(&resolved);
    if safety::current_mode() == Mode::Agent || std::env::var("AETHER_WORKSPACE").is_ok() {
        if !safety::within_workspace(&resolved) {
            return Err(format!("path outside workspace: {path}"));
        }
    }
    Ok(pb)
}

pub fn read_text_file(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))
}

pub fn write_text_file(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("cannot create parent {}: {e}", parent.display()))?;
        }
    }
    let tmp = path.with_extension(format!(
        "{}.ae_tmp",
        path.extension().and_then(|s| s.to_str()).unwrap_or("tmp")
    ));
    std::fs::write(&tmp, content).map_err(|e| format!("cannot write temp: {e}"))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("cannot rename into place: {e}"))?;
    Ok(())
}

pub fn guard_read(path: &str) -> Result<(), String> {
    safety::guard(GuardCtx {
        builtin: "file.read",
        effect: Effect::ReadLocal,
        what: "read",
        targets: vec![path.into()],
        blast_radius: json!({"path": path}),
        reversible: true,
        fs_paths: true,
    })
    .map_err(|e| e.message)
}

pub fn guard_write(path: &str) -> Result<(), String> {
    safety::guard(GuardCtx {
        builtin: "file.write",
        effect: Effect::WriteLocal,
        what: "write",
        targets: vec![path.into()],
        blast_radius: json!({"path": path}),
        reversible: true,
        fs_paths: true,
    })
    .map_err(|e| e.message)
}

pub fn guard_delete(path: &str) -> Result<(), String> {
    safety::guard(GuardCtx {
        builtin: "rm",
        effect: Effect::Destructive,
        what: "delete",
        targets: vec![path.into()],
        blast_radius: json!({"path": path}),
        reversible: true,
        fs_paths: true,
    })
    .map_err(|e| e.message)
}

/// Structured hash-check failure so agents can retry in one step.
#[derive(Debug, Clone)]
pub struct HashMismatch {
    pub expected: String,
    pub actual: String,
    pub message: String,
}

/// Hex characters kept in the compact digest (`hash`) returned by the read ops.
///
/// The full `sha256:<64 hex>` digest costs 71 characters per file, and a batched
/// read pays that cost once per file. A 16-hex-char (64-bit) prefix is enough to
/// detect a changed file, which is all optimistic concurrency needs.
pub const HASH_PREFIX_LEN: usize = 16;

/// Shortest prefix accepted from a caller for `expected_hash`.
///
/// 8 hex chars = 32 bits, so accepting a wrong-but-matching prefix needs a
/// 2^-32 collision against the current content — far below the rate at which a
/// stale read is accepted for unrelated reasons.
pub const HASH_PREFIX_MIN: usize = 8;

/// Compact change-detection digest: the first [`HASH_PREFIX_LEN`] hex chars of
/// the sha256 body, without the `sha256:` scheme.
pub fn short_hash(full: &str) -> String {
    full.strip_prefix("sha256:")
        .unwrap_or(full)
        .chars()
        .take(HASH_PREFIX_LEN)
        .collect()
}

/// Compare a caller-supplied `expected_hash` against the current content.
///
/// Accepts the full `sha256:<64 hex>` form, a bare 64-hex digest, or an
/// unambiguous hex prefix of at least [`HASH_PREFIX_MIN`] characters — which is
/// what the compact `hash` field of `file.view` / `file.read_range` /
/// `file.read_many` returns. Prefix matching is what lets the observation carry
/// a short digest without giving up the stale-write check; full digests still
/// compare exactly.
pub fn check_expected_hash(content: &str, expected: Option<&str>) -> Result<(), HashMismatch> {
    let Some(expected) = expected else {
        return Ok(());
    };
    let actual = content_hash_str(content);
    let actual_hex = actual
        .strip_prefix("sha256:")
        .unwrap_or(&actual)
        .to_ascii_lowercase();
    let given = expected.trim();
    let given_hex = given
        .strip_prefix("sha256:")
        .unwrap_or(given)
        .to_ascii_lowercase();
    let hex_only = !given_hex.is_empty() && given_hex.bytes().all(|b| b.is_ascii_hexdigit());
    let matches = hex_only
        && given_hex.len() >= HASH_PREFIX_MIN
        && given_hex.len() <= actual_hex.len()
        && actual_hex.starts_with(&given_hex);
    if !matches {
        let message = if !hex_only {
            format!(
                "content hash mismatch: expected {given} is not a hex sha256 digest or prefix, got {actual}"
            )
        } else if given_hex.len() < HASH_PREFIX_MIN {
            format!(
                "content hash mismatch: expected prefix {given} is shorter than {HASH_PREFIX_MIN} hex chars, got {actual}"
            )
        } else {
            format!("content hash mismatch: expected {given}, got {actual}")
        };
        return Err(HashMismatch {
            expected: given.to_string(),
            actual,
            message,
        });
    }
    Ok(())
}

pub fn arg_str(args: &Value, key: &str) -> Option<String> {
    args.get(key)
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

pub fn arg_u64(args: &Value, key: &str, default: u64) -> u64 {
    args.get(key)
        .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i.max(0) as u64)))
        .unwrap_or(default)
}

pub fn arg_bool(args: &Value, key: &str, default: bool) -> bool {
    args.get(key).and_then(|v| v.as_bool()).unwrap_or(default)
}

pub fn numbered_lines(lines: &[&str], start_line: usize) -> Vec<Value> {
    lines
        .iter()
        .enumerate()
        .map(|(i, line)| {
            json!({
                "line": start_line + i,
                "text": *line
            })
        })
        .collect()
}

pub fn ok(
    req: &OperationRequest,
    profile: &str,
    data: Value,
    effects: &[&str],
    caps: &[&str],
    start: Instant,
) -> Observation {
    Observation::success(
        &req.id,
        &req.op,
        profile,
        data,
        effects.iter().map(|s| (*s).to_string()).collect(),
        caps.iter().map(|s| (*s).to_string()).collect(),
        elapsed_ms(start),
        Vec::new(),
        Vec::new(),
    )
}

pub fn err(
    req: &OperationRequest,
    profile: &str,
    code: &str,
    message: impl Into<String>,
    start: Instant,
) -> Observation {
    Observation::fail_with(
        &req.id,
        &req.op,
        profile,
        code,
        message,
        true,
        None,
        Vec::new(),
        Vec::new(),
        None,
        elapsed_ms(start),
    )
}

pub fn err_data(
    req: &OperationRequest,
    profile: &str,
    code: &str,
    message: impl Into<String>,
    data: Value,
    diagnostics: Vec<Diagnostic>,
    suggested: Vec<SuggestedAction>,
    start: Instant,
) -> Observation {
    Observation::fail_with(
        &req.id,
        &req.op,
        profile,
        code,
        message,
        true,
        Some(data),
        diagnostics,
        suggested,
        None,
        elapsed_ms(start),
    )
}

#[allow(dead_code)]
pub fn display(path: &Path) -> String {
    crate::artifact::display_path(path)
}

pub fn audit(op: &str, effect: Effect, decision: &str, target: &str, detail: Value) {
    let _ = safety::audit(op, effect, decision, target, detail);
}

/// Preserve safety hint / approval token on Observation failures.
#[allow(dead_code)]
pub fn from_safety_error(
    req: &OperationRequest,
    profile: &str,
    err: safety::SafetyError,
) -> Observation {
    crate::operation::safety_error_to_observation(req, profile, err)
}
