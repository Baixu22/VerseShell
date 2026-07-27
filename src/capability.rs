//! V2 Capability-based security model.
//!
//! Replaces implicit deny/allow rules with explicit capability declarations.
//! Each builtin declares required capabilities. Runtime enforces them before execution.
//!
//! Usage:
//!   ae --serve --cap file.read,file.write,net.http.get
//!   ae -c "file.read(\"data.txt\")" --cap file.read

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::str::FromStr;
use std::sync::RwLock;

// ── Capability ───────────────────────────────────────────────────────

/// Granular capability tokens. Each builtin requires one or more.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Capability {
    // ── System ──
    SysRead, // sys.cpu_info, sys.mem_info, sys.disk_info, sys.load_avg, sys.hostname, sys.os, sys.arch
    SysUptime, // sys.uptime (can leak process start time)
    SysEnv,  // sys.env_all, win.env_get

    // ── File System ──
    FileRead,   // file.read, file.ls, file.pwd, file.head, file.tail, file.grep
    FileWrite,  // file.write, file.append, file.mkdir
    FileDelete, // file.delete (destructive)
    FileLock,   // file.lock
    FileWatch,  // file.watch (future)

    // ── Network ──
    NetHttpGet,    // http.get
    NetHttpPost,   // http.post, http.put
    NetHttpDelete, // http.delete
    NetPing,       // net.ping
    NetDns,        // net.dns_lookup

    // ── Process ──
    ProcList,  // proc.list
    ProcKill,  // proc.kill, win.process_kill
    ProcSpawn, // proc.spawn
    ShellExec, // shell.exec, sh (PASSTHROUGH — HIGH RISK)

    // ── Windows ──
    WinRegistry, // win.registry_get
    WinService,  // win.service_list, win.service_status
    WinEnv,      // win.env_get, win.env_set
    WinAdmin,    // win.is_admin

    // ── Crypto ──
    CryptoHash,   // crypto.hash
    CryptoRandom, // crypto.random_bytes, crypto.uuid

    // ── Database ──
    DbRead,  // db.sqlite_query
    DbWrite, // db.sqlite_exec, db.sqlite_insert

    // ── Git ──
    GitRead,  // git.status, git.log, git.diff, git.branch
    GitWrite, // git.commit

    // ── Universal ──
    All, // Grants ALL capabilities (equivalent to --cap all)
}

