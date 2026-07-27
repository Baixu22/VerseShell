//! V2 Intermediate Representation (IR) layer.
//!
//! Canonical, hashable, optimizable representation between AST and execution.
//! All v2 execution paths compile AST → IR → optimized IR → executor.
//! The legacy AST path remains intact for backward compatibility.
//!
//! Architecture:
//!   parser → AST → IRCompiler → IR → IROptimizer → Executor
//!                          ↑               ↑
//!                     canonical         fusion/
//!                     hashable          constant-fold

use crate::ast::{BinOp, Expr, Stmt, UnOp};
use std::collections::BTreeMap;
use std::hash::{Hash, Hasher};

// ── IR Node ──────────────────────────────────────────────────────────

/// Canonical IR node. All AST nodes lower into these.
/// Designed for structural hashing (node identity = content identity).
#[derive(Debug, Clone, PartialEq)]
pub enum IRNode {
    // ── Values ──
    Unit,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),

    // ── Collections ──
    Array(Vec<IRNode>),
    Record(BTreeMap<String, IRNode>),

    // ── Computation ──
    /// Reference to a variable (symbolic binding)
    Var(String),
    /// Let binding: name, value, body
    Let(String, Box<IRNode>, Box<IRNode>),

    // ── Arithmetic/Logic ──
    Binary(Box<IRNode>, BinOp, Box<IRNode>),
    Unary(UnOp, Box<IRNode>),

    // ── Control Flow ──
    /// If condition, then_branch, else_branch
    If(Box<IRNode>, Box<IRNode>, Box<IRNode>),
    /// Match: scrutinee, [(pattern, guard, body)]
    Match(Box<IRNode>, Vec<MatchArm>),
    /// Try: body, error_var, catch_body
    Try(Box<IRNode>, Option<String>, Box<IRNode>),
    /// Throw an error
    Throw(Box<IRNode>),

    // ── Functions ──
    /// Lambda: params, body (AST Expr preserved for Value::Lambda compat)
    Lambda(Vec<String>, Box<crate::ast::Expr>),
    /// Function call: callee, arguments
    Call(Box<IRNode>, Vec<IRNode>),

    // ── Pipeline (v2 primary execution form) ──
    /// Pipeline: source | stage1 | stage2 | ...
    Pipeline(Vec<IRNode>),

    // ── Pipeline Stages (lowered forms) ──
    /// Map: (params, body expr) applied to each element
    Map(Vec<String>, Box<crate::ast::Expr>),
    /// Filter/Where: (params, predicate expr)
    Filter(Vec<String>, Box<crate::ast::Expr>),
    /// Sort: (key params, key expr optional)
    Sort(Option<(Vec<String>, Box<crate::ast::Expr>)>),
    /// Reduce: (acc_param, elem_param, body expr), accumulator initial value
    Reduce(Vec<String>, Box<crate::ast::Expr>, Box<IRNode>),
    /// Take first N: count IRNode
    Take(Box<IRNode>),

    // ── Fused Pipeline Stages ──
    /// map + map fused: single-pass double transform
    FusedMapMap(Box<IRNode>, Box<IRNode>),
    /// map + filter fused: transform then test in one pass
    FusedMapFilter(Box<IRNode>, Box<IRNode>),
    /// filter + map fused: test then transform in one pass
    FusedFilterMap(Box<IRNode>, Box<IRNode>),

    // ── Builtin (v3: carries IREffect for capability enforcement) ──
    Builtin(String, Vec<IRNode>, IREffect),

    // ── Member Access ──
    MemberAccess(Box<IRNode>, String),

    // ── Error ──
    Error(String, Option<String>),

    // ── Metadata ──
    Annotate(String, String, Box<IRNode>),
}

// ── IR Effect (v3 capability annotation) ─────────────────────────────

/// Capability effect required by an IR node.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum IREffect {
    Pure,
    SysRead,
    FileRead,
    FileWrite,
    FileDelete,
    NetHttpGet,
    NetHttpPost,
    NetHttpDelete,
    ProcList,
    ProcKill,
    ProcSpawn,
    ShellExec,
    WinRegistry,
    WinService,
    CryptoHash,
    CryptoRandom,
    DbRead,
    DbWrite,
    GitRead,
    GitWrite,
    Combined(Vec<IREffect>),
}

impl IREffect {
    pub fn merge(self, other: IREffect) -> IREffect {
        use IREffect::*;
        match (self, other) {
            (Pure, e) | (e, Pure) => e,
            (Combined(mut a), Combined(b)) => {
                a.extend(b);
                Combined(a)
            }
            (Combined(mut a), e) | (e, Combined(mut a)) => {
                a.push(e);
                Combined(a)
            }
            (a, b) if a == b => a,
            (a, b) => Combined(vec![a, b]),
        }
    }

