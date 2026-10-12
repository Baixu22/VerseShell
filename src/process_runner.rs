//! Bounded, non-interactive external process execution for Agent operations.

use anyhow::{anyhow, Context, Result};
use lazy_static::lazy_static;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub const DEFAULT_TIMEOUT_MS: u64 = 30_000;
pub const DEFAULT_MAX_OUTPUT_BYTES: usize = 64 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
pub struct ExecLimits {
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default = "default_max_output_bytes")]
    pub max_output_bytes: usize,
    #[serde(default)]
    pub max_memory_mb: Option<usize>,
    #[serde(default)]
    pub max_processes: Option<u32>,
}

impl Default for ExecLimits {
    fn default() -> Self {
        Self {
            timeout_ms: DEFAULT_TIMEOUT_MS,
            max_output_bytes: DEFAULT_MAX_OUTPUT_BYTES,
            max_memory_mb: None,
            max_processes: None,
        }
    }
}

fn default_timeout_ms() -> u64 {
    DEFAULT_TIMEOUT_MS
}
pub fn default_max_output_bytes() -> usize {
    DEFAULT_MAX_OUTPUT_BYTES
}

#[derive(Debug, Clone, Serialize)]
pub struct CapturedStream {
    #[serde(skip)]
    pub bytes: Vec<u8>,
    pub raw_bytes: u64,
    pub raw_complete: bool,
    pub encoding: String,
    pub binary: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProcessOutput {
    pub exit_code: i32,
    pub timed_out: bool,
    pub elapsed_ms: u64,
    pub stdout: CapturedStream,
    pub stderr: CapturedStream,
}

#[derive(Debug)]
struct CaptureBytes {
    bytes: Vec<u8>,
    raw_bytes: u64,
    raw_complete: bool,
}

pub fn run(argv: &[String], cwd: &Path, limits: &ExecLimits) -> Result<ProcessOutput> {
    run_with_env_and_input(argv, cwd, limits, None, None)
}

pub fn run_with_env_and_input(
    argv: &[String],
    cwd: &Path,
    limits: &ExecLimits,
    env: Option<&BTreeMap<String, String>>,
    stdin: Option<&[u8]>,
) -> Result<ProcessOutput> {
    if argv.is_empty() || argv[0].is_empty() {
        return Err(anyhow!("E_EXEC_BAD_ARG: argv must contain a program"));
    }
    if limits.max_output_bytes == 0 {
        return Err(anyhow!("E_EXEC_BAD_ARG: max_output_bytes must be positive"));
    }

    #[cfg(not(windows))]
    if limits.max_memory_mb.is_some() || limits.max_processes.is_some() {
        return Err(anyhow!(
            "E_LIMIT_UNSUPPORTED: max_memory_mb/max_processes are supported on Windows in v0.6"
        ));
    }

    let resolved = crate::process_command::resolve_process_command(argv, cwd, env)?;
    let mut command = Command::new(&resolved.executable);
    command
        .args(&resolved.args)
        .current_dir(cwd)
        .stdin(if stdin.is_some() {
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

    let start = Instant::now();
    let mut child = command.spawn().with_context(|| {
        format!(
            "failed to spawn resolved executable '{}' for '{}'",
            resolved.audited_executable.display(),
            argv[0]
        )
    })?;
    if let Some(input) = stdin {
        let mut child_stdin = child
            .stdin
            .take()
            .ok_or_else(|| anyhow!("missing stdin pipe"))?;
        child_stdin.write_all(input)?;
    }
    #[cfg(unix)]
    let pid = child.id();

    #[cfg(windows)]
    let job = WindowsJob::attach(&child, limits)?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| anyhow!("missing stdout pipe"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| anyhow!("missing stderr pipe"))?;
    let stdout_reader = capture_reader(stdout, limits.max_output_bytes);
    let stderr_reader = capture_reader(stderr, limits.max_output_bytes);

    let timeout = if limits.timeout_ms == 0 {
        None
    } else {
        Some(Duration::from_millis(limits.timeout_ms))
    };
    let mut timed_out = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if timeout.map(|t| start.elapsed() >= t).unwrap_or(false) {
            timed_out = true;
            #[cfg(windows)]
            job.terminate();
            #[cfg(unix)]
            unsafe {
                libc::kill(-(pid as i32), libc::SIGKILL);
            }
            #[cfg(not(any(windows, unix)))]
            {
                let _ = child.kill();
            }
            break child.wait()?;
        }
        thread::sleep(Duration::from_millis(10));
    };

    let stdout = stdout_reader
        .join()
        .map_err(|_| anyhow!("stdout reader panicked"))?;
    let stderr = stderr_reader
        .join()
        .map_err(|_| anyhow!("stderr reader panicked"))?;

    Ok(ProcessOutput {
        exit_code: status.code().unwrap_or(-1),
        timed_out,
        elapsed_ms: start.elapsed().as_millis() as u64,
        stdout: decode_capture(stdout),
        stderr: decode_capture(stderr),
    })
}

fn capture_reader<R: Read + Send + 'static>(
    mut reader: R,
    cap: usize,
) -> thread::JoinHandle<CaptureBytes> {
    thread::spawn(move || {
        let mut captured = Vec::with_capacity(cap.min(64 * 1024));
        let mut raw_bytes = 0u64;
        let mut buf = [0u8; 8192];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    raw_bytes = raw_bytes.saturating_add(n as u64);
                    let remaining = cap.saturating_sub(captured.len());
                    if remaining > 0 {
                        captured.extend_from_slice(&buf[..n.min(remaining)]);
                    }
                }
                Err(_) => break,
            }
        }
        CaptureBytes {
            raw_complete: raw_bytes <= captured.len() as u64,
            raw_bytes,
            bytes: captured,
        }
    })
}

