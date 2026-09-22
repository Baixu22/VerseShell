# Changelog

## Unreleased

### Added
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
