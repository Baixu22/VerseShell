//! Approved argv and environment resolution shared by synchronous and lifecycle execution.

use anyhow::{anyhow, Context, Result};
use std::collections::BTreeMap;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone)]
pub struct ResolvedProcessCommand {
    /// Path handed to the OS as the application to launch.
    ///
    /// On Windows this is deliberately the path as resolved from PATH *without*
    /// following a final symlink. Win32 resolves an application symlink against
    /// the machine-wide PATH, and the child's `argv[0]` is derived from this
    /// value — so canonicalising it breaks every name-dispatching shim. Rustup's
    /// `cargo.exe` / `rustc.exe` are exactly that: symlinks to `rustup.exe` that
    /// pick a tool from the file name they were invoked as. Following the link
    /// made the shim run as rustup itself (`cargo check` -> exit 100 with
    /// "0 error(s)", `cargo build` -> "invalid value 'build' for '[+toolchain]'",
    /// `cargo --version` -> the rustup version), which silently broke every Rust
    /// task. See `resolve_candidate`.
    pub executable: PathBuf,
    pub args: Vec<String>,
    #[cfg(windows)]
    pub windows_raw_arg: Option<String>,
    /// Fully resolved real path (symlinks followed), used for audit identity and
    /// target reporting. Kept separate from [`Self::executable`] so the audit log
    /// still names the real binary while the launch keeps the shim's name.
    pub audited_executable: PathBuf,
    pub interpreter: Option<PathBuf>,
}

pub fn resolve_process_command(
    argv: &[String],
    cwd: &Path,
    env: Option<&BTreeMap<String, String>>,
) -> Result<ResolvedProcessCommand> {
    let program = argv
        .first()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow!("E_EXEC_BAD_ARG: argv must contain a program"))?;
    if program.contains('\0') || argv.iter().any(|arg| arg.contains(['\r', '\n', '\0'])) {
        return Err(anyhow!(
            "E_EXEC_BAD_ARG: argv contains a forbidden control character"
        ));
    }

    let resolved = resolve_executable(program, cwd, env)?;
    let audited = canonical_identity(resolved.clone()).unwrap_or_else(|_| resolved.clone());
    #[cfg(windows)]
    if is_batch_script(&resolved) {
        let interpreter = resolve_cmd(env)?;
        let command_line = batch_command_line(&windows_process_path(&resolved), &argv[1..])?;
        return Ok(ResolvedProcessCommand {
            executable: interpreter.clone(),
            args: vec!["/D".into(), "/S".into(), "/C".into()],
            windows_raw_arg: Some(command_line),
            audited_executable: audited,
            interpreter: Some(interpreter),
        });
    }

    Ok(ResolvedProcessCommand {
        executable: resolved,
        args: argv[1..].to_vec(),
        #[cfg(windows)]
        windows_raw_arg: None,
        audited_executable: audited,
        interpreter: None,
    })
}

#[cfg(windows)]
pub(crate) fn windows_process_path(path: &Path) -> PathBuf {
    let value = path.to_string_lossy();
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = value.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path.to_path_buf()
    }
}

pub fn configure_command_environment(
    command: &mut Command,
    env: Option<&BTreeMap<String, String>>,
) {
    if let Some(env) = env {
        command.env_clear();
        command.envs(env);
    }
}

fn resolve_executable(
    program: &str,
    cwd: &Path,
    env: Option<&BTreeMap<String, String>>,
) -> Result<PathBuf> {
    let input = Path::new(program);
    if input.is_absolute() || has_path_separator(program) {
        let candidate = if input.is_absolute() {
            input.to_path_buf()
        } else {
            cwd.join(input)
        };
        return resolve_candidate(candidate, env)
            .with_context(|| format!("E_EXEC_NOT_FOUND: executable '{program}' was not found"));
    }

    let path_value = env_value(env, "PATH")
        .map(OsString::from)
        .or_else(|| std::env::var_os("PATH"))
        .unwrap_or_default();
    for directory in std::env::split_paths(&path_value) {
        if let Ok(candidate) = resolve_candidate(directory.join(program), env) {
            return Ok(candidate);
        }
    }
    Err(anyhow!(
        "E_EXEC_NOT_FOUND: executable '{}' was not found on PATH",
        program
    ))
}

