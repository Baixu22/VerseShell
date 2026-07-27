# ACI-Bench

Agent-level A/B framework comparing **raw shell** (Condition A) vs **VerseShell ACI** (Condition D).

## Quick run

### Windows

```powershell
$env:AETHER_APPROVE_ALL = "1"
python bench/aci/runners/run_suite.py --mode mock
# Use --out <directory>/latest.json to keep a full result bundle outside the repo.
# optional live (multi-model config + cache)
python bench/aci/runners/run_suite.py --mode live
```

### Unix

```bash
export AETHER_APPROVE_ALL=1
python3 bench/aci/runners/run_suite.py --mode mock
```

Outputs:

| Path | Content |
|------|---------|
| `results/latest.json` | Full rows + aggregate + comparison |
| `results/leaderboard.md` | Table |
| `results/comparison.json` | A vs D deltas |
| `results/REPORT.md` | Human report + acceptance gate |

## Conditions

| Condition | Behavior (mock) |
|-----------|-----------------|
| `raw_shell` | Noisy multi-step shell trajectory; **does not** apply GOLDEN → task usually fails |
| `verseshell_aci` | Short typed-op trajectory; **applies GOLDEN** → task succeeds |

This encodes the product claim: structured ACI + reduced observations reach a correct fix with fewer tools/tokens.

## Task schema

See `tasks/*.json`. Success predicates are file-based for deterministic CI. Optional `optional_verify` commands run only with `--optional-verify` when toolchains exist.

## Live / multi-model

`runners/models.json` lists models. Env:

- `ACI_BENCH_MODEL` / `ACI_BENCH_MODEL_2`
- `ACI_BENCH_API_KEY` (or `OPENAI_API_KEY`)
- `ACI_BENCH_API_BASE` (default OpenAI)

Cached trajectories: `baselines/<model>/<task>__<condition>.json`.

## Seed / version

`tasks/manifest.json` → `task_set_version`, `seed`.
