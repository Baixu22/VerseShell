//! V2.1 Work-stealing scheduler with per-agent resource quotas.
//!
//! Architecture:
//!   ┌─────────────────────────────────────────────┐
//!   │              JobScheduler                    │
//!   │  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐   │
//!   │  │Worker1│ │Worker2│ │Worker3│ │Worker4│   │
//!   │  │ queue │ │ queue │ │ queue │ │ queue │   │
//!   │  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘   │
//!   │      │         │         │         │        │
//!   │      └────┬────┴────┬────┴────┬────┘        │
//!   │           │  work-stealing  │               │
//!   │           └─────────────────┘               │
//!   └─────────────────────────────────────────────┘
//!
//!   Per-agent quotas:
//!     - CPU budget (max concurrent ops)
//!     - Memory budget (soft limit on Env state)
//!     - Rate limit (req/s, enforced by runtime.rs)

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex, RwLock};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

// ── Job ────────────────────────────────────────────────────────────────

/// A unit of work submitted to the scheduler.
pub type Job = Box<dyn FnOnce() + Send + 'static>;

/// Priority levels for scheduling fairness.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    Low = 0,
    Normal = 1,
    High = 2,
    Critical = 3,
}

/// Job with metadata for scheduling decisions.
struct ScheduledJob {
    job: Job,
    priority: Priority,
    agent_id: String,
    submitted_at: Instant,
    estimated_cost_us: u64,
}

// ── Worker ─────────────────────────────────────────────────────────────

struct Worker {
    id: usize,
    queue: Mutex<VecDeque<ScheduledJob>>,
    condvar: Condvar,
    idle: AtomicU64, // nanoseconds spent idle
    jobs_completed: AtomicU64,
}

impl Worker {
    fn new(id: usize) -> Self {
        Self {
            id,
            queue: Mutex::new(VecDeque::new()),
            condvar: Condvar::new(),
            idle: AtomicU64::new(0),
            jobs_completed: AtomicU64::new(0),
        }
    }
}

// ── Agent Quota ────────────────────────────────────────────────────────

/// Per-agent resource quota tracking.
#[derive(Debug)]
struct AgentQuota {
    /// Max concurrent jobs for this agent.
    cpu_budget: usize,
    /// Currently active job count.
    active_jobs: AtomicUsize,
    /// Soft memory limit (bytes) for session state.
    mem_budget: u64,
    /// Total jobs submitted by this agent.
    total_submitted: AtomicU64,
    /// Total jobs completed by this agent.
    total_completed: AtomicU64,
    /// Total CPU time consumed (microseconds).
    total_cpu_us: AtomicU64,
}

impl AgentQuota {
    fn new(cpu_budget: usize, mem_budget: u64) -> Self {
        Self {
            cpu_budget,
            active_jobs: AtomicUsize::new(0),
            mem_budget,
            total_submitted: AtomicU64::new(0),
            total_completed: AtomicU64::new(0),
            total_cpu_us: AtomicU64::new(0),
        }
    }

    /// Try to acquire a CPU slot. Returns true if allowed.
    fn try_acquire(&self) -> bool {
        let current = self.active_jobs.load(Ordering::Relaxed);
        if current >= self.cpu_budget {
            return false;
        }
        self.active_jobs.fetch_add(1, Ordering::Relaxed) <= self.cpu_budget
    }

    fn release(&self) {
        self.active_jobs.fetch_sub(1, Ordering::Relaxed);
    }
}

// ── Scheduler ──────────────────────────────────────────────────────────

pub struct JobScheduler {
    workers: Vec<Arc<Worker>>,
    quotas: RwLock<std::collections::HashMap<String, Arc<AgentQuota>>>,
    default_cpu_budget: usize,
    default_mem_budget: u64,
    running: AtomicU64, // 1 = running, 0 = stopped
    handles: Mutex<Vec<JoinHandle<()>>>,
}

impl JobScheduler {
    /// Create a new scheduler with N worker threads.
    pub fn new(num_workers: usize, default_cpu_budget: usize, default_mem_budget: u64) -> Arc<Self> {
        let mut workers = Vec::with_capacity(num_workers);
        for i in 0..num_workers {
            workers.push(Arc::new(Worker::new(i)));
        }

        let scheduler = Arc::new(Self {
            workers: workers.clone(),
            quotas: RwLock::new(std::collections::HashMap::new()),
            default_cpu_budget,
            default_mem_budget,
            running: AtomicU64::new(1),
            handles: Mutex::new(Vec::new()),
        });

        // Start worker threads
        let mut handles = Vec::new();
        for worker in &workers {
            let w = Arc::clone(worker);
            let s = Arc::clone(&scheduler);
            let h = thread::Builder::new()
                .name(format!("ae-worker-{}", w.id))
                .spawn(move || worker_loop(w, s))
                .expect("failed to spawn worker thread");
            handles.push(h);
        }
        *scheduler.handles.lock().unwrap() = handles;

        scheduler
    }

