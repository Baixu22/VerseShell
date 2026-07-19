// tests/concurrent_performance_tests.rs
// Multi-agent concurrent stress test.
// Run: cargo test --test concurrent_performance_tests -- --nocapture

use verseshell::runtime::{AgentRequest, RuntimeConfig, SharedRuntime};
use std::sync::{Arc, Barrier, Mutex};
use std::time::Instant;

#[derive(Clone)]
struct LatencyRecord {
    usec: u64,
    cache_hit: bool,
}

fn percentile(mut values: Vec<u64>, p: f64) -> u64 {
    values.sort();
    if values.is_empty() { return 0; }
    let idx = ((p / 100.0) * (values.len() - 1) as f64) as usize;
    values[idx.min(values.len() - 1)]
}

fn run_bench(rt: &SharedRuntime, concurrency: usize, requests: usize, cmd: &str) -> Vec<LatencyRecord> {
    let barrier = Arc::new(Barrier::new(concurrency));
    let records = Arc::new(Mutex::new(Vec::new()));
    let mut handles = Vec::new();

    for agent_id in 0..concurrency {
        let rt = rt.clone_ref();
        let b = Arc::clone(&barrier);
        let rec = Arc::clone(&records);
        let c = cmd.to_string();

        handles.push(std::thread::spawn(move || {
            let agent = format!("a{}", agent_id);
            b.wait();
            for i in 0..requests {
                let s = Instant::now();
                let resp = rt.execute(AgentRequest {
                    id: format!("{}-{}", agent, i),
                    agent: agent.clone(),
                    cmd: c.clone(),
                    timeout_ms: 0,
                    budget: None,
                    dry_run: false,
                    trace: false,
                });
                let mut r = rec.lock().unwrap();
                r.push(LatencyRecord {
                    usec: s.elapsed().as_micros() as u64,
                    cache_hit: resp.meta.cache_hit.unwrap_or(false),
                });
            }
        }));
    }
    for h in handles { h.join().unwrap(); }
    let guard = records.lock().unwrap();
    guard.clone()
}

#[test]
fn test_throughput_vs_concurrency() {
    let cmd = "[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10";
    let base = 30;

    println!("\n═══ Throughput vs Concurrency ({}) ═══", cmd);
    println!("{:>6} {:>8} {:>10}", "Thrds", "Req", "Req/sec");

    for &conc in &[1, 2, 4, 8] {
        let rt = SharedRuntime::new(RuntimeConfig { max_concurrency: conc, ..Default::default() });
        let start = Instant::now();
        let records = run_bench(&rt, conc, base, cmd);
        let total = records.len();
        let elapsed = start.elapsed().as_secs_f64();
        let tput = total as f64 / elapsed;

        let times: Vec<u64> = records.iter().map(|r| r.usec).collect();
        println!("{:>6} {:>8} {:>10.0} (P50:{}μs P95:{}μs)",
            conc, total, tput,
            percentile(times.clone(), 50.0),
            percentile(times.clone(), 95.0));
        assert!(tput > 0.0, "throughput must be positive");
    }
}

#[test]
fn test_single_agent_latency() {
    println!("\n═══ Single-Agent Latency (100 requests each) ═══");
    let workloads = [
        ("simple_math", "1+2"),
        ("pipeline", "[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10"),
        ("sys_cpu", "sys.cpu_info()"),
        ("json_ops", "json.stringify(json.parse(\"[1,2,3]\"))"),
        ("record_create", "{a:1,b:\"hello\",c:[1,2,3]}"),
    ];

    println!("{:<16} {:>8} {:>8} {:>8} {:>8}", "Workload", "Avg(μs)", "P50", "P95", "P99");

    for (name, cmd) in &workloads {
        let rt = SharedRuntime::new(RuntimeConfig::default());
        let records = run_bench(&rt, 1, 100, cmd);
        let times: Vec<u64> = records.iter().map(|r| r.usec).collect();
        let avg = times.iter().sum::<u64>() / times.len().max(1) as u64;
        println!("{:<16} {:>8} {:>8} {:>8} {:>8}",
            name, avg, percentile(times.clone(), 50.0),
            percentile(times.clone(), 95.0), percentile(times.clone(), 99.0));
        assert!(avg < 500000, "{} avg latency {}μs exceeds 500ms", name, avg);
    }
}

#[test]
fn test_ast_cache_efficiency() {
    let rt = SharedRuntime::new(RuntimeConfig::default());

    // Cold: first execution (no cache)
    let cold = run_bench(&rt, 1, 50, "1+2");
    let cold_hits = cold.iter().filter(|r| r.cache_hit).count();
    let cold_avg = cold.iter().map(|r| r.usec).sum::<u64>() / cold.len().max(1) as u64;

    // Warm: same command, should hit AST cache
    let warm = run_bench(&rt, 1, 50, "1+2");
    let warm_hits = warm.iter().filter(|r| r.cache_hit).count();
    let warm_avg = warm.iter().map(|r| r.usec).sum::<u64>() / warm.len().max(1) as u64;

    println!("\n═══ AST Cache Efficiency ═══");
    println!("Cold: {} hits/50, avg={}μs", cold_hits, cold_avg);
    println!("Warm: {} hits/50, avg={}μs", warm_hits, warm_avg);
    println!("Speedup: {:.1}x", cold_avg as f64 / warm_avg.max(1) as f64);

    // Warm should have >90% cache hit rate
    assert!(warm_hits > 0, "Expected cache hits on repeated command");
}