impl Capability {
    /// Human-readable name string (e.g. `"sys.read"`, `"proc.kill"`).
    /// Used by `describe_capabilities` MCP tool to report granted caps.
    pub fn name_str(&self) -> &'static str {
        cap_name(self)
    }

    /// Human-readable description for CLI help / error messages.
    pub fn description(&self) -> &'static str {
        match self {
            Self::SysRead => "system info (cpu, mem, disk, os, arch)",
            Self::SysUptime => "system uptime",
            Self::SysEnv => "environment variables",
            Self::FileRead => "file read operations",
            Self::FileWrite => "file write operations",
            Self::FileDelete => "file deletion",
            Self::FileLock => "file locking",
            Self::FileWatch => "file watching",
            Self::NetHttpGet => "HTTP GET requests",
            Self::NetHttpPost => "HTTP POST/PUT requests",
            Self::NetHttpDelete => "HTTP DELETE requests",
            Self::NetPing => "network ping",
            Self::NetDns => "DNS lookups",
            Self::ProcList => "process listing",
            Self::ProcKill => "process termination",
            Self::ProcSpawn => "process spawning",
            Self::ShellExec => "shell command execution (HIGH RISK)",
            Self::WinRegistry => "Windows registry access",
            Self::WinService => "Windows service management",
            Self::WinEnv => "Windows environment variables",
            Self::WinAdmin => "admin privilege detection",
            Self::CryptoHash => "cryptographic hashing",
            Self::CryptoRandom => "random generation",
            Self::DbRead => "database read",
            Self::DbWrite => "database write",
            Self::GitRead => "git read operations",
            Self::GitWrite => "git write operations",
            Self::All => "ALL capabilities",
        }
    }

    /// Which builtins require this capability.
    pub fn covered_builtins(&self) -> &[&str] {
        match self {
            Self::SysRead => &[
                "sys_cpu_info",
                "sys_mem_info",
                "sys_disk_info",
                "sys_load_avg",
                "sys_hostname",
                "sys_os",
                "sys_arch",
                "sys_cpu_count",
                "sys_cpu_freq",
                "sys_swap_info",
                "sys_info",
                "sys_users",
                "sys_groups",
                "sys_user_info",
                "sys_boot_time",
                "sys_timezone",
                "sys_locale",
                "platform_os_version",
                "platform_arch",
                "platform_cpu",
                "platform_memory",
                "platform_disks",
                "platform_gpus",
                "platform_network_interfaces",
                "platform_hardware_summary",
                "platform_disk_usage",
                "hw_cpu",
                "hw_memory",
                "hw_disk",
                "hw_gpu",
                "hw_battery",
            ],
            Self::SysUptime => &["sys_uptime"],
            Self::SysEnv => &["sys_env_all", "win_env_get"],
            Self::FileRead => &[
                "cat",
                "read_text",
                "head",
                "tail",
                "grep",
                "find",
                "ls",
                "pwd",
                "file_exists",
                "fs_stat",
                "fs_walk",
                "fs_tree",
                "wc",
                "file_type",
                "file_diff",
                "fs_readlink",
                "fs_realpath",
                "fs_glob",
                "fs_df",
                "fs_du",
                "fs_mounts",
            ],
            Self::FileWrite => &[
                "file_write",
                "file_append",
                "file_mkdir",
                "file_copy",
                "file_move",
                "file_rename",
                "file_replace",
                "file_patch",
                "file_insert",
                "file_backup",
                "file_edit",
                "fs_mount",
                "fs_unmount",
                "fs_chmod",
                "fs_chown",
                "fs_link",
                "fs_symlink",
                "fs_tempfile",
                "fs_tempdir",
            ],
            Self::FileDelete => &["file_delete_lines", "fs_unmount"],
            Self::FileLock => &["file_lock"],
            Self::FileWatch => &["fs_watch", "fs_unwatch"],
            Self::NetHttpGet => &["http_get", "web_get", "web_fetch"],
            Self::NetHttpPost => &[
                "web_post",
                "web_json_post",
                "http_put",
                "web_form_submit",
                "web_upload_file",
            ],
            Self::NetHttpDelete => &["http_delete", "web_rest_api"],
            Self::NetPing => &["net_ping"],
            Self::NetDns => &["net_dns_lookup", "net_dns_reverse"],
            Self::ProcList => &[
                "proc_list",
                "proc_info",
                "proc_exists",
                "proc_children",
                "proc_parent",
                "proc_cpu_usage",
                "proc_mem_usage",
                "proc_threads",
                "proc_cwd",
                "proc_exe",
                "proc_cmdline",
                "proc_start_time",
                "proc_env",
            ],
            Self::ProcKill => &["proc_kill", "win_process_kill"],
            Self::ProcSpawn => &[
                "proc_spawn",
                "proc_resume",
                "proc_suspend",
                "proc_set_priority",
            ],
            Self::ShellExec => &["sh", "shell", "shell_exec"],
            Self::WinRegistry => &["win_registry_get"],
            Self::WinService => &["win_service_list", "win_service_status"],
            Self::WinEnv => &["win_env_get", "win_env_set"],
            Self::WinAdmin => &["win_is_admin"],
            Self::CryptoHash => &[
                "crypto_hash",
                "crypto_hash_file",
                "crypto_hmac",
                "crypto_checksum",
                "crypto_hex_encode",
                "crypto_hex_decode",
            ],
            Self::CryptoRandom => &["crypto_random_bytes", "crypto_uuid", "crypto_random_string"],
            Self::DbRead => &[
                "db_sqlite_query",
                "db_sqlite_schema",
                "db_sqlite_tables",
                "db_sqlite_count",
                "db_kv_get",
                "db_kv_keys",
            ],
            Self::DbWrite => &[
                "db_sqlite_open",
                "db_sqlite_exec",
                "db_sqlite_insert",
                "db_sqlite_update",
                "db_sqlite_delete",
                "db_sqlite_create_table",
                "db_sqlite_drop_table",
                "db_sqlite_dump",
                "db_sqlite_backup",
                "db_sqlite_vacuum",
                "db_kv_set",
                "db_kv_delete",
            ],
            Self::GitRead => &[
                "git_status",
                "git_log",
                "git_diff",
                "git_diff_staged",
                "git_branch",
                "git_branches",
                "git_show",
                "git_tags",
                "git_blame",
                "git_root",
                "git_rev_parse",
                "git_remote",
            ],
            Self::GitWrite => &[
                "git_commit",
                "git_add",
                "git_checkout",
                "git_merge",
                "git_rebase",
                "git_pull",
                "git_push",
                "git_stash",
                "git_stash_pop",
                "git_reset",
                "git_clean",
                "git_cherry_pick",
            ],
            Self::All => &[],
        }
    }
}

