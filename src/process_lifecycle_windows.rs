//! Windows ConPTY process creation without a shell or third-party PTY wrapper.

use crate::process_command::ResolvedProcessCommand;
use crate::process_lifecycle::ExitStatusValue;
use crate::process_runner::{ExecLimits, WindowsJob};
use anyhow::{anyhow, Result};
use std::collections::BTreeMap;
use std::ffi::c_void;
use std::fs::File;
use std::mem::{size_of, zeroed};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{FromRawHandle, RawHandle};
use std::path::Path;
use std::ptr::{null, null_mut};
use std::sync::Arc;
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, WAIT_OBJECT_0,
    WAIT_TIMEOUT,
};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Console::{ClosePseudoConsole, CreatePseudoConsole, COORD, HPCON};
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Threading::{
    CreateProcessW, DeleteProcThreadAttributeList, GetExitCodeProcess,
    InitializeProcThreadAttributeList, ResumeThread, TerminateProcess, UpdateProcThreadAttribute,
    WaitForSingleObject, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
    EXTENDED_STARTUPINFO_PRESENT, PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
    STARTF_USESTDHANDLES, STARTUPINFOEXW,
};

pub(crate) struct SpawnedConPty {
    pub process: WindowsPtyProcess,
    pub stdin: File,
    pub stdout: File,
    pub job: Arc<WindowsJob>,
    pub pid: u32,
}

pub(crate) struct WindowsPtyProcess {
    process: HANDLE,
    pseudo_console: Option<HPCON>,
}

unsafe impl Send for WindowsPtyProcess {}

impl WindowsPtyProcess {
    pub(crate) fn try_wait(&mut self) -> std::io::Result<Option<ExitStatusValue>> {
        let result = unsafe { WaitForSingleObject(self.process, 0) };
        if result == WAIT_TIMEOUT {
            return Ok(None);
        }
        if result != WAIT_OBJECT_0 {
            return Err(std::io::Error::last_os_error());
        }
        let mut code = 0u32;
        if unsafe { GetExitCodeProcess(self.process, &mut code) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        self.close_pseudo_console();
        Ok(Some(ExitStatusValue { code: code as i32 }))
    }

    fn close_pseudo_console(&mut self) {
        if let Some(handle) = self.pseudo_console.take() {
            unsafe { ClosePseudoConsole(handle) };
        }
    }
}

impl Drop for WindowsPtyProcess {
    fn drop(&mut self) {
        self.close_pseudo_console();
        if !self.process.is_null() {
            unsafe { CloseHandle(self.process) };
        }
    }
}

struct AttributeList {
    storage: Vec<u8>,
}

impl AttributeList {
    fn new(pseudo_console: HPCON) -> Result<Self> {
        let mut bytes = 0usize;
        unsafe {
            InitializeProcThreadAttributeList(null_mut(), 1, 0, &mut bytes);
        }
        if bytes == 0 {
            return Err(last_error("InitializeProcThreadAttributeList(size)"));
        }
        let mut storage = vec![0u8; bytes];
        let list = storage.as_mut_ptr().cast();
        if unsafe { InitializeProcThreadAttributeList(list, 1, 0, &mut bytes) } == 0 {
            return Err(last_error("InitializeProcThreadAttributeList"));
        }
        let updated = unsafe {
            UpdateProcThreadAttribute(
                list,
                0,
                PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE as usize,
                pseudo_console as *const c_void,
                size_of::<HPCON>(),
                null_mut(),
                null(),
            )
        };
        if updated == 0 {
            unsafe { DeleteProcThreadAttributeList(list) };
            return Err(last_error("UpdateProcThreadAttribute(PSEUDOCONSOLE)"));
        }
        Ok(Self { storage })
    }

