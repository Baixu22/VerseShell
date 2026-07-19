# Changelog

## Unreleased

### Added
- Semantic observation reducers for cargo / pytest / git / npm_install with structured diagnostics
- Optional Diagnostic fields: code, expected, found, suggested_fix
- Session observation ledger + ops.observation_recent / ops.observation_open_errors
- ACI-Bench framework under bench/aci (10 tasks, GOLDEN fixtures, A/D comparison, leaderboard, REPORT)
- Multi-model live runner stub with trajectory cache (`baselines/`) and models.json dual slots
- docs/quickstart/aci-mcp.md and docs/v1.1-freeze.md

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