impl FromStr for Capability {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "sys.read" | "sys_read" => Ok(Self::SysRead),
            "sys.uptime" | "sys_uptime" => Ok(Self::SysUptime),
            "sys.env" | "sys_env" => Ok(Self::SysEnv),
            "file.read" | "file_read" => Ok(Self::FileRead),
            "file.write" | "file_write" => Ok(Self::FileWrite),
            "file.delete" | "file_delete" => Ok(Self::FileDelete),
            "file.lock" | "file_lock" => Ok(Self::FileLock),
            "file.watch" | "file_watch" => Ok(Self::FileWatch),
            "net.http.get" | "net_http_get" => Ok(Self::NetHttpGet),
            "net.http.post" | "net_http_post" => Ok(Self::NetHttpPost),
            "net.http.delete" | "net_http_delete" => Ok(Self::NetHttpDelete),
            "net.ping" | "net_ping" => Ok(Self::NetPing),
            "net.dns" | "net_dns" => Ok(Self::NetDns),
            "proc.list" | "proc_list" => Ok(Self::ProcList),
            "proc.kill" | "proc_kill" => Ok(Self::ProcKill),
            "proc.spawn" | "proc_spawn" => Ok(Self::ProcSpawn),
            "shell.exec" | "shell_exec" => Ok(Self::ShellExec),
            "win.registry" | "win_registry" => Ok(Self::WinRegistry),
            "win.service" | "win_service" => Ok(Self::WinService),
            "win.env" | "win_env" => Ok(Self::WinEnv),
            "win.admin" | "win_admin" => Ok(Self::WinAdmin),
            "crypto.hash" | "crypto_hash" => Ok(Self::CryptoHash),
            "crypto.random" | "crypto_random" => Ok(Self::CryptoRandom),
            "db.read" | "db_read" => Ok(Self::DbRead),
            "db.write" | "db_write" => Ok(Self::DbWrite),
            "git.read" | "git_read" => Ok(Self::GitRead),
            "git.write" | "git_write" => Ok(Self::GitWrite),
            "all" | "*" => Ok(Self::All),
            other => Err(format!("unknown capability: '{}'. Valid: sys.read, file.read, file.write, net.http.get, proc.list, shell.exec, win.registry, crypto.hash, db.read, git.read, all", other)),
        }
    }
}

// ── Capability Set ───────────────────────────────────────────────────

/// A set of granted capabilities with runtime enforcement.
#[derive(Debug, Clone, Default)]
pub struct CapabilitySet {
    granted: HashSet<Capability>,
    mode: CapabilityMode,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapabilityMode {
    /// Only capabilities in the set are allowed (default).
    AllowList,
    /// All capabilities except those in the deny set are allowed (agent mode override).
    DenyList,
}

impl Default for CapabilityMode {
    fn default() -> Self {
        Self::AllowList
    }
}

impl CapabilitySet {
    /// Create a new capability set from a comma-separated string.
    pub fn parse(input: &str, mode: CapabilityMode) -> Result<Self, String> {
        if input == "all" || input == "*" {
            let mut set = Self {
                granted: HashSet::new(),
                mode,
            };
            set.grant(Capability::All);
            return Ok(set);
        }
        let mut caps = Self {
            granted: HashSet::new(),
            mode,
        };
        for part in input.split(',') {
            let part = part.trim();
            if part.is_empty() {
                continue;
            }
            let cap: Capability = part.parse()?;
            caps.grant(cap);
        }
        Ok(caps)
    }

