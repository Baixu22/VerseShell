# Changelog

## Unreleased

### Added
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
- README compact-protocol claim corrected: the unverified "50-70% token savings
  vs JSON" is replaced by the measured scope of claim C9 (`>=40%` on a small
  response envelope; no saving on observation or large nested payloads).
- `src/compact.rs` module docs now point at the measurement instead of repeating
  the old number.

### Fixed
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