fn resolve_candidate(
    candidate: PathBuf,
    env: Option<&BTreeMap<String, String>>,
) -> Result<PathBuf> {
    // On Windows `cmd.exe` resolves a bare name through PATHEXT, and an
    // extensionless sibling is usually a POSIX shell script that Win32 cannot
    // launch: npm-for-Windows ships `npm` next to `npm.cmd`. Returning the bare
    // file first made `exec.run(["npm", ...])` fail with `E_EXEC_SPAWN` while raw
    // shell (which spawns through `cmd`) kept working, so prefer the PATHEXT
    // candidate and keep the extensionless file only as a fallback.
    #[cfg(windows)]
    if candidate.extension().is_none() {
        for extension in windows_extensions(env) {
            let mut value = candidate.as_os_str().to_os_string();
            value.push(extension);
            let with_extension = PathBuf::from(value);
            if with_extension.is_file() {
                return Ok(with_extension);
            }
        }
    }
    if candidate.is_file() {
        return Ok(candidate);
    }
    Err(anyhow!("candidate is not an executable file"))
}

fn canonical_identity(path: PathBuf) -> Result<PathBuf> {
    path.canonicalize()
        .with_context(|| format!("failed to canonicalize executable '{}'", path.display()))
}

fn has_path_separator(value: &str) -> bool {
    value.contains('/') || value.contains('\\')
}

fn env_value<'a>(env: Option<&'a BTreeMap<String, String>>, key: &str) -> Option<&'a str> {
    env?.iter()
        .find(|(name, _)| name.eq_ignore_ascii_case(key))
        .map(|(_, value)| value.as_str())
}

#[cfg(windows)]
fn windows_extensions(env: Option<&BTreeMap<String, String>>) -> Vec<String> {
    let value = env_value(env, "PATHEXT")
        .map(str::to_owned)
        .or_else(|| std::env::var("PATHEXT").ok())
        .unwrap_or_else(|| ".COM;.EXE;.BAT;.CMD".into());
    value
        .split(';')
        .filter_map(|extension| {
            let extension = extension.trim();
            if extension.is_empty() {
                None
            } else if extension.starts_with('.') {
                Some(extension.to_ascii_lowercase())
            } else {
                Some(format!(".{extension}").to_ascii_lowercase())
            }
        })
        .collect()
}

#[cfg(windows)]
fn is_batch_script(path: &Path) -> bool {
    path.extension()
        .and_then(OsStr::to_str)
        .is_some_and(|extension| matches!(extension.to_ascii_lowercase().as_str(), "cmd" | "bat"))
}

#[cfg(windows)]
fn resolve_cmd(env: Option<&BTreeMap<String, String>>) -> Result<PathBuf> {
    if let Some(comspec) = env_value(env, "ComSpec") {
        let candidate = PathBuf::from(comspec);
        if candidate.is_file() {
            return canonical_identity(candidate);
        }
    }
    let system_root = env_value(env, "SystemRoot")
        .map(str::to_owned)
        .or_else(|| std::env::var("SystemRoot").ok())
        .ok_or_else(|| {
            anyhow!("E_EXEC_NOT_FOUND: SystemRoot is unavailable for batch execution")
        })?;
    resolve_candidate(
        PathBuf::from(system_root).join("System32").join("cmd.exe"),
        env,
    )
}

#[cfg(windows)]
fn batch_command_line(script: &Path, args: &[String]) -> Result<String> {
    if args.iter().any(|arg| arg.contains(['%', '!'])) {
        return Err(anyhow!(
            "E_EXEC_BAD_ARG: percent and delayed-expansion tokens are not accepted for batch argv"
        ));
    }
    let mut tokens = Vec::with_capacity(args.len() + 1);
    tokens.push(quote_cmd_token(&script.to_string_lossy()));
    tokens.extend(args.iter().map(|arg| quote_cmd_token(arg)));
    Ok(format!("\"{}\"", tokens.join(" ")))
}