    /// Grant a capability.
    pub fn grant(&mut self, cap: Capability) {
        if cap == Capability::All {
            // Add all individual capabilities
            self.grant(Capability::SysRead);
            self.grant(Capability::SysUptime);
            self.grant(Capability::SysEnv);
            self.grant(Capability::FileRead);
            self.grant(Capability::FileWrite);
            self.grant(Capability::FileDelete);
            self.grant(Capability::FileLock);
            self.grant(Capability::FileWatch);
            self.grant(Capability::NetHttpGet);
            self.grant(Capability::NetHttpPost);
            self.grant(Capability::NetHttpDelete);
            self.grant(Capability::NetPing);
            self.grant(Capability::NetDns);
            self.grant(Capability::ProcList);
            self.grant(Capability::ProcKill);
            self.grant(Capability::ProcSpawn);
            self.grant(Capability::ShellExec);
            self.grant(Capability::WinRegistry);
            self.grant(Capability::WinService);
            self.grant(Capability::WinEnv);
            self.grant(Capability::WinAdmin);
            self.grant(Capability::CryptoHash);
            self.grant(Capability::CryptoRandom);
            self.grant(Capability::DbRead);
            self.grant(Capability::DbWrite);
            self.grant(Capability::GitRead);
            self.grant(Capability::GitWrite);
        } else {
            self.granted.insert(cap);
        }
    }

    /// Check if a builtin is allowed given the current capability set.
    pub fn check(&self, builtin_name: &str) -> CapabilityResult {
        // Safe-by-default functions that never need capabilities
        if matches!(
            builtin_name,
            "abs"
                | "min"
                | "max"
                | "floor"
                | "ceil"
                | "round"
                | "sqrt"
                | "pow"
                | "sin"
                | "cos"
                | "log"
                | "sum"
                | "mean"
                | "upper"
                | "lower"
                | "trim"
                | "split"
                | "replace"
                | "contains"
                | "starts_with"
                | "ends_with"
                | "len"
                | "length"
                | "slice"
                | "join"
                | "range"
                | "flatten"
                | "unique"
                | "sort"
                | "reverse"
                | "zip"
                | "concat"
                | "in"
                | "first"
                | "last"
                | "any"
                | "all"
                | "take"
                | "map"
                | "where"
                | "filter"
                | "reduce"
                | "each"
                | "keys"
                | "values"
                | "group_by"
                | "select"
                | "json_parse"
                | "json_stringify"
                | "echo"
                | "print"
                | "help"
                | "describe"
                | "typeof"
                | "type_of"
                | "now"
                | "sleep"
                | "exit"
                | "pwd"
                | "which"
                | "clear"
                | "call"
                | "null"
                | "true"
                | "false"
        ) {
            return CapabilityResult::Allow;
        }

        match self.mode {
            CapabilityMode::AllowList => {
                if self.granted.is_empty() {
                    // Nothing granted — only safe functions allowed
                    return CapabilityResult::Deny(format!(
                        "no capabilities granted; '{}' requires explicit capability. Use --cap to grant.",
                        builtin_name
                    ));
                }
                // Check against granted set
                // Find which capability covers this builtin
                let all_caps = [
                    Capability::SysRead,
                    Capability::SysUptime,
                    Capability::SysEnv,
                    Capability::FileRead,
                    Capability::FileWrite,
                    Capability::FileDelete,
                    Capability::FileLock,
                    Capability::FileWatch,
                    Capability::NetHttpGet,
                    Capability::NetHttpPost,
                    Capability::NetHttpDelete,
                    Capability::NetPing,
                    Capability::NetDns,
                    Capability::ProcList,
                    Capability::ProcKill,
                    Capability::ProcSpawn,
                    Capability::ShellExec,
                    Capability::WinRegistry,
                    Capability::WinService,
                    Capability::WinEnv,
                    Capability::WinAdmin,
                    Capability::CryptoHash,
                    Capability::CryptoRandom,
                    Capability::DbRead,
                    Capability::DbWrite,
                    Capability::GitRead,
                    Capability::GitWrite,
                ];
                for cap in &all_caps {
                    if cap.covered_builtins().contains(&builtin_name) {
                        if self.granted.contains(cap) {
                            return CapabilityResult::Allow;
                        } else {
                            return CapabilityResult::Deny(format!(
                                "builtin '{}' requires capability '{}' ({})",
                                builtin_name,
                                cap_name(cap),
                                cap.description()
                            ));
                        }
                    }
                }
                // Unknown builtin — allow by default
                CapabilityResult::Allow
            }
            CapabilityMode::DenyList => {
                // In deny-list mode, check if any capability explicitly denies this builtin
                // For now, deny-list mode is equivalent to allow-all minus explicit denies
                CapabilityResult::Allow
            }
        }
    }

