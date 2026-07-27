//! JSON-RPC stdio server — v2.2 with async tokio runtime (Line B Phase 3).
//!
//! Streaming protocol messages (line-delimited JSON):
//!   {"type":"done", "id":"req-1", "value": {...}, "meta": {...}}
//!   {"type":"error", "id":"req-1", "error": {...}}
//!
//! ## Phase 3 migration (Line B)
//!
//! Replaced the legacy `std::thread` + `Arc<Mutex<()>>` pipeline with an
//! async tokio runtime:
//!
//! - `tokio::io::stdin()` + `AsyncBufReadExt::lines()` for non-blocking input
//! - `std::sync::Mutex<Stdout>` for serialized writes (sync mutex is fine
//!   here because stdout writes are fast; both sync scheduler callbacks and
//!   async tasks can lock it without blocking the executor for long)
//! - `tokio::spawn` + `tokio::time::interval` for the periodic GC task
//! - `tokio::task::spawn_blocking` for CPU-bound `runtime.execute()`
//! - Batch requests (`[req1, req2, ...]`) now run concurrently via
//!   `tokio::spawn` + join loop
//!
//! The wire protocol (line-delimited JSON, `STATS`/`GC`/`REFRESH`/`SHUTDOWN`
//! control commands) is unchanged — existing clients and tests are unaffected.

use crate::operation::{Observation, OperationRegistry, OperationRequest};
use crate::runtime::{AgentRequest, RuntimeConfig, SharedRuntime};
use crate::scheduler;
use anyhow::Result;
use serde::Serialize;
use std::io::Write;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncBufReadExt, BufReader};

pub struct ServerConfig {
    pub transport: Transport,
    pub runtime_config: RuntimeConfig,
    pub num_workers: usize,
    pub cpu_budget_per_agent: usize,
    pub mem_budget_per_agent: u64,
    pub enable_scheduler: bool,
}

pub enum Transport {
    Stdio,
}

/// Synchronous entry point — builds a tokio Runtime and blocks on the async
/// server. Kept sync so `main.rs` (a sync `fn main`) can call it unchanged.
pub fn run_server(config: ServerConfig) -> Result<()> {
    let rt = SharedRuntime::new(config.runtime_config);
    if config.enable_scheduler {
        scheduler::init_global_scheduler(
            config.num_workers,
            config.cpu_budget_per_agent,
            config.mem_budget_per_agent,
        );
        eprintln!(
            "[ae-serve] scheduler started (workers={})",
            config.num_workers
        );
    }

    let tokio_rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .map_err(|e| anyhow::anyhow!("failed to build tokio runtime: {}", e))?;

    tokio_rt.block_on(serve_stdio(rt, config.enable_scheduler))
}

#[derive(Serialize)]
struct StreamDone {
    #[serde(rename = "type")]
    msg_type: &'static str,
    id: String,
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    value: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<crate::runtime::AgentError>,
    meta: crate::runtime::ResponseMeta,
}

/// Encode a response in the active format (json or compact).
fn encode_response(resp: &crate::runtime::AgentResponse) -> String {
    let use_compact = std::env::var("AE_FORMAT")
        .map(|f| f == "compact")
        .unwrap_or(false);
    if use_compact {
        crate::compact::encode_response(resp)
    } else {
        let msg = StreamDone {
            msg_type: "done",
            id: resp.id.clone(),
            ok: resp.ok,
            value: resp.value.clone(),
            error: resp.error.clone(),
            meta: resp.meta.clone(),
        };
        serde_json::to_string(&msg).unwrap_or_default()
    }
}

fn encode_observation(observation: &Observation) -> String {
    let use_compact = std::env::var("AE_FORMAT")
        .map(|f| f == "compact")
        .unwrap_or(false);
    if use_compact {
        let json = serde_json::to_value(observation).unwrap_or_default();
        format!(
            "O {}",
            crate::compact::encode_value(&crate::value::Value::from_json(&json))
        )
    } else {
        serde_json::to_string(observation).unwrap_or_default()
    }
}

enum ServerRequest {
    Legacy(AgentRequest),
    Operation(OperationRequest),
}

impl ServerRequest {
    fn agent(&self) -> &str {
        match self {
            Self::Legacy(req) => &req.agent,
            Self::Operation(req) => &req.agent,
        }
    }
}

fn parse_request(value: serde_json::Value) -> Result<ServerRequest, serde_json::Error> {
    if value.get("op").is_some() {
        serde_json::from_value(value).map(ServerRequest::Operation)
    } else {
        serde_json::from_value(value).map(ServerRequest::Legacy)
    }
}

fn execute_server_request(
    request: ServerRequest,
    runtime: &SharedRuntime,
    operations: &OperationRegistry,
) -> String {
    match request {
        ServerRequest::Legacy(req) => encode_response(&runtime.execute(req)),
        ServerRequest::Operation(req) => encode_observation(&operations.execute(req)),
    }
}

/// Write a line to stdout under the lock. Called from both async tasks and
/// sync scheduler callbacks. Blocking lock is fine here — stdout writes are
/// fast and contention is low.
fn write_line(out: &Arc<Mutex<std::io::Stdout>>, s: &str) {
    let mut guard = out.lock().unwrap();
    let _ = writeln!(guard, "{}", s);
}