    pub fn for_builtin(name: &str) -> IREffect {
        match name {
            "abs" | "min" | "max" | "floor" | "ceil" | "round" | "sqrt" | "pow" | "sum"
            | "mean" | "upper" | "lower" | "trim" | "split" | "replace" | "contains"
            | "starts_with" | "ends_with" | "len" | "length" | "slice" | "join" | "range"
            | "flatten" | "unique" | "sort" | "reverse" | "zip" | "concat" | "in" | "first"
            | "last" | "any" | "all" | "take" | "map" | "where" | "filter" | "reduce" | "each"
            | "keys" | "values" | "group_by" | "select" | "json_parse" | "json_stringify"
            | "echo" | "print" | "help" | "describe" | "typeof" | "type_of" | "now" | "sleep"
            | "exit" | "pwd" | "clear" | "par_map" | "uniq" | "which" | "call" => IREffect::Pure,

            "sys_cpu_info"
            | "sys_mem_info"
            | "sys_disk_info"
            | "sys_load_avg"
            | "sys_hostname"
            | "sys_os"
            | "sys_arch"
            | "sys_cpu_count"
            | "sys_swap_info"
            | "sys_info"
            | "sys_users"
            | "sys_groups"
            | "sys_user_info"
            | "sys_boot_time"
            | "sys_timezone"
            | "sys_locale"
            | "sys_kernel"
            | "sys_uptime"
            | "platform_arch"
            | "platform_os_version"
            | "platform_cpu"
            | "platform_memory"
            | "platform_disks"
            | "platform_gpus"
            | "platform_network_interfaces"
            | "platform_hardware_summary"
            | "hw_cpu"
            | "hw_memory"
            | "hw_disk"
            | "hw_gpu"
            | "hw_battery"
            | "sys_env_all"
            | "win_snapshot"
            | "win_env_path"
            | "win_env_get"
            | "win_is_admin" => IREffect::SysRead,

            "cat" | "read_text" | "head" | "tail" | "grep" | "find" | "ls" | "list"
            | "file_exists" | "fs_stat" | "fs_walk" | "fs_tree" | "fs_readlink" | "fs_realpath"
            | "fs_glob" | "fs_df" | "fs_du" | "fs_mounts" | "wc" | "file_type" | "file_diff" => {
                IREffect::FileRead
            }

            "file_write" | "file_append" | "file_mkdir" | "file_copy" | "file_move"
            | "file_rename" | "file_replace" | "file_patch" | "file_insert" | "file_backup"
            | "file_edit" | "fs_chmod" | "fs_chown" | "fs_link" | "fs_symlink" | "fs_tempfile"
            | "fs_tempdir" | "fs_mount" | "fs_unmount" => IREffect::FileWrite,

            "file_delete_lines" | "delete_lines" | "remove_lines" => IREffect::FileDelete,

            "http_get" | "web_get" | "web_fetch" => IREffect::NetHttpGet,
            "web_post" | "web_json_post" | "http_put" | "web_form_submit" | "web_upload_file" => {
                IREffect::NetHttpPost
            }
            "http_delete" | "web_rest_api" => IREffect::NetHttpDelete,
            "net_ping" | "net_dns_lookup" | "net_dns_reverse" => IREffect::NetHttpGet,

            "proc_list" | "proc_info" | "proc_exists" | "proc_children" | "proc_parent"
            | "proc_cpu_usage" | "proc_mem_usage" | "proc_threads" | "proc_cwd" | "proc_exe"
            | "proc_cmdline" | "proc_start_time" | "proc_env" | "proc_wait" => IREffect::ProcList,
            "proc_kill" | "win_process_kill" => IREffect::ProcKill,
            "proc_spawn" | "proc_resume" | "proc_suspend" | "proc_set_priority" => {
                IREffect::ProcSpawn
            }
            "sh" | "shell" | "shell_exec" | "shell_which" => IREffect::ShellExec,

            "win_registry_get" => IREffect::WinRegistry,
            "win_service_list" | "win_service_status" => IREffect::WinService,
            "win_env_set" | "win_shortcut_resolve" => IREffect::SysRead,

            "crypto_hash" | "crypto_hash_file" | "crypto_hmac" | "crypto_checksum"
            | "crypto_hex_encode" | "crypto_hex_decode" | "sha256" | "md5" => IREffect::CryptoHash,
            "crypto_random_bytes" | "crypto_uuid" | "crypto_random_string" => {
                IREffect::CryptoRandom
            }

            "db_sqlite_query" | "db_sqlite_schema" | "db_sqlite_tables" | "db_sqlite_count"
            | "db_kv_get" | "db_kv_keys" | "db_sqlite_open" | "db_sqlite_close" => IREffect::DbRead,
            "db_sqlite_exec"
            | "db_sqlite_insert"
            | "db_sqlite_update"
            | "db_sqlite_delete"
            | "db_sqlite_create_table"
            | "db_sqlite_drop_table"
            | "db_sqlite_dump"
            | "db_kv_set"
            | "db_kv_delete" => IREffect::DbWrite,

            "git_status" | "git_log" | "git_diff" | "git_branch" | "git_branches" | "git_show"
            | "git_tags" | "git_blame" | "git_root" | "git_rev_parse" | "git_remote"
            | "git_fetch" | "git_diff_staged" => IREffect::GitRead,
            "git_commit" | "git_add" | "git_checkout" | "git_merge" | "git_rebase" | "git_pull"
            | "git_push" | "git_stash" | "git_stash_pop" | "git_reset" | "git_clean"
            | "git_cherry_pick" => IREffect::GitWrite,

            _ => IREffect::Pure,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct MatchArm {
    pub pattern: MatchPattern,
    pub guard: Option<Box<IRNode>>,
    pub body: Box<IRNode>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum MatchPattern {
    Wildcard,
    Literal(IRNode),
    Binding(String),
    Or(Vec<MatchPattern>),
}

// ── IR Hash (structural) ────────────────────────────────────────────

/// Structural hash of an IR node. Identical IR trees produce identical hashes.
/// Used for cache keys, deduplication, and deterministic replay.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct IRHash(u64);

impl IRHash {
    pub fn compute(node: &IRNode) -> Self {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        hash_node(node, &mut hasher);
        IRHash(hasher.finish())
    }
}

fn hash_node<H: Hasher>(node: &IRNode, h: &mut H) {
    use IRNode::*;
    // Tag each variant for disambiguation
    match node {
        Unit => 0u8.hash(h),
        Bool(b) => {
            1u8.hash(h);
            b.hash(h);
        }
        Int(n) => {
            2u8.hash(h);
            n.hash(h);
        }
        Float(f) => {
            3u8.hash(h);
            f.to_bits().hash(h);
        }
        Str(s) => {
            4u8.hash(h);
            s.hash(h);
        }
        Array(items) => {
            5u8.hash(h);
            for i in items {
                hash_node(i, h);
            }
        }
        Record(map) => {
            6u8.hash(h);
            for (k, v) in map {
                k.hash(h);
                hash_node(v, h);
            }
        }
        Var(name) => {
            7u8.hash(h);
            name.hash(h);
        }
        Let(name, val, body) => {
            8u8.hash(h);
            name.hash(h);
            hash_node(val, h);
            hash_node(body, h);
        }
        Binary(l, op, r) => {
            9u8.hash(h);
            hash_node(l, h);
            format!("{:?}", op).hash(h);
            hash_node(r, h);
        }
        Unary(op, e) => {
            10u8.hash(h);
            format!("{:?}", op).hash(h);
            hash_node(e, h);
        }
        If(cond, t, f) => {
            11u8.hash(h);
            hash_node(cond, h);
            hash_node(t, h);
            hash_node(f, h);
        }
        Match(scrut, arms) => {
            12u8.hash(h);
            hash_node(scrut, h);
            for arm in arms {
                hash_node(&arm.body, h);
            }
        }
        Try(body, var, catch) => {
            13u8.hash(h);
            hash_node(body, h);
            var.hash(h);
            hash_node(catch, h);
        }
        Throw(e) => {
            14u8.hash(h);
            hash_node(e, h);
        }
        Lambda(params, body) => {
            15u8.hash(h);
            params.hash(h);
            format!("{:?}", body).hash(h);
        }
        Call(callee, args) => {
            16u8.hash(h);
            hash_node(callee, h);
            for a in args {
                hash_node(a, h);
            }
        }
        Pipeline(stages) => {
            17u8.hash(h);
            for s in stages {
                hash_node(s, h);
            }
        }
        Map(params, body) => {
            18u8.hash(h);
            params.hash(h);
            format!("{:?}", body).hash(h);
        }
        Filter(params, pred) => {
            19u8.hash(h);
            params.hash(h);
            format!("{:?}", pred).hash(h);
        }
        Sort(key) => {
            20u8.hash(h);
            if let Some((_, k)) = key {
                format!("{:?}", k).hash(h);
            }
        }
        Reduce(params, body, init) => {
            21u8.hash(h);
            params.hash(h);
            format!("{:?}", body).hash(h);
            hash_node(init, h);
        }
        Take(n) => {
            22u8.hash(h);
            hash_node(n, h);
        }
        FusedMapMap(a, b) => {
            27u8.hash(h);
            hash_node(a, h);
            hash_node(b, h);
        }
        FusedMapFilter(a, b) => {
            28u8.hash(h);
            hash_node(a, h);
            hash_node(b, h);
        }
        FusedFilterMap(a, b) => {
            29u8.hash(h);
            hash_node(a, h);
            hash_node(b, h);
        }
        Builtin(name, args, _eff) => {
            23u8.hash(h);
            name.hash(h);
            for a in args {
                hash_node(a, h);
            }
        }
        MemberAccess(obj, field) => {
            24u8.hash(h);
            hash_node(obj, h);
            field.hash(h);
        }
        Error(code, msg) => {
            25u8.hash(h);
            code.hash(h);
            msg.hash(h);
        }
        Annotate(key, val, inner) => {
            26u8.hash(h);
            key.hash(h);
            val.hash(h);
            hash_node(inner, h);
        }
    }
}

// ── IR Optimizer ─────────────────────────────────────────────────────

/// Optimization passes applied to IR trees.
pub struct IROptimizer {
    pub fold_constants: bool,
    pub fuse_pipelines: bool,
    pub fuse_map_filter: bool,
    pub dead_code_elimination: bool,
}

impl Default for IROptimizer {
    fn default() -> Self {
        Self {
            fold_constants: true,
            fuse_pipelines: true,
            fuse_map_filter: true,
            dead_code_elimination: false,
        }
    }
}

impl IROptimizer {
    /// Run all enabled optimization passes on an IR node.
    pub fn optimize(&self, node: IRNode) -> IRNode {
        let mut node = node;
        if self.fold_constants {
            node = self.constant_fold(node);
        }
        if self.fuse_pipelines {
            node = self.fuse_pipeline_stages(node);
        }
        if self.fuse_map_filter {
            node = self.fuse_map_filter_chain(node);
        }
        node
    }

    /// Constant folding: evaluate constant sub-expressions at compile time.
    fn constant_fold(&self, node: IRNode) -> IRNode {
        match node {
            IRNode::Binary(left, op, right) => {
                let l = self.constant_fold(*left);
                let r = self.constant_fold(*right);
                match (&l, &r) {
                    (IRNode::Int(a), IRNode::Int(b)) => match op {
                        BinOp::Add => IRNode::Int(a + b),
                        BinOp::Sub => IRNode::Int(a - b),
                        BinOp::Mul => IRNode::Int(a * b),
                        BinOp::Div => IRNode::Float(*a as f64 / *b as f64),
                        BinOp::Rem => IRNode::Int(a % b),
                        BinOp::Eq => IRNode::Bool(a == b),
                        BinOp::Ne => IRNode::Bool(a != b),
                        BinOp::Lt => IRNode::Bool(a < b),
                        BinOp::Lte => IRNode::Bool(a <= b),
                        BinOp::Gt => IRNode::Bool(a > b),
                        BinOp::Gte => IRNode::Bool(a >= b),
                        BinOp::Pow => {
                            if *b >= 0 {
                                IRNode::Int(a.pow(*b as u32))
                            } else {
                                IRNode::Float((*a as f64).powf(*b as f64))
                            }
                        }
                        _ => IRNode::Binary(Box::new(l), op, Box::new(r)),
                    },
                    (IRNode::Float(a), IRNode::Float(b)) => match op {
                        BinOp::Add => IRNode::Float(a + b),
                        BinOp::Sub => IRNode::Float(a - b),
                        BinOp::Mul => IRNode::Float(a * b),
                        BinOp::Div => IRNode::Float(a / b),
                        _ => IRNode::Binary(Box::new(l), op, Box::new(r)),
                    },
                    (IRNode::Str(a), IRNode::Str(b)) if op == BinOp::Add => {
                        IRNode::Str(format!("{}{}", a, b))
                    }
                    _ => IRNode::Binary(Box::new(l), op, Box::new(r)),
                }
            }
            IRNode::Unary(op, expr) => {
                let e = self.constant_fold(*expr);
                match (&e, &op) {
                    (IRNode::Int(n), UnOp::Neg) => IRNode::Int(-n),
                    (IRNode::Float(f), UnOp::Neg) => IRNode::Float(-f),
                    (IRNode::Bool(b), UnOp::Not) => IRNode::Bool(!b),
                    _ => IRNode::Unary(op, Box::new(e)),
                }
            }
            IRNode::Let(name, val, body) => IRNode::Let(
                name,
                Box::new(self.constant_fold(*val)),
                Box::new(self.constant_fold(*body)),
            ),
            IRNode::Pipeline(stages) => {
                IRNode::Pipeline(stages.into_iter().map(|s| self.constant_fold(s)).collect())
            }
            IRNode::Map(_, _)
            | IRNode::Filter(_, _)
            | IRNode::Sort(_)
            | IRNode::Take(_)
            | IRNode::Reduce(_, _, _) => {
                node // Pipeline stages pass through without constant folding
            }
            IRNode::Array(items) => {
                IRNode::Array(items.into_iter().map(|i| self.constant_fold(i)).collect())
            }
            IRNode::Record(map) => IRNode::Record(
                map.into_iter()
                    .map(|(k, v)| (k, self.constant_fold(v)))
                    .collect(),
            ),
            IRNode::Call(callee, args) => IRNode::Call(
                Box::new(self.constant_fold(*callee)),
                args.into_iter().map(|a| self.constant_fold(a)).collect(),
            ),
            other => other,
        }
    }

    /// Fuse consecutive Map/Filter/Sort stages in a pipeline.
    fn fuse_pipeline_stages(&self, node: IRNode) -> IRNode {
        match node {
            IRNode::Pipeline(stages) => {
                let mut fused: Vec<IRNode> = Vec::new();
                for stage in stages {
                    let stage = self.constant_fold(stage);
                    // Attempt to fuse with previous stage
                    if fused.is_empty() {
                        fused.push(stage);
                    } else {
                        let prev = fused.pop().unwrap();
                        fused.push(self.try_fuse(prev, stage));
                    }
                }
                IRNode::Pipeline(fused)
            }
            other => other,
        }
    }

    fn try_fuse(&self, a: IRNode, b: IRNode) -> IRNode {
        match (&a, &b) {
            (IRNode::Map(_, _), IRNode::Map(_, _)) => {
                // map + map → fused single map (compose lambdas)
                IRNode::FusedMapMap(Box::new(a), Box::new(b))
            }
            (IRNode::Map(_, _), IRNode::Filter(_, _)) => {
                // map + filter → fused: apply map then test filter in one pass
                IRNode::FusedMapFilter(Box::new(a), Box::new(b))
            }
            (IRNode::Filter(_, _), IRNode::Map(_, _)) => {
                // filter + map → fused: test filter then apply map in one pass
                IRNode::FusedFilterMap(Box::new(a), Box::new(b))
            }
            _ => IRNode::Pipeline(vec![a, b]),
        }
    }

    /// Detect map + filter chains that can fuse into a single iteration.
    fn fuse_map_filter_chain(&self, node: IRNode) -> IRNode {
        // Phase 1 implementation: identity transform.
        // Full map/filter fusion requires dataflow analysis.
        // We'll implement this in v2.1 with a proper dataflow graph.
        node
    }
}

// ── IR Compiler (AST → IR) ──────────────────────────────────────────

/// Check if a name is a builtin dispatched via the fallback match statement.
fn is_fallback_builtin(name: &str) -> bool {
    matches!(
        name,
        "Get-Files"
            | "get-files"
            | "Get-Content"
            | "get-content"
            | "select"
            | "select-object"
            | "Select-Object"
            | "where-object"
            | "Where-Object"
            | "foreach"
            | "ForEach-Object"
            | "foreach-object"
            | "sort-object"
            | "Sort-Object"
            | "group"
            | "group_by"
            | "Group-Object"
            | "group-object"
            | "measure"
            | "Measure-Object"
            | "measure-object"
            | "from-json"
            | "from_json"
            | "to-json"
            | "to_json"
            | "from-csv"
            | "from_csv"
            | "to-csv"
            | "to_csv"
            | "from-yaml"
            | "from_yaml"
            | "to-yaml"
            | "to_yaml"
            | "columns"
            | "describe"
    )
}

fn compile_pattern(pattern: &crate::ast::Pattern) -> MatchPattern {
    match pattern {
        crate::ast::Pattern::Wildcard => MatchPattern::Wildcard,
        crate::ast::Pattern::LitInt(n) => MatchPattern::Literal(IRNode::Int(*n)),
        crate::ast::Pattern::LitStr(s) => MatchPattern::Literal(IRNode::Str(s.clone())),
        crate::ast::Pattern::LitBool(b) => MatchPattern::Literal(IRNode::Bool(*b)),
        crate::ast::Pattern::Null => MatchPattern::Literal(IRNode::Unit),
        crate::ast::Pattern::Ident(name) => MatchPattern::Binding(name.clone()),
        _ => MatchPattern::Wildcard,
    }
}

/// Compiles AST (Stmt/Expr) into canonical IR.
pub struct IRCompiler {
    optimize: bool,
}

impl IRCompiler {
    pub fn new(optimize: bool) -> Self {
        Self { optimize }
    }

    /// Compile a program (list of statements) into IR.
    pub fn compile_program(&self, stmts: &[Stmt]) -> Vec<IRNode> {
        let mut ir = Vec::new();
        for stmt in stmts {
            ir.push(self.compile_stmt(stmt));
        }
        if self.optimize {
            let opt = IROptimizer::default();
            ir = ir.into_iter().map(|n| opt.optimize(n)).collect();
        }
        ir
    }

    fn compile_stmt(&self, stmt: &Stmt) -> IRNode {
        match stmt {
            Stmt::Let {
                name,
                value,
                is_mut: _,
                visibility: _,
            } => {
                let val_ir = self.compile_expr(value);
                // For single-let, use the Let IR node.
                // For multi-statement programs, the final IR is the sequence.
                IRNode::Let(name.clone(), Box::new(val_ir), Box::new(IRNode::Unit))
            }
            Stmt::Expr(expr) => self.compile_expr(expr),
            Stmt::Import { .. } => {
                IRNode::Error("E_IMPORT".into(), Some("import not supported in IR".into()))
            }
            Stmt::Export {
                items: _,
                from_source: _,
            } => IRNode::Unit,
            Stmt::Cfg { condition: _, body } => self.compile_stmt(body),
        }
    }

    fn compile_expr(&self, expr: &Expr) -> IRNode {
        match expr {
            Expr::LitInt(n) => IRNode::Int(*n),
            Expr::LitFloat(f) => IRNode::Float(*f),
            Expr::LitStr(s) => IRNode::Str(s.clone()),
            Expr::LitBool(b) => IRNode::Bool(*b),
            Expr::Null => IRNode::Unit,
            Expr::Ident(name) => IRNode::Var(name.clone()),
            Expr::Array(items) => {
                IRNode::Array(items.iter().map(|e| self.compile_expr(e)).collect())
            }
            Expr::Record(kvs) => IRNode::Record(
                kvs.iter()
                    .map(|(k, v)| (k.clone(), self.compile_expr(v)))
                    .collect(),
            ),
            Expr::Lambda { params, body } => IRNode::Lambda(params.clone(), body.clone()),
            Expr::AsyncLambda { params, body } => IRNode::Lambda(params.clone(), body.clone()),
            Expr::Await(inner) => self.compile_expr(inner),
            Expr::TryCatch {
                try_expr,
                catch_var,
                catch_expr,
            } => IRNode::Try(
                Box::new(self.compile_expr(try_expr)),
                catch_var.clone(),
                Box::new(self.compile_expr(catch_expr)),
            ),
            Expr::Throw(inner) => IRNode::Throw(Box::new(self.compile_expr(inner))),
            Expr::Call {
                callee,
                args,
                named: _,
            } => {
                let args_ir: Vec<IRNode> = args.iter().map(|a| self.compile_expr(a)).collect();

                // If callee is a simple identifier, keep as Builtin for dispatch
                if let Expr::Ident(name) = callee.as_ref() {
                    // Check if it's a known builtin — if not, treat as variable call
                    if crate::builtins::BUILTIN_LOOKUP.contains_key(name.as_str())
                        || is_fallback_builtin(name)
                    {
                        if let Some(pipeline_ir) = self.try_lower_builtin(name, &args_ir, None) {
                            return pipeline_ir;
                        }
                        IRNode::Builtin(name.clone(), args_ir, IREffect::for_builtin(name))
                    } else {
                        // User-defined functions live in Env. At evaluation time,
                        // an unresolved variable call falls back to builtin
                        // dispatch so typo hints remain available.
                        IRNode::Call(Box::new(IRNode::Var(name.clone())), args_ir)
                    }
                } else if let Expr::MemberAccess { object, field } = callee.as_ref() {
                    // Module-access call: `module.method(args)` (e.g., `sys.cpu_info()`)
                    // Lower to `IRNode::Builtin` so that:
                    //   1. Capability checks apply (security)
                    //   2. dry_run preflight analysis detects effects
                    //   3. Execution traces label these as Builtin nodes
                    if let Expr::Ident(mod_name) = object.as_ref() {
                        if let Some(builtin_name) =
                            crate::modules::resolve_module_builtin(mod_name, field)
                        {
                            return IRNode::Builtin(
                                builtin_name.to_string(),
                                args_ir,
                                IREffect::for_builtin(builtin_name),
                            );
                        }
                        // Known module, unknown method — produce a hint
                        if crate::modules::is_module_name(mod_name) {
                            let methods: Vec<String> =
                                crate::modules::module_method_names(mod_name)
                                    .iter()
                                    .map(|s| s.to_string())
                                    .collect();
                            let hint =
                                crate::builtins::nearest_method_hint(&methods, field, mod_name);
                            return IRNode::Error("E_UNKNOWN_BUILTIN".into(), Some(hint));
                        }
                    }
                    // Unknown module/method — fall through to generic Call form
                    let callee_ir = self.compile_expr(callee);
                    IRNode::Call(Box::new(callee_ir), args_ir)
                } else {
                    let callee_ir = self.compile_expr(callee);
                    IRNode::Call(Box::new(callee_ir), args_ir)
                }
            }
            Expr::Pipe { left, right } => {
                let left_ir = self.compile_expr(left);
                // If right is a builtin identifier, lower as pipeline stage
                if let Expr::Ident(name) = right.as_ref() {
                    if let Some(stage_ir) = self.try_lower_builtin(name, &[], Some(left_ir.clone()))
                    {
                        return stage_ir;
                    }
                    if crate::builtins::BUILTIN_LOOKUP.contains_key(name.as_str())
                        || is_fallback_builtin(name)
                    {
                        return IRNode::Pipeline(vec![
                            left_ir,
                            IRNode::Builtin(name.clone(), vec![], IREffect::for_builtin(name)),
                        ]);
                    }
                }
                // Pipeline call with arguments, e.g. `items | take 3`.
                if let Expr::Call {
                    callee,
                    args,
                    named: _,
                } = right.as_ref()
                {
                    if let Expr::Ident(name) = callee.as_ref() {
                        let args_ir: Vec<IRNode> =
                            args.iter().map(|arg| self.compile_expr(arg)).collect();
                        if let Some(stage_ir) =
                            self.try_lower_builtin(name, &args_ir, Some(left_ir.clone()))
                        {
                            return stage_ir;
                        }
                    }
                }
                // Generic pipeline
                let right_ir = self.compile_expr(right);
                // If already a Pipeline, extend it
                match left_ir {
                    IRNode::Pipeline(mut stages) => {
                        stages.push(right_ir);
                        IRNode::Pipeline(stages)
                    }
                    other => IRNode::Pipeline(vec![other, right_ir]),
                }
            }
            Expr::Binary { left, op, right } => {
                let l = self.compile_expr(left);
                let r = self.compile_expr(right);
                IRNode::Binary(Box::new(l), *op, Box::new(r))
            }
            Expr::Unary { op, expr } => IRNode::Unary(*op, Box::new(self.compile_expr(expr))),
            Expr::MemberAccess { object, field } => {
                IRNode::MemberAccess(Box::new(self.compile_expr(object)), field.clone())
            }
            Expr::Match { scrutinee, arms } => IRNode::Match(
                Box::new(self.compile_expr(scrutinee)),
                arms.iter()
                    .map(|arm| MatchArm {
                        pattern: compile_pattern(&arm.pattern),
                        guard: arm.guard.as_ref().map(|g| Box::new(self.compile_expr(g))),
                        body: Box::new(self.compile_expr(&arm.body)),
                    })
                    .collect(),
            ),
        }
    }

    /// Try to lower a builtin call into a specific IR pipeline stage.
    fn try_lower_builtin(
        &self,
        name: &str,
        args: &[IRNode],
        pipe_input: Option<IRNode>,
    ) -> Option<IRNode> {
        let has_pipe = pipe_input.is_some();
        let source = pipe_input.unwrap_or_else(|| args.first().cloned().unwrap_or(IRNode::Unit));

        // Extract lambda (params, body) from an IRNode
        let extract_lam = |lam: &IRNode| -> Option<(Vec<String>, Box<crate::ast::Expr>)> {
            match lam {
                IRNode::Lambda(p, b) => Some((p.clone(), b.clone())),
                _ => None,
            }
        };

        match name {
            "map" => {
                let lam = args
                    .get(if has_pipe { 0 } else { 1 })
                    .and_then(extract_lam)?;
                return Some(IRNode::Pipeline(vec![
                    source.clone(),
                    IRNode::Map(lam.0, lam.1),
                ]));
            }
            "where" | "filter" => {
                let pred = args
                    .get(if has_pipe { 0 } else { 1 })
                    .and_then(extract_lam)?;
                return Some(IRNode::Pipeline(vec![
                    source.clone(),
                    IRNode::Filter(pred.0, pred.1),
                ]));
            }
            "sort" => {
                let key = args.get(if has_pipe { 0 } else { 1 }).and_then(extract_lam);
                return Some(IRNode::Pipeline(vec![
                    source.clone(),
                    IRNode::Sort(key.map(|k| (k.0, k.1))),
                ]));
            }
            "reduce" => {
                let (lam, init) = if has_pipe {
                    (
                        args.first().and_then(extract_lam),
                        args.get(1).cloned().unwrap_or(IRNode::Unit),
                    )
                } else {
                    (
                        args.get(1).and_then(extract_lam),
                        args.get(2).cloned().unwrap_or(IRNode::Unit),
                    )
                };
                let (params, body) = lam?;
                return Some(IRNode::Reduce(params, body, Box::new(init)));
            }
            "take" => {
                let n = args
                    .get(if has_pipe { 0 } else { 1 })
                    .cloned()
                    .unwrap_or(IRNode::Int(10));
                return Some(IRNode::Pipeline(vec![
                    source.clone(),
                    IRNode::Take(Box::new(n)),
                ]));
            }
            "reverse" => {
                // Lower to Call(Var("arr.reverse"), [source]) which routes
                // through the builtin dispatch and uses the pipeline input.
                return Some(IRNode::Call(
                    Box::new(IRNode::Var("arr.reverse".to_string())),
                    vec![source.clone()],
                ));
            }
            _ => None,
        }
    }
} // impl IRCompiler

// ── V3 IR Evaluator ────────────────────────────────────

use crate::env::Env;
use crate::value::Value;
use anyhow::{anyhow, Result};

/// Evaluate an IR program using the unified v3 execution path.
pub struct IREvaluator;

impl IREvaluator {
    /// Evaluate a sequence of IR nodes (a compiled program) in the given env.
    pub fn eval_program(nodes: &[IRNode], env: &mut Env) -> Result<Value> {
        let mut last = Value::Null;
        for node in nodes {
            env.set_input(None);
            last = Self::eval(node, env)?;
        }
        Ok(last)
    }

    /// Evaluate a single IR node.
    ///
    /// This is the public entry point. When `env.trace` is `Some`, it wraps
    /// `eval_raw` to collect per-node `ExecutionEvent`s for observability
    /// (Line B Phase 1, InterCode-inspired structured feedback).
    pub fn eval(node: &IRNode, env: &mut Env) -> Result<Value> {
        // Fast path: no trace collection — delegate directly to eval_raw.
        if env.trace.is_none() {
            return Self::eval_raw(node, env);
        }

        let start = std::time::Instant::now();
        let result = Self::eval_raw(node, env);
        if let Some(trace) = env.trace.as_mut() {
            let (ok, result_summary) = match &result {
                Ok(v) => (true, Some(summarize_value(v))),
                Err(e) => (false, Some(e.to_string())),
            };
            trace.push(crate::env::ExecutionEvent {
                node_type: node_type_name(node).to_string(),
                builtin_name: builtin_name_of(node).map(String::from),
                elapsed_us: start.elapsed().as_micros() as u64,
                ok,
                result_summary: result_summary.map(|s| s.chars().take(200).collect()),
            });
        }
        result
    }

    /// Inner evaluation without trace collection. Called by `eval` or directly
    /// when trace is not needed (REPL, tests, recursive inner calls that
    /// `eval` already wraps).
    fn eval_raw(node: &IRNode, env: &mut Env) -> Result<Value> {
        // T5: per-request deadline check. Cheap (just a load + compare) so
        // safe to run on every node. `env.deadline` is `None` by default,
        // which makes this a no-op for REPL/tests/non-agent paths.
        if let Some(dl) = env.deadline {
            if std::time::Instant::now() >= dl {
                return Err(anyhow!("timeout: deadline exceeded"));
            }
        }
        match node {
            IRNode::Unit => Ok(Value::Null),
            IRNode::Bool(b) => Ok(Value::Bool(*b)),
            IRNode::Int(n) => Ok(Value::Int(*n)),
            IRNode::Float(f) => Ok(Value::Float(*f)),
            IRNode::Str(s) => {
                if s.contains("${") {
                    crate::eval::interpolate_string(s, env)
                } else {
                    Ok(Value::Str(s.clone()))
                }
            }

            IRNode::Array(items) => {
                let vals: Result<Vec<Value>> = items.iter().map(|i| Self::eval(i, env)).collect();
                Ok(Value::Array(vals?))
            }
            IRNode::Record(map) => {
                let mut m = std::collections::BTreeMap::new();
                for (k, v) in map {
                    m.insert(k.clone(), Self::eval(v, env)?);
                }
                Ok(Value::Record(m))
            }
            IRNode::Var(name) => Ok(env.get_var(name).cloned().unwrap_or(Value::Null)),
            IRNode::Let(name, val, body) => {
                let v = Self::eval(val, env)?;
                let old = env.get_var(name).cloned();
                env.set_var_unchecked(name, v);
                let result = Self::eval(body, env);
                // Only restore if body is NOT Unit (i.e., scoped let within expression)
                if !matches!(body.as_ref(), IRNode::Unit) {
                    match old {
                        Some(ov) => env.set_var_unchecked(name, ov),
                        None => env.del_var(name),
                    }
                }
                result
            }
            IRNode::Binary(left, op, right) => {
                let l = Self::eval(left, env)?;
                let r = Self::eval(right, env)?;
                binop_value(op, l, r)
            }
            IRNode::Unary(op, expr) => {
                let v = Self::eval(expr, env)?;
                match (op, v) {
                    (UnOp::Neg, Value::Int(n)) => Ok(Value::Int(-n)),
                    (UnOp::Neg, Value::Float(x)) => Ok(Value::Float(-x)),
                    (UnOp::Not, v) => Ok(Value::Bool(!is_truthy_v(&v))),
                    _ => Err(anyhow!("bad unary op")),
                }
            }
            IRNode::Lambda(params, body) => Ok(Value::Lambda(crate::value::Lambda {
                params: params.clone(),
                body: body.clone(),
            })),
            IRNode::Call(callee, args) => {
                let vals: Result<Vec<Value>> = args.iter().map(|a| Self::eval(a, env)).collect();
                let pin = env.input().cloned();
                if let IRNode::Var(name) = callee.as_ref() {
                    if env.get_var(name).is_none() {
                        return crate::builtins::call_with_input(name, vals?, pin, env);
                    }
                }
                let f = Self::eval(callee, env)?;
                match f {
                    Value::Builtin(ref b) => {
                        crate::builtins::call_with_input(&b.name, vals?, pin, env)
                    }
                    Value::Lambda(ref lam) => {
                        let vs = vals?;
                        let mut bindings: Vec<(String, Value)> =
                            Vec::with_capacity(lam.params.len());
                        for (i, p) in lam.params.iter().enumerate() {
                            bindings.push((p.clone(), vs.get(i).cloned().unwrap_or(Value::Null)));
                        }
                        let bindings_refs: Vec<(&str, Value)> = bindings
                            .iter()
                            .map(|(k, v)| (k.as_str(), v.clone()))
                            .collect();
                        env.with_frame(&bindings_refs, |env| crate::eval::eval_expr(&lam.body, env))
                    }
                    _ => Err(anyhow!("IR Call: cannot call non-function value")),
                }
            }
            IRNode::Pipeline(stages) => {
                let mut val = Value::Null;
                for stage in stages {
                    env.set_input(Some(val));
                    val = Self::eval(stage, env)?;
                }
                Ok(val)
            }
            // ── Fused pipeline stages ──
            // These fuse two stages into a single iteration, reducing allocations
            // and cache misses. FusedMapFilter: transform, then test → one pass.
            IRNode::FusedMapFilter(map_node, filter_node) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                match (map_node.as_ref(), filter_node.as_ref()) {
                    (IRNode::Map(mparams, mbody), IRNode::Filter(fparams, fbody)) => {
                        let mut out = Vec::new();
                        for (i, v) in arr.iter().enumerate() {
                            let mut bindings = vec![(mparams[0].as_str(), v.clone())];
                            if let Some(index_param) = mparams.get(1) {
                                bindings.push((index_param.as_str(), Value::Int(i as i64)));
                            }
                            let mapped = env
                                .with_frame(&bindings, |env| crate::eval::eval_expr(mbody, env))?;
                            let keep =
                                env.with_frame(&[(fparams[0].as_str(), mapped.clone())], |env| {
                                    is_truthy_v(
                                        &crate::eval::eval_expr(fbody, env)
                                            .unwrap_or(Value::Bool(false)),
                                    )
                                });
                            if keep {
                                out.push(mapped);
                            }
                        }
                        Ok(Value::Array(out))
                    }
                    _ => {
                        // Fallback: evaluate as pipeline
                        let mut val = Value::Array(arr.clone());
                        for stage in [map_node.as_ref(), filter_node.as_ref()] {
                            env.set_input(Some(val));
                            val = Self::eval(stage, env)?;
                        }
                        Ok(val)
                    }
                }
            }
            IRNode::FusedFilterMap(filter_node, map_node) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                match (filter_node.as_ref(), map_node.as_ref()) {
                    (IRNode::Filter(fparams, fbody), IRNode::Map(mparams, mbody)) => {
                        let mut out = Vec::new();
                        for (i, v) in arr.iter().enumerate() {
                            let passes =
                                env.with_frame(&[(fparams[0].as_str(), v.clone())], |env| {
                                    is_truthy_v(
                                        &crate::eval::eval_expr(fbody, env)
                                            .unwrap_or(Value::Bool(false)),
                                    )
                                });
                            if !passes {
                                continue;
                            }
                            let mut bindings = vec![(mparams[0].as_str(), v.clone())];
                            if let Some(index_param) = mparams.get(1) {
                                bindings.push((index_param.as_str(), Value::Int(i as i64)));
                            }
                            out.push(
                                env.with_frame(&bindings, |env| {
                                    crate::eval::eval_expr(mbody, env)
                                })?,
                            );
                        }
                        Ok(Value::Array(out))
                    }
                    _ => {
                        let mut val = Value::Array(arr.clone());
                        for stage in [filter_node.as_ref(), map_node.as_ref()] {
                            env.set_input(Some(val));
                            val = Self::eval(stage, env)?;
                        }
                        Ok(val)
                    }
                }
            }
            IRNode::FusedMapMap(a, b) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                match (a.as_ref(), b.as_ref()) {
                    (IRNode::Map(ap, ab), IRNode::Map(bp, bb)) => {
                        let mut out = Vec::with_capacity(arr.len());
                        for (i, v) in arr.iter().enumerate() {
                            let mut first = vec![(ap[0].as_str(), v.clone())];
                            if let Some(index_param) = ap.get(1) {
                                first.push((index_param.as_str(), Value::Int(i as i64)));
                            }
                            let mid =
                                env.with_frame(&first, |env| crate::eval::eval_expr(ab, env))?;
                            let mut second = vec![(bp[0].as_str(), mid)];
                            if let Some(index_param) = bp.get(1) {
                                second.push((index_param.as_str(), Value::Int(i as i64)));
                            }
                            out.push(
                                env.with_frame(&second, |env| crate::eval::eval_expr(bb, env))?,
                            );
                        }
                        Ok(Value::Array(out))
                    }
                    _ => {
                        let mut val = Value::Array(arr.clone());
                        for stage in [a.as_ref(), b.as_ref()] {
                            env.set_input(Some(val));
                            val = Self::eval(stage, env)?;
                        }
                        Ok(val)
                    }
                }
            }
            // Pipeline stages — IR-native evaluation (v3: params+Expr bodies)
            IRNode::Map(params, body) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                let mut out = Vec::with_capacity(arr.len());
                for (i, v) in arr.iter().enumerate() {
                    let mut bindings = vec![(params[0].as_str(), v.clone())];
                    if let Some(index_param) = params.get(1) {
                        bindings.push((index_param.as_str(), Value::Int(i as i64)));
                    }
                    out.push(env.with_frame(&bindings, |env| crate::eval::eval_expr(body, env))?);
                }
                Ok(Value::Array(out))
            }
            IRNode::Filter(params, body) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                let mut out = Vec::new();
                for v in arr {
                    let passes = env.with_frame(&[(params[0].as_str(), v.clone())], |env| {
                        match crate::eval::eval_expr(body, env) {
                            Ok(r) => is_truthy_v(&r),
                            Err(_) => false,
                        }
                    });
                    if passes {
                        out.push(v.clone());
                    }
                }
                Ok(Value::Array(out))
            }
            IRNode::Sort(key) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let mut arr = expect_array(&input)?.clone();
                if let Some((ref kparams, ref kbody)) = key {
                    // Decorate-sort-undecorate: eval key once per element
                    let mut decorated: Vec<(Value, Value)> = Vec::with_capacity(arr.len());
                    for v in arr {
                        let k = env.with_frame(&[(kparams[0].as_str(), v.clone())], |env| {
                            crate::eval::eval_expr(kbody, env).unwrap_or(Value::Null)
                        });
                        decorated.push((k, v));
                    }
                    decorated.sort_by(|a, b| compare_values(&a.0, &b.0));
                    arr = decorated.into_iter().map(|(_, v)| v).collect();
                } else {
                    arr.sort_by(|a, b| compare_values(a, b));
                }
                Ok(Value::Array(arr))
            }
            IRNode::Reduce(params, body, init) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                let mut acc = Self::eval(init, env)?;
                for (i, v) in arr.iter().enumerate() {
                    let mut bindings =
                        vec![(params[0].as_str(), acc), (params[1].as_str(), v.clone())];
                    if let Some(index_param) = params.get(2) {
                        bindings.push((index_param.as_str(), Value::Int(i as i64)));
                    }
                    acc = env.with_frame(&bindings, |env| crate::eval::eval_expr(body, env))?;
                }
                Ok(acc)
            }
            IRNode::Take(n) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let count = match Self::eval(n, env)? {
                    Value::Int(c) => c.max(0) as usize,
                    Value::Float(f) => (f as i64).max(0) as usize,
                    _ => 10,
                };
                if let Value::Array(ref arr_data) = input {
                    Ok(Value::Array(arr_data.iter().take(count).cloned().collect()))
                } else {
                    Err(anyhow!("expected array, got {}", input.type_name()))
                }
            }
            // Builtin dispatch
            IRNode::Builtin(name, args, effect) => {
                // Check capability
                if !matches!(effect, IREffect::Pure) {
                    match crate::capability::check_capability(name) {
                        crate::capability::CapabilityResult::Deny(reason) => {
                            return Err(anyhow!("{}", reason));
                        }
                        _ => {}
                    }
                }
                let arg_vals: Result<Vec<Value>> =
                    args.iter().map(|a| Self::eval(a, env)).collect();
                let pin = env.input().cloned();
                crate::builtins::call_with_input(name, arg_vals?, pin, env)
            }
            IRNode::MemberAccess(obj, field) => {
                let val = Self::eval(obj, env)?;
                match val {
                    Value::Record(map) => map
                        .get(field)
                        .cloned()
                        .ok_or_else(|| anyhow!("field '{}' not found", field)),
                    _ => Err(anyhow!("cannot access field on non-record")),
                }
            }
            IRNode::Try(body, catch_var, catch_expr) => match Self::eval(body, env) {
                Ok(v) => Ok(v),
                Err(e) => {
                    if let Some(var) = catch_var {
                        env.set_var_unchecked(var, Value::Str(e.to_string()));
                    }
                    Self::eval(catch_expr, env)
                }
            },
            IRNode::Throw(inner) => {
                let v = Self::eval(inner, env)?;
                Err(anyhow!("{}", v))
            }
            IRNode::Error(code, msg) => Err(anyhow!(
                "[{}] {}",
                code,
                msg.as_deref().unwrap_or("unknown")
            )),
            IRNode::If(cond, then_branch, else_branch) => {
                // Control flow: eval cond, branch on truthiness (matches eval.rs semantics
                // via is_truthy_v: Null / false / 0 / 0.0 / "" are falsy, everything else truthy)
                let c = Self::eval(cond, env)?;
                if is_truthy_v(&c) {
                    Self::eval(then_branch, env)
                } else {
                    Self::eval(else_branch, env)
                }
            }
            IRNode::Match(scrutinee, arms) => {
                // Pattern matching: eval scrutinee, try each arm's pattern; on match,
                // check optional guard (in a scope that sees the pattern bindings),
                // then commit bindings to env and eval body. Mirrors eval.rs::Expr::Match.
                let value = Self::eval(scrutinee, env)?;
                for arm in arms {
                    if let Some(bindings) = match_pattern_ir(&arm.pattern, &value) {
                        if let Some(guard) = &arm.guard {
                            let mut guard_env = env.clone();
                            for (name, val) in &bindings {
                                guard_env.set_var_unchecked(name, val.clone());
                            }
                            let guard_val = Self::eval(guard, &mut guard_env)?;
                            if !is_truthy_v(&guard_val) {
                                continue;
                            }
                        }
                        for (name, val) in bindings {
                            env.set_var_unchecked(&name, val);
                        }
                        return Self::eval(&arm.body, env);
                    }
                }
                Err(anyhow!("match: no arm matched the value"))
            }
            IRNode::Annotate(_, _, inner) => Self::eval(inner, env),
        }
    }

    fn eval_lambda(_node: &IRNode, _env: &mut Env) -> Result<(Vec<String>, IRNode)> {
        Err(anyhow!("eval_lambda not needed in v3"))
    }
}