    fn as_mut_ptr(
        &mut self,
    ) -> windows_sys::Win32::System::Threading::LPPROC_THREAD_ATTRIBUTE_LIST {
        self.storage.as_mut_ptr().cast()
    }
}

impl Drop for AttributeList {
    fn drop(&mut self) {
        if !self.storage.is_empty() {
            unsafe { DeleteProcThreadAttributeList(self.as_mut_ptr()) };
        }
    }
}

pub(crate) fn spawn_conpty(
    resolved: &ResolvedProcessCommand,
    cwd: &Path,
    env: Option<&BTreeMap<String, String>>,
    cols: u16,
    rows: u16,
    limits: &ExecLimits,
) -> Result<SpawnedConPty> {
    let mut input_read: HANDLE = null_mut();
    let mut input_write: HANDLE = null_mut();
    let mut output_read: HANDLE = null_mut();
    let mut output_write: HANDLE = null_mut();
    let mut security: SECURITY_ATTRIBUTES = unsafe { zeroed() };
    security.nLength = size_of::<SECURITY_ATTRIBUTES>() as u32;
    security.bInheritHandle = 1;

    if unsafe { CreatePipe(&mut input_read, &mut input_write, &security, 0) } == 0 {
        return Err(last_error("CreatePipe(ConPTY input)"));
    }
    if unsafe { CreatePipe(&mut output_read, &mut output_write, &security, 0) } == 0 {
        close_handle(input_read);
        close_handle(input_write);
        return Err(last_error("CreatePipe(ConPTY output)"));
    }
    if unsafe { SetHandleInformation(input_write, HANDLE_FLAG_INHERIT, 0) } == 0
        || unsafe { SetHandleInformation(output_read, HANDLE_FLAG_INHERIT, 0) } == 0
    {
        close_handle(input_read);
        close_handle(input_write);
        close_handle(output_read);
        close_handle(output_write);
        return Err(last_error("SetHandleInformation(ConPTY)"));
    }

    let mut pseudo_console: HPCON = 0;
    let hr = unsafe {
        CreatePseudoConsole(
            COORD {
                X: cols as i16,
                Y: rows as i16,
            },
            input_read,
            output_write,
            0,
            &mut pseudo_console,
        )
    };
    if hr < 0 {
        close_handle(input_read);
        close_handle(input_write);
        close_handle(output_read);
        close_handle(output_write);
        return Err(anyhow!(
            "E_PROCESS_PTY: CreatePseudoConsole failed with HRESULT 0x{hr:08x}"
        ));
    }

    let mut attributes = match AttributeList::new(pseudo_console) {
        Ok(attributes) => attributes,
        Err(error) => {
            unsafe { ClosePseudoConsole(pseudo_console) };
            close_handle(input_read);
            close_handle(input_write);
            close_handle(output_read);
            close_handle(output_write);
            return Err(error.context("E_PROCESS_PTY"));
        }
    };
    let mut startup: STARTUPINFOEXW = unsafe { zeroed() };
    startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = null_mut();
    startup.StartupInfo.hStdOutput = null_mut();
    startup.StartupInfo.hStdError = null_mut();
    startup.lpAttributeList = attributes.as_mut_ptr();

    let application = wide_null(resolved.executable.as_os_str());
    let mut command_line = command_line(resolved);
    let process_cwd = crate::process_command::windows_process_path(cwd);
    let current_directory = wide_null(process_cwd.as_os_str());
    let environment = env.map(environment_block);
    let environment_ptr = environment
        .as_ref()
        .map(|block| block.as_ptr().cast::<c_void>())
        .unwrap_or(null());
    let mut process_info: PROCESS_INFORMATION = unsafe { zeroed() };
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            null(),
            null(),
            0,
            EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
            environment_ptr,
            current_directory.as_ptr(),
            &startup.StartupInfo,
            &mut process_info,
        )
    };
    drop(attributes);
    close_handle(input_read);
    close_handle(output_write);
    if created == 0 {
        unsafe { ClosePseudoConsole(pseudo_console) };
        close_handle(input_write);
        close_handle(output_read);
        return Err(last_error("E_PROCESS_PTY: CreateProcessW"));
    }

    let job = match WindowsJob::attach_handle(process_info.hProcess as RawHandle, limits) {
        Ok(job) => Arc::new(job),
        Err(error) => {
            unsafe { TerminateProcess(process_info.hProcess, 1) };
            close_handle(process_info.hThread);
            close_handle(process_info.hProcess);
            unsafe { ClosePseudoConsole(pseudo_console) };
            close_handle(input_write);
            close_handle(output_read);
            return Err(error.context("E_PROCESS_JOB"));
        }
    };
    if unsafe { ResumeThread(process_info.hThread) } == u32::MAX {
        let error = last_error("E_PROCESS_PTY: ResumeThread");
        job.terminate();
        close_handle(process_info.hThread);
        close_handle(process_info.hProcess);
        unsafe { ClosePseudoConsole(pseudo_console) };
        close_handle(input_write);
        close_handle(output_read);
        return Err(error);
    }
    close_handle(process_info.hThread);

    let stdin = unsafe { File::from_raw_handle(input_write as RawHandle) };
    let stdout = unsafe { File::from_raw_handle(output_read as RawHandle) };
    Ok(SpawnedConPty {
        process: WindowsPtyProcess {
            process: process_info.hProcess,
            pseudo_console: Some(pseudo_console),
        },
        stdin,
        stdout,
        job,
        pid: process_info.dwProcessId,
    })
}

