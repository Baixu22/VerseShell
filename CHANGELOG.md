# Changelog

## Unreleased

### Added
- `file.read_many` on-demand windows: `windows[]` gives each file its own
  `{start_line, window}`, and `max_total_lines` (default 240) bounds the whole
  batch. An entry cut by its own window is `truncated`, one that no longer fits
  the budget comes back `deferred`; both return `next_start_line`, so a bounded
  batch stays paginable instead of silently dropping files.
- Read ops (`file.view` / `file.read_range` / `file.read_many`) return a compact
  `hash` (16 hex chars) next to the full `content_hash`, and `expected_hash` now
  accepts any unambiguous hex prefix of at least 8 characters. The stale-write
  check is unchanged in strength (a wrong prefix still fails with
  `E_STALE_HASH` + `data.actual_hash`), but an observation stops paying 71
  characters per file for a digest the agent only hands back. Additive: an
  existing consumer that reads `content_hash` keeps working.
- Claim C14 + `tools/tf45_envelope_replay.py`: a deterministic replay that pins
  the read calls the model actually issued in the stored live run, re-runs them
  against the current binary, and projects each envelope twice (legacy full
  digest vs compact digest). It measures the observation surface, not model
  behaviour, and lists every call it could not reproduce with both token counts.
- `bench/aci/runners/merge_live_runs.py`: merging per-seed live runs now refuses
  to merge when any row carries `api_error` (exit 2), instead of letting an
  upstream 500 into the average as a 0-tool / 0-token data point.
- `file.read_many`: read up to 8 files in one call, each entry carrying its own
  `content_hash` / `total_lines` / line window; a missing path is reported in its
  own entry instead of failing the batch. It gives an agent the single call raw
  shell gets from `type a & type b`, instead of N separate `file.view` calls.
  Exposed to the live benchmark as the `read_files` tool.
- Live runner: `--exclude-tools` (hide a tool from condition D to A/B it on the
  same model) and an `api_error` flag on every row, so an upstream outage can
  never be averaged into the benchmark as a 0-tool / 0-token data point.
- Live runner sampling controls: `--temperature` (default 0), `--seed`, and
  `--repeat N`; every row carries `run_index` and `live_config` records all
  three, so a live result can be repeated and quoted with a spread instead of a
  single sample.
- Live ACI-Bench evaluation is actually usable: the runner now starts the AE
  server with an explicit capability set (`--cap`, overridable via `--caps`).
  Before this, condition D ran with **no** grants, so every ACI op returned
  `E_CAPABILITY_DENY` and the D condition never executed a single operation.
- Live artifacts (`bench/aci/results/latest_live.json`) record `live_config`
  (model / api_base / caps / max_turns / tasks / conditions) plus the code
  fingerprint, and are covered by claim C12.
- Claim C13 registers the live A-vs-D result separately from the mock C1/C2:
  on one real model (10 tasks x 2 conditions, two full runs) condition D used
  ~2.0-2.6x the tool calls and ~2.0-2.6x the observation tokens of raw shell at
  the same 0.6 success rate — the ACI did not reduce steps or tokens there.
  Single-run variance is large, so the direction is the finding, not the ratio.

### Changed
- Decomposed condition D's extra observation tokens with stored artifacts only
  (claim C15, `tools/exec_token_breakdown.py`). `exec.run` is D's biggest single
  line item (50.4% of D, 63.1 tokens/call) but it is **not** why D costs more
  than raw shell: of the +144.0 tokens/run gap, reading is +84.8 (58.9%), edits
  +24.8 (17.2%) and exec only +23.3 (16.2%). D pays 48.0 tokens per file
  reference against raw shell's 26.0 and reads ~1.6x as many file references.
  80.1% of D's exec tokens come from failed commands (96.2 tokens each versus
  26.4 for successes), and adding batch reads raised exec tokens only by issuing
  7 more failing commands while the per-success cost fell. The next token lever
  is the read envelope, not the exec reducer.
- Re-measured the live A/B on the new envelope (same model `sn-glm-5-3-flash`,
  same endpoint, seeds 42/43/44, 10 tasks x 2 conditions x 2 arms, 120 rows,
  `api_error` 0). Condition D/A is now **1.64x the tool calls and 1.69x the
  observation tokens** of raw shell (previously 1.75x / 2.44x). Within this
  round, hiding `read_files` moves D by **-11.8% tool calls and +22.7%
  observation tokens** (previously -8.8% / +36.9%). The clean cross-round signal
  is the per-call cost of `file.read_many`: 175.6 -> 135.6 tokens (-22.8%),
  matching the deterministic replay's -22.1% (claim C14). Raw shell is untouched
  code yet its own average moved 168.6 -> 197.4 tokens between rounds, so the
  ratio movement is not attributable to the envelope alone (claim C13).
- Measured effect of `file.read_many` (live A/B: same model `sn-glm-5-3-flash`,
  same seeds 42/43/44, 10 tasks x 2 conditions x 2 arms): condition D's tool calls
  drop from 6.03 to 5.50 (-8.8%) and the D/A tool ratio from 1.95 to 1.75, while
  observation tokens rise from 300.2 to 411.1 (+36.9%) because one call now pulls
  more file content. Fewer steps, not fewer tokens — ACI still costs ~1.75x the
  steps and ~2.4x the tokens of raw shell here (claim C13). **Superseded by the
  re-measurement above**, which was taken after the read envelope shrank; the
  numbers stay here as the record of what that round measured.
