//! Module system for aeshell builtins.
//!
//! This module provides namespaced access to builtin functions.

use crate::value::{BuiltinRef, Value};
use std::collections::BTreeMap;

pub fn builtin_ref(name: &str) -> Value {
    Value::Builtin(BuiltinRef {
        name: name.to_string(),
    })
}

fn module(functions: &[(&str, &str)]) -> Value {
    let mut map = BTreeMap::new();
    for (fn_name, builtin_name) in functions {
        map.insert(fn_name.to_string(), builtin_ref(builtin_name));
    }
    Value::Record(map)
}

// ── Module Tables (static, for compile-time resolution) ─────────────
//
// Each module's method→builtin mapping is defined as a const table so that
// `resolve_module_builtin` can look up the actual builtin name at compile
// time without allocating a `Value::Record`. This is used by `IRCompiler`
// to lower `sys.cpu_info()` → `IRNode::Builtin("sys_cpu_info", ...)`,
// which ensures:
//   1. Capability enforcement applies to module-access calls (security)
//   2. dry_run preflight analysis detects module-access effects
//   3. Execution traces label module-access calls as Builtin nodes

const SYS_MODULE: &[(&str, &str)] = &[
    ("info", "sys_info"),
    ("hostname", "sys_hostname"),
    ("os", "sys_os"),
    ("arch", "sys_arch"),
    ("kernel", "sys_kernel"),
    ("uptime", "sys_uptime"),
    ("boot_time", "sys_boot_time"),
    ("cpu_info", "sys_cpu_info"),
    ("cpu_count", "sys_cpu_count"),
    ("cpu_freq", "sys_cpu_freq"),
    ("mem_info", "sys_mem_info"),
    ("swap_info", "sys_swap_info"),
    ("disk_info", "sys_disk_info"),
    ("load_avg", "sys_load_avg"),
    ("users", "sys_users"),
    ("groups", "sys_groups"),
    ("user_info", "sys_user_info"),
    ("env_all", "sys_env_all"),
    ("locale", "sys_locale"),
    ("timezone", "sys_timezone"),
    ("describe", "describe"),
    ("audit_log", "sys_audit_log"),
    ("process_info", "sys_process_info"),
];

const PROC_MODULE: &[(&str, &str)] = &[
    ("list", "proc_list"),
    ("kill", "proc_kill"),
    ("info", "proc_info"),
    ("spawn", "proc_spawn"),
    ("wait", "proc_wait"),
    ("exists", "proc_exists"),
    ("children", "proc_children"),
    ("parent", "proc_parent"),
    ("priority", "proc_priority"),
    ("set_priority", "proc_set_priority"),
    ("cpu_usage", "proc_cpu_usage"),
    ("mem_usage", "proc_mem_usage"),
    ("threads", "proc_threads"),
    ("env", "proc_env"),
    ("cwd", "proc_cwd"),
    ("exe", "proc_exe"),
    ("cmdline", "proc_cmdline"),
    ("start_time", "proc_start_time"),
    ("suspend", "proc_suspend"),
    ("resume", "proc_resume"),
];

const FS_MODULE: &[(&str, &str)] = &[
    ("stat", "fs_stat"),
    ("find", "find"),
    ("walk", "fs_walk"),
    ("tree", "fs_tree"),
    ("du", "fs_du"),
    ("free", "fs_df"),
    ("mounts", "fs_mounts"),
    ("type_of", "file_type"),
    ("read", "read_text"),
    ("write", "file_write"),
    ("append", "file_append"),
];

const FILE_MODULE: &[(&str, &str)] = &[
    ("ls", "ls"),
    ("pwd", "pwd"),
    ("read", "cat"),
    ("stat", "fs_stat"),
    ("write", "file_write"),
    ("append", "file_append"),
    ("exists", "file_exists"),
    ("copy", "file_copy"),
    ("move", "file_move"),
    ("rename", "file_rename"),
    ("replace", "file_replace"),
    ("patch", "file_patch"),
    ("insert", "file_insert"),
    ("backup", "file_backup"),
    ("mkdir", "file_mkdir"),
    ("type", "file_type"),
    ("diff", "file_diff"),
    ("edit", "file_edit"),
    ("head", "head"),
    ("tail", "tail"),
    ("grep", "grep"),
    ("wc", "wc"),
    ("lock", "file_lock"),
];