fn decode_capture(capture: CaptureBytes) -> CapturedStream {
    if capture.bytes.iter().any(|b| *b == 0) {
        return CapturedStream {
            bytes: capture.bytes,
            raw_bytes: capture.raw_bytes,
            raw_complete: capture.raw_complete,
            encoding: "binary".into(),
            binary: true,
            text: None,
        };
    }

    let (text, encoding) = decode_output_bytes(&capture.bytes);
    CapturedStream {
        bytes: capture.bytes,
        raw_bytes: capture.raw_bytes,
        raw_complete: capture.raw_complete,
        encoding,
        binary: false,
        text: Some(normalize_preview(&text)),
    }
}

pub(crate) fn decode_output_bytes(bytes: &[u8]) -> (String, String) {
    let bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(bytes);
    if let Ok(text) = std::str::from_utf8(bytes) {
        return (text.to_string(), "utf-8".into());
    }

    #[cfg(windows)]
    if let Some((text, label)) = decode_windows_oem(bytes) {
        return (text, label);
    }

    (
        String::from_utf8_lossy(bytes).into_owned(),
        "utf-8-lossy".into(),
    )
}

#[cfg(windows)]
fn decode_windows_oem(bytes: &[u8]) -> Option<(String, String)> {
    use windows_sys::Win32::Globalization::GetOEMCP;
    let cp = unsafe { GetOEMCP() };
    decode_windows_code_page(bytes, cp)
}

fn decode_windows_code_page(bytes: &[u8], cp: u32) -> Option<(String, String)> {
    let label = match cp {
        65001 => "utf-8",
        936 => "gbk",
        950 => "big5",
        932 => "shift_jis",
        949 => "euc-kr",
        1250 => "windows-1250",
        1251 => "windows-1251",
        1252 => "windows-1252",
        1253 => "windows-1253",
        1254 => "windows-1254",
        1255 => "windows-1255",
        1256 => "windows-1256",
        1257 => "windows-1257",
        1258 => "windows-1258",
        _ => return None,
    };
    let encoding = encoding_rs::Encoding::for_label(label.as_bytes())?;
    let (text, _, lossy) = encoding.decode(bytes);
    let suffix = if lossy { "-lossy" } else { "" };
    Some((text.into_owned(), format!("windows-oem-{cp}{suffix}")))
}

pub(crate) fn decode_recorded_output(bytes: &[u8], declared: &str) -> (String, String) {
    if let Some(cp) = declared.strip_prefix("windows-oem-")
        .and_then(|s| s.trim_end_matches("-lossy").parse().ok())
    {
        if let Some(decoded) = decode_windows_code_page(bytes, cp) {
            return decoded;
        }
    }
    let bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(bytes);
    match std::str::from_utf8(bytes) {
        Ok(text) => (text.into(), "utf-8".into()),
        Err(_) => (String::from_utf8_lossy(bytes).into_owned(), "utf-8-lossy".into()),
    }
}

pub fn normalize_preview(text: &str) -> String {
    lazy_static! {
        static ref ANSI: Regex = Regex::new(r"\x1B\[[0-?]*[ -/]*[@-~]").unwrap();
    }
    let stripped = ANSI.replace_all(text, "");
    let mut out = String::new();
    let mut previous_blank = false;
    for line in stripped.split('\n') {
        let line = line.trim_end_matches('\r');
        let line = line.rsplit('\r').next().unwrap_or(line).trim_end();
        let blank = line.trim().is_empty();
        if blank && previous_blank {
            continue;
        }
        if !out.is_empty() {
            out.push('\n');
        }
        out.push_str(line);
        previous_blank = blank;
    }
    out.trim().to_string()
}

#[cfg(windows)]
pub(crate) struct WindowsJob {
    handle: windows_sys::Win32::Foundation::HANDLE,
}

