# ACI-Bench Report

- Generated: 2026-09-22T14:27:22.955335+00:00
- Task set: 1.1.0
- Mode: mock
- Seed: 42

## Leaderboard

| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |
|---|---|---:|---:|---:|---:|
| mock | raw_shell | 10 | 0.0 | 10.0 | 3820.0 |
| mock | verseshell_aci | 10 | 1.0 | 5.5 | 405.0 |

## Condition A vs D

### model `mock`

- success A=0.0 -> D=1.0 (delta=1.0)
- tool_calls A=10.0 -> D=5.5 (ratio=0.55)
- observation_tokens A=3820.0 -> D=405.0 (ratio=0.106)
- acceptance gate: **PASS**

## Notes

- Condition D applies GOLDEN solutions under mock/live-fallback to model an ACI-competent agent.
- Condition A does not apply GOLDEN (raw shell baseline fails without correct edits).
- Live mode can load `baselines/<model>/<task>__<condition>.json` trajectories when present.
- Set `ACI_BENCH_API_KEY` + `ACI_BENCH_MODEL` for optional live HTTP probes.