/// Async stdio server. Reads line-delimited JSON requests, executes them on
/// `spawn_blocking` (CPU-bound work), and writes responses under a stdout
/// mutex so concurrent tasks don't interleave output.
async fn serve_stdio(runtime: SharedRuntime, use_scheduler: bool) -> Result<()> {
    let stdin = tokio::io::stdin();
    let reader = BufReader::new(stdin);
    let out: Arc<Mutex<std::io::Stdout>> = Arc::new(Mutex::new(std::io::stdout()));
    let operations = OperationRegistry::new();

    eprintln!(
        "[ae-serve] JSON-RPC v2.2 ready (scheduler={}, runtime=tokio)",
        use_scheduler
    );

    // ── Periodic GC task ────────────────────────────────────────────
    let gc_rt = runtime.clone_ref();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(60));
        interval.tick().await; // first tick is immediate
        loop {
            interval.tick().await;
            let evicted = gc_rt.gc();
            gc_rt.refresh_snapshot();
            if evicted > 0 {
                eprintln!("[ae-serve] GC: evicted {} idle sessions", evicted);
            }
        }
    });

    let mut lines = reader.lines();

    while let Some(line) = lines.next_line().await? {
        let t = line.trim();
        if t.is_empty() {
            continue;
        }

        if t == "SHUTDOWN" {
            break;
        }
        if t == "STATS" {
            let mut s = serde_json::to_value(runtime.stats()).unwrap_or_default();
            if let Some(ss) = scheduler::global_scheduler() {
                if let serde_json::Value::Object(ref mut m) = s {
                    m.insert(
                        "scheduler".into(),
                        serde_json::to_value(ss.stats()).unwrap_or_default(),
                    );
                }
            }
            write_line(&out, &serde_json::to_string(&s).unwrap_or_default());
            continue;
        }
        if t == "GC" {
            let evicted = runtime.gc();
            runtime.refresh_snapshot();
            let out_str = serde_json::json!({
                "id": "__gc__",
                "ok": true,
                "value": {"evicted": evicted}
            })
            .to_string();
            write_line(&out, &out_str);
            continue;
        }
        if t == "REFRESH" {
            runtime.refresh_snapshot();
            let out_str = serde_json::json!({
                "id": "__refresh__",
                "ok": true,
                "value": "snapshot refreshed"
            })
            .to_string();
            write_line(&out, &out_str);
            continue;
        }

        // ── Parse request (single or batch) ─────────────────────────
        let requests: Vec<ServerRequest> = if t.starts_with('[') {
            match serde_json::from_str::<Vec<serde_json::Value>>(t)
                .and_then(|values| values.into_iter().map(parse_request).collect())
            {
                Ok(r) => r,
                Err(e) => {
                    let out_str = serde_json::json!({
                        "type": "error",
                        "id": null,
                        "ok": false,
                        "error": {
                            "code": "E_PARSE",
                            "message": e.to_string(),
                            "recoverable": true
                        }
                    })
                    .to_string();
                    write_line(&out, &out_str);
                    continue;
                }
            }
        } else {
            match serde_json::from_str::<serde_json::Value>(t).and_then(parse_request) {
                Ok(r) => vec![r],
                Err(e) => {
                    let out_str = serde_json::json!({
                        "type": "error",
                        "id": null,
                        "ok": false,
                        "error": {
                            "code": "E_PARSE",
                            "message": e.to_string(),
                            "recoverable": true
                        }
                    })
                    .to_string();
                    write_line(&out, &out_str);
                    continue;
                }
            }
        };

        // ── Dispatch each request ───────────────────────────────────
        // Batch requests run concurrently via tokio::spawn; single requests
        // run on the current task. CPU-bound `rt.execute()` is wrapped in
        // `spawn_blocking` so the async executor stays free for I/O.
        if requests.len() == 1 {
            let req = requests.into_iter().next().unwrap();
            if use_scheduler {
                let agent = req.agent().to_string();
                let out_clone = Arc::clone(&out);
                let rt_clone = runtime.clone_ref();
                let operations_clone = operations.clone();
                scheduler::dispatch(&agent, scheduler::Priority::Normal, 1000, move || {
                    let out_str = execute_server_request(req, &rt_clone, &operations_clone);
                    write_line(&out_clone, &out_str);
                });
            } else {
                let rt_clone = runtime.clone_ref();
                let operations_clone = operations.clone();
                let out_str = tokio::task::spawn_blocking(move || {
                    execute_server_request(req, &rt_clone, &operations_clone)
                })
                .await
                .map_err(|e| anyhow::anyhow!("worker task panicked: {}", e))?;
                write_line(&out, &out_str);
            }
        } else {
            // Batch: spawn one task per request, then join all.
            let mut handles = Vec::with_capacity(requests.len());
            for req in requests {
                let rt_clone = runtime.clone_ref();
                let out_clone = Arc::clone(&out);
                let operations_clone = operations.clone();
                let handle = tokio::spawn(async move {
                    let out_str = tokio::task::spawn_blocking(move || {
                        execute_server_request(req, &rt_clone, &operations_clone)
                    })
                    .await
                    .map_err(|e| anyhow::anyhow!("worker task panicked: {}", e))?;
                    write_line(&out_clone, &out_str);
                    Ok::<(), anyhow::Error>(())
                });
                handles.push(handle);
            }
            for h in handles {
                let _ = h.await;
            }
        }
    }

    if let Some(s) = scheduler::global_scheduler() {
        s.shutdown();
    }
    eprintln!("[ae-serve] server stopped");
    Ok(())
}