// ── Trace helpers (Line B Phase 1) ───────────────────────────────────

/// Return the variant name of an IRNode for trace labeling.
fn node_type_name(node: &IRNode) -> &'static str {
    match node {
        IRNode::Unit => "Unit",
        IRNode::Bool(_) => "Bool",
        IRNode::Int(_) => "Int",
        IRNode::Float(_) => "Float",
        IRNode::Str(_) => "Str",
        IRNode::Array(_) => "Array",
        IRNode::Record(_) => "Record",
        IRNode::Var(_) => "Var",
        IRNode::Let(..) => "Let",
        IRNode::Binary(..) => "Binary",
        IRNode::Unary(..) => "Unary",
        IRNode::If(..) => "If",
        IRNode::Match(..) => "Match",
        IRNode::Try(..) => "Try",
        IRNode::Throw(..) => "Throw",
        IRNode::Lambda(..) => "Lambda",
        IRNode::Call(..) => "Call",
        IRNode::Pipeline(..) => "Pipeline",
        IRNode::Map(..) => "Map",
        IRNode::Filter(..) => "Filter",
        IRNode::Sort(..) => "Sort",
        IRNode::Reduce(..) => "Reduce",
        IRNode::Take(..) => "Take",
        IRNode::FusedMapMap(..) => "FusedMapMap",
        IRNode::FusedMapFilter(..) => "FusedMapFilter",
        IRNode::FusedFilterMap(..) => "FusedFilterMap",
        IRNode::Builtin(..) => "Builtin",
        IRNode::MemberAccess(..) => "MemberAccess",
        IRNode::Error(..) => "Error",
        IRNode::Annotate(..) => "Annotate",
    }
}

