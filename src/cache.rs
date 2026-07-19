//! Global cache for AST, compiled IR, and system snapshots.
//!
//! Thread-safe via `Arc<RwLock<>>` — designed for multi-agent concurrent access.
//! v0.6.0: HashMap + VecDeque LRU (O(1) lookup), AtomicU64 stats, compiled IR cache.

use crate::ast::Stmt;
use crate::ir::IRNode;
use crate::plan::ExecutionPlan;
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, RwLock};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

// ── Cached unit: pre-computed compiled IR + plan ─────────────────────

/// A complete compiled program. Cache hits must be semantically identical to
/// freshly compiled execution, including preflight metadata.
#[derive(Clone)]
pub struct CompiledUnit {
    pub ir: Arc<[IRNode]>,
    pub plan: Arc<ExecutionPlan>,
}

// ── LRU cache (v0.6.0: HashMap + VecDeque eviction order) ───────────

pub struct TieredCache<V: Clone> {
    map: HashMap<String, CacheEntry<V>>,
    order: VecDeque<String>, // front = most-recent, back = oldest
    max_entries: usize,
    ttl: Duration,
}

pub struct CacheEntry<V> {
    value: V,
    inserted_at: Instant,
}

impl<V: Clone> TieredCache<V> {
    pub fn new(max_entries: usize, ttl_ms: u64) -> Self {
        Self {
            map: HashMap::with_capacity(max_entries.min(256)),
            order: VecDeque::with_capacity(max_entries.min(256)),
            max_entries,
            ttl: Duration::from_millis(ttl_ms),
        }
    }

    pub fn get(&mut self, key: &str) -> Option<V> {
        if let Some(entry) = self.map.get(key) {
            if entry.inserted_at.elapsed() < self.ttl {
                // Promote to front (LRU touch)
                if let Some(pos) = self.order.iter().position(|k| k == key) {
                    self.order.remove(pos);
                }
                self.order.push_front(key.to_string());
                return Some(entry.value.clone());
            }
        }
        None
    }

    pub fn insert(&mut self, key: String, value: V) {
        // Remove old entry
        self.map.remove(&key);
        self.order.retain(|k| k != &key);

        self.map.insert(key.clone(), CacheEntry {
            value,
            inserted_at: Instant::now(),
        });
        self.order.push_front(key);

        // Evict oldest if over capacity
        while self.order.len() > self.max_entries {
            if let Some(oldest) = self.order.pop_back() {
                self.map.remove(&oldest);
            }
        }
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }
}

// ── System snapshot (unchanged) ──────────────────────────────────────

#[derive(Clone)]
pub struct SystemSnapshot {
    pub cpu_info: crate::value::Value,
    pub mem_info: crate::value::Value,
    pub disk_info: crate::value::Value,
    pub load_avg: crate::value::Value,
    pub hostname: String,
    pub os: String,
    pub process_list: crate::value::Value,
    pub sys_info: crate::value::Value,
    pub taken_at: Instant,
    pub ttl: Duration,
}

impl SystemSnapshot {
    pub fn expired(&self) -> bool {
        self.taken_at.elapsed() >= self.ttl
    }
}

impl Default for SystemSnapshot {
    fn default() -> Self {
        Self {
            cpu_info: crate::value::Value::Null,
            mem_info: crate::value::Value::Null,
            disk_info: crate::value::Value::Null,
            load_avg: crate::value::Value::Null,
            hostname: String::new(),
            os: String::new(),
            process_list: crate::value::Value::Null,
            sys_info: crate::value::Value::Null,
            taken_at: Instant::now() - Duration::from_secs(3600),
            ttl: Duration::from_secs(5),
        }
    }
}

// ── Global cache (v0.6.0: atomic stats, compiled IR tier) ────────────

pub struct GlobalCache {
    /// AST cache: source code → parsed statements (never expires)
    pub ast: RwLock<TieredCache<Arc<Vec<Stmt>>>>,
    /// Compiled IR cache: source → compiled IR + plan + caps (never expires)
    pub compiled: RwLock<TieredCache<Arc<CompiledUnit>>>,
    /// System snapshot: cached sys_info results (TTL-based)
    pub sys: RwLock<SystemSnapshot>,
    /// Stats counters (atomic — no write lock needed for increment)
    pub stats: CacheStats,
}

pub struct CacheStats {
    pub ast_hits: AtomicU64,
    pub ast_misses: AtomicU64,
    pub ir_hits: AtomicU64,
    pub ir_misses: AtomicU64,
    pub sys_hits: AtomicU64,
    pub sys_misses: AtomicU64,
    pub total_requests: AtomicU64,
}