- The model-visible observation projection drops structural redundancy:
  `file.view` lines are flattened from `[{line, text}]` to plain strings with a
  single `start_line` (a 10-line window: 444 -> 250 chars, -43.7%), and a failure
  `summary` is omitted when the diagnostics already carry its message and
  `stats` carries the counts (failing pytest: 529 -> 399 chars, -24.6%). The raw
  observation envelope is unchanged, so this is a projection choice, not a
  contract change.
- Fixture workspaces no longer copy `__pycache__` / `.pytest_cache`. Stale
  bytecode made pytest report the *fixture source* path
  (`../../../../Desktop/...`) instead of the workspace-relative one, which both
  wasted tokens and misled the agent.
- Failure observations no longer carry fields that merely repeat each other: a
  stream summary byte-identical to `summary`, and an `error.hint` that
  duplicates a diagnostic message. Reproduced failing-pytest observation:
  958 -> 689 chars (-28%).
- Claim C12 (evidence freshness): the three stored measurements (ACI-Bench
  results, L3 observation report, cross-shell bench) record the sha256
  fingerprint of the surface they measured, and `claim_gate` fails when that
  fingerprint no longer matches the code — a stale artifact can no longer pass
  the gate.
- The ACI-Bench dataset and its tooling are now tracked: `.gitignore` no longer
  hides `bench/aci/**/*.py`, so a fresh clone has the fixture code, runners and
  scorers that the task descriptions and the C1/C2 reproduction command need.
- `tools/readme_claims_check.py` + claim C10: every documented README example is
  executed against the real binary and every README implementation number is
  re-derived from its source of truth. It also verifies the README cross-shell
  table row by row against `eval/cross_shell.json`.
- `tools/cross_shell_bench.py` + claim C11: reproducible wall-clock comparison
  for the five advertised operations, with raw per-iteration samples in
  `eval/cross_shell.json`.
- Process lifecycle ops (`process.start` / `process.poll` / `process.write` /
  `process.kill` / `process.list`): runtime-owned long-lived processes with a
  monotonic byte cursor, a rolling retained output window, idempotent process-tree
  kill, explicit lifecycle state (`running` / `exited` / `killed` / `lost`) and
  24-hour record retention. JSON-RPC only — not registered as MCP tools.
- Windows ConPTY backend for `process.start` with `pty: true` (single `pty`
  stream, `cols`/`rows`, Job Object still attached); other builds return
  `E_PROCESS_PTY_UNSUPPORTED`.
- `runtime.handshake` feature flags: `process_lifecycle`,
  `monotonic_process_cursor`, `windows_conpty`.
- Docs: `docs/1.0-aci.md` "Process lifecycle" section (ownership echo, cursor and
  retention semantics, approval/capability rules, error codes); README process
  contract now covers both the one-shot and long-lived paths.
- Semantic observation reducers for cargo / pytest / git / npm_install with structured diagnostics
- Optional Diagnostic fields: code, expected, found, suggested_fix
- Session observation ledger + ops.observation_recent / ops.observation_open_errors
- ACI-Bench framework under bench/aci (10 tasks, GOLDEN fixtures, A/D comparison, leaderboard, REPORT)
- Multi-model live runner stub with trajectory cache (`baselines/`) and models.json dual slots
- docs/quickstart/aci-mcp.md and docs/v1.1-freeze.md

### Changed
- Evaluation artifacts (`bench/aci/results/*`, `eval/*.json`) are written with
  LF newlines, so re-running a dataset produces a minimal, reviewable diff
  instead of a whole-file rewrite on Windows.
- README compact-protocol claim corrected: the unverified "50-70% token savings
  vs JSON" is replaced by the measured scope of claim C9 (`>=40%` on a small
  response envelope; no saving on observation or large nested payloads).
- `src/compact.rs` module docs now point at the measurement instead of repeating
  the old number.

### Fixed
- `reduce` pipeline stage: the IR lowering returned a bare `Reduce` node and
  dropped the pipeline source, so every `... | reduce fn(..) 0` (the form README
  documents) failed with `expected array`. The `let`-bound form hid the bug
  because it never took the lowering path.
- `reverse` pipeline stage: it was lowered to the unregistered builtin name
  `arr.reverse` and to a `Call` instead of a pipeline stage, so standalone,
  direct and chained forms all failed. It is now a real `IRNode::Reverse` stage
  that reads the upstream value like `Take`.
- README numbers corrected against their sources: 5 Criterion benchmark suites
  (was 4) and 52 integration tests (was 50).
- Match-arm guards no longer clone the entire Env (scoped with_frame)

## 1.0.0 — Agent-Computer Interface surface

Operation-first ACI runtime (single-track delivery):

- Unified OperationRegistry for all agent ops (JSON-RPC + MCP auto tools)
- File ACI: file.view, file.read_range, file.hash, file.replace_exact, file.apply_patch, file.edit_range, file.diff, file.remove (agent trash)
- Safety: tx.begin/commit/rollback/status/restore, trash restore tokens
- Repo: repo.search, repo.changed_files, repo.summary
- Test: test.discover, test.run_target, test.summarize_last
- Meta: ops.list
- Retains 0.6 observation quality for exec.run / result.query
- `E_NEEDS_APPROVAL` observations now preserve `error.hint` (+ optional `data.approval_token`)
- Closed-loop acceptance tests: `tests/aci_1_0_closed_loop_acceptance.rs`

## 0.6.1 — Observation quality

Non-breaking polish of the 0.6 Observation Budget contract:

- Success silence for npm/cargo/python/pytest/msbuild
- Failure focus: error-window extraction
- ANSI strip on the observation path
- git auto-profile
- Expanded unit + integration protocol tests

## 0.6.0 — Agent Action / Observation Runtime

- Typed exec.run / result.query operations
- Observation envelope, artifact store, process runner with Windows Job Objects
- Compiled IR + plan cache, HashMap LRU