/// If the node is a `Builtin`, return its name. Used for trace labeling.
fn builtin_name_of(node: &IRNode) -> Option<&str> {
    match node {
        IRNode::Builtin(name, _, _) => Some(name.as_str()),
        _ => None,
    }
}

/// Produce a short summary string of a Value for trace output.
/// Truncated to 200 chars by the caller.
fn summarize_value(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => b.to_string(),
        Value::Int(n) => n.to_string(),
        Value::Float(f) => f.to_string(),
        Value::Str(s) => {
            if s.len() > 100 {
                format!("\"{}...\" ({} chars)", &s[..50], s.len())
            } else {
                format!("\"{}\"", s)
            }
        }
        Value::Uri(s) => format!("<uri: {}>", s),
        Value::Array(arr) => format!("[array: {} items]", arr.len()),
        Value::Record(map) => format!("{{record: {} fields}}", map.len()),
        Value::Table(t) => format!("<table: {} rows>", t.rows.len()),
        Value::Lambda(_) => "<lambda>".into(),
        Value::AsyncLambda(_) => "<async_lambda>".into(),
        Value::Future(_) => "<future>".into(),
        Value::Error(e) => format!("<error: {}>", e),
        Value::Builtin(b) => format!("<builtin: {}>", b.name),
    }
}