    /// Submit a job for execution. CPU quota limits concurrently running work;
    /// queued work is accepted so brief bursts are not dropped.
    pub fn submit(
        &self,
        agent_id: &str,
        priority: Priority,
        job: Job,
        estimated_cost_us: u64,
    ) -> bool {
        if self.running.load(Ordering::Relaxed) == 0 {
            return false;
        }

        // Ensure quota/accounting exists. The slot is acquired by a worker
        // immediately before execution, not while the job is merely queued.
        let quota = self.get_or_create_quota(agent_id);
        quota.total_submitted.fetch_add(1, Ordering::Relaxed);

        let scheduled = ScheduledJob {
            job,
            priority,
            agent_id: agent_id.to_string(),
            submitted_at: Instant::now(),
            estimated_cost_us,
        };

        // Find the least loaded worker (by queue depth)
        let target = self
            .workers
            .iter()
            .min_by_key(|w| w.queue.lock().unwrap().len())
            .unwrap();

        let mut queue = target.queue.lock().unwrap();
        // Insert in priority order within queue
        let pos = queue
            .iter()
            .position(|j| j.priority < priority)
            .unwrap_or(queue.len());
        queue.insert(pos, scheduled);
        drop(queue);
        target.condvar.notify_one();

        true
    }

    /// Get or create per-agent quota.
    fn get_or_create_quota(&self, agent_id: &str) -> Arc<AgentQuota> {
        let quotas = self.quotas.read().unwrap();
        if let Some(q) = quotas.get(agent_id) {
            return Arc::clone(q);
        }
        drop(quotas);
        let mut quotas = self.quotas.write().unwrap();
        let q = Arc::new(AgentQuota::new(self.default_cpu_budget, self.default_mem_budget));
        quotas.insert(agent_id.to_string(), Arc::clone(&q));
        q
    }

    /// Release a CPU slot for an agent.
    fn release_quota(&self, agent_id: &str, cpu_us: u64) {
        if let Some(q) = self.quotas.read().unwrap().get(agent_id) {
            q.release();
            q.total_completed.fetch_add(1, Ordering::Relaxed);
            q.total_cpu_us.fetch_add(cpu_us, Ordering::Relaxed);
        }
    }

    /// Steal a job from another worker's queue if available.
    fn steal_job(&self, thief_id: usize) -> Option<ScheduledJob> {
        // Try to steal from the worker with the longest queue
        let targets: Vec<_> = self
            .workers
            .iter()
            .filter(|w| w.id != thief_id)
            .collect();

        // Shuffle to avoid herd behavior
        let mut targets = targets;
        // Use simple pseudo-random based on current time
        let seed = Instant::now().elapsed().as_nanos() as usize;
        // Fisher-Yates shuffle
        for i in (1..targets.len()).rev() {
            let j = seed.wrapping_mul(i + 1) % (i + 1);
            targets.swap(i, j);
        }

        for target in &targets {
            let mut queue = target.queue.lock().unwrap();
            // Steal from the back (oldest low-priority job)
            if let Some(pos) = queue.iter().rposition(|j| j.priority <= Priority::Normal) {
                return Some(queue.remove(pos).unwrap());
            }
        }
        None
    }

    /// Get scheduler statistics.
    pub fn stats(&self) -> SchedulerStats {
        let mut stats = SchedulerStats::default();
        for w in &self.workers {
            stats.total_jobs += w.jobs_completed.load(Ordering::Relaxed);
        }
        stats.workers = self.workers.len();
        stats.agent_quotas = self.quotas.read().unwrap().len();
        stats.running = self.running.load(Ordering::Relaxed) == 1;
        stats
    }

    /// Graceful shutdown: stop accepting new jobs, drain queues, join workers.
    pub fn shutdown(&self) {
        self.running.store(0, Ordering::Relaxed);
        // Wake all workers
        for w in &self.workers {
            w.condvar.notify_all();
        }
        let mut handles = self.handles.lock().unwrap();
        for h in handles.drain(..) {
            h.join().ok();
        }
    }
}

// ── Worker Loop ────────────────────────────────────────────────────────

fn worker_loop(worker: Arc<Worker>, scheduler: Arc<JobScheduler>) {
    let idle_poll = Duration::from_millis(10);
    let steal_poll = Duration::from_millis(5);

    loop {
        if scheduler.running.load(Ordering::Relaxed) == 0 {
            // Drain remaining jobs before exit
            let mut queue = worker.queue.lock().unwrap();
            for job in queue.drain(..) {
                execute_job(&worker, &scheduler, job);
            }
            break;
        }

        // Try to get from own queue
        let job = {
            let mut queue = worker.queue.lock().unwrap();
            queue.pop_front()
        };

        match job {
            Some(job) => {
                execute_job(&worker, &scheduler, job);
            }
            None => {
                // Try to steal
                if let Some(job) = scheduler.steal_job(worker.id) {
                    execute_job(&worker, &scheduler, job);
                    continue;
                }
                // Wait with timeout
                let idle_start = Instant::now();
                let mut queue = worker.queue.lock().unwrap();
                let result = worker
                    .condvar
                    .wait_timeout(queue, idle_poll)
                    .unwrap();
                queue = result.0;
                // Check if a job arrived
                if let Some(job) = queue.pop_front() {
                    drop(queue);
                    execute_job(&worker, &scheduler, job);
                } else {
                    worker.idle.fetch_add(idle_start.elapsed().as_nanos() as u64, Ordering::Relaxed);
                }
            }
        }
    }
}

