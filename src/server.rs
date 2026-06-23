//! JSON-RPC stdio server — v2.1 with streaming protocol + scheduler.
//!
//! Streaming protocol messages (line-delimited JSON):
//!   {"type":"done", "id":"req-1", "value": {...}, "meta": {...}}
//!   {"type":"error", "id":"req-1", "error": {...}}

use crate::runtime::{AgentRequest, RuntimeConfig, SharedRuntime};
use crate::scheduler;
use anyhow::Result;
use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

pub struct ServerConfig {
    pub transport: Transport,
    pub runtime_config: RuntimeConfig,
    pub num_workers: usize,
    pub cpu_budget_per_agent: usize,
    pub mem_budget_per_agent: u64,
    pub enable_scheduler: bool,
}

pub enum Transport { Stdio }

pub fn run_server(config: ServerConfig) -> Result<()> {
    let rt = SharedRuntime::new(config.runtime_config);
    if config.enable_scheduler {
        scheduler::init_global_scheduler(config.num_workers, config.cpu_budget_per_agent, config.mem_budget_per_agent);
        eprintln!("[ae-serve] scheduler started (workers={})", config.num_workers);
    }
    match config.transport { Transport::Stdio => serve_stdio(rt, config.enable_scheduler) }
}

#[derive(Serialize)]
struct StreamDone {
    #[serde(rename = "type")] msg_type: &'static str,
    id: String, ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")] value: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")] error: Option<crate::runtime::AgentError>,
    meta: crate::runtime::ResponseMeta,
}

fn serve_stdio(runtime: SharedRuntime, use_scheduler: bool) -> Result<()> {
    let stdin = std::io::stdin();
    let reader = BufReader::new(stdin.lock());
    let out: Arc<Mutex<()>> = Arc::new(Mutex::new(()));

    eprintln!("[ae-serve] JSON-RPC v2.1 ready (scheduler={})", use_scheduler);

    let gc_rt = runtime.clone_ref();
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(60));
        let evicted = gc_rt.gc(); gc_rt.refresh_snapshot();
        if evicted > 0 { eprintln!("[ae-serve] GC: evicted {} idle sessions", evicted); }
    });

    for line in reader.lines() {
        let line = match line { Ok(l) => l, Err(_) => break };
        let t = line.trim();
        if t.is_empty() { continue; }

        if t == "SHUTDOWN" { break; }
        if t == "STATS" {
            let mut s = serde_json::to_value(runtime.stats()).unwrap_or_default();
            if let Some(ss) = scheduler::global_scheduler() {
                if let serde_json::Value::Object(ref mut m) = s {
                    m.insert("scheduler".into(), serde_json::to_value(ss.stats()).unwrap_or_default());
                }
            }
            let _l = out.lock().unwrap(); println!("{}", s); continue;
        }
        if t == "GC" {
            let evicted = runtime.gc(); runtime.refresh_snapshot();
            let _l = out.lock().unwrap();
            println!("{}", serde_json::json!({"id":"__gc__","ok":true,"value":{"evicted":evicted}}));
            continue;
        }
        if t == "REFRESH" {
            runtime.refresh_snapshot();
            let _l = out.lock().unwrap();
            println!("{}", serde_json::json!({"id":"__refresh__","ok":true,"value":"snapshot refreshed"}));
            continue;
        }

        let requests: Vec<AgentRequest> = if t.starts_with('[') {
            match serde_json::from_str::<Vec<AgentRequest>>(t) {
                Ok(r) => r,
                Err(e) => { let _l = out.lock().unwrap(); println!("{}", serde_json::json!({"type":"error","id":null,"ok":false,"error":{"code":"E_PARSE","message":e.to_string(),"recoverable":true}})); continue; }
            }
        } else {
            match serde_json::from_str::<AgentRequest>(t) {
                Ok(r) => vec![r],
                Err(e) => { let _l = out.lock().unwrap(); println!("{}", serde_json::json!({"type":"error","id":null,"ok":false,"error":{"code":"E_PARSE","message":e.to_string(),"recoverable":true}})); continue; }
            }
        };

        for req in requests {
            let rt = runtime.clone_ref();
            let lock = Arc::clone(&out);
            if use_scheduler {
                let agent = req.agent.clone(); let rid = req.id.clone();
                scheduler::dispatch(&agent, scheduler::Priority::Normal, 1000, move || {
                    let r = rt.execute(req);
                    let msg = StreamDone { msg_type: "done", id: rid, ok: r.ok, value: r.value, error: r.error, meta: r.meta };
                    if let Ok(j) = serde_json::to_string(&msg) { let _l = lock.lock().unwrap(); println!("{}", j); }
                });
            } else {
                let rid = req.id.clone();
                let r = rt.execute(req);
                let msg = StreamDone { msg_type: "done", id: rid, ok: r.ok, value: r.value, error: r.error, meta: r.meta };
                let _l = lock.lock().unwrap();
                println!("{}", serde_json::to_string(&msg).unwrap_or_default());
            }
        }
    }
    if let Some(s) = scheduler::global_scheduler() { s.shutdown(); }
    eprintln!("[ae-serve] server stopped");
    Ok(())
}