fn binop_value(op: &BinOp, a: Value, b: Value) -> Result<Value> {
    use BinOp::*;
    Ok(match (op, a, b) {
        (Add, Value::Int(x), Value::Int(y)) => Value::Int(x + y),
        (Add, Value::Float(x), Value::Float(y)) => Value::Float(x + y),
        (Add, Value::Int(x), Value::Float(y)) => Value::Float(x as f64 + y),
        (Add, Value::Float(x), Value::Int(y)) => Value::Float(x + y as f64),
        (Add, Value::Str(x), Value::Str(y)) => Value::Str(format!("{}{}", x, y)),
        (Sub, Value::Int(x), Value::Int(y)) => Value::Int(x - y),
        (Sub, Value::Float(x), Value::Float(y)) => Value::Float(x - y),
        (Mul, Value::Int(x), Value::Int(y)) => Value::Int(x * y),
        (Mul, Value::Float(x), Value::Float(y)) => Value::Float(x * y),
        (Div, Value::Int(x), Value::Int(y)) => Value::Float(x as f64 / y as f64),
        (Div, Value::Float(x), Value::Float(y)) => Value::Float(x / y),
        (Rem, Value::Int(x), Value::Int(y)) => Value::Int(x % y),
        (Eq, x, y) => Value::Bool(value_eq_v(&x, &y)),
        (Ne, x, y) => Value::Bool(!value_eq_v(&x, &y)),
        (Lt, Value::Int(x), Value::Int(y)) => Value::Bool(x < y),
        (Lt, Value::Float(x), Value::Float(y)) => Value::Bool(x < y),
        (Lte, Value::Int(x), Value::Int(y)) => Value::Bool(x <= y),
        (Lte, Value::Float(x), Value::Float(y)) => Value::Bool(x <= y),
        (Gt, Value::Int(x), Value::Int(y)) => Value::Bool(x > y),
        (Gt, Value::Float(x), Value::Float(y)) => Value::Bool(x > y),
        (Gte, Value::Int(x), Value::Int(y)) => Value::Bool(x >= y),
        (Gte, Value::Float(x), Value::Float(y)) => Value::Bool(x >= y),
        (And, x, y) => Value::Bool(is_truthy_v(&x) && is_truthy_v(&y)),
        (Or, x, y) => Value::Bool(is_truthy_v(&x) || is_truthy_v(&y)),
        (Pow, Value::Int(x), Value::Int(y)) if y >= 0 => Value::Int(x.pow(y as u32)),
        (Pow, Value::Float(x), Value::Float(y)) => Value::Float(x.powf(y)),
        (Pow, Value::Int(x), Value::Float(y)) => Value::Float((x as f64).powf(y)),
        (Pow, Value::Float(x), Value::Int(y)) => Value::Float(x.powf(y as f64)),
        _ => return Err(anyhow!("unsupported op")),
    })
}