fn execute_job(worker: &Worker, scheduler: &JobScheduler, job: ScheduledJob) {
    let quota = scheduler.get_or_create_quota(&job.agent_id);
    while !quota.try_acquire() {
        thread::sleep(Duration::from_millis(1));
    }
    let start = Instant::now();
    (job.job)();
    let elapsed_us = start.elapsed().as_micros() as u64;
    worker.jobs_completed.fetch_add(1, Ordering::Relaxed);
    scheduler.release_quota(&job.agent_id, elapsed_us);
}

// ── Stats ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct SchedulerStats {
    pub workers: usize,
    pub total_jobs: u64,
    pub agent_quotas: usize,
    pub running: bool,
}

// ── Convenience: Global Scheduler Singleton ────────────────────────────

use std::sync::OnceLock;
static GLOBAL_SCHEDULER: OnceLock<Arc<JobScheduler>> = OnceLock::new();

/// Initialize the global scheduler. Called once at server startup.
pub fn init_global_scheduler(num_workers: usize, cpu_budget: usize, mem_budget: u64) {
    let s = JobScheduler::new(num_workers, cpu_budget, mem_budget);
    GLOBAL_SCHEDULER.set(s).ok();
}

/// Get a reference to the global scheduler.
pub fn global_scheduler() -> Option<Arc<JobScheduler>> {
    GLOBAL_SCHEDULER.get().cloned()
}

// ── Scheduler-backed Job Dispatcher ────────────────────────────────────

/// Submit a job through the global scheduler. Falls back to direct execution.
pub fn dispatch<F>(agent_id: &str, priority: Priority, estimated_cost_us: u64, f: F) -> bool
where
    F: FnOnce() + Send + 'static,
{
    if let Some(s) = global_scheduler() {
        s.submit(agent_id, priority, Box::new(f), estimated_cost_us)
    } else {
        // No global scheduler — execute directly (backward compat)
        f();
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scheduler_basic() {
        let s = JobScheduler::new(2, 4, 1024 * 1024);
        let counter = Arc::new(AtomicU64::new(0));

        for _ in 0..10 {
            let c = Arc::clone(&counter);
            assert!(s.submit("agent-a", Priority::Normal, Box::new(move || {
                c.fetch_add(1, Ordering::Relaxed);
                thread::sleep(Duration::from_millis(1));
            }), 1000));
        }

        // Wait for completion
        thread::sleep(Duration::from_millis(50));
        s.shutdown();

        assert_eq!(counter.load(Ordering::Relaxed), 10);
    }

    #[test]
    fn test_quota_enforcement() {
        let s = JobScheduler::new(2, 1, 1024 * 1024); // cpu_budget=1 per agent
        let running = Arc::new(AtomicU64::new(0));
        let max_running = Arc::new(AtomicU64::new(0));
        for _ in 0..5 {
            let running_now = Arc::clone(&running);
            let maximum = Arc::clone(&max_running);
            assert!(s.submit("agent-a", Priority::Normal, Box::new(move || {
                let active = running_now.fetch_add(1, Ordering::SeqCst) + 1;
                maximum.fetch_max(active, Ordering::SeqCst);
                thread::sleep(Duration::from_millis(5));
                running_now.fetch_sub(1, Ordering::SeqCst);
            }), 5000));
        }

        thread::sleep(Duration::from_millis(100));
        s.shutdown();
        assert_eq!(max_running.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_priority_ordering() {
        let s = JobScheduler::new(1, 4, 1024 * 1024);
        let order = Arc::new(Mutex::new(Vec::new()));

        // Occupy the only worker so low/high are both queued before selection.
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        s.submit("blocker", Priority::Normal, Box::new(move || {
            let _ = release_rx.recv();
        }), 1000);
        thread::sleep(Duration::from_millis(5));

        // Submit low priority first, then high
        let o1 = Arc::clone(&order);
        s.submit("a", Priority::Low, Box::new(move || {
            o1.lock().unwrap().push("low");
        }), 1000);

        let o2 = Arc::clone(&order);
        s.submit("a", Priority::High, Box::new(move || {
            o2.lock().unwrap().push("high");
        }), 1000);

        release_tx.send(()).unwrap();
        thread::sleep(Duration::from_millis(30));
        s.shutdown();

        let ord = order.lock().unwrap();
        // High should be processed before low (inserted at front)
        assert_eq!(ord.first().unwrap(), &"high");
    }
}
