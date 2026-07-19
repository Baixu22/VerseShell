use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

use crate::value::Value;

/// A single execution event for tracing. One per IR node evaluated.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ExecutionEvent {
    pub node_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub builtin_name: Option<String>,
    pub elapsed_us: u64,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result_summary: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn with_frame_restores_bindings_after_error() {
        let mut env = Env::new();
        env.set_var_unchecked("x", Value::Int(1));
        let result: Result<(), &'static str> = env.with_frame(&[("x", Value::Int(2))], |env| {
            assert_eq!(env.get_var("x"), Some(&Value::Int(2)));
            Err("stop")
        });
        assert!(result.is_err());
        assert_eq!(env.get_var("x"), Some(&Value::Int(1)));
    }
}

/// Runtime environment for the evaluator & builtins.
///
/// v0.6.0: Added frame stack for scoped variable bindings — pipeline stages
/// push/pop frames instead of cloning the entire environment.
#[derive(Debug, Default, Clone)]
pub struct Env {
    vars: BTreeMap<String, Value>,
    mutable_vars: BTreeMap<String, bool>,
    public_vars: HashSet<String>,
    exported_names: HashSet<String>,
    cwd: Option<PathBuf>,
    pipe_input: Option<Value>,
    pub deadline: Option<std::time::Instant>,
    pub trace: Option<Vec<ExecutionEvent>>,
    /// v0.6.0: scoped variable frame stack
    frames: Vec<BTreeMap<String, Value>>,
}

impl Env {
    pub fn new() -> Self {
        Self {
            vars: BTreeMap::new(),
            mutable_vars: BTreeMap::new(),
            public_vars: HashSet::new(),
            exported_names: HashSet::new(),
            cwd: None,
            pipe_input: None,
            deadline: None,
            trace: None,
            frames: Vec::new(),
        }
    }

    // ── v0.6.0: Scoped frame push/pop ──────────────────────────────────

    pub fn push_frame(&mut self, bindings: &[(&str, Value)]) {
        let mut frame = BTreeMap::new();
        for (name, val) in bindings {
            frame.insert(name.to_string(), val.clone());
        }
        self.frames.push(frame);
    }

    pub fn pop_frame(&mut self) {
        self.frames.pop();
    }

    /// Evaluate a closure with temporary lexical bindings. The frame is always
    /// removed when the closure returns, including `Result::Err` and early `?`.
    pub fn with_frame<T>(
        &mut self,
        bindings: &[(&str, Value)],
        f: impl FnOnce(&mut Self) -> T,
    ) -> T {
        self.push_frame(bindings);
        let result = f(self);
        self.pop_frame();
        result
    }

    /// Lookup scans frames (innermost first), then base `vars`.
    pub fn get_var(&self, name: &str) -> Option<&Value> {
        for frame in self.frames.iter().rev() {
            if let Some(v) = frame.get(name) {
                return Some(v);
            }
        }
        self.vars.get(name)
    }

    /// Unchecked set — writes into the innermost frame, or base vars.
    pub fn set_var_unchecked(&mut self, name: &str, value: Value) {
        if let Some(frame) = self.frames.last_mut() {
            frame.insert(name.to_string(), value);
        } else {
            self.vars.insert(name.to_string(), value);
        }
    }

    // ── Module registration ────────────────────────────────────────────

    pub fn register_module(&mut self, name: &str, module: Value) {
        self.vars.insert(name.to_string(), module);
        self.mutable_vars.insert(name.to_string(), false);
    }

    // ── Pipeline input ─────────────────────────────────────────────────

    pub fn input(&self) -> Option<&Value> {
        self.pipe_input.as_ref()
    }
    pub fn set_input(&mut self, v: Option<Value>) {
        self.pipe_input = v;
    }
    pub fn take_input(&mut self) -> Option<Value> {
        self.pipe_input.take()
    }
    pub fn clear_input(&mut self) {
        self.pipe_input = None;
    }

    // ── Variable accessors ─────────────────────────────────────────────

    pub fn set_var<S: Into<String>>(&mut self, name: S, value: Value) -> Result<(), String> {
        let name_str = name.into();
        if self.vars.contains_key(&name_str) {
            if !self.is_mutable(&name_str) {
                return Err(format!(
                    "Cannot reassign immutable variable '{}'. Use 'let mut {}' to make it mutable.",
                    name_str, name_str
                ));
            }
        }
        self.vars.insert(name_str, value);
        Ok(())
    }

    pub fn declare_var<S: Into<String>>(
        &mut self,
        name: S,
        value: Value,
        is_mut: bool,
    ) -> Result<(), String> {
        let name_str = name.into();
        if self.vars.contains_key(&name_str) {
            if !self.is_mutable(&name_str) {
                return Err(format!(
                    "Cannot reassign immutable variable '{}'. Use 'let mut {}' to make it mutable.",
                    name_str, name_str
                ));
            }
            self.vars.insert(name_str, value);
            return Ok(());
        }
        self.vars.insert(name_str.clone(), value);
        self.mutable_vars.insert(name_str, is_mut);
        Ok(())
    }

    pub(crate) fn set_var_unchecked_compat<S: Into<String>>(&mut self, name: S, value: Value) {
        let name_str = name.into();
        self.vars.insert(name_str.clone(), value);
        self.mutable_vars.insert(name_str, true);
    }

    pub fn add_export(&mut self, name: &str) {
        self.exported_names.insert(name.to_string());
    }

    pub fn del_var(&mut self, name: &str) {
        self.vars.remove(name);
        self.mutable_vars.remove(name);
        self.public_vars.remove(name);
        // Also remove from frames
        for frame in self.frames.iter_mut().rev() {
            frame.remove(name);
        }
    }

    pub fn is_mutable(&self, name: &str) -> bool {
        self.mutable_vars.get(name).copied().unwrap_or(false)
    }

    pub fn is_public(&self, name: &str) -> bool {
        self.public_vars.contains(name)
    }

    pub fn set_public(&mut self, name: &str, is_public: bool) {
        if is_public {
            self.public_vars.insert(name.to_string());
        } else {
            self.public_vars.remove(name);
        }
    }

    pub fn export(&mut self, name: &str) {
        self.exported_names.insert(name.to_string());
    }

    pub fn is_exported(&self, name: &str) -> bool {
        self.exported_names.contains(name)
    }

    pub fn exported_names(&self) -> &HashSet<String> {
        &self.exported_names
    }

    pub fn remove_var(&mut self, name: &str) {
        self.vars.remove(name);
        self.mutable_vars.remove(name);
        self.public_vars.remove(name);
        self.exported_names.remove(name);
    }

    pub fn take_var(&mut self, name: &str) -> Option<Value> {
        self.vars.remove(name)
    }

    pub fn vars(&self) -> &BTreeMap<String, Value> {
        &self.vars
    }

    pub fn vars_mut(&mut self) -> &mut BTreeMap<String, Value> {
        &mut self.vars
    }

    // ── Working directory ──────────────────────────────────────────────

    pub fn cwd(&self) -> Option<&Path> {
        self.cwd.as_deref()
    }

    pub fn set_cwd<P: Into<PathBuf>>(&mut self, p: P) {
        self.cwd = Some(p.into());
    }
}