fn command_line(resolved: &ResolvedProcessCommand) -> Vec<u16> {
    let executable = resolved.executable.to_string_lossy();
    let mut text = quote_windows_arg(&executable);
    for arg in &resolved.args {
        text.push(' ');
        text.push_str(&quote_windows_arg(arg));
    }
    if let Some(raw_arg) = resolved.windows_raw_arg.as_ref() {
        text.push(' ');
        text.push_str(raw_arg);
    }
    text.encode_utf16().chain(Some(0)).collect()
}

fn quote_windows_arg(value: &str) -> String {
    if !value.is_empty()
        && !value
            .chars()
            .any(|character| character.is_whitespace() || character == '"')
    {
        return value.to_string();
    }
    let mut output = String::from("\"");
    let mut backslashes = 0usize;
    for character in value.chars() {
        if character == '\\' {
            backslashes += 1;
            continue;
        }
        if character == '"' {
            output.extend(std::iter::repeat('\\').take(backslashes * 2 + 1));
            output.push('"');
        } else {
            output.extend(std::iter::repeat('\\').take(backslashes));
            output.push(character);
        }
        backslashes = 0;
    }
    output.extend(std::iter::repeat('\\').take(backslashes * 2));
    output.push('"');
    output
}

fn environment_block(env: &BTreeMap<String, String>) -> Vec<u16> {
    let mut entries: Vec<_> = env.iter().collect();
    entries.sort_by(|(left, _), (right, _)| {
        left.to_ascii_lowercase()
            .cmp(&right.to_ascii_lowercase())
            .then_with(|| left.cmp(right))
    });
    let mut block = Vec::new();
    for (key, value) in entries {
        block.extend(format!("{key}={value}").encode_utf16());
        block.push(0);
    }
    block.push(0);
    block
}

fn wide_null(value: &std::ffi::OsStr) -> Vec<u16> {
    value.encode_wide().chain(Some(0)).collect()
}

fn close_handle(handle: HANDLE) {
    if !handle.is_null() {
        unsafe { CloseHandle(handle) };
    }
}

fn last_error(context: &str) -> anyhow::Error {
    let code = unsafe { GetLastError() };
    anyhow!("E_PROCESS_WIN32: {context} failed with Win32 error {code}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_windows_arguments_without_losing_trailing_backslashes() {
        assert_eq!(quote_windows_arg("plain"), "plain");
        assert_eq!(quote_windows_arg("two words"), "\"two words\"");
        assert_eq!(
            quote_windows_arg("C:\\path with space\\"),
            "\"C:\\path with space\\\\\""
        );
        assert_eq!(quote_windows_arg("a\"b"), "\"a\\\"b\"");
    }
}
