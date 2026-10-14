//! Stateful, bounded process lifecycle owned by the long-running ACI runtime.

use crate::artifact::{display_path, ArtifactStore};
use crate::operation::{safety_error_to_observation, Observation, OperationRequest};
use crate::process_command::{resolve_process_command, ResolvedProcessCommand};
#[cfg(windows)]
use crate::process_runner::WindowsJob;
use crate::process_runner::{ExecLimits, DEFAULT_MAX_OUTPUT_BYTES};
use crate::safety::{self, Effect, GuardCtx};
use anyhow::{anyhow, Context, Result};
use base64::Engine;
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const DEFAULT_RETENTION_MS: u64 = 24 * 60 * 60 * 1_000;
const DEFAULT_POLL_BYTES: usize = 64 * 1024;
const MAX_POLL_BYTES: usize = 256 * 1024;
const MAX_ENV_ENTRIES: usize = 512;
const MAX_ENV_BYTES: usize = 256 * 1024;
const MAX_STDIN_BYTES: usize = 1024 * 1024;
const MAX_WAIT_MS: u64 = 30_000;

lazy_static! {
    static ref MANAGER: Mutex<Option<Arc<LifecycleManager>>> = Mutex::new(None);
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleState {
    Starting,
    Running,
    Exited,
    Killed,
    Lost,
}

impl LifecycleState {
    fn terminal(self) -> bool {
        matches!(self, Self::Exited | Self::Killed | Self::Lost)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
struct ProcessOwner {
    runtime_id: String,
    workspace_id: String,
    agent_id: String,
    session_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ArtifactLineage {
    stream: String,
    handle: String,
    retained_bytes: u64,
    raw_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DurableRecord {
    process_id: String,
    owner: ProcessOwner,
    state: LifecycleState,
    pid: u32,
    argv: Vec<String>,
    cwd: String,
    executable: String,
    interpreter: Option<String>,
    mode: String,
    stdin_mode: String,
    started_at_ms: u64,
    updated_at_ms: u64,
    exited_at_ms: Option<u64>,
    exit_code: Option<i32>,
    termination_reason: Option<String>,
    timed_out: bool,
    max_output_bytes: usize,
    retention_expires_at_ms: u64,
    artifacts: Vec<ArtifactLineage>,
}

#[derive(Debug, Deserialize)]
struct PersistedOutputChunk {
    start_cursor: u64,
    end_cursor: u64,
    stream: String,
    data_base64: String,
}

#[derive(Debug, Clone)]
struct OutputChunk {
    start_cursor: u64,
    end_cursor: u64,
    stream: &'static str,
    bytes: Vec<u8>,
}

struct OutputLog {
    chunks: VecDeque<OutputChunk>,
    retained_start_cursor: u64,
    next_cursor: u64,
    retained_bytes: usize,
    max_bytes: usize,
    persist_path: PathBuf,
    raw_stdout_bytes: u64,
    raw_stderr_bytes: u64,
    raw_pty_bytes: u64,
}

impl OutputLog {
    fn new(persist_path: PathBuf, max_bytes: usize) -> Self {
        Self {
            chunks: VecDeque::new(),
            retained_start_cursor: 0,
            next_cursor: 0,
            retained_bytes: 0,
            max_bytes,
            persist_path,
            raw_stdout_bytes: 0,
            raw_stderr_bytes: 0,
            raw_pty_bytes: 0,
        }
    }

    fn load(persist_path: PathBuf, max_bytes: usize) -> Self {
        let mut log = Self::new(persist_path.clone(), max_bytes);
        let Ok(text) = fs::read_to_string(&persist_path) else {
            return log;
        };
        for line in text.lines() {
            let Ok(frame) = serde_json::from_str::<PersistedOutputChunk>(line) else {
                continue;
            };
            let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(frame.data_base64)
            else {
                continue;
            };
            let stream = match frame.stream.as_str() {
                "stdout" => "stdout",
                "stderr" => "stderr",
                "pty" => "pty",
                _ => continue,
            };
            log.add_raw_bytes(stream, bytes.len() as u64);
            log.next_cursor = log.next_cursor.max(frame.end_cursor);
            log.retained_bytes = log.retained_bytes.saturating_add(bytes.len());
            log.chunks.push_back(OutputChunk {
                start_cursor: frame.start_cursor,
                end_cursor: frame.end_cursor,
                stream,
                bytes,
            });
        }
        if log.enforce_budget() {
            log.rewrite_persisted();
        }
        log
    }

    fn append(&mut self, stream: &'static str, bytes: &[u8]) {
        if bytes.is_empty() {
            return;
        }
        let start_cursor = self.next_cursor;
        self.next_cursor = self.next_cursor.saturating_add(bytes.len() as u64);
        let end_cursor = self.next_cursor;
        self.add_raw_bytes(stream, bytes.len() as u64);
        let frame = json!({
            "start_cursor": start_cursor,
            "end_cursor": end_cursor,
            "stream": stream,
            "data_base64": base64::engine::general_purpose::STANDARD.encode(bytes),
        });
        if let Some(parent) = self.persist_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.persist_path)
        {
            let _ = writeln!(file, "{frame}");
            let _ = file.flush();
        }
        self.retained_bytes = self.retained_bytes.saturating_add(bytes.len());
        self.chunks.push_back(OutputChunk {
            start_cursor,
            end_cursor,
            stream,
            bytes: bytes.to_vec(),
        });
        if self.enforce_budget() {
            self.rewrite_persisted();
        }
    }

    fn enforce_budget(&mut self) -> bool {
        let mut changed = false;
        while self.retained_bytes > self.max_bytes {
            let Some(mut front) = self.chunks.pop_front() else {
                break;
            };
            let excess = self.retained_bytes - self.max_bytes;
            if front.bytes.len() <= excess {
                changed = true;
                self.retained_bytes -= front.bytes.len();
                self.retained_start_cursor = front.end_cursor;
                continue;
            }
            front.bytes.drain(..excess);
            changed = true;
            front.start_cursor = front.start_cursor.saturating_add(excess as u64);
            self.retained_bytes -= excess;
            self.retained_start_cursor = front.start_cursor;
            self.chunks.push_front(front);
            break;
        }
        if self.chunks.is_empty() {
            self.retained_start_cursor = self.next_cursor;
        }
        changed
    }

    fn rewrite_persisted(&self) {
        let temp = self
            .persist_path
            .with_extension(format!("{}.tmp", std::process::id()));
        let Ok(mut file) = fs::File::create(&temp) else {
            return;
        };
        for chunk in &self.chunks {
            let frame = json!({
                "start_cursor": chunk.start_cursor,
                "end_cursor": chunk.end_cursor,
                "stream": chunk.stream,
                "data_base64": base64::engine::general_purpose::STANDARD.encode(&chunk.bytes),
            });
            if writeln!(file, "{frame}").is_err() {
                let _ = fs::remove_file(&temp);
                return;
            }
        }
        if file.flush().is_ok() {
            let _ = fs::rename(&temp, &self.persist_path).or_else(|_| {
                let _ = fs::remove_file(&self.persist_path);
                fs::rename(&temp, &self.persist_path)
            });
        }
    }

    fn add_raw_bytes(&mut self, stream: &str, bytes: u64) {
        match stream {
            "stdout" => self.raw_stdout_bytes = self.raw_stdout_bytes.saturating_add(bytes),
            "stderr" => self.raw_stderr_bytes = self.raw_stderr_bytes.saturating_add(bytes),
            "pty" => self.raw_pty_bytes = self.raw_pty_bytes.saturating_add(bytes),
            _ => {}
        }
    }

    fn read(&self, requested_cursor: u64, max_bytes: usize) -> Result<Value> {
        if requested_cursor > self.next_cursor {
            return Err(anyhow!(
                "E_PROCESS_CURSOR: cursor {requested_cursor} exceeds next cursor {}",
                self.next_cursor
            ));
        }
        let cursor = requested_cursor.max(self.retained_start_cursor);
        let mut returned = 0usize;
        let mut chunks = Vec::new();
        let mut response_cursor = cursor;
        for chunk in &self.chunks {
            if chunk.end_cursor <= cursor || returned >= max_bytes {
                continue;
            }
            let offset = cursor.saturating_sub(chunk.start_cursor) as usize;
            let available = chunk.bytes.len().saturating_sub(offset);
            let take = available.min(max_bytes - returned);
            if take == 0 {
                continue;
            }
            let start = chunk.start_cursor.saturating_add(offset as u64);
            let end = start.saturating_add(take as u64);
            let (text, encoding) =
                crate::process_runner::decode_output_bytes(&chunk.bytes[offset..offset + take]);
            chunks.push(json!({
                "stream": chunk.stream,
                "start_cursor": start,
                "end_cursor": end,
                "encoding": encoding,
                "text": text,
            }));
            returned += take;
            response_cursor = end;
        }
        Ok(json!({
            "chunks": chunks,
            "requested_cursor": requested_cursor,
            "cursor": response_cursor,
            "next_cursor": self.next_cursor,
            "retained_start_cursor": self.retained_start_cursor,
            "lost_bytes": self.retained_start_cursor.saturating_sub(requested_cursor),
            "truncated": requested_cursor < self.retained_start_cursor || response_cursor < self.next_cursor,
            "returned_bytes": returned,
        }))
    }

    fn stream_bytes(&self, stream: &str) -> Vec<u8> {
        let mut bytes = Vec::new();
        for chunk in &self.chunks {
            if chunk.stream == stream || (stream == "stdout" && chunk.stream == "pty") {
                bytes.extend_from_slice(&chunk.bytes);
            }
        }
        bytes
    }

    fn raw_bytes(&self, stream: &str) -> u64 {
        match stream {
            "stdout" => self.raw_stdout_bytes.saturating_add(self.raw_pty_bytes),
            "stderr" => self.raw_stderr_bytes,
            "pty" => self.raw_pty_bytes,
            _ => 0,
        }
    }
}

struct SharedRecord {
    core: Mutex<DurableRecord>,
    output: Mutex<OutputLog>,
    stdin: Mutex<Option<Box<dyn Write + Send>>>,
    control: Arc<dyn ProcessControl>,
    changed: Condvar,
}

trait ProcessControl: Send + Sync {
    fn terminate(&self) -> Result<()>;
}

#[cfg(windows)]
impl ProcessControl for WindowsJob {
    fn terminate(&self) -> Result<()> {
        self.terminate_checked()
    }
}

#[cfg(unix)]
struct UnixProcessGroup {
    pid: i32,
}

#[cfg(unix)]
impl ProcessControl for UnixProcessGroup {
    fn terminate(&self) -> Result<()> {
        let rc = unsafe { libc::kill(-self.pid, libc::SIGKILL) };
        if rc == 0 {
            Ok(())
        } else {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ESRCH) {
                Ok(())
            } else {
                Err(error.into())
            }
        }
    }
}

enum ChildWaiter {
    Standard(Child),
    #[cfg(windows)]
    Pty(crate::process_lifecycle_windows::WindowsPtyProcess),
}

impl ChildWaiter {
    fn try_wait(&mut self) -> Result<Option<ExitStatusValue>> {
        match self {
            Self::Standard(child) => child
                .try_wait()
                .map(|status| status.map(ExitStatusValue::from)),
            #[cfg(windows)]
            Self::Pty(process) => process.try_wait(),
        }
        .map_err(Into::into)
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ExitStatusValue {
    pub code: i32,
}

impl From<ExitStatus> for ExitStatusValue {
    fn from(status: ExitStatus) -> Self {
        Self {
            code: status.code().unwrap_or(-1),
        }
    }
}

struct SpawnedProcess {
    pid: u32,
    stdin: Option<Box<dyn Write + Send>>,
    stdout: Box<dyn Read + Send>,
    stderr: Option<Box<dyn Read + Send>>,
    control: Arc<dyn ProcessControl>,
    waiter: ChildWaiter,
    mode: &'static str,
}

struct LifecycleManager {
    runtime_id: String,
    workspace: PathBuf,
    workspace_id: String,
    root: PathBuf,
    records: Mutex<HashMap<String, Arc<SharedRecord>>>,
}

impl LifecycleManager {
    fn new(workspace: PathBuf) -> Result<Arc<Self>> {
        let workspace = workspace.canonicalize().unwrap_or(workspace);
        let root = crate::safety::state_root_for(&workspace).join("process-lifecycle");
        fs::create_dir_all(&root)?;
        let normalized = if cfg!(windows) {
            display_path(&workspace).to_ascii_lowercase()
        } else {
            display_path(&workspace)
        };
        let workspace_id = format!(
            "ws_sha256_{}",
            hex::encode(Sha256::digest(normalized.as_bytes()))
        );
        let manager = Arc::new(Self {
            runtime_id: format!("rt_{}", uuid::Uuid::new_v4().simple()),
            workspace,
            workspace_id,
            root,
            records: Mutex::new(HashMap::new()),
        });
        manager.reconcile()?;
        Ok(manager)
    }

    fn reconcile(&self) -> Result<()> {
        let now = now_ms();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let Ok(bytes) = fs::read(&path) else {
                continue;
            };
            let Ok(mut durable) = serde_json::from_slice::<DurableRecord>(&bytes) else {
                continue;
            };
            if durable.retention_expires_at_ms <= now {
                let _ = fs::remove_file(&path);
                let _ = fs::remove_file(self.output_path(&durable.process_id));
                continue;
            }
            if matches!(
                durable.state,
                LifecycleState::Starting | LifecycleState::Running
            ) {
                durable.state = LifecycleState::Lost;
                durable.termination_reason = Some("runtime_restart_unrecoverable".into());
                durable.exited_at_ms = Some(now);
                durable.updated_at_ms = now;
                self.persist(&durable)?;
            }
            let output = OutputLog::load(
                self.output_path(&durable.process_id),
                durable.max_output_bytes,
            );
            let record = Arc::new(SharedRecord {
                core: Mutex::new(durable.clone()),
                output: Mutex::new(output),
                stdin: Mutex::new(None),
                control: Arc::new(TerminalControl),
                changed: Condvar::new(),
            });
            self.records
                .lock()
                .unwrap()
                .insert(durable.process_id.clone(), record);
        }
        Ok(())
    }

    fn record_path(&self, process_id: &str) -> PathBuf {
        self.root.join(format!("{process_id}.json"))
    }

    fn output_path(&self, process_id: &str) -> PathBuf {
        self.root.join(format!("{process_id}.output.jsonl"))
    }

    fn persist(&self, record: &DurableRecord) -> Result<()> {
        let path = self.record_path(&record.process_id);
        let temp = self
            .root
            .join(format!(".{}.{}.tmp", record.process_id, std::process::id()));
        fs::write(&temp, serde_json::to_vec_pretty(record)?)?;
        fs::rename(&temp, &path).or_else(|_| {
            let _ = fs::remove_file(&path);
            fs::rename(&temp, &path)
        })?;
        Ok(())
    }

    fn lookup(&self, process_id: &str) -> Result<Arc<SharedRecord>> {
        self.records
            .lock()
            .unwrap()
            .get(process_id)
            .cloned()
            .ok_or_else(|| anyhow!("E_PROCESS_NOT_FOUND: process '{process_id}' does not exist"))
    }
}

struct TerminalControl;

impl ProcessControl for TerminalControl {
    fn terminate(&self) -> Result<()> {
        Ok(())
    }
}

#[derive(Debug, Deserialize)]
struct StartArgs {
    argv: Vec<String>,
    #[serde(default = "default_cwd")]
    cwd: String,
    agent_id: String,
    session_id: String,
    #[serde(default)]
    env: Option<BTreeMap<String, String>>,
    #[serde(default = "default_stdin_mode")]
    stdin_mode: String,
    #[serde(default)]
    stdin: Option<String>,
    #[serde(default = "default_encoding")]
    stdin_encoding: String,
    #[serde(default)]
    stdin_eof: bool,
    #[serde(default)]
    pty: bool,
    #[serde(default = "default_cols")]
    cols: u16,
    #[serde(default = "default_rows")]
    rows: u16,
    #[serde(default)]
    timeout_ms: Option<u64>,
    #[serde(default = "crate::process_runner::default_max_output_bytes")]
    max_output_bytes: usize,
    #[serde(default)]
    max_memory_mb: Option<usize>,
    #[serde(default)]
    max_processes: Option<u32>,
    #[serde(default)]
    wait_ms: u64,
}

#[derive(Debug, Deserialize)]
struct OwnedProcessArgs {
    process_id: String,
    runtime_id: String,
    agent_id: String,
    session_id: String,
}

#[derive(Debug, Deserialize)]
struct PollArgs {
    #[serde(flatten)]
    owner: OwnedProcessArgs,
    #[serde(default)]
    cursor: u64,
    #[serde(default = "default_poll_bytes")]
    max_bytes: usize,
    #[serde(default)]
    wait_ms: u64,
}

#[derive(Debug, Deserialize)]
struct WriteArgs {
    #[serde(flatten)]
    owner: OwnedProcessArgs,
    #[serde(default)]
    data: String,
    #[serde(default = "default_encoding")]
    encoding: String,
    #[serde(default)]
    submit: bool,
    #[serde(default)]
    eof: bool,
}

#[derive(Debug, Deserialize)]
struct KillArgs {
    #[serde(flatten)]
    owner: OwnedProcessArgs,
    #[serde(default = "default_kill_reason")]
    reason: String,
    #[serde(default = "default_kill_wait_ms")]
    wait_ms: u64,
}

#[derive(Debug, Deserialize)]
struct ListArgs {
    runtime_id: String,
    agent_id: String,
    session_id: String,
    #[serde(default)]
    include_terminal: bool,
}

fn default_cwd() -> String {
    ".".into()
}

fn default_stdin_mode() -> String {
    "null".into()
}

fn default_encoding() -> String {
    "utf8".into()
}

fn default_cols() -> u16 {
    120
}

fn default_rows() -> u16 {
    30
}

fn default_poll_bytes() -> usize {
    DEFAULT_POLL_BYTES
}

fn default_kill_reason() -> String {
    "manual_cancel".into()
}

fn default_kill_wait_ms() -> u64 {
    2_000
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn manager() -> Result<Arc<LifecycleManager>> {
    let workspace = safety::workspace_root();
    let workspace = workspace.canonicalize().unwrap_or(workspace);
    let mut guard = MANAGER.lock().unwrap();
    if let Some(manager) = guard.as_ref() {
        if manager.workspace != workspace {
            return Err(anyhow!(
                "E_PROCESS_WORKSPACE: lifecycle runtime is already bound to '{}'",
                display_path(&manager.workspace)
            ));
        }
        return Ok(Arc::clone(manager));
    }
    let manager = LifecycleManager::new(workspace)?;
    *guard = Some(Arc::clone(&manager));
    Ok(manager)
}

fn parse_args<T: for<'de> Deserialize<'de>>(req: &OperationRequest) -> Result<T, Observation> {
    serde_json::from_value(req.args.clone()).map_err(|error| {
        Observation::failure(
            &req.id,
            &req.op,
            "process",
            "E_PROCESS_BAD_ARG",
            error.to_string(),
            true,
        )
    })
}

fn require_shell(req: &OperationRequest) -> Result<(), Observation> {
    if let crate::capability::CapabilityResult::Deny(reason) =
        crate::capability::check_capability("sh")
    {
        return Err(Observation::failure(
            &req.id,
            &req.op,
            "process",
            "E_CAPABILITY_DENY",
            reason,
            true,
        ));
    }
    Ok(())
}

fn failure(req: &OperationRequest, error: anyhow::Error) -> Observation {
    let message = error.to_string();
    let code = message
        .split_once(':')
        .map(|(code, _)| code)
        .filter(|code| code.starts_with("E_"))
        .unwrap_or("E_PROCESS_INTERNAL")
        .to_string();
    Observation::failure(&req.id, &req.op, "process", &code, message, true)
}

fn success(req: &OperationRequest, data: Value, start: Instant) -> Observation {
    Observation::success(
        &req.id,
        &req.op,
        "process",
        data,
        vec!["process".into()],
        vec!["shell.exec".into()],
        start.elapsed().as_millis() as u64,
        Vec::new(),
        Vec::new(),
    )
}

pub(crate) fn execute_start(req: &OperationRequest) -> Observation {
    let start = Instant::now();
    if let Err(observation) = require_shell(req) {
        return observation;
    }
    let args: StartArgs = match parse_args(req) {
        Ok(args) => args,
        Err(observation) => return observation,
    };
    if args.agent_id != req.agent {
        return failure(
            req,
            anyhow!("E_PROCESS_OWNER: agent_id must match request.agent"),
        );
    }
    if let Err(error) = validate_start_args(&args) {
        return failure(req, error);
    }
    let manager = match manager() {
        Ok(manager) => manager,
        Err(error) => return failure(req, error),
    };
    let cwd = match resolve_cwd(&manager.workspace, &args.cwd) {
        Ok(cwd) => cwd,
        Err(error) => return failure(req, error),
    };
    let resolved = match resolve_process_command(&args.argv, &cwd, args.env.as_ref()) {
        Ok(resolved) => resolved,
        Err(error) => return failure(req, error),
    };
    if let Err(error) = safety::guard(GuardCtx {
        builtin: "process.start",
        effect: Effect::Exec,
        what: "start process",
        targets: vec![display_path(&resolved.audited_executable)],
        blast_radius: json!({
            "argv": args.argv,
            "cwd": display_path(&cwd),
            "agent_id": args.agent_id,
            "session_id": args.session_id,
            "pty": args.pty,
            "executable": display_path(&resolved.audited_executable),
            "interpreter": resolved.interpreter.as_ref().map(|path| display_path(path)),
        }),
        reversible: false,
        fs_paths: false,
    }) {
        return safety_error_to_observation(req, "process", error);
    }
    let input = match decode_input(args.stdin.as_deref().unwrap_or(""), &args.stdin_encoding) {
        Ok(input) => input,
        Err(error) => return failure(req, error),
    };
    let process_id = format!("proc_{}", uuid::Uuid::new_v4().simple());
    let limits = ExecLimits {
        timeout_ms: args.timeout_ms.unwrap_or(req.timeout_ms),
        max_output_bytes: args.max_output_bytes,
        max_memory_mb: args.max_memory_mb,
        max_processes: args.max_processes,
    };
    let spawned = match spawn_process(
        &resolved,
        &cwd,
        args.env.as_ref(),
        &args.stdin_mode,
        args.pty,
        args.cols,
        args.rows,
        &limits,
    ) {
        Ok(spawned) => spawned,
        Err(error) => return failure(req, error),
    };
    let now = now_ms();
    let owner = ProcessOwner {
        runtime_id: manager.runtime_id.clone(),
        workspace_id: manager.workspace_id.clone(),
        agent_id: args.agent_id.clone(),
        session_id: args.session_id.clone(),
    };
    let durable = DurableRecord {
        process_id: process_id.clone(),
        owner,
        state: LifecycleState::Running,
        pid: spawned.pid,
        argv: args.argv.clone(),
        cwd: display_path(&cwd),
        executable: display_path(&resolved.audited_executable),
        interpreter: resolved.interpreter.as_ref().map(|path| display_path(path)),
        mode: spawned.mode.into(),
        stdin_mode: args.stdin_mode.clone(),
        started_at_ms: now,
        updated_at_ms: now,
        exited_at_ms: None,
        exit_code: None,
        termination_reason: None,
        timed_out: false,
        max_output_bytes: args.max_output_bytes,
        retention_expires_at_ms: now.saturating_add(DEFAULT_RETENTION_MS),
        artifacts: Vec::new(),
    };
    let record = Arc::new(SharedRecord {
        core: Mutex::new(durable.clone()),
        output: Mutex::new(OutputLog::new(
            manager.output_path(&process_id),
            args.max_output_bytes,
        )),
        stdin: Mutex::new(spawned.stdin),
        control: spawned.control,
        changed: Condvar::new(),
    });
    if let Err(error) = manager.persist(&durable) {
        let _ = record.control.terminate();
        return failure(
            req,
            error.context("E_PROCESS_PERSIST: failed to persist starting record"),
        );
    }
    manager
        .records
        .lock()
        .unwrap()
        .insert(process_id.clone(), Arc::clone(&record));

    let stdout_reader = spawn_reader(
        Arc::clone(&record),
        spawned.stdout,
        if args.pty { "pty" } else { "stdout" },
    );
    let stderr_reader = spawned
        .stderr
        .map(|reader| spawn_reader(Arc::clone(&record), reader, "stderr"));
    spawn_monitor(
        Arc::clone(&manager),
        Arc::clone(&record),
        spawned.waiter,
        stdout_reader,
        stderr_reader,
        limits.timeout_ms,
    );

    if !input.is_empty() || args.stdin_eof {
        if let Err(error) = write_input(&record, &input, args.stdin_eof) {
            {
                let mut core = record.core.lock().unwrap();
                core.termination_reason = Some("initial_stdin_failed".into());
                core.updated_at_ms = now_ms();
                let _ = manager.persist(&core);
            }
            let _ = record.control.terminate();
            return failure(req, error);
        }
    }
    wait_for_change(&record, 0, args.wait_ms.min(MAX_WAIT_MS));
    match snapshot(&record, 0, DEFAULT_POLL_BYTES) {
        Ok(data) => success(req, data, start),
        Err(error) => failure(req, error),
    }
}

pub(crate) fn execute_poll(req: &OperationRequest) -> Observation {
    let start = Instant::now();
    if let Err(observation) = require_shell(req) {
        return observation;
    }
    let args: PollArgs = match parse_args(req) {
        Ok(args) => args,
        Err(observation) => return observation,
    };
    let manager = match manager() {
        Ok(manager) => manager,
        Err(error) => return failure(req, error),
    };
    let record = match manager.lookup(&args.owner.process_id) {
        Ok(record) => record,
        Err(error) => return failure(req, error),
    };
    if let Err(error) = verify_owner(req, &record, &args.owner) {
        return failure(req, error);
    }
    let max_bytes = args.max_bytes.clamp(1, MAX_POLL_BYTES);
    wait_for_change(&record, args.cursor, args.wait_ms.min(MAX_WAIT_MS));
    match snapshot(&record, args.cursor, max_bytes) {
        Ok(data) => success(req, data, start),
        Err(error) => failure(req, error),
    }
}

pub(crate) fn execute_write(req: &OperationRequest) -> Observation {
    let start = Instant::now();
    if let Err(observation) = require_shell(req) {
        return observation;
    }
    let args: WriteArgs = match parse_args(req) {
        Ok(args) => args,
        Err(observation) => return observation,
    };
    let manager = match manager() {
        Ok(manager) => manager,
        Err(error) => return failure(req, error),
    };
    let record = match manager.lookup(&args.owner.process_id) {
        Ok(record) => record,
        Err(error) => return failure(req, error),
    };
    if let Err(error) = verify_owner(req, &record, &args.owner) {
        return failure(req, error);
    }
    let mut bytes = match decode_input(&args.data, &args.encoding) {
        Ok(bytes) => bytes,
        Err(error) => return failure(req, error),
    };
    if args.submit {
        bytes.push(b'\r');
    }
    if let Err(error) = write_input(&record, &bytes, args.eof) {
        return failure(req, error);
    }
    success(
        req,
        json!({
            "process_id": args.owner.process_id,
            "written_bytes": bytes.len(),
            "eof": args.eof,
        }),
        start,
    )
}

pub(crate) fn execute_kill(req: &OperationRequest) -> Observation {
    let start = Instant::now();
    if let Err(observation) = require_shell(req) {
        return observation;
    }
    let args: KillArgs = match parse_args(req) {
        Ok(args) => args,
        Err(observation) => return observation,
    };
    let manager = match manager() {
        Ok(manager) => manager,
        Err(error) => return failure(req, error),
    };
    let record = match manager.lookup(&args.owner.process_id) {
        Ok(record) => record,
        Err(error) => return failure(req, error),
    };
    if let Err(error) = verify_owner(req, &record, &args.owner) {
        return failure(req, error);
    }
    let should_terminate = {
        let mut core = record.core.lock().unwrap();
        if core.state.terminal() {
            false
        } else {
            if core.termination_reason.is_none() {
                core.termination_reason = Some(sanitize_reason(&args.reason));
                core.updated_at_ms = now_ms();
                let _ = manager.persist(&core);
            }
            true
        }
    };
    if should_terminate {
        if let Err(error) = record.control.terminate() {
            return failure(
                req,
                error.context("E_PROCESS_KILL: failed to terminate process tree"),
            );
        }
    }
    wait_until_terminal(&record, args.wait_ms.min(MAX_WAIT_MS));
    let cursor = record.output.lock().unwrap().next_cursor;
    match snapshot(&record, cursor, 1) {
        Ok(data) => success(req, data, start),
        Err(error) => failure(req, error),
    }
}

pub(crate) fn execute_list(req: &OperationRequest) -> Observation {
    let start = Instant::now();
    if let Err(observation) = require_shell(req) {
        return observation;
    }
    let args: ListArgs = match parse_args(req) {
        Ok(args) => args,
        Err(observation) => return observation,
    };
    if args.agent_id != req.agent {
        return failure(
            req,
            anyhow!("E_PROCESS_OWNER: agent_id must match request.agent"),
        );
    }
    let manager = match manager() {
        Ok(manager) => manager,
        Err(error) => return failure(req, error),
    };
    let records: Vec<_> = manager.records.lock().unwrap().values().cloned().collect();
    let mut processes = Vec::new();
    for record in records {
        let core = record.core.lock().unwrap();
        if core.owner.runtime_id != args.runtime_id
            || core.owner.agent_id != args.agent_id
            || core.owner.session_id != args.session_id
            || (!args.include_terminal && core.state.terminal())
        {
            continue;
        }
        processes.push(summary_json(&core));
    }
    success(
        req,
        json!({
            "runtime_id": args.runtime_id,
            "workspace_id": manager.workspace_id,
            "processes": processes,
            "count": processes.len(),
        }),
        start,
    )
}

fn validate_start_args(args: &StartArgs) -> Result<()> {
    if args.argv.is_empty() || args.argv[0].is_empty() {
        return Err(anyhow!("E_PROCESS_BAD_ARG: argv must contain a program"));
    }
    if args.agent_id.trim().is_empty() || args.session_id.trim().is_empty() {
        return Err(anyhow!(
            "E_PROCESS_BAD_ARG: agent_id and session_id are required"
        ));
    }
    if !matches!(args.stdin_mode.as_str(), "null" | "pipe") {
        return Err(anyhow!(
            "E_PROCESS_BAD_ARG: stdin_mode must be null or pipe"
        ));
    }
    if args.stdin_mode == "null" && (args.stdin.is_some() || args.stdin_eof) {
        return Err(anyhow!("E_PROCESS_BAD_ARG: stdin requires stdin_mode=pipe"));
    }
    if args.max_output_bytes == 0 || args.max_output_bytes > DEFAULT_MAX_OUTPUT_BYTES {
        return Err(anyhow!(
            "E_PROCESS_BAD_ARG: max_output_bytes must be between 1 and {DEFAULT_MAX_OUTPUT_BYTES}"
        ));
    }
    if args.cols == 0 || args.rows == 0 {
        return Err(anyhow!(
            "E_PROCESS_BAD_ARG: PTY rows and cols must be positive"
        ));
    }
    if let Some(env) = args.env.as_ref() {
        if env.len() > MAX_ENV_ENTRIES {
            return Err(anyhow!("E_PROCESS_ENV: environment has too many entries"));
        }
        let mut bytes = 0usize;
        for (key, value) in env {
            if key.is_empty() || key.contains(['=', '\0', '\r', '\n']) || value.contains('\0') {
                return Err(anyhow!(
                    "E_PROCESS_ENV: environment contains an invalid entry"
                ));
            }
            bytes = bytes.saturating_add(key.len()).saturating_add(value.len());
        }
        if bytes > MAX_ENV_BYTES {
            return Err(anyhow!(
                "E_PROCESS_ENV: environment exceeds the byte budget"
            ));
        }
    }
    Ok(())
}

fn resolve_cwd(workspace: &Path, input: &str) -> Result<PathBuf> {
    let candidate = PathBuf::from(input);
    let candidate = if candidate.is_absolute() {
        candidate
    } else {
        workspace.join(candidate)
    };
    let canonical = candidate.canonicalize().with_context(|| {
        format!(
            "E_PROCESS_CWD: cannot resolve cwd '{}'",
            candidate.display()
        )
    })?;
    if !canonical.starts_with(workspace) {
        return Err(anyhow!("E_PROCESS_CWD: cwd is outside the workspace"));
    }
    if !canonical.is_dir() {
        return Err(anyhow!("E_PROCESS_CWD: cwd is not a directory"));
    }
    Ok(canonical)
}

fn decode_input(value: &str, encoding: &str) -> Result<Vec<u8>> {
    let bytes = match encoding {
        "utf8" => value.as_bytes().to_vec(),
        "base64" => base64::engine::general_purpose::STANDARD
            .decode(value)
            .map_err(|error| anyhow!("E_PROCESS_INPUT: invalid base64 input: {error}"))?,
        _ => return Err(anyhow!("E_PROCESS_INPUT: encoding must be utf8 or base64")),
    };
    if bytes.len() > MAX_STDIN_BYTES {
        return Err(anyhow!(
            "E_PROCESS_INPUT: input exceeds {MAX_STDIN_BYTES} bytes"
        ));
    }
    Ok(bytes)
}

fn sanitize_reason(reason: &str) -> String {
    let reason = reason.trim();
    if reason.is_empty() {
        "manual_cancel".into()
    } else {
        reason.chars().take(128).collect()
    }
}

fn verify_owner(
    req: &OperationRequest,
    record: &SharedRecord,
    args: &OwnedProcessArgs,
) -> Result<()> {
    if args.agent_id != req.agent {
        return Err(anyhow!(
            "E_PROCESS_OWNER: agent_id must match request.agent"
        ));
    }
    let core = record.core.lock().unwrap();
    if core.owner.runtime_id != args.runtime_id
        || core.owner.agent_id != args.agent_id
        || core.owner.session_id != args.session_id
    {
        return Err(anyhow!("E_PROCESS_OWNER: process ownership does not match"));
    }
    Ok(())
}

fn spawn_process(
    resolved: &ResolvedProcessCommand,
    cwd: &Path,
    env: Option<&BTreeMap<String, String>>,
    stdin_mode: &str,
    pty: bool,
    cols: u16,
    rows: u16,
    limits: &ExecLimits,
) -> Result<SpawnedProcess> {
    if pty {
        #[cfg(windows)]
        {
            let spawned = crate::process_lifecycle_windows::spawn_conpty(
                resolved, cwd, env, cols, rows, limits,
            )?;
            return Ok(SpawnedProcess {
                pid: spawned.pid,
                stdin: Some(Box::new(spawned.stdin)),
                stdout: Box::new(spawned.stdout),
                stderr: None,
                control: spawned.job,
                waiter: ChildWaiter::Pty(spawned.process),
                mode: "pty",
            });
        }
        #[cfg(not(windows))]
        {
            return Err(anyhow!(
                "E_PROCESS_PTY_UNSUPPORTED: this build does not provide a PTY backend"
            ));
        }
    }

    let mut command = Command::new(&resolved.executable);
    command
        .args(&resolved.args)
        .current_dir(cwd)
        .stdin(if stdin_mode == "pipe" {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    crate::process_command::configure_command_environment(&mut command, env);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
        if let Some(raw_arg) = resolved.windows_raw_arg.as_ref() {
            command.raw_arg(raw_arg);
        }
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command.spawn().with_context(|| {
        format!(
            "E_PROCESS_SPAWN: failed to spawn '{}'",
            resolved.audited_executable.display()
        )
    })?;
    let pid = child.id();
    let stdin = child
        .stdin
        .take()
        .map(|input| Box::new(input) as Box<dyn Write + Send>);
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| anyhow!("E_PROCESS_SPAWN: stdout pipe is unavailable"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| anyhow!("E_PROCESS_SPAWN: stderr pipe is unavailable"))?;
    #[cfg(windows)]
    let control: Arc<dyn ProcessControl> = match WindowsJob::attach(&child, limits) {
        Ok(job) => Arc::new(job),
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    #[cfg(unix)]
    let control: Arc<dyn ProcessControl> = Arc::new(UnixProcessGroup { pid: pid as i32 });
    #[cfg(not(any(windows, unix)))]
    compile_error!("process lifecycle requires a Windows or Unix target");
    Ok(SpawnedProcess {
        pid,
        stdin,
        stdout: Box::new(stdout),
        stderr: Some(Box::new(stderr)),
        control,
        waiter: ChildWaiter::Standard(child),
        mode: "pipe",
    })
}

fn spawn_reader(
    record: Arc<SharedRecord>,
    mut reader: Box<dyn Read + Send>,
    stream: &'static str,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut buffer = [0u8; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => {
                    record
                        .output
                        .lock()
                        .unwrap()
                        .append(stream, &buffer[..read]);
                    record.changed.notify_all();
                }
                Err(_) => break,
            }
        }
        record.changed.notify_all();
    })
}

fn spawn_monitor(
    manager: Arc<LifecycleManager>,
    record: Arc<SharedRecord>,
    mut waiter: ChildWaiter,
    stdout_reader: thread::JoinHandle<()>,
    stderr_reader: Option<thread::JoinHandle<()>>,
    timeout_ms: u64,
) {
    thread::spawn(move || {
        let started = Instant::now();
        let status = loop {
            match waiter.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) => {}
                Err(error) => {
                    let mut core = record.core.lock().unwrap();
                    core.termination_reason = Some(format!("wait_failed:{error}"));
                    drop(core);
                    let _ = record.control.terminate();
                    break ExitStatusValue { code: -1 };
                }
            }
            if timeout_ms > 0 && started.elapsed() >= Duration::from_millis(timeout_ms) {
                let should_kill = {
                    let mut core = record.core.lock().unwrap();
                    if core.state.terminal() || core.timed_out {
                        false
                    } else {
                        core.timed_out = true;
                        core.termination_reason = Some("timeout".into());
                        true
                    }
                };
                if should_kill {
                    let _ = record.control.terminate();
                }
            }
            thread::sleep(Duration::from_millis(10));
        };
        let _ = stdout_reader.join();
        if let Some(reader) = stderr_reader {
            let _ = reader.join();
        }
        record.stdin.lock().unwrap().take();
        let artifacts = store_terminal_artifacts(&manager, &record);
        {
            let mut core = record.core.lock().unwrap();
            let killed = core.termination_reason.is_some();
            core.state = if killed {
                LifecycleState::Killed
            } else {
                LifecycleState::Exited
            };
            core.exit_code = Some(status.code);
            core.exited_at_ms = Some(now_ms());
            core.updated_at_ms = now_ms();
            core.artifacts = artifacts;
            core.retention_expires_at_ms = now_ms().saturating_add(DEFAULT_RETENTION_MS);
            let _ = manager.persist(&core);
        }
        record.changed.notify_all();
    });
}

fn store_terminal_artifacts(
    manager: &LifecycleManager,
    record: &SharedRecord,
) -> Vec<ArtifactLineage> {
    let core = record.core.lock().unwrap().clone();
    let output = record.output.lock().unwrap();
    let Ok(store) = ArtifactStore::new(&manager.workspace) else {
        return Vec::new();
    };
    let mut artifacts = Vec::new();
    for stream in ["stdout", "stderr"] {
        let bytes = output.stream_bytes(stream);
        if bytes.is_empty() {
            continue;
        }
        let Ok(stored) = store.store(
            &bytes,
            "binary",
            stream,
            "process.lifecycle",
            &core.owner.agent_id,
        ) else {
            continue;
        };
        artifacts.push(ArtifactLineage {
            stream: stream.into(),
            handle: stored.metadata.handle,
            retained_bytes: bytes.len() as u64,
            raw_bytes: output.raw_bytes(stream),
        });
    }
    artifacts
}

fn write_input(record: &SharedRecord, bytes: &[u8], eof: bool) -> Result<()> {
    if record.core.lock().unwrap().state.terminal() {
        return Err(anyhow!("E_PROCESS_EXITED: process is no longer running"));
    }
    let mut stdin = record.stdin.lock().unwrap();
    let writer = stdin
        .as_mut()
        .ok_or_else(|| anyhow!("E_PROCESS_STDIN_CLOSED: process stdin is closed"))?;
    if !bytes.is_empty() {
        writer
            .write_all(bytes)
            .context("E_PROCESS_WRITE: failed to write stdin")?;
        writer
            .flush()
            .context("E_PROCESS_WRITE: failed to flush stdin")?;
    }
    if eof {
        stdin.take();
    }
    Ok(())
}

fn wait_for_change(record: &SharedRecord, cursor: u64, wait_ms: u64) {
    if wait_ms == 0 {
        return;
    }
    let deadline = Instant::now() + Duration::from_millis(wait_ms);
    let mut core = record.core.lock().unwrap();
    loop {
        let has_output = record.output.lock().unwrap().next_cursor > cursor;
        if has_output || core.state.terminal() {
            return;
        }
        let now = Instant::now();
        if now >= deadline {
            return;
        }
        let duration = deadline.saturating_duration_since(now);
        let result = record.changed.wait_timeout(core, duration).unwrap();
        core = result.0;
        if result.1.timed_out() {
            return;
        }
    }
}

fn wait_until_terminal(record: &SharedRecord, wait_ms: u64) {
    if wait_ms == 0 {
        return;
    }
    let deadline = Instant::now() + Duration::from_millis(wait_ms);
    let mut core = record.core.lock().unwrap();
    while !core.state.terminal() {
        let now = Instant::now();
        if now >= deadline {
            return;
        }
        let result = record
            .changed
            .wait_timeout(core, deadline.saturating_duration_since(now))
            .unwrap();
        core = result.0;
        if result.1.timed_out() {
            return;
        }
    }
}

fn snapshot(record: &SharedRecord, cursor: u64, max_bytes: usize) -> Result<Value> {
    let output = record.output.lock().unwrap().read(cursor, max_bytes)?;
    let core = record.core.lock().unwrap();
    let mut value = summary_json(&core);
    let object = value.as_object_mut().expect("process summary is an object");
    object.insert("output".into(), output);
    object.insert("artifacts".into(), serde_json::to_value(&core.artifacts)?);
    Ok(value)
}

fn summary_json(core: &DurableRecord) -> Value {
    json!({
        "process_id": core.process_id,
        "runtime_id": core.owner.runtime_id,
        "workspace_id": core.owner.workspace_id,
        "agent_id": core.owner.agent_id,
        "session_id": core.owner.session_id,
        "state": core.state,
        "pid": core.pid,
        "argv": core.argv,
        "cwd": core.cwd,
        "executable": core.executable,
        "interpreter": core.interpreter,
        "mode": core.mode,
        "stdin_mode": core.stdin_mode,
        "started_at_ms": core.started_at_ms,
        "updated_at_ms": core.updated_at_ms,
        "exited_at_ms": core.exited_at_ms,
        "exit_code": core.exit_code,
        "termination_reason": core.termination_reason,
        "timed_out": core.timed_out,
        "retention_expires_at_ms": core.retention_expires_at_ms,
    })
}

/// Terminate all live process trees before the JSONL runtime exits.
pub fn shutdown() {
    let manager = MANAGER.lock().unwrap().as_ref().cloned();
    let Some(manager) = manager else {
        return;
    };
    let records: Vec<_> = manager.records.lock().unwrap().values().cloned().collect();
    for record in &records {
        let live = {
            let mut core = record.core.lock().unwrap();
            if core.state.terminal() {
                false
            } else {
                core.termination_reason = Some("runtime_shutdown".into());
                core.updated_at_ms = now_ms();
                let _ = manager.persist(&core);
                true
            }
        };
        if live {
            let _ = record.control.terminate();
        }
    }
    for record in records {
        wait_until_terminal(&record, 2_000);
    }
}