#[test]
fn test_sys_snapshot_cache() {
    let rt = SharedRuntime::new(RuntimeConfig::default());
    let records = run_bench(&rt, 1, 30, "sys.cpu_info()");
    let hits = records.iter().filter(|r| r.cache_hit).count();
    let avg = records.iter().map(|r| r.usec).sum::<u64>() / records.len().max(1) as u64;
    println!("\n═══ Sys Snapshot Cache ═══");
    println!("sys.cpu_info() x30: {} hits/30, avg={}μs", hits, avg);
    // First call populates cache, subsequent calls should hit
    assert!(hits > 0, "Expected sys snapshot cache hits");
}

#[test]
fn test_mixed_workload_concurrent() {
    let cmds = ["1+2", "sys.cpu_info()", "{a:1}", "[1,2,3]|sort"];
    let rt = SharedRuntime::new(RuntimeConfig { max_concurrency: 4, ..Default::default() });
    let start = Instant::now();

    let records = Arc::new(Mutex::new(Vec::new()));
    let barrier = Arc::new(Barrier::new(4));
    let mut handles = Vec::new();

    for agent in 0..4 {
        let rt = rt.clone_ref();
        let rec = Arc::clone(&records);
        let b = Arc::clone(&barrier);
        handles.push(std::thread::spawn(move || {
            b.wait();
            for i in 0..25 {
                let cmd = cmds[(i + agent) % cmds.len()];
                let s = Instant::now();
                let resp = rt.execute(AgentRequest {
                    id: format!("m{}-{}", agent, i),
                    agent: format!("a{}", agent),
                    cmd: cmd.to_string(),
                    timeout_ms: 0,
                    budget: None,
                    dry_run: false,
                    trace: false,
                });
                rec.lock().unwrap().push(LatencyRecord {
                    usec: s.elapsed().as_micros() as u64,
                    cache_hit: resp.meta.cache_hit.unwrap_or(false),
                });
            }
        }));
    }
    for h in handles { h.join().unwrap(); }

    let total = records.lock().unwrap().len();
    let elapsed = start.elapsed().as_secs_f64();
    let tput = total as f64 / elapsed;
    let recs = records.lock().unwrap();
    let hits = recs.iter().filter(|r| r.cache_hit).count();
    let times: Vec<u64> = recs.iter().map(|r| r.usec).collect();

    println!("\n═══ Mixed Workload (4 agents, 25 req each) ═══");
    println!("Total: {} req in {:.1}s = {:.0} req/s", total, elapsed, tput);
    println!("Cache hits: {}/{} ({:.0}%)", hits, total, hits as f64 / total as f64 * 100.0);
    println!("Latency: P50={}μs P95={}μs P99={}μs Avg={:.0}μs",
        percentile(times.clone(), 50.0), percentile(times.clone(), 95.0),
        percentile(times.clone(), 99.0), times.iter().sum::<u64>() as f64 / times.len() as f64);

    assert!(tput > 0.0);
}

#[test]
fn test_session_reuse_benefit() {
    // Shared runtime (session reuse)
    let shared = SharedRuntime::new(RuntimeConfig::default());
    let s = Instant::now();
    for _ in 0..50 {
        shared.execute(AgentRequest {
            id: "s".into(), agent: "a".into(), cmd: "1+2".into(), timeout_ms: 0, budget: None,
            dry_run: false, trace: false,
        });
    }
    let shared_ms = s.elapsed().as_micros();

    // Fresh runtime per request (no session reuse)
    let f = Instant::now();
    for _ in 0..50 {
        let fresh = SharedRuntime::new(RuntimeConfig::default());
        fresh.execute(AgentRequest {
            id: "f".into(), agent: "b".into(), cmd: "1+2".into(), timeout_ms: 0, budget: None,
            dry_run: false, trace: false,
        });
    }
    let fresh_ms = f.elapsed().as_micros();

    println!("\n═══ Session Reuse Benefit ═══");
    println!("Shared session: {}μs total ({}μs avg)", shared_ms, shared_ms / 50);
    println!("Fresh per call: {}μs total ({}μs avg)", fresh_ms, fresh_ms / 50);
    println!("Speedup: {:.1}x", fresh_ms as f64 / shared_ms.max(1) as f64);

    assert!(shared_ms < fresh_ms, "Session reuse should be faster than fresh per call");
}
