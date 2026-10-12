# VerseShell ACI Quickstart (Codex / Claude Code / MCP)

Minimal integration so **Condition D** (VerseShell ACI) can be reproduced for ACI-Bench and agent workflows.

## 1. Build

```bash
cargo build --release
# binary: target/release/ae  (ae.exe on Windows)
```

## 2. MCP config fragment

### Claude Code / generic MCP

```json
{
  "mcpServers": {
    "verseshell": {
      "command": "target/release/ae-mcp",
      "args": [],
      "env": {
        "AETHER_MODE": "agent",
        "AETHER_WORKSPACE": "${workspaceFolder}",
        "AETHER_APPROVE_ALL": "1"
      }
    }
  }
}
```

On Windows PowerShell for local experiments:

```powershell
$env:AETHER_MODE = "agent"
$env:AETHER_WORKSPACE = (Get-Location).Path
$env:AETHER_APPROVE_ALL = "1"
```

### Codex / JSON-RPC serve

```powershell
$env:AETHER_APPROVE_ALL = "1"
$env:AETHER_MODE = "agent"
$env:AETHER_WORKSPACE = "."
# line-delimited JSON, UTF-8 no BOM
'{"id":"1","agent":"coder","op":"ops.list","args":{}}' | .\target\release\ae.exe --serve --agent
```

## 3. System prompt fragment

```
You are coding with VerseShell ACI (typed ops + verseshell.observation/v1).
Prefer:
- file.view / file.replace_exact / file.edit_range for edits (use content_hash / expected_hash)
- repo.search before broad shell greps
- exec.run for builds/tests; trust observation.diagnostics and data.summary/stats
- result.query only when you need more of an artifact
- ops.observation_recent / ops.observation_open_errors for reference context
- tx.begin/commit/rollback for multi-file risky edits
Do not dump full install/build logs; use reduced observations.
```

## 4. Three example op flows

### A. Read → exact edit

```json
{"id":"1","agent":"coder","op":"file.view","args":{"path":"src/lib.rs","cursor":1,"window":40}}
{"id":"2","agent":"coder","op":"file.replace_exact","args":{"path":"src/lib.rs","old":"return a * b;","new":"return a + b;","expected_hash":"e3b0c44298fc1c14"}}
```

**`expected_hash` must be the literal hash returned by the preceding read** — the
16-hex `hash` field (or the full `content_hash`). The digest above is an *example
value*, not something to send. Sending a placeholder string, or a hash that does
not match the file's current content, fails with `E_STALE_HASH` and returns
`data.actual_hash` / `data.expected_hash` so you can retry with the real value.
A stale hash is never a reason to fall back to shell redirection.

### B. Build with semantic diagnostics

```json
{"id":"3","agent":"coder","op":"exec.run","args":{"argv":["cargo","check"],"profile":"auto"}}
```

On failure, `diagnostics[]` may include `path`, `line`, `code` (e.g. E0308), `expected`/`found`, and `suggested_next` with `file.view`.

### C. Test + ledger reference

```json
{"id":"4","agent":"coder","op":"test.run_target","args":{"target":"tests","framework":"pytest"}}
{"id":"5","agent":"coder","op":"ops.observation_recent","args":{"limit":8}}
{"id":"6","agent":"coder","op":"ops.observation_open_errors","args":{}}
```

## 5. ACI-Bench

```powershell
python bench/aci/runners/run_suite.py --mode mock
# see bench/aci/README.md
```

## Safety note

`AETHER_APPROVE_ALL=1` is for local CI/bench only. Production agents should use explicit approval flows.