const NET_MODULE: &[(&str, &str)] = &[
    ("interfaces", "net_interfaces"),
    ("ping", "net_ping"),
    ("dns_lookup", "net_dns_lookup"),
    ("ports", "net_ports"),
    ("connections", "net_connections"),
    ("route", "net_route"),
    ("arp", "net_arp"),
];

const HTTP_MODULE: &[(&str, &str)] = &[
    ("get", "http_get"),
    ("post", "web_post"),
    ("put", "http_put"),
    ("delete", "http_delete"),
    ("json_post", "web_json_post"),
];

const CRYPTO_MODULE: &[(&str, &str)] = &[
    ("uuid", "crypto_uuid"),
    ("hash", "crypto_hash"),
    ("random_bytes", "crypto_random_bytes"),
    ("base64_encode", "crypto_base64_encode"),
    ("base64_decode", "crypto_base64_decode"),
];

const DB_MODULE: &[(&str, &str)] = &[
    ("sqlite_open", "db_sqlite_open"),
    ("sqlite_query", "db_sqlite_query"),
];

const SVC_MODULE: &[(&str, &str)] = &[
    ("list", "svc_list"),
    ("info", "svc_info"),
    ("start", "svc_start"),
    ("stop", "svc_stop"),
    ("restart", "svc_restart"),
    ("enable", "svc_enable"),
    ("disable", "svc_disable"),
];

const CRON_MODULE: &[(&str, &str)] = &[
    ("list", "cron_list"),
    ("add", "cron_add"),
    ("remove", "cron_remove"),
];

const ARCHIVE_MODULE: &[(&str, &str)] = &[
    ("compress", "compress"),
    ("extract", "decompress"),
    ("tar_create", "tar_create"),
    ("tar_extract", "tar_extract"),
    ("zip_create", "zip_create"),
    ("zip_extract", "zip_extract"),
];

const USER_MODULE: &[(&str, &str)] = &[
    ("current", "whoami"),
    ("info", "sys_user_info"),
    ("list", "user_list"),
    ("groups", "sys_groups"),
];

const PERM_MODULE: &[(&str, &str)] = &[
    ("get", "perm_get"),
    ("set", "perm_set"),
    ("check", "perm_check"),
];

const PKG_MODULE: &[(&str, &str)] = &[
    ("list", "pkg_list"),
    ("search", "pkg_search"),
    ("info", "pkg_info"),
];

const HW_MODULE: &[(&str, &str)] = &[
    ("cpu", "hw_cpu"),
    ("memory", "hw_memory"),
    ("disks", "hw_disk"),
    ("gpus", "hw_gpu"),
    ("battery", "hw_battery"),
];

const CLIP_MODULE: &[(&str, &str)] = &[("read", "clipboard_get"), ("write", "clipboard_set")];

const INPUT_MODULE: &[(&str, &str)] = &[
    ("read_line", "input_read_line"),
    ("read_char", "input_read_char"),
    ("read_password", "input_read_password"),
];

const MATH_MODULE: &[(&str, &str)] = &[
    ("abs", "abs"),
    ("min", "min"),
    ("max", "max"),
    ("floor", "floor"),
    ("ceil", "ceil"),
    ("round", "round"),
    ("sqrt", "sqrt"),
    ("pow", "pow"),
    ("sum", "sum"),
    ("mean", "mean"),
];

const STR_MODULE: &[(&str, &str)] = &[
    ("upper", "upper"),
    ("lower", "lower"),
    ("trim", "trim"),
    ("split", "split"),
    ("replace", "replace"),
    ("contains", "contains"),
    ("starts_with", "starts_with"),
    ("ends_with", "ends_with"),
    ("join", "join"),
    ("length", "len"),
    ("slice", "slice"),
];

