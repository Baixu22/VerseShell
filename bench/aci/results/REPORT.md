# ACI-Bench Report

- Generated: 2026-09-30T01:03:33.363161+00:00
- Task set: 3.0.0
- Mode: mock
- Seed: 42

## Leaderboard

| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |
|---|---|---:|---:|---:|---:|
| mock | raw_shell | 35 | 0.0 | 10.0 | 3820.0 |
| mock | verseshell_aci | 35 | 1.0 | 5.63 | 414.86 |

## Condition A vs D

### model `mock`

- success A=0.0 -> D=1.0 (delta=1.0)
- tool_calls A=10.0 -> D=5.63 (ratio=0.5629)
- observation_tokens A=3820.0 -> D=414.86 (ratio=0.1086)
- acceptance gate: **PASS**

## Notes

- Condition D applies GOLDEN solutions under mock/live-fallback to model an ACI-competent agent.
- Condition A does not apply GOLDEN (raw shell baseline fails without correct edits).
- Live mode can load `baselines/<model>/<task>__<condition>.json` trajectories when present.
- Set `ACI_BENCH_API_KEY` + `ACI_BENCH_MODEL` for optional live HTTP probes.