impl GlobalCache {
    pub fn new(max_entries: usize, sys_ttl_ms: u64) -> Arc<Self> {
        Arc::new(Self {
            ast: RwLock::new(TieredCache::new(max_entries, u64::MAX)),
            compiled: RwLock::new(TieredCache::new(max_entries, u64::MAX)),
            sys: RwLock::new(SystemSnapshot {
                ttl: Duration::from_millis(sys_ttl_ms),
                ..Default::default()
            }),
            stats: CacheStats {
                ast_hits: AtomicU64::new(0),
                ast_misses: AtomicU64::new(0),
                ir_hits: AtomicU64::new(0),
                ir_misses: AtomicU64::new(0),
                sys_hits: AtomicU64::new(0),
                sys_misses: AtomicU64::new(0),
                total_requests: AtomicU64::new(0),
            },
        })
    }

    // ── AST cache ──────────────────────────────────────────────────

    pub fn get_ast(&self, source: &str) -> Option<Arc<Vec<Stmt>>> {
        let mut cache = self.ast.write().unwrap();
        let result = cache.get(source);
        if result.is_some() {
            self.stats.ast_hits.fetch_add(1, Ordering::Relaxed);
        } else {
            self.stats.ast_misses.fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    pub fn put_ast(&self, source: String, stmts: Vec<Stmt>) {
        self.ast.write().unwrap().insert(source, Arc::new(stmts));
    }

    // ── Compiled IR cache (v0.6.0) ─────────────────────────────────

    pub fn get_compiled(&self, source: &str) -> Option<Arc<CompiledUnit>> {
        let mut cache = self.compiled.write().unwrap();
        let result = cache.get(source);
        if result.is_some() {
            self.stats.ir_hits.fetch_add(1, Ordering::Relaxed);
        } else {
            self.stats.ir_misses.fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    pub fn put_compiled(&self, source: String, unit: CompiledUnit) {
        self.compiled.write().unwrap().insert(source, Arc::new(unit));
    }

    // ── System snapshot ────────────────────────────────────────────

    pub fn get_sys_snapshot(&self) -> Option<SystemSnapshot> {
        let snap = self.sys.read().unwrap().clone();
        if snap.cpu_info != crate::value::Value::Null && !snap.expired() {
            self.stats.sys_hits.fetch_add(1, Ordering::Relaxed);
            Some(snap)
        } else {
            self.stats.sys_misses.fetch_add(1, Ordering::Relaxed);
            None
        }
    }

    pub fn put_sys_snapshot(&self, snap: SystemSnapshot) {
        *self.sys.write().unwrap() = snap;
    }

    pub fn inc_requests(&self) {
        self.stats.total_requests.fetch_add(1, Ordering::Relaxed);
    }

    // ── Snapshot stats (for STATS command) ─────────────────────────

    pub fn snapshot_stats(&self) -> CacheStatsSnapshot {
        CacheStatsSnapshot {
            ast_hits: self.stats.ast_hits.load(Ordering::Relaxed),
            ast_misses: self.stats.ast_misses.load(Ordering::Relaxed),
            ir_hits: self.stats.ir_hits.load(Ordering::Relaxed),
            ir_misses: self.stats.ir_misses.load(Ordering::Relaxed),
            sys_hits: self.stats.sys_hits.load(Ordering::Relaxed),
            sys_misses: self.stats.sys_misses.load(Ordering::Relaxed),
            total_requests: self.stats.total_requests.load(Ordering::Relaxed),
            ast_cache_size: self.ast.read().unwrap().len(),
            ir_cache_size: self.compiled.read().unwrap().len(),
        }
    }

    // ── File index cache ───────────────────────────────────────────

    pub fn get_file_index(&self, dir: &std::path::Path) -> Option<Arc<Vec<Stmt>>> {
        self.get_ast(&format!("__file_ls:{}", dir.display()))
    }

    pub fn put_file_index(&self, dir: &std::path::Path, stmts: Vec<Stmt>) {
        self.put_ast(format!("__file_ls:{}", dir.display()), stmts);
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct CacheStatsSnapshot {
    pub ast_hits: u64,
    pub ast_misses: u64,
    pub ir_hits: u64,
    pub ir_misses: u64,
    pub sys_hits: u64,
    pub sys_misses: u64,
    pub total_requests: u64,
    pub ast_cache_size: usize,
    pub ir_cache_size: usize,
}
