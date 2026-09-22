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

**Read this before quoting the mock numbers.** Mock condition D applies the
GOLDEN patch directly, so the mock ratio (tokens 0.106, calls 0.55) is a
harness self-test: it checks the scoring pipeline, it is **not** a measurement
of what a real agent achieves. For a real-model measurement use the live agent
loop below and quote claim C13 — never mix the two.

## Live agent loop (real model)

`runners/live_agent_loop.py` drives a real function-calling model through the
same tasks and conditions:

```powershell
$env:DEEPSEEK_API_KEY = "<key>"   # credentials stay in the environment, never in the repo
python bench/aci/runners/live_agent_loop.py --full `
  --model <model> --base-url http://127.0.0.1:3065/v1 --max-turns 8
```

| Flag | Meaning |
|------|---------|
| `--tasks a,b` / `--smoke` / `--full` | task selection (smoke = 3, full = 10) |
| `--model` / `--base-url` / `--api-key` | endpoint config (key may come from the env instead) |
| `--caps` | capabilities granted to the AE server for condition D (default: the ACI surface set) |
| `--temperature` / `--seed` | sampling controls (default temperature 0; the endpoint may ignore `seed`) |
| `--repeat N` | run the whole task × condition matrix N times; each row carries `run_index` |

For a reportable number, run at least 3 times and quote the spread: a single
run varies by 1.5–3x per task on a reasoning model, so one run supports a
*direction*, not a magnitude.

Condition D starts `ae --serve --agent --cap <caps>`. **Without `--cap` the
server grants nothing and every op fails with `E_CAPABILITY_DENY`** — a live run
made that way measures nothing, so the flag is mandatory in practice.

Outputs: `results/latest_live.json`, `results/live_REPORT.md`.

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
