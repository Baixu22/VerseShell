# VerseShell v1.0 — Agent-Computer Interface Runtime

A local-systems runtime designed around the information an AI agent actually
needs: typed actions, bounded structured observations, explicit failures,
recoverable raw-output artifacts, and safe process-tree execution.

The primary Agent contract is the versioned **typed operation** API
(`op` + `verseshell.observation/v1`). `exec.run` / `result.query` remain the
process I/O spine; File / Tx / Repo / Test ops complete the 1.0 ACI surface.
The VerseShell language remains a typed orchestration DSL and compatibility
layer; it is **not** a bash-compatible text shell.

### Coder Agent op checklist

| Task | Op |
|------|-----|
| Run command | `exec.run` |
| Inspect large logs | `result.query` |
| Read code window | `file.view` / `file.read_range` |
| Exact edit | `file.replace_exact` / `file.edit_range` |
| Search repo | `repo.search` |
| Changed files | `repo.changed_files` |
| Safe delete | `file.remove` → `tx.restore` |
| Transaction | `tx.begin` / `tx.commit` / `tx.rollback` |
| Tests | `test.discover` / `test.run_target` |
| List ops | `ops.list` |

Legacy `cmd` / `eval` / language builtins remain available as a secondary path.
Agent-mode `exec.run` / `test.run_target` require approval (`E_NEEDS_APPROVAL` + `error.hint`). For local CI use `AETHER_APPROVE_ALL=1`; see [docs/1.0-aci.md](docs/1.0-aci.md). Closed-loop gate: `tests/aci_1_0_closed_loop_acceptance.rs`.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
  - [One-shot vs Server mode](#one-shot-vs-server-mode)
  - [Functional pipelines](#functional-pipelines)
  - [Module system](#module-system)
  - [Process execution](#process-execution)
- [CLI Reference](#cli-reference)
- [Language Guide](#language-guide)
- [Agent Quick Reference](#agent-quick-reference)
- [Module Reference](#module-reference)
- [JSON-RPC Server](#json-rpc-server)
- [Security Model](#security-model)
- [MCP Integration](#mcp-integration)
- [Bash Transpiler](#bash-transpiler)
- [Architecture](#architecture)
- [Performance](#performance)
- [Building & Testing](#building--testing)
- [Changelog](CHANGELOG.md)
- [1.0 ACI Surface](docs/1.0-aci.md)
- [0.6 Migration](docs/0.6-migration.md)

---

## Quick Start

```bash
cargo build --release

# One-shot: get hostname
ae -c "sys.hostname()"

# JSON output (agent-friendly)
ae --json -c "{cpu: sys.cpu_info().cores, mem: sys.mem_info().total}"

# Safety sandbox: confine writes to /tmp, deny destructive ops
ae --agent --workspace /tmp -c 'file.write("out.txt", "hello")'

# Bash transpilation: write bash, get VerseShell
ae -b -c "echo hello && echo world"

# Preferred Agent API: typed ops + Observation (approve exec in agent mode for CI)
AETHER_APPROVE_ALL=1 AETHER_MODE=agent AETHER_WORKSPACE=. \
  ae --serve --agent <<'EOF'
{"id":"1","agent":"coder","op":"file.view","args":{"path":"README.md","cursor":1,"window":40}}
{"id":"2","agent":"coder","op":"exec.run","args":{"argv":["cargo","check"]}}
EOF
```

Windows (cmd, UTF-8 no BOM):

```bat
set AETHER_APPROVE_ALL=1
set AETHER_MODE=agent
set AETHER_WORKSPACE=.
echo {"id":"1","agent":"coder","op":"ops.list","args":{}}| ae --serve --agent
```

---

## Core Concepts

### One-shot vs Server mode

VerseShell runs in two modes:

**One-shot** (`-c CMD` or `FILE.ae`): single command, exits immediately.
Good for CLI use, scripts, and debugging.

```bash
ae -c "sys.hostname()"
ae --json -c "sys.cpu_info()"
ae my_script.ae
```

**Server** (`--serve`): long-running JSON-RPC process over stdin/stdout.
Designed for multi-agent systems. Each agent gets an isolated session
pooled by agent ID. Supports batch requests, caching, and streaming.

```bash
ae --serve --agent --workspace /safe --max-concurrency 8
```

```
→ {"id":"r1","agent":"planner","cmd":"sys.cpu_info()","timeout_ms":5000}
← {"type":"done","id":"r1","ok":true,"value":{...},"meta":{...}}
```

### Functional Pipelines

Pipelines pass typed `Value` objects between functions — no text serialization,
no shell quoting hell.

```
# Map: transform each element
[1,2,3] | map fn(x) => x * 2          → [2, 4, 6]

# Where: keep only matching elements
[1,2,3,4,5] | where fn(x) => x > 3    → [4, 5]

# Sort: order elements
[3,1,4,1,5] | sort                     → [1, 1, 3, 4, 5]

# Chain: sort → filter → map
[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10
                                       → [30, 40, 50]

# Reduce: aggregate
[1,2,3,4] | reduce fn(acc,x)=>acc+x 0 → 10

# Parallel map (multi-threaded, auto thread count)
large_array | par_map fn(x) => expensive(x)
```

### Module System

All functionality is organized into 26 namespaced modules. Call them with
`module.method(args)`:

```
sys.cpu_info()          → {name: "...", cores: 8, mhz: 3601}
file.ls("src")          → [{name: "main.rs", size: 12345, ...}, ...]
http.get("https://...") → {status: 200, body: "...", headers: {...}}
```

Use `sys.describe(module)` to introspect a module's methods at runtime.
Use `arr.keys(module)` to list method names.

### Process Execution

For new Agent integrations, use typed `exec.run`: it drains stdout/stderr
concurrently, applies an observation budget, and returns artifact handles for
reduced output. `shell.exec` remains available as the legacy DSL escape hatch:

```bash
# Preferred: argv array form (safe, no shell parsing)
ae -c 'shell.exec(["rg", "--files", "."])'

# Shorthand: whitespace-split (convenience only, no quoting)
ae -c 'shell.exec("rg --files .")'

# Full shell: when you really need bash/pwsh syntax
ae -c 'shell.exec(["bash", "-lc", "rg --files | rg README"])'
```

The argv form is always preferred — it avoids quoting bugs and
shell injection risks. The string shorthand supports simple `cmd arg arg`
only; it does NOT handle pipes, `$()`, `&&`, redirections, or glob expansion.

Use `ae -b -c "..."` to transpile bash idioms to VerseShell before execution.

---

## CLI Reference

| Flag | Description |
|------|-------------|
| `-c, --command CMD` | Execute a VerseShell command string |
| `-b, --bash` | Transpile bash → VerseShell before executing |
| `--json` | Canonical byte-stable JSON output (alias for `--deterministic`) |
| `--compact` | Token-efficient compact protocol (50-70% savings vs JSON) |
| `--agent` | Agent mode: deny dangerous operations by default |
| `--workspace DIR` | Confine file write operations to DIR |
| `--timeout SECS` | Per-operation timeout (default: 30s) |
| `--cap CAPS` | Capability grants: `file.read,net.http.get,all` |
| `--serve` | Start JSON-RPC server (stdin/stdout) |
| `--max-concurrency N` | Max concurrent sessions in server mode (default: 4) |
| `--scheduler` | Enable work-stealing scheduler |
| `--scheduler-workers N` | Worker threads (default: 4) |
| `--cpu-budget N` | Max concurrent ops per agent (default: 8) |
| `--rate-limit N` | Per-agent rate limit req/s (0 = unlimited) |
| `--cache-ttl-ms N` | System snapshot cache TTL (default: 5000ms) |
| `--format FORMAT` | Output: `json`, `compact`, `human` (default) |
| `[FILE]` | Execute a `.ae` script file |

---

## Language Guide

VerseShell is a typed functional language with Hindley-Milner type inference.

### Literals

```
42                  → 42 (int)
3.14                → 3.14 (float)
true / false        → bool
"hello ${name}"     → string interpolation
[1, 2, 3]           → array
{a: 1, b: "x"}      → record
```

### Arithmetic & Logic

```
1 + 2 * 3           → 7
10 / 3              → 3.333...
2 ^ 8               → 256
x > 2 && y < 10     → logical and
!false              → true
```

### Variables & Functions

```
let x = 42
let add = fn(a, b) => a + b
add(3, 4)           → 7
(fn(x) => x * 2)(5) → 10
```

### Control Flow

```
if x > 10 { x * 2 } else { x }

match value {
    0 => "zero",
    1 => "one",
    _ => "many"
}
```

### Error Handling

```
try {
    json.parse("bad input")
} catch e {
    "recovered: ${e}"
}
```

### Pipelines (Typed Data Flow)

```
[1,2,3] | map fn(x) => x * 2           → [2, 4, 6]
[1,2,3,4,5] | where fn(x) => x > 3     → [4, 5]
[3,1,4,1,5] | sort | reverse | take(3)  → [5, 4, 4]
[1,2,3,4] | reduce fn(acc,x)=>acc+x 0  → 10
[1,2,3] | any fn(x) => x > 2           → true
```

---

## Agent Quick Reference

Full typed-op catalog: [docs/1.0-aci.md](docs/1.0-aci.md). MCP tool names replace `.` with `_` (e.g. `file_view`).

The ~50 most-used builtins for AI agent tasks. Use `ae --core` to print
this list at the CLI, or `list_commands(core=true)` via MCP.

### System

| Function | Returns |
|----------|---------|
| `sys.cpu_info()` | `{name, cores, mhz}` |
| `sys.mem_info()` | `{total, free, available}` bytes |
| `sys.disk_info()` | Array of `{filesystem, size, used, available}` |
| `sys.hostname()` | Hostname string |
| `sys.os()` | `"windows"` / `"linux"` / `"macos"` |
| `sys.arch()` | `"x86_64"` / `"aarch64"` |
| `sys.uptime()` | Seconds since boot |
| `sys.load_avg()` | `{1min, 5min, 15min}` |
| `sys.env_all()` | All environment variables as a record |
| `sys.process_info(pid)` | Detailed process info |
| `sys.describe(value)` | Type introspection — pipe a value through it |

### File System

| Function | Description |
|----------|-------------|
| `file.ls(path)` | List directory contents |
| `file.read(path)` | Read file content as string |
| `file.write(path, content)` | Atomic write (temp → fsync → rename) |
| `file.head(path, n)` | First N lines |
| `file.tail(path, n)` | Last N lines |
| `file.grep(pattern, path)` | Search file for regex pattern |
| `file.wc(path)` | Line/word/char count |
| `file.exists(path)` | Check if path exists |
| `file.mkdir(path)` | Create directory |
| `file.copy(src, dst)` | Copy file |
| `file.move(src, dst)` | Move/rename file |
| `file.stat(path)` | File metadata `{size, modified, is_dir, ...}` |
| `file.find(dir, pattern)` | Recursive file search |
| `file.lock(path, fn)` | Advisory lock + atomic execute |

### Process & Shell

| Function | Description |
|----------|-------------|
| `shell.exec([prog, ...args])` | Execute process with explicit argv (preferred) |
| `shell.exec("prog arg")` | Whitespace-split shorthand (simple commands only) |
| `proc.list()` | List all processes |
| `proc.kill(pid)` | Terminate process by PID |
| `proc.info(pid)` | Detailed process info |
| `proc.grep(name)` | Find processes by name substring |

### Array / Data Pipeline

| Function / Stage | Description |
|------------------|-------------|
| `arr.sort(arr)` / `sort` | Sort array |
| `arr.filter(arr, pred)` / `where` | Filter by predicate |
| `arr.map(arr, fn)` / `map` | Transform elements |
| `arr.reduce(arr, fn, init)` / `reduce` | Aggregate |
| `arr.first(arr)` / `first` | First element |
| `arr.last(arr)` / `last` | Last element |
| `arr.take(arr, n)` / `take(n)` | First N elements |
| `arr.any(arr, pred)` / `any` | True if any element matches |
| `arr.all(arr, pred)` / `all` | True if all elements match |
| `arr.reverse(arr)` / `reverse` | Reverse order |
| `arr.unique(arr)` / `unique` | Deduplicate |
| `arr.flatten(arr)` | Flatten nested arrays |
| `arr.range(start, end)` | Generate integer range |
| `arr.group_by(arr, prop)` | Group records by field |
| `arr.keys(rec)` / `arr.values(rec)` | Record keys/values |
| `arr.par_map(arr, fn)` | Multi-threaded parallel map |

### String

| Function | Description |
|----------|-------------|
| `str.upper(s)` / `str.lower(s)` | Case conversion |
| `str.trim(s)` | Trim whitespace |
| `str.split(s, sep)` | Split by separator |
| `str.join(sep, arr)` | Join array with separator |
| `str.replace(s, from, to)` | Replace substring |
| `str.contains(s, substr)` | Substring test |
| `str.length(s)` | String length |
| `str.grep(text, pattern)` | Find regex matches in text |
| `str.slice(s, start, end)` | Substring |

### Math

| Function | Description |
|----------|-------------|
| `math.abs(n)` | Absolute value |
| `math.min(a, b)` / `math.max(a, b)` | Min/max |
| `math.floor(n)` / `math.ceil(n)` / `math.round(n)` | Rounding |
| `math.sqrt(n)` | Square root |
| `math.pow(b, e)` | Power |
| `math.sum(arr)` / `math.mean(arr)` | Statistics |

### JSON & Serialization

| Function | Description |
|----------|-------------|
| `json.parse(str)` | Parse JSON string → record/array |
| `json.stringify(val)` | Convert value → JSON string |

### HTTP & Network

| Function | Description |
|----------|-------------|
| `http.get(url)` | HTTP GET |
| `http.post(url, body)` | HTTP POST |
| `http.put(url, body)` | HTTP PUT |
| `http.delete(url)` | HTTP DELETE |
| `net.ping(host)` | ICMP ping |
| `net.dns_lookup(host)` | DNS resolution |
| `net.interfaces()` | Network interfaces |
| `net.connections()` | Active TCP/UDP connections |

### Windows-Native

| Function | Description |
|----------|-------------|
| `win.snapshot()` | Full system snapshot (CPU, RAM, disks, PATH, user) |
| `win.registry_get(key, val)` | Read Windows registry value |
| `win.service_list()` | List all Windows services |
| `win.service_status(name)` | Service status |
| `win.env_path()` | PATH entries as array |
| `win.env_get(name)` | Environment variable |
| `win.is_admin()` | Check admin privileges |

### Crypto

| Function | Description |
|----------|-------------|
| `crypto.hash(data, algo)` | SHA-256 / MD5 hash |
| `crypto.uuid()` | Generate UUID v4 |
| `crypto.random_bytes(n)` | Random hex bytes |
| `crypto.base64_encode(data)` | Base64 encode |
| `crypto.base64_decode(data)` | Base64 decode |

### Other Modules

| Module | Key Methods |
|--------|------------|
| `git` | `git.status()`, `git.log()`, `git.branch()`, `git.diff()` |
| `db` | SQLite: `db.open(path)`, `db.query(sql)`, `db.exec(sql)` |
| `svc` | Service manager: `svc.list()`, `svc.start(name)`, `svc.stop(name)` |
| `hw` | Hardware: `hw.cpu()`, `hw.memory()`, `hw.disk()`, `hw.gpu()`, `hw.battery()` |
| `platform` | OS detection: `platform.os()`, `platform.arch()`, `platform.cpus()` |
| `archive` | `archive.tar(src, dst)`, `archive.zip(src, dst)` |
| `user` | `user.current()`, `user.groups()` |
| `input` | `input.read_line()`, `input.read_password()` |
| `clip` | `clip.read()`, `clip.write(text)` |
| `cron` | `cron.list()`, `cron.add(schedule, cmd)`, `cron.remove(id)` |
| `pkg` | `pkg.install(name)`, `pkg.remove(name)`, `pkg.list()` |

---

## Module Reference (Complete)

### sys — System Information (24 methods)

`sys.cpu_info()` `sys.mem_info()` `sys.disk_info()` `sys.hostname()`
`sys.os()` `sys.arch()` `sys.uptime()` `sys.load_avg()` `sys.env_all()`
`sys.env(name)` `sys.describe(value)` `sys.process_info(pid)`
`sys.info()` `sys.kernel()` `sys.users()` `sys.sessions()` `sys.boot_time()`
`sys.swap_info()` `sys.network_stats()` `sys.temp()` `sys.audit_log(n)`
`sys.whoami()` `sys.pid()` `sys.ppid()`

### file — File System (33+ methods)

`file.ls(dir)` `file.read(path)` `file.write(path, content)`
`file.head(path, n)` `file.tail(path, n)` `file.grep(pattern, path)`
`file.wc(path)` `file.exists(path)` `file.mkdir(path)` `file.copy(src, dst)`
`file.move(src, dst)` `file.remove(path)` `file.stat(path)`
`file.find(dir, pattern)` `file.pwd()` `file.cd(path)` `file.realpath(path)`
`file.basename(path)` `file.dirname(path)` `file.readlink(path)`
`file.touch(path)` `file.chmod(path, mode)` `file.chown(path, user)`
`file.lock(path, fn)` `file.watch(path)` `file.truncate(path, n)`
`file.append(path, content)` `file.temp_file()` `file.temp_dir()`
`file.mktemp()` `file.diff(a, b)` `file.tee(path)` `file.link(src, dst)`

### arr — Array Operations (24 methods)

`arr.sort(arr)` `arr.filter(arr, pred)` `arr.map(arr, fn)`
`arr.reduce(arr, fn, init)` `arr.first(arr)` `arr.last(arr)`
`arr.take(arr, n)` `arr.any(arr)` `arr.all(arr)` `arr.unique(arr)`
`arr.flatten(arr)` `arr.range(start, end)` `arr.zip(a, b)`
`arr.concat(a, b)` `arr.in(needle, haystack)` `arr.group_by(arr, key_fn)`
`arr.select(arr, fields...)` `arr.keys(rec)` `arr.values(rec)`
`arr.reverse(arr)` `arr.repeat(val, n)` `arr.partition(arr, pred)`
`arr.par_map(arr, fn)` `arr.chunk(arr, size)`

### str — String Operations (16 methods)

`str.upper(s)` `str.lower(s)` `str.trim(s)` `str.split(s, sep)`
`str.join(sep, arr)` `str.replace(s, from, to)` `str.contains(s, sub)`
`str.length(s)` `str.slice(s, start, end)` `str.grep(text, pattern)`
`str.starts_with(s, prefix)` `str.ends_with(s, suffix)` `str.reverse(s)`
`str.repeat(s, n)` `str.pad_left(s, n, ch)` `str.pad_right(s, n, ch)`

### math — Math Functions (14 methods)

`math.abs(n)` `math.min(a, b)` `math.max(a, b)` `math.floor(n)`
`math.ceil(n)` `math.round(n)` `math.sqrt(n)` `math.pow(b, e)`
`math.sum(arr)` `math.mean(arr)` `math.median(arr)` `math.std(arr)`
`math.sin(n)` `math.cos(n)` `math.log(n)`

### shell — Process Control (4 methods)

`shell.exec([prog, ...args])` `shell.exec("prog arg")`
`shell.sleep(secs)` `shell.echo(msg)` `shell.exit(code)`

### crypto — Cryptography (8 methods)

`crypto.hash(data, algo)` `crypto.uuid()` `crypto.random_bytes(n)`
`crypto.base64_encode(data)` `crypto.base64_decode(data)`
`crypto.md5(data)` `crypto.sha256(data)` `crypto.hmac(data, key, algo)`

### json — JSON (2 methods)

`json.parse(str)` `json.stringify(val)`

### http — HTTP Client (5 methods)

`http.get(url)` `http.post(url, body)` `http.put(url, body)`
`http.delete(url)` `http.json_post(url, data)`

### net — Network (8 methods)

`net.ping(host)` `net.dns_lookup(host)` `net.interfaces()`
`net.connections()` `net.ports()` `net.traceroute(host)`
`net.ip()` `net.resolve(hostname)`

### win — Windows-Native (9 methods)

`win.snapshot()` `win.registry_get(key, val)` `win.registry_set(key, val)`
`win.service_list()` `win.service_status(name)` `win.env_path()`
`win.env_get(name)` `win.env_set(name, val)` `win.is_admin()`
`win.shortcut_resolve(path)` `win.process_kill(pid)`

### proc — Process Management (10+ methods)

`proc.list()` `proc.kill(pid)` `proc.info(pid)` `proc.grep(name)`
`proc.spawn([cmd, args])` `proc.wait(pid)` `proc.children(pid)`
`proc.parent(pid)` `proc.exists(pid)` `proc.killall(name)`
`proc.pkill(pattern)`

---

## JSON-RPC Server

Start a long-running server for multi-agent workloads:

```bash
ae --serve --agent --workspace /safe --max-concurrency 8

# With scheduler (high-throughput)
ae --serve --scheduler --scheduler-workers 8 --cpu-budget 4 --cap file.read,net.http.get

# With compact token-efficient protocol
ae --serve --format compact
```

### Protocol

Requests are one JSON object per line on stdin. Responses are one JSON object
per line on stdout.

The server accepts both the legacy `cmd` protocol and the v0.6 typed operation
protocol. Existing clients remain compatible; new clients should use `op`.

**Typed operation request:**

```json
{
  "id": "req-1",
  "agent": "coder",
  "op": "exec.run",
  "args": {
    "argv": ["npm", "install"],
    "cwd": ".",
    "profile": "auto",
    "artifact": "auto"
  },
  "timeout_ms": 30000,
  "budget": {"max_tokens": 4000}
}
```

The response uses `verseshell.observation/v1` (v0.6.1 observation quality):

- **Success silence** for noisy profiles (`npm_install`, `cargo`, `python_install`,
  `pytest`, `msbuild`): model-visible stream has `status: "reduced"`, a short
  `summary` (<=120 tokens / <=4 lines), and **no full log text**. Progress noise is dropped.
- **Failure focus**: non-zero exits surface an error window (not a uniform head/tail of
  the whole log). Structured `diagnostics` and `suggested_next` -> `result.query` grep.
- **ANSI stripped** before reduce/truncate; omitted content is always explicit.
- **git** is auto-detected; large status/diff/log output is reduced or truncated rather
  than dumped into context.
- Full raw output is always recoverable via `stdout.artifact` / `stderr.artifact` with
  `result.query` (`meta`, `head`, `tail`, `slice`, `grep`, or bounded `raw`).

**Legacy request:**

**Request:**
```json
{"id": "req-1", "agent": "planner", "cmd": "sys.cpu_info()", "timeout_ms": 5000}
```

**Response (success):**
```json
{
  "type": "done",
  "id": "req-1",
  "ok": true,
  "value": {"cores": 8, "mhz": 3601, "name": "AMD Ryzen 7 7745HX"},
  "meta": {
    "elapsed_ms": 12,
    "agent": "planner",
    "cache_hit": true,
    "session_age_ms": 120
  }
}
```

**Response (error):**
```json
{
  "type": "error",
  "id": "req-1",
  "ok": false,
  "error": {
    "code": "E_UNKNOWN_BUILTIN",
    "message": "unknown builtin: srot",
    "hint": "did you mean 'sort'? (distance 2)",
    "recoverable": true
  }
}
```

### Error Codes

| Code | Trigger | Agent Action |
|------|---------|-------------|
| `E_UNKNOWN_BUILTIN` | Typo in function name | Try the suggested alternative |
| `E_PARSE` | Syntax error | Check brackets, quotes, operators |
| `E_TYPE` | Type mismatch | Use `sys.describe(value)` to inspect |
| `E_IO` | File/path not found | Verify path exists |
| `E_TIMEOUT` | Operation exceeded deadline | Increase `timeout_ms` |
| `E_RATE_LIMIT` | Rate exceeded | Slow down request frequency |
| `E_CAPABILITY_DENY` | Missing capability grant | Add required cap to `--cap` |
| `E_INTERNAL` | Unexpected crash | Retry; report if persistent |

### Batch Requests

```bash
echo '[{"id":"1","agent":"b","cmd":"sys.hostname()"},{"id":"2","agent":"b","cmd":"sys.os()"}]' | ae --serve
```

### Server Control

| Command | Action |
|---------|--------|
| `STATS` | Cache hit rates, active sessions, uptime |
| `GC` | Force garbage-collect idle sessions |
| `REFRESH` | Invalidate system snapshot cache |
| `SHUTDOWN` | Graceful shutdown |

### Session Pool & Caching

- **Session pool**: Same `agent` ID reuses the session context (variables, modules)
- **AST cache**: 1024-entry global cache, identical commands skip re-parsing
- **Snapshot cache**: `sys.*` results cached with configurable TTL (default 5s)
- **Lock-free**: Per-session `Mutex<Env>`; N agents execute concurrently
- **Panic recovery**: `catch_unwind` per request; a crash in one never affects others

---

## Security Model

### Capability-Based Security (27 caps)

Fine-grained access control enforced at builtin dispatch:

```bash
# Grant specific capabilities
ae --cap file.read,file.write,net.http.get -c 'file.read("data.txt")'

# Grant everything
ae --cap all -c "..."

# Only sys.read — file.write is denied
ae --cap sys.read -c 'file.read("config.toml")'  # DENIED
```

| Category | Capabilities |
|----------|-------------|
| System | `sys.read`, `sys.uptime`, `sys.env` |
| Files | `file.read`, `file.write`, `file.delete`, `file.lock`, `file.watch` |
| Network | `net.http.get`, `net.http.post`, `net.http.delete`, `net.ping`, `net.dns` |
| Process | `proc.list`, `proc.kill`, `proc.spawn`, `shell.exec` |
| Windows | `win.registry`, `win.service`, `win.env`, `win.admin` |
| Data | `crypto.hash`, `crypto.random`, `db.read`, `db.write`, `git.read`, `git.write` |

Safe functions (math, strings, arrays, json) are always allowed.

### Agent Mode (`--agent`)

Default-deny posture:

```bash
ae --agent --workspace /tmp -c 'file.write("out.txt", "data")'
```

- Destructive operations (process kill, file delete, shell exec) denied by default
- File writes confined to `--workspace`
- All operations audited to `.ae/audit.log`

---

## MCP Integration

VerseShell ships `ae-mcp` — a Model Context Protocol binary exposing 11 tools
for Claude Code, Codex, and other MCP clients.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `health` | Server version check |
| `list_commands` | List all module.fn → builtin mappings (filter: `"core": true` for agent surface) |
| `eval` / `exec` | Execute VerseShell source |
| `exec_run` | Preferred typed argv execution returning an Observation |
| `result_query` | Query `result://` artifacts without replaying full logs |
| `system_snapshot` | One-shot CPU/mem/processes/disk/load snapshot |
| `process_inspect` | Query processes with filter/sort/limit |
| `process_terminate` | Kill process by PID with optional name confirmation |
| `transpile_bash` | Convert bash → VerseShell source (optionally explain as MCP tool calls) |
| `describe_capabilities` | Report granted capabilities |

```bash
# Start MCP server
ae-mcp

# Example: transpile bash with tool call explanation
→ {"method":"tools/call","params":{"name":"transpile_bash","arguments":{"bash_code":"ps aux","explain_as_tools":true}}}
← {"result":{"ae_source":"proc.list()","tool_calls":[{"tool":"process_inspect","arguments":{"limit":20}}]}}
```

---

## Bash Transpiler

`ae -b` transpiles bash to VerseShell before execution. Supported patterns
in v0.6.0:

| Pattern | Example | Transpiled To |
|---------|---------|---------------|
| Simple command | `ls -la` | `ls()` |
| Mapped builtin | `cat file.txt` | `file.read("file.txt")` |
| Pipeline | `cmd1 \| cmd2` | `cmd1() \| cmd2()` |
| Logical AND | `cmd1 && cmd2` | Sequential execution with comment marker |
| Logical OR | `cmd1 \|\| cmd2` | Sequential execution with comment marker |
| Export | `export FOO=bar` | `set_env("FOO", "bar")` |
| Cmd substitution | `echo $(date)` | `shell.exec(...).stdout` |
| Stderr redirect | `cmd 2>/dev/null` | Strip `2>/dev/null` (AE captures stderr separately) |
| Variable expansion | `echo $HOME` | `echo(HOME)` |
| Single/double quotes | `'no expand'` / `"expand $VAR"` | Preserved |

Fallback: unsupported constructs (`<`, `>`, `if/for/while`, here-docs) emit
`sh(["bash","-lc","original line"])`.

```bash
# Transpile and execute
ae -b -c "ps aux | head -10"

# Transpile only (print VerseShell source)
ae -b -c "echo hello && echo world"
```

Use `transpile_bash` MCP tool with `explain_as_tools=true` to map bash idioms
directly to ACI tools without learning VerseShell syntax.

---

## Architecture

```
Source text
  → parser.rs (recursive descent, 47 token types)
    → AST (ast.rs: Stmt, Expr, 28 expression variants)
      → IRCompiler (ir.rs: AST → IRNode, ~31 IR variants)
        → IROptimizer (constant folding, pipeline fusion, map+filter fusion)
          → IREvaluator (ir.rs: single 28-arm match, unified v3 executor)
            → Value (value.rs: 15 runtime value variants)

Typed Agent request
  → OperationRegistry (exec / file / tx / repo / test / ops.list)
    → src/ops/* handlers + ProcessRunner for exec.run
      → Observation budget / trash / workspace jail
        → verseshell.observation/v1 (+ artifacts when large)
```

### Source Layout

```
src/
├── ops/              # 1.0 ACI ops (file, tx, repo, test) + common helpers
├── main.rs           # CLI entry point (run/serve modes, --core flag)
├── lib.rs            # Module declarations
├── bin/ae-mcp.rs     # MCP server binary
│
├── parser.rs         # Source → AST (recursive descent)
├── ast.rs            # AST node types
├── ir.rs             # V3 IR: IREvaluator, IREffect (22 types), IRCompiler, IROptimizer
├── eval.rs           # Legacy AST evaluator (backward compat)
│
├── builtins.rs       # Legacy/DSL builtin compatibility surface
├── modules.rs        # 26 namespaced module → builtin mappings + introspection
├── value.rs          # Runtime value system (Null, Bool, Int, Float, Str, Record, Array, ...)
├── env.rs            # Variable scope, module registry, deadline, trace
│
├── types.rs          # Type lattice
├── typecheck.rs      # Hindley-Milner type inference
│
├── capability.rs     # 27-capability allow-list security model
├── safety.rs         # Effect taxonomy, RBAC, audit log, workspace jail
├── rule.rs           # AgentSpec rule layer (TOML declarative policy)
│
├── runtime.rs        # AgentRuntime: session pool, dispatch, stats, error classification
├── server.rs         # JSON-RPC stdio server (tokio async)
├── operation.rs      # Versioned exec.run/result.query registry + observations
├── process_runner.rs # Bounded process execution and process-tree termination
├── artifact.rs       # TTL-managed content-addressed result store
├── plan.rs           # Shared static ExecutionPlan types
├── scheduler.rs      # Work-stealing scheduler with priority queues + per-agent quotas
├── cache.rs          # GlobalCache: AST (never expires), SystemSnapshot (5s TTL)
├── config.rs         # Configuration management (TOML)
├── tx.rs             # Transaction engine (begin/commit/rollback)
│
├── repl.rs           # run_one, run_eval, output formatting (human/JSON/compact)
├── compact.rs        # Token-efficient positional+type-tag protocol encoding
│
├── mcp/              # MCP protocol implementation
│   ├── mod.rs        # Module re-exports
│   ├── server.rs     # Stdio MCP server
│   ├── tools.rs      # 11 MCP tools, including exec_run/result_query
│   ├── registry.rs   # Tool registry
│   └── protocol.rs   # JSON-RPC 2.0 types
│
├── transpile/        # Bash → VerseShell transpiler
│   ├── bash.rs       # Core transpiler (line-oriented, 70+ builtin mappings)
│   └── explain.rs    # Bash → MCP tool call translator (21 patterns)
│
├── benches/          # 4 Criterion benchmark suites
└── tests/            # 50 integration tests + concurrency stress tests
```

### Key Design Decisions

- **Unified IR execution** (v3): All code paths (REPL, one-shot, server, MCP) go through `IREvaluator::eval_raw` — a single 28-arm match statement. No divergent execution paths.
- **Operation-first Agent API** (v0.6): MCP and JSON-RPC share the same typed operation and observation implementation without source-code generation or reparsing.
- **Raw output is an artifact**: model-visible output is bounded; omitted raw bytes are stored under `.ae/results` with a 24-hour TTL and explicit handles.
- **Process-tree safety**: Windows Job Objects and Unix process groups terminate descendants on timeout and prevent orphaned Agent workloads.
- **Effect-aware compilation**: Every builtin node carries an `IREffect` at compile time. Capability checks happen once at dispatch, not on every argument.
- **Pipeline fusion** (v2): `map + map` → `FusedMapMap`, `map + filter` → `FusedMapFilter` — single-pass iteration, no intermediate allocations.
- **Lock-free concurrency**: `RwLock<HashMap>` for session lookup, per-session `Mutex<Env>`. N agents execute in parallel.
- **Arc-shared modules**: Session creation is O(1) — no deep clone of 26 modules.

---

## Performance

Built-in optimizations for both throughput and latency:

| Optimization | Detail |
|-------------|--------|
| IR optimizer | Constant folding (`1+2` → `3`), pipeline fusion (map+map → single pass) |
| AST cache | 1024-entry global cache — identical commands skip re-parsing |
| Compiled IR cache | Identical programs reuse real optimized IR and their complete preflight plan |
| Snapshot cache | `sys.*` cached with configurable TTL (default 5s) |
| `par_map` | Multi-threaded array processing (Rayon, auto thread count) |
| Work-stealing scheduler | Priority queues, per-agent CPU/memory budgets |
| Compact protocol | 50-70% token savings vs JSON for agent communication |
| Observation Budget (0.6.1) | Success silence, failure windows, ANSI strip, git profile, explicit truncation, recoverable artifacts |
| Arc-shared modules | O(1) session creation, no deep clone overhead |
| Panic recovery | `catch_unwind` per request — crash isolation |

```bash
cargo bench                       # 4 benchmark suites
cargo bench -- --quick            # Quick mode (fewer samples)
```

### Cross-Shell Comparison (v0.5.1 benchmark, Ryzen 7 7745HX)

| Operation | VerseShell | PowerShell | Bash | AE vs PWsh |
|-----------|-----------|------------|------|------------|
| CPU info | 362ms* | 1326ms* | 443ms* | **3.7x faster** |
| Disk info | **28ms** | 403ms | N/A | **14.4x faster** |
| List dir | **26ms** | 315ms | 405ms | **12.1x faster** |
| Read file | **29ms** | 198ms | 428ms | **6.8x faster** |
| Pipeline 1K | **67ms** | 256ms | 426ms | **3.8x faster** |

\* 20-iteration total; includes process spawn overhead for bash/pwsh

---

## Building & Testing

Requirements: Rust 1.75+

```bash
cargo build --release
cargo test
```

### 1.0 ACI acceptance gates

```bash
# Full Coder Agent closed loop (file/tx/repo/exec/test/trash)
cargo test --test aci_1_0_closed_loop_acceptance -- --nocapture

# Op surface slices + observation quality regression
cargo test --test aci_1_0_ops_tests -- --nocapture
cargo test --test operation_protocol_tests -- --nocapture
```

Agent-mode process ops need approval. For local/CI functional tests:

```bash
# Windows PowerShell
$env:AETHER_APPROVE_ALL="1"
# Unix
export AETHER_APPROVE_ALL=1
```

JSON-RPC clients must send **UTF-8 without BOM** (line-delimited). Prefer raw byte stdin over PowerShell `Get-Content | ae`.

See [docs/1.0-aci.md](docs/1.0-aci.md) for the full op surface and [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

AGPL-3.0-or-later