fn is_truthy_v(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(false) => false,
        Value::Int(0) => false,
        Value::Float(0.0) => false,
        Value::Str(s) if s.is_empty() => false,
        _ => true,
    }
}

fn value_eq_v(a: &Value, b: &Value) -> bool {
    use Value::*;
    match (a, b) {
        (Null, Null) => true,
        (Bool(x), Bool(y)) => x == y,
        (Int(x), Int(y)) => x == y,
        (Float(x), Float(y)) => x == y,
        (Str(x), Str(y)) => x == y,
        _ => false,
    }
}

/// Attempt to match an IR `MatchPattern` against a `Value`.
/// Returns `Some(bindings)` on success, `None` on failure.
/// Bindings are accumulated in order; for `Or`, the first matching sub-pattern wins.
fn match_pattern_ir(pattern: &MatchPattern, value: &Value) -> Option<Vec<(String, Value)>> {
    let mut bindings = Vec::new();
    if match_pattern_ir_impl(pattern, value, &mut bindings) {
        Some(bindings)
    } else {
        None
    }
}

fn match_pattern_ir_impl(
    pattern: &MatchPattern,
    value: &Value,
    bindings: &mut Vec<(String, Value)>,
) -> bool {
    match pattern {
        MatchPattern::Wildcard => true,
        MatchPattern::Binding(name) => {
            bindings.push((name.clone(), value.clone()));
            true
        }
        MatchPattern::Literal(ir_node) => {
            // compile_pattern emits literal patterns only for primitive constants;
            // match by structural equality against the encoded literal.
            match ir_node {
                IRNode::Int(n) => matches!(value, Value::Int(v) if v == n),
                IRNode::Float(f) => matches!(value, Value::Float(v) if v == f),
                IRNode::Str(s) => matches!(value, Value::Str(v) if v == s),
                IRNode::Bool(b) => matches!(value, Value::Bool(v) if v == b),
                IRNode::Unit => matches!(value, Value::Null),
                _ => false,
            }
        }
        MatchPattern::Or(patterns) => {
            for p in patterns {
                let mut trial = Vec::new();
                if match_pattern_ir_impl(p, value, &mut trial) {
                    bindings.extend(trial);
                    return true;
                }
            }
            false
        }
    }
}