#[cfg(windows)]
fn quote_cmd_token(value: &str) -> String {
    let escaped = value.replace('"', "\"\"");
    format!("\"{escaped}\"")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_control_characters_before_resolution() {
        let result = resolve_process_command(&["tool\nname".into()], Path::new("."), None);
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("forbidden control"));
    }

    #[cfg(windows)]
    #[test]
    fn resolves_pathext_case_insensitively() {
        let root =
            std::env::temp_dir().join(format!("verseshell-resolve-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let executable = root.join("sample.CMD");
        std::fs::write(&executable, "@echo ok\r\n").unwrap();
        let env = BTreeMap::from([
            ("Path".into(), root.to_string_lossy().to_string()),
            ("PathExt".into(), ".EXE;.CMD".into()),
            ("SystemRoot".into(), std::env::var("SystemRoot").unwrap()),
        ]);
        let resolved = resolve_process_command(&["sample".into()], &root, Some(&env)).unwrap();
        assert_eq!(
            resolved.audited_executable,
            executable.canonicalize().unwrap()
        );
        assert!(resolved.interpreter.is_some());
        let _ = std::fs::remove_dir_all(root);
    }

    /// A bare name must not lose to an extensionless shim that sits next to it.
    ///
    /// npm-for-Windows ships `npm` (a `#!/bin/sh` script) beside `npm.cmd` in the
    /// same directory. Win32 cannot launch the former, and `cmd.exe` resolves a
    /// bare name through PATHEXT — so the launcher must too. Before this, `npm`
    /// resolved to the shell script and every `exec.run(["npm", ...])` failed with
    /// `E_EXEC_SPAWN` while raw shell (which spawns through `cmd`) worked.
    #[cfg(windows)]
    #[test]
    fn prefers_a_pathext_candidate_over_an_extensionless_shim() {
        let root =
            std::env::temp_dir().join(format!("verseshell-shadow-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("npm"), b"#!/bin/sh\nexec npm.cmd \"$@\"\n").unwrap();
        std::fs::write(root.join("npm.cmd"), b"@echo off\r\n").unwrap();
        let env = BTreeMap::from([
            ("Path".into(), root.to_string_lossy().to_string()),
            ("PathExt".into(), ".COM;.EXE;.BAT;.CMD".into()),
            ("SystemRoot".into(), std::env::var("SystemRoot").unwrap()),
        ]);
        let resolved = resolve_process_command(&["npm".into()], &root, Some(&env)).unwrap();
        assert_eq!(
            resolved.audited_executable,
            root.join("npm.cmd").canonicalize().unwrap()
        );
        assert!(
            resolved.interpreter.is_some(),
            "a .cmd candidate must launch through cmd.exe"
        );
        let _ = std::fs::remove_dir_all(root);
    }

    /// With no PATHEXT candidate the extensionless file is still the answer, so an
    /// unusual but launchable image without an extension keeps working.
    #[cfg(windows)]
    #[test]
    fn falls_back_to_an_extensionless_candidate() {
        let root =
            std::env::temp_dir().join(format!("verseshell-bare-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("tool"), b"not a real executable").unwrap();
        let env = BTreeMap::from([
            ("Path".into(), root.to_string_lossy().to_string()),
            ("PathExt".into(), ".EXE;.CMD".into()),
        ]);
        let resolved = resolve_process_command(&["tool".into()], &root, Some(&env)).unwrap();
        assert_eq!(resolved.executable, root.join("tool"));
        let _ = std::fs::remove_dir_all(root);
    }

    /// A name-dispatching shim must keep the name it was invoked as.
    ///
    /// This is the rustup case: `cargo.exe` / `rustc.exe` are symlinks to
    /// `rustup.exe`, and rustup picks the tool from the file name it was invoked
    /// by. The launcher must therefore hand the OS the shim path, not the
    /// canonicalised target — otherwise `cargo check` runs as plain `rustup`
    /// (observed as exit 100 with "0 error(s)" and as `cargo build` being read as
    /// the `+build` toolchain). Requires the symlink privilege, so it degrades to
    /// a no-op rather than failing when that is unavailable.
    #[cfg(windows)]
    #[test]
    fn keeps_a_dispatching_symlink_name_for_launch_but_audits_the_real_path() {
        let root =
            std::env::temp_dir().join(format!("verseshell-shim-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let real = root.join("real.exe");
        std::fs::write(&real, b"not a real executable").unwrap();
        let shim = root.join("dispatcher.exe");
        if std::os::windows::fs::symlink_file(&real, &shim).is_err() {
            let _ = std::fs::remove_dir_all(root);
            return; // symlink privilege not held; nothing to assert
        }
        let env = BTreeMap::from([
            ("Path".into(), root.to_string_lossy().to_string()),
            ("PathExt".into(), ".EXE".into()),
        ]);
        let resolved =
            resolve_process_command(&["dispatcher".into()], &root, Some(&env)).unwrap();

        // Launch path keeps the name the caller asked for ...
        assert_eq!(resolved.executable, shim);
        assert_eq!(
            resolved.executable.file_name().unwrap().to_string_lossy(),
            "dispatcher.exe"
        );
        // ... while the audit identity is the real binary.
        assert_eq!(
            resolved.audited_executable,
            real.canonicalize().unwrap()
        );
        let _ = std::fs::remove_dir_all(root);
    }

    /// A regular (non-symlink) executable is still launched by its resolved path.
    #[cfg(windows)]
    #[test]
    fn launches_a_plain_executable_by_its_resolved_path() {
        let root =
            std::env::temp_dir().join(format!("verseshell-plain-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let exe = root.join("plain.exe");
        std::fs::write(&exe, b"not a real executable").unwrap();
        let env = BTreeMap::from([
            ("Path".into(), root.to_string_lossy().to_string()),
            ("PathExt".into(), ".EXE".into()),
        ]);
        let resolved = resolve_process_command(&["plain".into()], &root, Some(&env)).unwrap();
        assert_eq!(resolved.executable, exe);
        assert_eq!(resolved.audited_executable, exe.canonicalize().unwrap());
        let _ = std::fs::remove_dir_all(root);
    }
}