    pub fn is_empty(&self) -> bool {
        self.granted.is_empty() && self.mode == CapabilityMode::AllowList
    }

    /// Return the list of granted capability names as strings
    /// (e.g. `["file.read", "proc.kill"]`), sorted alphabetically.
    /// Used by the `describe_capabilities` MCP tool.
    pub fn granted_caps_as_strings(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .granted
            .iter()
            .map(|c| c.name_str().to_string())
            .collect();
        names.sort();
        names
    }

    /// Return the current mode as a string label.
    pub fn mode_str(&self) -> &'static str {
        match self.mode {
            CapabilityMode::AllowList => "allow_list",
            CapabilityMode::DenyList => "deny_list",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum CapabilityResult {
    Allow,
    Deny(String), // reason for denial
}

fn cap_name(cap: &Capability) -> &'static str {
    match cap {
        Capability::SysRead => "sys.read",
        Capability::SysUptime => "sys.uptime",
        Capability::SysEnv => "sys.env",
        Capability::FileRead => "file.read",
        Capability::FileWrite => "file.write",
        Capability::FileDelete => "file.delete",
        Capability::FileLock => "file.lock",
        Capability::FileWatch => "file.watch",
        Capability::NetHttpGet => "net.http.get",
        Capability::NetHttpPost => "net.http.post",
        Capability::NetHttpDelete => "net.http.delete",
        Capability::NetPing => "net.ping",
        Capability::NetDns => "net.dns",
        Capability::ProcList => "proc.list",
        Capability::ProcKill => "proc.kill",
        Capability::ProcSpawn => "proc.spawn",
        Capability::ShellExec => "shell.exec",
        Capability::WinRegistry => "win.registry",
        Capability::WinService => "win.service",
        Capability::WinEnv => "win.env",
        Capability::WinAdmin => "win.admin",
        Capability::CryptoHash => "crypto.hash",
        Capability::CryptoRandom => "crypto.random",
        Capability::DbRead => "db.read",
        Capability::DbWrite => "db.write",
        Capability::GitRead => "git.read",
        Capability::GitWrite => "git.write",
        Capability::All => "all",
    }
}

// ── Global Capability State ──────────────────────────────────────────

lazy_static::lazy_static! {
    static ref GLOBAL_CAPS: RwLock<GlobalCapabilityState> =
        RwLock::new(GlobalCapabilityState::Uninitialized);
}

#[derive(Debug, Clone)]
enum GlobalCapabilityState {
    /// No production policy has been installed yet. Capability-gated calls fail closed.
    Uninitialized,
    /// An explicit allow-list, including an intentionally empty list.
    Enforced(CapabilitySet),
    /// Compatibility behavior for an explicitly human/legacy CLI entry point.
    LegacyUnrestricted,
}

/// Initialize an enforced capability allow-list from the environment or CLI.
/// An absent or empty value is an explicit deny-by-default policy.
pub fn init_caps(caps_str: Option<&str>) {
    let caps_str = caps_str
        .map(str::to_owned)
        .or_else(|| std::env::var("AETHER_CAPS").ok())
        .unwrap_or_default();
    let caps = CapabilitySet::parse(&caps_str, CapabilityMode::AllowList)
        .unwrap_or_else(|_| CapabilitySet::default());
    *GLOBAL_CAPS.write().unwrap() = GlobalCapabilityState::Enforced(caps);
}

/// Preserve the historical unrestricted behavior only for explicit human and
/// legacy CLI paths. Agent and server entry points must call [`init_caps`].
pub fn init_caps_legacy(caps_str: Option<&str>) {
    let configured = caps_str
        .map(str::to_owned)
        .or_else(|| std::env::var("AETHER_CAPS").ok());
    let state = match configured {
        Some(value) => CapabilitySet::parse(&value, CapabilityMode::AllowList)
            .map(GlobalCapabilityState::Enforced)
            .unwrap_or_else(|_| GlobalCapabilityState::Enforced(CapabilitySet::default())),
        None => GlobalCapabilityState::LegacyUnrestricted,
    };
    *GLOBAL_CAPS.write().unwrap() = state;
}

/// Check a builtin against the current capability state. Both an uninitialized
/// production surface and an explicitly empty allow-list deny gated calls.
pub fn check_capability(builtin_name: &str) -> CapabilityResult {
    let state = GLOBAL_CAPS.read().unwrap();
    match &*state {
        GlobalCapabilityState::LegacyUnrestricted => CapabilityResult::Allow,
        GlobalCapabilityState::Enforced(caps) => caps.check(builtin_name),
        GlobalCapabilityState::Uninitialized => match CapabilitySet::default().check(builtin_name) {
            CapabilityResult::Allow => CapabilityResult::Allow,
            CapabilityResult::Deny(_) => CapabilityResult::Deny(format!(
                "capability state is uninitialized; '{builtin_name}' is denied until an explicit allow-list is installed"
            )),
        },
    }
}

/// Return the explicitly granted capability names, sorted alphabetically.
pub fn current_capabilities() -> Vec<String> {
    let state = GLOBAL_CAPS.read().unwrap();
    match &*state {
        GlobalCapabilityState::Enforced(caps) => caps.granted_caps_as_strings(),
        GlobalCapabilityState::Uninitialized | GlobalCapabilityState::LegacyUnrestricted => {
            Vec::new()
        }
    }
}

/// Return a stable capability-policy label for handshakes and diagnostics.
pub fn current_mode_str() -> &'static str {
    let state = GLOBAL_CAPS.read().unwrap();
    match &*state {
        GlobalCapabilityState::Uninitialized => "uninitialized_deny",
        GlobalCapabilityState::Enforced(caps) => caps.mode_str(),
        GlobalCapabilityState::LegacyUnrestricted => "legacy_unrestricted",
    }
}

/// Return true only for an explicitly enforced empty allow-list.
pub fn caps_is_empty() -> bool {
    let state = GLOBAL_CAPS.read().unwrap();
    matches!(&*state, GlobalCapabilityState::Enforced(caps) if caps.is_empty())
}

/// Whether compatibility mode intentionally grants every capability.
pub fn is_unrestricted() -> bool {
    matches!(
        &*GLOBAL_CAPS.read().unwrap(),
        GlobalCapabilityState::LegacyUnrestricted
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_capabilities() {
        let caps = CapabilitySet::parse("file.read,file.write", CapabilityMode::AllowList).unwrap();
        assert_eq!(caps.check("cat"), CapabilityResult::Allow);
        assert!(matches!(caps.check("file_write"), CapabilityResult::Allow));
        assert!(matches!(
            caps.check("file_delete_lines"),
            CapabilityResult::Deny(_)
        ));
    }

    #[test]
    fn test_safe_by_default() {
        let caps = CapabilitySet::default();
        assert_eq!(caps.check("abs"), CapabilityResult::Allow);
        assert_eq!(caps.check("map"), CapabilityResult::Allow);
        assert_eq!(caps.check("json_parse"), CapabilityResult::Allow);
    }

    #[test]
    fn test_file_read_requires_cap() {
        let caps = CapabilitySet::default();
        let r = caps.check("cat");
        assert!(
            matches!(r, CapabilityResult::Deny(_)),
            "cat should require capability"
        );
    }

    #[test]
    fn test_all_grant() {
        let mut caps = CapabilitySet::default();
        caps.grant(Capability::All);
        assert_eq!(caps.check("cat"), CapabilityResult::Allow);
        assert_eq!(caps.check("file_write"), CapabilityResult::Allow);
        assert_eq!(caps.check("http_get"), CapabilityResult::Allow);
    }

    #[test]
    fn test_parse_allows_dots_and_underscores() {
        assert!("file.read".parse::<Capability>().is_ok());
        assert!("file_read".parse::<Capability>().is_ok());
    }
}
