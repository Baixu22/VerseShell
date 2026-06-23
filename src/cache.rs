//! Global cache for AST, types, and system snapshots.
//!
//! Thread-safe via `Arc<RwLock<>>` — designed for multi-agent concurrent access.

use crate::ast::Stmt;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

/// LRU-like bounded cache with TTL-based expiry.
pub struct TieredCache<V: Clone> {
    pub entries: Vec<(String, CacheEntry<V>)>,
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
            entries: Vec::with_capacity(max_entries),
            max_entries,
            ttl: Duration::from_millis(ttl_ms),
        }
    }

    pub fn get(&self, key: &str) -> Option<V> {
        for (k, entry) in &self.entries {
            if k == key && entry.inserted_at.elapsed() < self.ttl {
                return Some(entry.value.clone());
            }
        }
        None
    }

    pub fn insert(&mut self, key: String, value: V) {
        // Remove existing entry if present
        self.entries.retain(|(k, _)| k != &key);
        // Insert at front (most recent)
        self.entries.insert(
            0,
            (
                key,
                CacheEntry {
                    value,
                    inserted_at: Instant::now(),
                },
            ),
        );
        // Evict oldest if over capacity
        if self.entries.len() > self.max_entries {
            self.entries.truncate(self.max_entries);
        }
    }
}

/// System information snapshot with TTL.
#[derive(Clone)]
pub struct SystemSnapshot {
    pub cpu_info: crate::value::Value,
    pub mem_info: crate::value::Value,
    pub disk_info: crate::value::Value,
    pub load_avg: crate::value::Value,
    pub hostname: String,
    pub os: String,
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
            taken_at: Instant::now() - Duration::from_secs(3600),
            ttl: Duration::from_secs(5),
        }
    }
}

/// The global shared cache for agent runtime.
pub struct GlobalCache {
    /// AST cache: source code → parsed statements (never expires)
    pub ast: RwLock<TieredCache<Arc<Vec<Stmt>>>>,
    /// System snapshot: cached sys_info results (TTL-based)
    pub sys: RwLock<SystemSnapshot>,
    /// Stats counters
    pub stats: RwLock<CacheStats>,
}

#[derive(Default, Clone)]
pub struct CacheStats {
    pub ast_hits: u64,
    pub ast_misses: u64,
    pub sys_hits: u64,
    pub sys_misses: u64,
    pub total_requests: u64,
}

impl GlobalCache {
    pub fn new(max_ast_entries: usize, sys_ttl_ms: u64) -> Arc<Self> {
        Arc::new(Self {
            ast: RwLock::new(TieredCache::new(max_ast_entries, u64::MAX)), // AST never expires
            sys: RwLock::new(SystemSnapshot {
                ttl: Duration::from_millis(sys_ttl_ms),
                ..Default::default()
            }),
            stats: RwLock::new(CacheStats::default()),
        })
    }

    /// Try to get parsed AST from cache.
    pub fn get_ast(&self, source: &str) -> Option<Arc<Vec<Stmt>>> {
        let cache = self.ast.read().unwrap();
        let result = cache.get(source);
        let mut stats = self.stats.write().unwrap();
        if result.is_some() {
            stats.ast_hits += 1;
        } else {
            stats.ast_misses += 1;
        }
        result
    }

    /// Store parsed AST in cache.
    pub fn put_ast(&self, source: String, stmts: Vec<Stmt>) {
        self.ast.write().unwrap().insert(source, Arc::new(stmts));
    }

    /// Get cached system snapshot, or None if expired/empty.
    pub fn get_sys_snapshot(&self) -> Option<SystemSnapshot> {
        let snap = self.sys.read().unwrap().clone();
        let mut stats = self.stats.write().unwrap();
        if snap.cpu_info != crate::value::Value::Null && !snap.expired() {
            stats.sys_hits += 1;
            Some(snap)
        } else {
            stats.sys_misses += 1;
            None
        }
    }

    /// Store a fresh system snapshot.
    pub fn put_sys_snapshot(&self, snap: SystemSnapshot) {
        *self.sys.write().unwrap() = snap;
    }

    pub fn inc_requests(&self) {
        self.stats.write().unwrap().total_requests += 1;
    }

    /// File index cache: directory path → (mtime, file listing).
    /// Invalidated when the directory's mtime changes.
    pub fn get_file_index(&self, dir: &std::path::Path) -> Option<Arc<Vec<Stmt>>> {
        // For now, reuse AST cache keyed by "file.ls:PATH" for simplicity.
        // In a full implementation, this would be a separate cache with mtime invalidation.
        self.get_ast(&format!("__file_ls:{}", dir.display()))
    }

    pub fn put_file_index(&self, dir: &std::path::Path, stmts: Vec<Stmt>) {
        self.put_ast(format!("__file_ls:{}", dir.display()), stmts);
    }
}
