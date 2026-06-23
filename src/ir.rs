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
    SysRead, FileRead, FileWrite, FileDelete,
    NetHttpGet, NetHttpPost, NetHttpDelete,
    ProcList, ProcKill, ProcSpawn, ShellExec,
    WinRegistry, WinService,
    CryptoHash, CryptoRandom,
    DbRead, DbWrite, GitRead, GitWrite,
    Combined(Vec<IREffect>),
}

impl IREffect {
    pub fn merge(self, other: IREffect) -> IREffect {
        use IREffect::*;
        match (self, other) {
            (Pure, e) | (e, Pure) => e,
            (Combined(mut a), Combined(b)) => { a.extend(b); Combined(a) }
            (Combined(mut a), e) | (e, Combined(mut a)) => { a.push(e); Combined(a) }
            (a, b) if a == b => a,
            (a, b) => Combined(vec![a, b]),
        }
    }

    pub fn for_builtin(name: &str) -> IREffect {
        match name {
            "abs"|"min"|"max"|"floor"|"ceil"|"round"|"sqrt"|"pow"|"sum"|"mean"
            |"upper"|"lower"|"trim"|"split"|"replace"|"contains"|"starts_with"|"ends_with"
            |"len"|"length"|"slice"|"join"|"range"|"flatten"|"unique"|"sort"|"reverse"|"zip"
            |"concat"|"in"|"first"|"last"|"any"|"all"|"take"|"map"|"where"|"filter"|"reduce"
            |"each"|"keys"|"values"|"group_by"|"select"|"json_parse"|"json_stringify"|"echo"
            |"print"|"help"|"describe"|"typeof"|"type_of"|"now"|"sleep"|"exit"|"pwd"|"clear"
            |"par_map"|"uniq"|"which"|"call" => IREffect::Pure,

            "sys_cpu_info"|"sys_mem_info"|"sys_disk_info"|"sys_load_avg"|"sys_hostname"
            |"sys_os"|"sys_arch"|"sys_cpu_count"|"sys_swap_info"|"sys_info"|"sys_users"
            |"sys_groups"|"sys_user_info"|"sys_boot_time"|"sys_timezone"|"sys_locale"
            |"sys_kernel"|"sys_uptime"|"platform_arch"|"platform_os_version"|"platform_cpu"
            |"platform_memory"|"platform_disks"|"platform_gpus"|"platform_network_interfaces"
            |"platform_hardware_summary"|"hw_cpu"|"hw_memory"|"hw_disk"|"hw_gpu"|"hw_battery"
            |"sys_env_all"|"win_snapshot"|"win_env_path"|"win_env_get"|"win_is_admin" => IREffect::SysRead,

            "cat"|"read_text"|"head"|"tail"|"grep"|"find"|"ls"|"list"|"file_exists"
            |"fs_stat"|"fs_walk"|"fs_tree"|"fs_readlink"|"fs_realpath"|"fs_glob"|"fs_df"
            |"fs_du"|"fs_mounts"|"wc"|"file_type"|"file_diff" => IREffect::FileRead,

            "file_write"|"file_append"|"file_mkdir"|"file_copy"|"file_move"|"file_rename"
            |"file_replace"|"file_patch"|"file_insert"|"file_backup"|"file_edit"|"fs_chmod"
            |"fs_chown"|"fs_link"|"fs_symlink"|"fs_tempfile"|"fs_tempdir"|"fs_mount"
            |"fs_unmount" => IREffect::FileWrite,

            "file_delete_lines"|"delete_lines"|"remove_lines" => IREffect::FileDelete,

            "http_get"|"web_get"|"web_fetch" => IREffect::NetHttpGet,
            "web_post"|"web_json_post"|"http_put"|"web_form_submit"|"web_upload_file" => IREffect::NetHttpPost,
            "http_delete"|"web_rest_api" => IREffect::NetHttpDelete,
            "net_ping"|"net_dns_lookup"|"net_dns_reverse" => IREffect::NetHttpGet,

            "proc_list"|"proc_info"|"proc_exists"|"proc_children"|"proc_parent"
            |"proc_cpu_usage"|"proc_mem_usage"|"proc_threads"|"proc_cwd"|"proc_exe"
            |"proc_cmdline"|"proc_start_time"|"proc_env"|"proc_wait" => IREffect::ProcList,
            "proc_kill"|"win_process_kill" => IREffect::ProcKill,
            "proc_spawn"|"proc_resume"|"proc_suspend"|"proc_set_priority" => IREffect::ProcSpawn,
            "sh"|"shell"|"shell_exec"|"shell_which" => IREffect::ShellExec,

            "win_registry_get" => IREffect::WinRegistry,
            "win_service_list"|"win_service_status" => IREffect::WinService,
            "win_env_set"|"win_shortcut_resolve" => IREffect::SysRead,

            "crypto_hash"|"crypto_hash_file"|"crypto_hmac"|"crypto_checksum"|"crypto_hex_encode"
            |"crypto_hex_decode"|"sha256"|"md5" => IREffect::CryptoHash,
            "crypto_random_bytes"|"crypto_uuid"|"crypto_random_string" => IREffect::CryptoRandom,

            "db_sqlite_query"|"db_sqlite_schema"|"db_sqlite_tables"|"db_sqlite_count"
            |"db_kv_get"|"db_kv_keys"|"db_sqlite_open"|"db_sqlite_close" => IREffect::DbRead,
            "db_sqlite_exec"|"db_sqlite_insert"|"db_sqlite_update"|"db_sqlite_delete"
            |"db_sqlite_create_table"|"db_sqlite_drop_table"|"db_sqlite_dump"|"db_kv_set"
            |"db_kv_delete" => IREffect::DbWrite,

            "git_status"|"git_log"|"git_diff"|"git_branch"|"git_branches"|"git_show"
            |"git_tags"|"git_blame"|"git_root"|"git_rev_parse"|"git_remote"|"git_fetch"
            |"git_diff_staged" => IREffect::GitRead,
            "git_commit"|"git_add"|"git_checkout"|"git_merge"|"git_rebase"|"git_pull"
            |"git_push"|"git_stash"|"git_stash_pop"|"git_reset"|"git_clean"
            |"git_cherry_pick" => IREffect::GitWrite,

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
        Bool(b) => { 1u8.hash(h); b.hash(h); }
        Int(n) => { 2u8.hash(h); n.hash(h); }
        Float(f) => { 3u8.hash(h); f.to_bits().hash(h); }
        Str(s) => { 4u8.hash(h); s.hash(h); }
        Array(items) => { 5u8.hash(h); for i in items { hash_node(i, h); } }
        Record(map) => { 6u8.hash(h); for (k, v) in map { k.hash(h); hash_node(v, h); } }
        Var(name) => { 7u8.hash(h); name.hash(h); }
        Let(name, val, body) => { 8u8.hash(h); name.hash(h); hash_node(val, h); hash_node(body, h); }
        Binary(l, op, r) => { 9u8.hash(h); hash_node(l, h); format!("{:?}", op).hash(h); hash_node(r, h); }
        Unary(op, e) => { 10u8.hash(h); format!("{:?}", op).hash(h); hash_node(e, h); }
        If(cond, t, f) => { 11u8.hash(h); hash_node(cond, h); hash_node(t, h); hash_node(f, h); }
        Match(scrut, arms) => {
            12u8.hash(h); hash_node(scrut, h);
            for arm in arms { hash_node(&arm.body, h); }
        }
        Try(body, var, catch) => { 13u8.hash(h); hash_node(body, h); var.hash(h); hash_node(catch, h); }
        Throw(e) => { 14u8.hash(h); hash_node(e, h); }
        Lambda(params, body) => { 15u8.hash(h); params.hash(h); format!("{:?}", body).hash(h); }
        Call(callee, args) => { 16u8.hash(h); hash_node(callee, h); for a in args { hash_node(a, h); } }
        Pipeline(stages) => { 17u8.hash(h); for s in stages { hash_node(s, h); } }
        Map(params, body) => { 18u8.hash(h); params.hash(h); format!("{:?}", body).hash(h); }
        Filter(params, pred) => { 19u8.hash(h); params.hash(h); format!("{:?}", pred).hash(h); }
        Sort(key) => { 20u8.hash(h); if let Some((_, k)) = key { format!("{:?}", k).hash(h); } }
        Reduce(params, body, init) => { 21u8.hash(h); params.hash(h); format!("{:?}", body).hash(h); hash_node(init, h); }
        Take(n) => { 22u8.hash(h); hash_node(n, h); }
        Builtin(name, args, _eff) => { 23u8.hash(h); name.hash(h); for a in args { hash_node(a, h); } }
        MemberAccess(obj, field) => { 24u8.hash(h); hash_node(obj, h); field.hash(h); }
        Error(code, msg) => { 25u8.hash(h); code.hash(h); msg.hash(h); }
        Annotate(key, val, inner) => { 26u8.hash(h); key.hash(h); val.hash(h); hash_node(inner, h); }
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
                            if *b >= 0 { IRNode::Int(a.pow(*b as u32)) }
                            else { IRNode::Float((*a as f64).powf(*b as f64)) }
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
                    (IRNode::Str(a), IRNode::Str(b)) if op == BinOp::Add =>
                        IRNode::Str(format!("{}{}", a, b)),
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
            IRNode::Let(name, val, body) => {
                IRNode::Let(name, Box::new(self.constant_fold(*val)), Box::new(self.constant_fold(*body)))
            }
            IRNode::Pipeline(stages) => {
                IRNode::Pipeline(stages.into_iter().map(|s| self.constant_fold(s)).collect())
            }
            IRNode::Map(_, _) | IRNode::Filter(_, _) | IRNode::Sort(_) | IRNode::Take(_) | IRNode::Reduce(_, _, _) => {
                node // Pipeline stages pass through without constant folding
            }
            IRNode::Array(items) => {
                IRNode::Array(items.into_iter().map(|i| self.constant_fold(i)).collect())
            }
            IRNode::Record(map) => {
                IRNode::Record(map.into_iter().map(|(k, v)| (k, self.constant_fold(v))).collect())
            }
            IRNode::Call(callee, args) => {
                IRNode::Call(
                    Box::new(self.constant_fold(*callee)),
                    args.into_iter().map(|a| self.constant_fold(a)).collect(),
                )
            }
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
            (IRNode::Map(ap, ab), IRNode::Map(_, bb)) => {
                // map + map → fused (compose lambdas — for now identity)
                IRNode::Pipeline(vec![a, b])
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
    matches!(name,
        "Get-Files"|"get-files"|"Get-Content"|"get-content"|"select"|"select-object"
        |"Select-Object"|"where-object"|"Where-Object"|"foreach"|"ForEach-Object"
        |"foreach-object"|"sort-object"|"Sort-Object"|"group"|"group_by"|"Group-Object"
        |"group-object"|"measure"|"Measure-Object"|"measure-object"|"from-json"
        |"from_json"|"to-json"|"to_json"|"from-csv"|"from_csv"|"to-csv"|"to_csv"
        |"from-yaml"|"from_yaml"|"to-yaml"|"to_yaml"|"columns"|"describe"
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
            Stmt::Let { name, value, is_mut: _, visibility: _ } => {
                let val_ir = self.compile_expr(value);
                // For single-let, use the Let IR node.
                // For multi-statement programs, the final IR is the sequence.
                IRNode::Let(name.clone(), Box::new(val_ir), Box::new(IRNode::Unit))
            }
            Stmt::Expr(expr) => self.compile_expr(expr),
            Stmt::Import { .. } => IRNode::Error("E_IMPORT".into(), Some("import not supported in IR".into())),
            Stmt::Export { items: _, from_source: _ } => IRNode::Unit,
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
            Expr::Record(kvs) => {
                IRNode::Record(kvs.iter().map(|(k, v)| (k.clone(), self.compile_expr(v))).collect())
            }
            Expr::Lambda { params, body } => {
                IRNode::Lambda(params.clone(), body.clone())
            }
            Expr::AsyncLambda { params, body } => {
                IRNode::Lambda(params.clone(), body.clone())
            }
            Expr::Await(inner) => self.compile_expr(inner),
            Expr::TryCatch { try_expr, catch_var, catch_expr } => {
                IRNode::Try(
                    Box::new(self.compile_expr(try_expr)),
                    catch_var.clone(),
                    Box::new(self.compile_expr(catch_expr)),
                )
            }
            Expr::Throw(inner) => IRNode::Throw(Box::new(self.compile_expr(inner))),
            Expr::Call { callee, args, named: _ } => {
                let callee_ir = self.compile_expr(callee);
                let args_ir: Vec<IRNode> = args.iter().map(|a| self.compile_expr(a)).collect();

                // If callee is a simple identifier, keep as Builtin for dispatch
                if let Expr::Ident(name) = callee.as_ref() {
                    // Check if it's a known builtin — if not, treat as variable call
                    if crate::builtins::BUILTIN_LOOKUP.contains_key(name.as_str())
                        || is_fallback_builtin(name) {
                        if let Some(pipeline_ir) = self.try_lower_builtin(name, &args_ir, None) {
                            return pipeline_ir;
                        }
                        IRNode::Builtin(name.clone(), args_ir, IREffect::for_builtin(name))
                    } else {
                        // Variable call
                        IRNode::Call(Box::new(IRNode::Var(name.clone())), args_ir)
                    }
                } else {
                    IRNode::Call(Box::new(callee_ir), args_ir)
                }
            }
            Expr::Pipe { left, right } => {
                let left_ir = self.compile_expr(left);
                // If right is a builtin identifier, lower as pipeline stage
                if let Expr::Ident(name) = right.as_ref() {
                    if let Some(stage_ir) = self.try_lower_builtin(name, &[], Some(left_ir.clone())) {
                        return stage_ir;
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
            Expr::Unary { op, expr } => {
                IRNode::Unary(*op, Box::new(self.compile_expr(expr)))
            }
            Expr::MemberAccess { object, field } => {
                IRNode::MemberAccess(Box::new(self.compile_expr(object)), field.clone())
            }
            Expr::Match { scrutinee, arms } => {
                IRNode::Match(
                    Box::new(self.compile_expr(scrutinee)),
                    arms.iter().map(|arm| MatchArm {
                        pattern: compile_pattern(&arm.pattern),
                        guard: arm.guard.as_ref().map(|g| Box::new(self.compile_expr(g))),
                        body: Box::new(self.compile_expr(&arm.body)),
                    }).collect(),
                )
            }
        }
    }

    /// Try to lower a builtin call into a specific IR pipeline stage.
    fn try_lower_builtin(&self, name: &str, args: &[IRNode], pipe_input: Option<IRNode>) -> Option<IRNode> {
        let has_pipe = pipe_input.is_some();
        let source = pipe_input.unwrap_or_else(|| {
            args.first().cloned().unwrap_or(IRNode::Unit)
        });

        // Extract lambda (params, body) from an IRNode
        let extract_lam = |lam: &IRNode| -> Option<(Vec<String>, Box<crate::ast::Expr>)> {
            match lam {
                IRNode::Lambda(p, b) => Some((p.clone(), b.clone())),
                _ => None,
            }
        };

        match name {
            "map" => {
                let lam = args.get(if has_pipe { 0 } else { 1 })
                    .and_then(extract_lam)?;
                return Some(IRNode::Pipeline(vec![source.clone(), IRNode::Map(lam.0, lam.1)]));
            }
            "where" | "filter" => {
                let pred = args.get(if has_pipe { 0 } else { 1 })
                    .and_then(extract_lam)?;
                return Some(IRNode::Pipeline(vec![source.clone(), IRNode::Filter(pred.0, pred.1)]));
            }
            "sort" => {
                let key = args.get(if has_pipe { 0 } else { 1 })
                    .and_then(extract_lam);
                return Some(IRNode::Pipeline(vec![source.clone(), IRNode::Sort(key.map(|k| (k.0, k.1)))]));
            }
            "reduce" => {
                let (lam, init) = if has_pipe {
                    (args.first().and_then(extract_lam),
                     args.get(1).cloned().unwrap_or(IRNode::Unit))
                } else {
                    (args.get(1).and_then(extract_lam),
                     args.get(2).cloned().unwrap_or(IRNode::Unit))
                };
                let (params, body) = lam?;
                return Some(IRNode::Reduce(params, body, Box::new(init)));
            }
            "take" => {
                let n = args.get(if has_pipe { 0 } else { 1 })
                    .cloned()
                    .unwrap_or(IRNode::Int(10));
                return Some(IRNode::Pipeline(vec![source.clone(), IRNode::Take(Box::new(n))]));
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
    pub fn eval(node: &IRNode, env: &mut Env) -> Result<Value> {
        match node {
            IRNode::Unit => Ok(Value::Null),
            IRNode::Bool(b) => Ok(Value::Bool(*b)),
            IRNode::Int(n) => Ok(Value::Int(*n)),
            IRNode::Float(f) => Ok(Value::Float(*f)),
            IRNode::Str(s) => Ok(Value::Str(s.clone())),

            IRNode::Array(items) => {
                let vals: Result<Vec<Value>> = items.iter().map(|i| Self::eval(i, env)).collect();
                Ok(Value::Array(vals?))
            }
            IRNode::Record(map) => {
                let mut m = std::collections::BTreeMap::new();
                for (k, v) in map { m.insert(k.clone(), Self::eval(v, env)?); }
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
                    match old { Some(ov) => env.set_var_unchecked(name, ov), None => env.del_var(name), }
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
            IRNode::Lambda(params, body) => {
                Ok(Value::Lambda(crate::value::Lambda { params: params.clone(), body: body.clone() }))
            }
            IRNode::Call(callee, args) => {
                let f = Self::eval(callee, env)?;
                let vals: Result<Vec<Value>> = args.iter().map(|a| Self::eval(a, env)).collect();
                let pin = env.input().cloned();
                match f {
                    Value::Builtin(ref b) => {
                        crate::builtins::call_with_input(&b.name, vals?, pin, env)
                    }
                    Value::Lambda(ref lam) => {
                        // Evaluate lambda by binding params and running body through AST eval
                        let mut local = env.clone();
                        let vs = vals?;
                        for (i, p) in lam.params.iter().enumerate() {
                            local.set_var_unchecked(p, vs.get(i).cloned().unwrap_or(Value::Null));
                        }
                        crate::eval::eval_expr(&lam.body, &mut local)
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
            // Pipeline stages — IR-native evaluation (v3: params+Expr bodies)
            IRNode::Map(params, body) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                let mut out = Vec::with_capacity(arr.len());
                for (i, v) in arr.iter().enumerate() {
                    let mut local = env.clone();
                    local.set_input(None);
                    local.set_var_unchecked(&params[0], v.clone());
                    if params.len() > 1 { local.set_var_unchecked(&params[1], Value::Int(i as i64)); }
                    out.push(crate::eval::eval_expr(body, &mut local)?);
                }
                Ok(Value::Array(out))
            }
            IRNode::Filter(params, body) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let arr = expect_array(&input)?;
                let mut out = Vec::new();
                for v in arr {
                    let mut local = env.clone();
                    local.set_var_unchecked(&params[0], v.clone());
                    if let Ok(r) = crate::eval::eval_expr(body, &mut local) {
                        if is_truthy_v(&r) { out.push(v.clone()); }
                    }
                }
                Ok(Value::Array(out))
            }
            IRNode::Sort(key) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let mut arr = expect_array(&input)?.clone();
                if let Some((ref kparams, ref kbody)) = key {
                    arr.sort_by(|a, b| {
                        let mut la = env.clone(); la.set_var_unchecked(&kparams[0], a.clone());
                        let mut lb = env.clone(); lb.set_var_unchecked(&kparams[0], b.clone());
                        let ka = crate::eval::eval_expr(kbody, &mut la).unwrap_or(Value::Null);
                        let kb = crate::eval::eval_expr(kbody, &mut lb).unwrap_or(Value::Null);
                        compare_values(&ka, &kb)
                    });
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
                    let mut local = env.clone();
                    local.set_var_unchecked(&params[0], acc);
                    local.set_var_unchecked(&params[1], v.clone());
                    if params.len() > 2 { local.set_var_unchecked(&params[2], Value::Int(i as i64)); }
                    acc = crate::eval::eval_expr(body, &mut local)?;
                }
                Ok(acc)
            }
            IRNode::Take(n) => {
                let input = env.input().cloned().unwrap_or(Value::Null);
                let count = match Self::eval(n, env)? {
                    Value::Int(c) => c.max(0) as usize,
                    _ => 10,
                };
                let arr = expect_array(&input)?;
                Ok(Value::Array(arr.iter().take(count).cloned().collect()))
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
                let arg_vals: Result<Vec<Value>> = args.iter().map(|a| Self::eval(a, env)).collect();
                let pin = env.input().cloned();
                crate::builtins::call_with_input(name, arg_vals?, pin, env)
            }
            IRNode::MemberAccess(obj, field) => {
                let val = Self::eval(obj, env)?;
                match val {
                    Value::Record(map) => map.get(field).cloned().ok_or_else(|| anyhow!("field '{}' not found", field)),
                    _ => Err(anyhow!("cannot access field on non-record")),
                }
            }
            IRNode::Try(body, catch_var, catch_expr) => {
                match Self::eval(body, env) {
                    Ok(v) => Ok(v),
                    Err(e) => {
                        if let Some(var) = catch_var {
                            env.set_var_unchecked(var, Value::Str(e.to_string()));
                        }
                        Self::eval(catch_expr, env)
                    }
                }
            }
            IRNode::Throw(inner) => {
                let v = Self::eval(inner, env)?;
                Err(anyhow!("{}", v))
            }
            IRNode::Error(code, msg) => Err(anyhow!("[{}] {}", code, msg.as_deref().unwrap_or("unknown"))),
            IRNode::If(_, _, _) | IRNode::Match(_, _) => {
                // Control flow not yet implemented in IR evaluator — fall through to AST path
                Err(anyhow!("IR evaluator: {node:?} not yet implemented"))
            }
            IRNode::Annotate(_, _, inner) => Self::eval(inner, env),
        }
    }

    fn eval_lambda(_node: &IRNode, _env: &mut Env) -> Result<(Vec<String>, IRNode)> {
        Err(anyhow!("eval_lambda not needed in v3"))
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
    match v { Value::Null => false, Value::Bool(false) => false, Value::Int(0) => false, Value::Float(0.0) => false, Value::Str(s) if s.is_empty() => false, _ => true }
}

fn value_eq_v(a: &Value, b: &Value) -> bool {
    use Value::*;
    match (a, b) {
        (Null, Null) => true, (Bool(x), Bool(y)) => x == y, (Int(x), Int(y)) => x == y,
        (Float(x), Float(y)) => x == y, (Str(x), Str(y)) => x == y,
        _ => false,
    }
}

fn expect_array(v: &Value) -> Result<&Vec<Value>> {
    match v { Value::Array(arr) => Ok(arr), _ => Err(anyhow!("expected array")) }
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
}
