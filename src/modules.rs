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

// ── Core Shell Modules ──────────────────────────────────────────────

pub fn sys_module() -> Value {
    module(&[
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
    ])
}

pub fn proc_module() -> Value {
    module(&[
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
    ])
}

pub fn fs_module() -> Value {
    module(&[
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
    ])
}

pub fn file_module() -> Value {
    module(&[
        ("ls", "ls"),
        ("pwd", "pwd"),
        ("read", "cat"),
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
    ])
}

pub fn net_module() -> Value {
    module(&[
        ("interfaces", "net_interfaces"),
        ("ping", "net_ping"),
        ("dns_lookup", "net_dns_lookup"),
        ("ports", "net_ports"),
        ("connections", "net_connections"),
        ("route", "net_route"),
        ("arp", "net_arp"),
    ])
}

pub fn http_module() -> Value {
    module(&[
        ("get", "http_get"),
        ("post", "web_post"),
        ("put", "http_put"),
        ("delete", "http_delete"),
        ("json_post", "web_json_post"),
    ])
}

pub fn crypto_module() -> Value {
    module(&[
        ("uuid", "crypto_uuid"),
        ("hash", "crypto_hash"),
        ("random_bytes", "crypto_random_bytes"),
        ("base64_encode", "crypto_base64_encode"),
        ("base64_decode", "crypto_base64_decode"),
    ])
}

pub fn db_module() -> Value {
    module(&[
        ("sqlite_open", "db_sqlite_open"),
        ("sqlite_query", "db_sqlite_query"),
    ])
}

pub fn svc_module() -> Value {
    module(&[
        ("list", "svc_list"),
        ("info", "svc_info"),
        ("start", "svc_start"),
        ("stop", "svc_stop"),
        ("restart", "svc_restart"),
        ("enable", "svc_enable"),
        ("disable", "svc_disable"),
    ])
}

pub fn cron_module() -> Value {
    module(&[
        ("list", "cron_list"),
        ("add", "cron_add"),
        ("remove", "cron_remove"),
    ])
}

pub fn archive_module() -> Value {
    module(&[
        ("compress", "compress"),
        ("extract", "decompress"),
        ("tar_create", "tar_create"),
        ("tar_extract", "tar_extract"),
        ("zip_create", "zip_create"),
        ("zip_extract", "zip_extract"),
    ])
}

pub fn user_module() -> Value {
    module(&[
        ("current", "whoami"),
        ("info", "sys_user_info"),
        ("list", "user_list"),
        ("groups", "sys_groups"),
    ])
}

pub fn perm_module() -> Value {
    module(&[
        ("get", "perm_get"),
        ("set", "perm_set"),
        ("check", "perm_check"),
    ])
}

pub fn pkg_module() -> Value {
    module(&[
        ("list", "pkg_list"),
        ("search", "pkg_search"),
        ("info", "pkg_info"),
    ])
}

pub fn hw_module() -> Value {
    module(&[
        ("cpu", "hw_cpu"),
        ("memory", "hw_memory"),
        ("disks", "hw_disk"),
        ("gpus", "hw_gpu"),
        ("battery", "hw_battery"),
    ])
}

pub fn clip_module() -> Value {
    module(&[
        ("read", "clipboard_get"),
        ("write", "clipboard_set"),
    ])
}

pub fn input_module() -> Value {
    module(&[
        ("read_line", "input_read_line"),
        ("read_char", "input_read_char"),
        ("read_password", "input_read_password"),
    ])
}

pub fn math_module() -> Value {
    module(&[
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
    ])
}

pub fn str_module() -> Value {
    module(&[
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
    ])
}

pub fn arr_module() -> Value {
    module(&[
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
    ])
}

pub fn win_module() -> Value {
    module(&[
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
    ])
}

pub fn json_module() -> Value {
    module(&[
        ("parse", "json_parse"),
        ("stringify", "json_stringify"),
    ])
}

pub fn shell_module() -> Value {
    module(&[
        ("exec", "sh"),
        ("sleep", "sleep"),
        ("exit", "exit"),
        ("echo", "echo"),
    ])
}

pub fn git_module() -> Value {
    module(&[
        ("status", "git_status"),
        ("branch", "git_branch"),
        ("commit", "git_commit"),
        ("log", "git_log"),
        ("diff", "git_diff"),
    ])
}

pub fn platform_module() -> Value {
    module(&[
        ("os", "platform_os_version"),
        ("arch", "platform_arch"),
        ("cpu", "platform_cpu"),
        ("memory", "platform_memory"),
        ("disks", "platform_disks"),
        ("disk_usage", "platform_disk_usage"),
        ("gpus", "platform_gpus"),
        ("network_interfaces", "platform_network_interfaces"),
        ("hardware_summary", "platform_hardware_summary"),
    ])
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