const ARR_MODULE: &[(&str, &str)] = &[
    ("range", "range"),
    ("flatten", "flatten"),
    ("unique", "unique"),
    ("sort", "sort"),
    ("reverse", "reverse"),
    ("zip", "zip"),
    ("filter", "where"),
    ("where", "where"),
    ("reduce", "reduce"),
    ("each", "each"),
    ("take", "take"),
    ("first", "first"),
    ("last", "last"),
    ("any", "any"),
    ("all", "all"),
    ("group_by", "group_by"),
    ("keys", "keys"),
    ("values", "values"),
    ("concat", "concat"),
    ("in", "in"),
    ("select", "select"),
    ("uniq", "uniq"),
    ("par_map", "par_map"),
];

const WIN_MODULE: &[(&str, &str)] = &[
    ("registry_get", "win_registry_get"),
    ("service_list", "win_service_list"),
    ("service_status", "win_service_status"),
    ("env_path", "win_env_path"),
    ("snapshot", "win_snapshot"),
    ("is_admin", "win_is_admin"),
    ("shortcut_resolve", "win_shortcut_resolve"),
    ("process_kill", "win_process_kill"),
    ("env_get", "win_env_get"),
    ("env_set", "win_env_set"),
];

const JSON_MODULE: &[(&str, &str)] = &[("parse", "json_parse"), ("stringify", "json_stringify")];

const SHELL_MODULE: &[(&str, &str)] = &[
    ("exec", "sh"),
    ("sleep", "sleep"),
    ("exit", "exit"),
    ("echo", "echo"),
];

const GIT_MODULE: &[(&str, &str)] = &[
    ("status", "git_status"),
    ("branch", "git_branch"),
    ("commit", "git_commit"),
    ("log", "git_log"),
    ("diff", "git_diff"),
];

const PLATFORM_MODULE: &[(&str, &str)] = &[
    ("os", "platform_os_version"),
    ("arch", "platform_arch"),
    ("cpu", "platform_cpu"),
    ("memory", "platform_memory"),
    ("disks", "platform_disks"),
    ("disk_usage", "platform_disk_usage"),
    ("gpus", "platform_gpus"),
    ("network_interfaces", "platform_network_interfaces"),
    ("hardware_summary", "platform_hardware_summary"),
];

/// Resolve a `module.method` access to the actual builtin name.
///
/// Used by `IRCompiler` to lower `sys.cpu_info()` →
/// `IRNode::Builtin("sys_cpu_info", ..., IREffect::for_builtin("sys_cpu_info"))`.
/// This ensures module-access calls go through the `Builtin` IR path, which:
///   1. Enforces capability checks (security)
///   2. Appears in `dry_run` preflight analysis (observability)
///   3. Appears in execution traces as a `Builtin` node (observability)
///
/// Returns `None` if the module or method is unknown — the caller should
/// then fall back to the generic `Call(MemberAccess(...))` IR form.
pub fn resolve_module_builtin(module: &str, method: &str) -> Option<&'static str> {
    let table: &[(&str, &str)] = match module {
        "sys" => SYS_MODULE,
        "proc" => PROC_MODULE,
        "fs" => FS_MODULE,
        "file" => FILE_MODULE,
        "net" => NET_MODULE,
        "http" => HTTP_MODULE,
        "crypto" => CRYPTO_MODULE,
        "db" => DB_MODULE,
        "svc" => SVC_MODULE,
        "cron" => CRON_MODULE,
        "archive" => ARCHIVE_MODULE,
        "user" => USER_MODULE,
        "perm" => PERM_MODULE,
        "pkg" => PKG_MODULE,
        "hw" => HW_MODULE,
        "clip" => CLIP_MODULE,
        "input" => INPUT_MODULE,
        "math" => MATH_MODULE,
        "str" => STR_MODULE,
        "arr" => ARR_MODULE,
        "json" => JSON_MODULE,
        "shell" => SHELL_MODULE,
        "git" => GIT_MODULE,
        "platform" => PLATFORM_MODULE,
        "win" => WIN_MODULE,
        _ => return None,
    };
    table
        .iter()
        .find_map(|(m, b)| if *m == method { Some(*b) } else { None })
}

/// Check whether `name` is a known module (26 total).
pub fn is_module_name(name: &str) -> bool {
    matches!(
        name,
        "sys"
            | "proc"
            | "fs"
            | "file"
            | "net"
            | "http"
            | "crypto"
            | "db"
            | "svc"
            | "cron"
            | "archive"
            | "user"
            | "perm"
            | "pkg"
            | "hw"
            | "clip"
            | "input"
            | "math"
            | "str"
            | "arr"
            | "json"
            | "shell"
            | "git"
            | "platform"
            | "win"
    )
}

