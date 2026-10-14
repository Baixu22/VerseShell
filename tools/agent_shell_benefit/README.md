# Agent-shell positive-benefit experiment

This directory implements the frozen handoff:

- `docs/dev/handoffs/AGENT-SHELL-POSITIVE-BENEFIT-2026-10-12.md`
- 10 tasks × 3 arms × 1 seed = 30 cells
- execution layer: `microsandbox 0.7.8`
- model: `step-5-preview`
- arms: `A` raw shell, `A_prime` matched raw prompt, `D` VerseShell observation
- verdicts: `POSITIVE`, `NO_EVIDENCE`, `INVALID`

## Important boundary

All arms execute commands in the same persistent Python microVM. Provider D copies
the current Linux `ae` binary into that microVM and invokes `ae exec.run` there,
so the returned `verseshell.observation/v1` envelope is produced by the real
VerseShell binary, not by a synthetic schema in the Python harness.

The Linux binary is built from the current checkout with only mechanical
variable-name fixes required by pre-existing Linux compile errors in
`src/builtins.rs`. The binary hash is frozen into the round manifest and must be
recorded by the operator. The repository source is not modified by the harness.

## Commands

```powershell
# Exact host-side contract check against the Windows build.
cargo build --release --bin ae
python tools\agent_shell_benefit\contract_check.py --ae .\target\release\ae.exe

# P1 smoke: T01-T03, all arms.
python tools\agent_shell_benefit\run_round.py `
  --round-id p1-20261012 `
  --output-root D:\VerseShellEval\agent-shell-benefit `
  --tasks T01,T02,T03 --arms all --seed 42 --resume

# Complete P1, preserving the nine smoke cells.
python tools\agent_shell_benefit\run_round.py `
  --round-id p1-20261012 `
  --output-root D:\VerseShellEval\agent-shell-benefit `
  --tasks all --arms all --seed 42 --resume

python tools\agent_shell_benefit\rescore.py `
  --round-dir D:\VerseShellEval\agent-shell-benefit\p1-20261012
python tools\agent_shell_benefit\report.py `
  --round-dir D:\VerseShellEval\agent-shell-benefit\p1-20261012
```

The runner never deletes a failed sample. A failed cell is retained and is
counted in the anomaly and oracle tables. Use a new round id after any frozen
task, prompt, binary, execution-layer, model, or oracle change.

## 80-task suite (four tiers)

Beyond the 10-task P1 harness, `suite/` implements an 80-task comprehensive suite
(4 tiers x 20) aimed at complex strategies and high-concurrency handling:

- L1 simple (T101-T120), L2 medium (T201-T220), L3 hard (T301-T320), L4 devil (T401-T420).
- Declarative tasks + a composable oracle engine (`suite/oracles.py`); no per-task Python.
- Coverage axes: strategy, recovery, concurrency, lifecycle, safety, artifact.
- Every task requires a verifiable artifact or trace check (no summary-only oracles).
- Concurrency is measured directly: parallel_used, parallel_result_count,
  parallel_wall_lt, plus race/lock/cascade tasks.

```powershell
python tools\agent_shell_benefit\suite\run_suite.py --round-id suite-p1-20261012 --tiers L1 --arms all --seed 42 --resume
python tools\agent_shell_benefit\suite\rescore_suite.py --round-dir D:\VerseShellEval\agent-shell-benefit\suite-p1-20261012
```

Full 80 x 3 arms = 240 cells and will exceed the 2h default budget; confirm scope
before launching. See docs/agent-shell-suite-80-design-2026-10-12.md.