#[cfg(windows)]
impl WindowsJob {
    pub(crate) fn attach(child: &std::process::Child, limits: &ExecLimits) -> Result<Self> {
        use std::os::windows::io::AsRawHandle;

        Self::attach_handle(child.as_raw_handle(), limits)
    }

    pub(crate) fn attach_handle(
        process_handle: std::os::windows::io::RawHandle,
        limits: &ExecLimits,
    ) -> Result<Self> {
        use std::mem::{size_of, zeroed};
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::System::JobObjects::*;

        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(anyhow!("E_EXEC_JOB: CreateJobObjectW failed"));
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if let Some(max_processes) = limits.max_processes {
            info.BasicLimitInformation.ActiveProcessLimit = max_processes;
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        }
        if let Some(max_memory_mb) = limits.max_memory_mb {
            info.ProcessMemoryLimit = max_memory_mb.saturating_mul(1024 * 1024);
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY;
        }
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            unsafe { CloseHandle(handle) };
            return Err(anyhow!("E_EXEC_JOB: SetInformationJobObject failed"));
        }
        let assigned = unsafe { AssignProcessToJobObject(handle, process_handle) };
        if assigned == 0 {
            unsafe { CloseHandle(handle) };
            return Err(anyhow!("E_EXEC_JOB: AssignProcessToJobObject failed"));
        }
        Ok(Self { handle })
    }

    pub(crate) fn terminate(&self) {
        let _ = self.terminate_checked();
    }

    pub(crate) fn terminate_checked(&self) -> Result<()> {
        use windows_sys::Win32::System::JobObjects::TerminateJobObject;
        if unsafe { TerminateJobObject(self.handle, 1) } == 0 {
            Err(anyhow!("E_EXEC_JOB: TerminateJobObject failed"))
        } else {
            Ok(())
        }
    }
}

#[cfg(windows)]
unsafe impl Send for WindowsJob {}

#[cfg(windows)]
unsafe impl Sync for WindowsJob {}

#[cfg(windows)]
impl Drop for WindowsJob {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.handle);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recorded_output_uses_its_code_page_and_marks_loss() {
        let chinese = [0xd6, 0xd0, 0xce, 0xc4];
        assert_eq!(decode_recorded_output(&chinese, "windows-oem-936"),
            ("中文".into(), "windows-oem-936".into()));
        let (text, encoding) = decode_recorded_output(&[0xff], "windows-oem-936");
        assert!(text.contains('\u{fffd}'));
        assert_eq!(encoding, "windows-oem-936-lossy");
        assert_eq!(decode_output_bytes("中文\u{fffd}".as_bytes()),
            ("中文\u{fffd}".into(), "utf-8".into()));
    }

    #[test]
    fn normalization_strips_ansi_and_progress_updates() {
        let input = "\x1b[31mred\x1b[0m\rgreen\n\n\nend";
        assert_eq!(normalize_preview(input), "green\n\nend");
    }

    #[test]
    fn captures_stdout_and_stderr_without_deadlock() {
        #[cfg(windows)]
        let argv = vec!["cmd".into(), "/C".into(), "echo out & echo err 1>&2".into()];
        #[cfg(not(windows))]
        let argv = vec!["sh".into(), "-c".into(), "echo out; echo err >&2".into()];
        let result = run(&argv, Path::new("."), &ExecLimits::default()).unwrap();
        assert_eq!(result.exit_code, 0);
        assert!(result.stdout.text.unwrap().contains("out"));
        assert!(result.stderr.text.unwrap().contains("err"));
    }

    #[test]
    fn timeout_terminates_promptly() {
        #[cfg(windows)]
        let argv = vec![
            "cmd".into(),
            "/C".into(),
            "ping 127.0.0.1 -n 6 > nul".into(),
        ];
        #[cfg(not(windows))]
        let argv = vec!["sh".into(), "-c".into(), "sleep 5".into()];
        let result = run(
            &argv,
            Path::new("."),
            &ExecLimits {
                timeout_ms: 50,
                ..Default::default()
            },
        )
        .unwrap();
        assert!(result.timed_out);
        assert!(result.elapsed_ms < 2_000);
    }

    #[test]
    fn output_cap_is_explicit_and_still_drains() {
        #[cfg(windows)]
        let argv = vec![
            "cmd".into(),
            "/C".into(),
            "for /L %i in (1,1,5000) do @echo 1234567890".into(),
        ];
        #[cfg(not(windows))]
        let argv = vec![
            "sh".into(),
            "-c".into(),
            "yes 1234567890 | head -n 5000".into(),
        ];
        let result = run(
            &argv,
            Path::new("."),
            &ExecLimits {
                max_output_bytes: 4096,
                ..Default::default()
            },
        )
        .unwrap();
        assert!(result.stdout.raw_bytes > 4096);
        assert!(!result.stdout.raw_complete);
        assert_eq!(result.stdout.bytes.len(), 4096);
    }
}