/// Return method names for a known module.
pub fn module_method_names(module: &str) -> Vec<&'static str> {
    let table: &[(&str, &str)] = match module {
        "sys" => SYS_MODULE,
        "proc" => PROC_MODULE,
        "fs" => FS_MODULE,
        "file" => FILE_MODULE,
        "net" => NET_MODULE,
        "http" => HTTP_MODULE,
        "crypto" => CRYPTO_MODULE,
        "db" => DB_MODULE,
        "svc" => SVC_MODULE,
        "cron" => CRON_MODULE,
        "archive" => ARCHIVE_MODULE,
        "user" => USER_MODULE,
        "perm" => PERM_MODULE,
        "pkg" => PKG_MODULE,
        "hw" => HW_MODULE,
        "clip" => CLIP_MODULE,
        "input" => INPUT_MODULE,
        "math" => MATH_MODULE,
        "str" => STR_MODULE,
        "arr" => ARR_MODULE,
        "json" => JSON_MODULE,
        "shell" => SHELL_MODULE,
        "git" => GIT_MODULE,
        "platform" => PLATFORM_MODULE,
        "win" => WIN_MODULE,
        _ => return Vec::new(),
    };
    table.iter().map(|(m, _)| *m).collect()
}

// ── Core Shell Modules ──────────────────────────────────────────────

pub fn sys_module() -> Value {
    module(SYS_MODULE)
}

pub fn proc_module() -> Value {
    module(PROC_MODULE)
}

pub fn fs_module() -> Value {
    module(FS_MODULE)
}

pub fn file_module() -> Value {
    module(FILE_MODULE)
}

pub fn net_module() -> Value {
    module(NET_MODULE)
}

pub fn http_module() -> Value {
    module(HTTP_MODULE)
}

pub fn crypto_module() -> Value {
    module(CRYPTO_MODULE)
}

pub fn db_module() -> Value {
    module(DB_MODULE)
}

pub fn svc_module() -> Value {
    module(SVC_MODULE)
}

pub fn cron_module() -> Value {
    module(CRON_MODULE)
}

pub fn archive_module() -> Value {
    module(ARCHIVE_MODULE)
}

pub fn user_module() -> Value {
    module(USER_MODULE)
}

pub fn perm_module() -> Value {
    module(PERM_MODULE)
}

pub fn pkg_module() -> Value {
    module(PKG_MODULE)
}

pub fn hw_module() -> Value {
    module(HW_MODULE)
}

pub fn clip_module() -> Value {
    module(CLIP_MODULE)
}

pub fn input_module() -> Value {
    module(INPUT_MODULE)
}

pub fn math_module() -> Value {
    module(MATH_MODULE)
}

pub fn str_module() -> Value {
    module(STR_MODULE)
}

pub fn arr_module() -> Value {
    module(ARR_MODULE)
}

pub fn win_module() -> Value {
    module(WIN_MODULE)
}

pub fn json_module() -> Value {
    module(JSON_MODULE)
}

pub fn shell_module() -> Value {
    module(SHELL_MODULE)
}

pub fn git_module() -> Value {
    module(GIT_MODULE)
}

pub fn platform_module() -> Value {
    module(PLATFORM_MODULE)
}

pub fn all_modules() -> Vec<(&'static str, Value)> {
    vec![
        ("sys", sys_module()),
        ("proc", proc_module()),
        ("fs", fs_module()),
        ("file", file_module()),
        ("net", net_module()),
        ("http", http_module()),
        ("crypto", crypto_module()),
        ("db", db_module()),
        ("svc", svc_module()),
        ("cron", cron_module()),
        ("archive", archive_module()),
        ("user", user_module()),
        ("perm", perm_module()),
        ("pkg", pkg_module()),
        ("hw", hw_module()),
        ("clip", clip_module()),
        ("input", input_module()),
        ("math", math_module()),
        ("str", str_module()),
        ("arr", arr_module()),
        ("json", json_module()),
        ("shell", shell_module()),
        ("git", git_module()),
        ("platform", platform_module()),
        ("win", win_module()),
    ]
}