fn expect_array(v: &Value) -> Result<&Vec<Value>> {
    match v {
        Value::Array(arr) => Ok(arr),
        _ => Err(anyhow!("expected array")),
    }
}

fn compare_values(a: &Value, b: &Value) -> std::cmp::Ordering {
    use std::cmp::Ordering;
    match (a, b) {
        (Value::Int(x), Value::Int(y)) => x.cmp(y),
        (Value::Float(x), Value::Float(y)) => x.partial_cmp(y).unwrap_or(Ordering::Equal),
        (Value::Str(x), Value::Str(y)) => x.cmp(y),
        _ => Ordering::Equal,
    }
}

// ── Tests ────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_t5_deadline_expired_returns_timeout() {
        // T5: when env.deadline is Some(past), eval must abort immediately
        // with a "timeout: deadline exceeded" error, regardless of the node.
        let mut env = Env::new();
        env.deadline = Some(std::time::Instant::now() - std::time::Duration::from_millis(1));
        let node = IRNode::Int(42);
        let result = IREvaluator::eval(&node, &mut env);
        assert!(result.is_err(), "expected timeout error");
        let msg = result.unwrap_err().to_string();
        assert!(
            msg.contains("timeout"),
            "error should mention timeout, got: {msg}"
        );
    }

    #[test]
    fn test_t5_no_deadline_evaluates_normally() {
        // T5: deadline=None means no timeout, normal evaluation proceeds.
        let mut env = Env::new();
        env.deadline = None;
        let node = IRNode::Int(42);
        let result = IREvaluator::eval(&node, &mut env);
        assert_eq!(result.unwrap(), Value::Int(42));
    }

    #[test]
    fn test_t5_future_deadline_evaluates_normally() {
        // T5: deadline in the future should not block normal evaluation.
        let mut env = Env::new();
        env.deadline = Some(std::time::Instant::now() + std::time::Duration::from_secs(60));
        let node = IRNode::Binary(
            Box::new(IRNode::Int(1)),
            BinOp::Add,
            Box::new(IRNode::Int(2)),
        );
        let result = IREvaluator::eval(&node, &mut env);
        assert_eq!(result.unwrap(), Value::Int(3));
    }

    #[test]
    fn test_ir_hash_deterministic() {
        let a = IRNode::Binary(
            Box::new(IRNode::Int(1)),
            BinOp::Add,
            Box::new(IRNode::Int(2)),
        );
        let b = IRNode::Binary(
            Box::new(IRNode::Int(1)),
            BinOp::Add,
            Box::new(IRNode::Int(2)),
        );
        assert_eq!(IRHash::compute(&a), IRHash::compute(&b));
    }

    #[test]
    fn test_ir_hash_different_values() {
        let a = IRNode::Int(42);
        let b = IRNode::Int(43);
        assert_ne!(IRHash::compute(&a), IRHash::compute(&b));
    }

    #[test]
    fn test_constant_fold_add() {
        let opt = IROptimizer::default();
        let input = IRNode::Binary(
            Box::new(IRNode::Int(40)),
            BinOp::Add,
            Box::new(IRNode::Int(2)),
        );
        assert_eq!(opt.constant_fold(input), IRNode::Int(42));
    }

    #[test]
    fn test_constant_fold_nested() {
        let opt = IROptimizer::default();
        let input = IRNode::Binary(
            Box::new(IRNode::Binary(
                Box::new(IRNode::Int(10)),
                BinOp::Mul,
                Box::new(IRNode::Int(4)),
            )),
            BinOp::Add,
            Box::new(IRNode::Int(2)),
        );
        assert_eq!(opt.constant_fold(input), IRNode::Int(42));
    }

    #[test]
    fn test_ir_compile_simple() {
        let compiler = IRCompiler::new(true);
        let stmts = crate::parser::parse_program("1 + 2").unwrap();
        let ir = compiler.compile_program(&stmts);
        assert_eq!(ir.len(), 1);
        // Should be constant-folded to Int(3)
        assert_eq!(ir[0], IRNode::Int(3));
    }

    // ── If / Match control-flow tests (T12) ──

    fn eval_node(node: &IRNode) -> Result<Value> {
        let mut env = Env::new();
        IREvaluator::eval(node, &mut env)
    }

    #[test]
    fn test_ir_if_truthy_cond() {
        // if 1 then "yes" else "no"  → "yes"
        let node = IRNode::If(
            Box::new(IRNode::Int(1)),
            Box::new(IRNode::Str("yes".into())),
            Box::new(IRNode::Str("no".into())),
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("yes".into()));
    }

    #[test]
    fn test_ir_if_falsy_cond() {
        // if 0 then "yes" else "no"  → "no"
        let node = IRNode::If(
            Box::new(IRNode::Int(0)),
            Box::new(IRNode::Str("yes".into())),
            Box::new(IRNode::Str("no".into())),
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("no".into()));
    }

    #[test]
    fn test_ir_if_falsy_values_all_go_else() {
        // Verifies is_truthy_v alignment: Null / false / 0 / 0.0 / "" are all falsy
        let falsy = vec![
            IRNode::Unit,
            IRNode::Bool(false),
            IRNode::Int(0),
            IRNode::Float(0.0),
            IRNode::Str(String::new()),
        ];
        for cond in falsy {
            let node = IRNode::If(
                Box::new(cond),
                Box::new(IRNode::Int(1)),
                Box::new(IRNode::Int(2)),
            );
            assert_eq!(
                eval_node(&node).unwrap(),
                Value::Int(2),
                "expected else branch"
            );
        }
    }

    #[test]
    fn test_ir_if_nested() {
        // if 1 then (if 0 then 10 else 20) else 30  → 20
        let inner = IRNode::If(
            Box::new(IRNode::Int(0)),
            Box::new(IRNode::Int(10)),
            Box::new(IRNode::Int(20)),
        );
        let outer = IRNode::If(
            Box::new(IRNode::Int(1)),
            Box::new(inner),
            Box::new(IRNode::Int(30)),
        );
        assert_eq!(eval_node(&outer).unwrap(), Value::Int(20));
    }

    #[test]
    fn test_ir_if_evaluates_cond_expr() {
        // if 2 > 1 then "ok" else "bad"  → "ok"
        let cond = IRNode::Binary(
            Box::new(IRNode::Int(2)),
            BinOp::Gt,
            Box::new(IRNode::Int(1)),
        );
        let node = IRNode::If(
            Box::new(cond),
            Box::new(IRNode::Str("ok".into())),
            Box::new(IRNode::Str("bad".into())),
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("ok".into()));
    }

    #[test]
    fn test_ir_match_literal_int() {
        // match 2 { 1 => "one", 2 => "two", _ => "other" }  → "two"
        let node = IRNode::Match(
            Box::new(IRNode::Int(2)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Int(1)),
                    guard: None,
                    body: Box::new(IRNode::Str("one".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Int(2)),
                    guard: None,
                    body: Box::new(IRNode::Str("two".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("other".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("two".into()));
    }

    #[test]
    fn test_ir_match_literal_str_and_bool() {
        let str_arm = IRNode::Match(
            Box::new(IRNode::Str("hi".into())),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Str("yo".into())),
                    guard: None,
                    body: Box::new(IRNode::Int(0)),
                },
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Str("hi".into())),
                    guard: None,
                    body: Box::new(IRNode::Int(1)),
                },
            ],
        );
        assert_eq!(eval_node(&str_arm).unwrap(), Value::Int(1));

        let bool_arm = IRNode::Match(
            Box::new(IRNode::Bool(false)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Bool(true)),
                    guard: None,
                    body: Box::new(IRNode::Int(10)),
                },
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Bool(false)),
                    guard: None,
                    body: Box::new(IRNode::Int(20)),
                },
            ],
        );
        assert_eq!(eval_node(&bool_arm).unwrap(), Value::Int(20));
    }

    #[test]
    fn test_ir_match_null_literal() {
        // compile_pattern maps Pattern::Null → MatchPattern::Literal(IRNode::Unit)
        let node = IRNode::Match(
            Box::new(IRNode::Unit),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Unit),
                    guard: None,
                    body: Box::new(IRNode::Str("null".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("non-null".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("null".into()));
    }

    #[test]
    fn test_ir_match_binding() {
        // match 42 { x => x + 1 }  → 43
        let body = IRNode::Binary(
            Box::new(IRNode::Var("x".into())),
            BinOp::Add,
            Box::new(IRNode::Int(1)),
        );
        let node = IRNode::Match(
            Box::new(IRNode::Int(42)),
            vec![MatchArm {
                pattern: MatchPattern::Binding("x".into()),
                guard: None,
                body: Box::new(body),
            }],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Int(43));
    }

    #[test]
    fn test_ir_match_wildcard_default() {
        // match "anything" { 1 => "one", _ => "default" }  → "default"
        let node = IRNode::Match(
            Box::new(IRNode::Str("anything".into())),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Int(1)),
                    guard: None,
                    body: Box::new(IRNode::Str("one".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("default".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("default".into()));
    }

    #[test]
    fn test_ir_match_or_pattern() {
        // match 2 { 1 | 2 | 3 => "small", _ => "big" }  → "small"
        let node = IRNode::Match(
            Box::new(IRNode::Int(2)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Or(vec![
                        MatchPattern::Literal(IRNode::Int(1)),
                        MatchPattern::Literal(IRNode::Int(2)),
                        MatchPattern::Literal(IRNode::Int(3)),
                    ]),
                    guard: None,
                    body: Box::new(IRNode::Str("small".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("big".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("small".into()));
    }

    #[test]
    fn test_ir_match_guard_true() {
        // match 5 { x if x > 3 => "big", _ => "small" }  → "big"
        let guard = IRNode::Binary(
            Box::new(IRNode::Var("x".into())),
            BinOp::Gt,
            Box::new(IRNode::Int(3)),
        );
        let node = IRNode::Match(
            Box::new(IRNode::Int(5)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Binding("x".into()),
                    guard: Some(Box::new(guard)),
                    body: Box::new(IRNode::Str("big".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("small".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("big".into()));
    }

    #[test]
    fn test_ir_match_guard_false_falls_through() {
        // match 2 { x if x > 3 => "big", _ => "small" }  → "small" (guard fails, falls through)
        let guard = IRNode::Binary(
            Box::new(IRNode::Var("x".into())),
            BinOp::Gt,
            Box::new(IRNode::Int(3)),
        );
        let node = IRNode::Match(
            Box::new(IRNode::Int(2)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Binding("x".into()),
                    guard: Some(Box::new(guard)),
                    body: Box::new(IRNode::Str("big".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Wildcard,
                    guard: None,
                    body: Box::new(IRNode::Str("small".into())),
                },
            ],
        );
        assert_eq!(eval_node(&node).unwrap(), Value::Str("small".into()));
    }

    #[test]
    fn test_ir_match_no_arm_matched_errors() {
        // match 99 { 1 => "one", 2 => "two" }  → error
        let node = IRNode::Match(
            Box::new(IRNode::Int(99)),
            vec![
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Int(1)),
                    guard: None,
                    body: Box::new(IRNode::Str("one".into())),
                },
                MatchArm {
                    pattern: MatchPattern::Literal(IRNode::Int(2)),
                    guard: None,
                    body: Box::new(IRNode::Str("two".into())),
                },
            ],
        );
        assert!(eval_node(&node).is_err());
    }
}
