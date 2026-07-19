//! ACI-Bench mock acceptance: Condition D must beat raw_shell on the gate.

use std::path::PathBuf;
use std::process::Command;

#[test]
fn aci_bench_mock_meets_acceptance_gate() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let runner = root.join("bench/aci/runners/run_suite.py");
    let scorer = root.join("bench/aci/scorers/score.py");
    let latest = root.join("bench/aci/results/latest.json");

    let py = if Command::new("python").arg("--version").output().is_ok() {
        "python"
    } else {
        "python3"
    };

    let status = Command::new(py)
        .arg(&runner)
        .arg("--mode")
        .arg("mock")
        .current_dir(&root)
        .status()
        .expect("spawn run_suite");
    assert!(status.success(), "run_suite.py failed");
    assert!(latest.exists(), "latest.json missing");

    let status = Command::new(py)
        .arg(&scorer)
        .arg(&latest)
        .arg("--require-accept")
        .current_dir(&root)
        .status()
        .expect("spawn score");
    assert!(status.success(), "acceptance gate failed — see bench/aci/results/REPORT.md");
}
