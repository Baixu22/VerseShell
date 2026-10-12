use criterion::{criterion_group, criterion_main, Criterion};
use serde_json::json;
use std::time::Duration;
use verseshell::artifact::ArtifactStore;
use verseshell::operation::{ObservationBudget, OperationRegistry, OperationRequest};

fn benchmark_observation(c: &mut Criterion) {
    let workspace = std::env::temp_dir().join("verseshell-observation-bench");
    std::fs::create_dir_all(&workspace).unwrap();
    std::env::set_var("AETHER_WORKSPACE", &workspace);

    let store = ArtifactStore::new(&workspace).unwrap();
    let payload = vec![b'x'; 1024 * 1024];
    c.bench_function("artifact_store_1mb", |b| {
        b.iter(|| {
            store
                .store(&payload, "utf-8", "stdout", "benchmark", "bench")
                .unwrap()
        })
    });

    #[cfg(windows)]
    let argv = json!([
        "cmd",
        "/C",
        "for /L %i in (1,1,20) do @echo installing package %i"
    ]);
    #[cfg(not(windows))]
    let argv = json!([
        "sh",
        "-c",
        "for i in $(seq 1 20); do echo installing package $i; done"
    ]);
    let registry = OperationRegistry::new();
    let request = || OperationRequest {
        id: "bench".into(),
        agent: "bench".into(),
        op: "exec.run".into(),
        args: json!({"argv": argv, "cwd": ".", "profile": "npm_install", "artifact": "auto"}),
        timeout_ms: 30_000,
        budget: ObservationBudget { max_tokens: 4_000 },
    };
    let sample = registry.execute(request());
    let data = sample.data.as_ref().unwrap();
    eprintln!(
        "observation metrics: raw_bytes={} returned_bytes={} token_estimate={} elapsed_ms={} reduction={:.2}%",
        data["stdout"]["raw_bytes"].as_u64().unwrap_or(0),
        data["stdout"]["returned_bytes"].as_u64().unwrap_or(0),
        sample.meta.token_estimate,
        sample.meta.elapsed_ms,
        100.0 * (1.0 - data["stdout"]["returned_bytes"].as_f64().unwrap_or(0.0)
            / data["stdout"]["raw_bytes"].as_f64().unwrap_or(1.0))
    );
    c.bench_function("agent_noisy_success_observation", |b| {
        b.iter(|| registry.execute(request()))
    });

    let _ = std::fs::remove_dir_all(workspace);
}

criterion_group! {
    name = benches;
    config = Criterion::default()
        .sample_size(10)
        .warm_up_time(Duration::from_secs(1))
        .measurement_time(Duration::from_secs(2));
    targets = benchmark_observation
}
criterion_main!(benches);
