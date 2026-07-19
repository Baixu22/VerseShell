# ae — VerseShell: Production-Grade Typed Functional Shell Runtime for AI Agents (v3 Kernel)

A production-grade, deterministic shell runtime with a typed functional pipeline language and unified IR-native execution engine, designed for AI agents to interact with systems safely and reliably.

## Quick Start

```bash
cargo build --release

# One-shot command
./target/release/ae -c "sys.hostname()"

# Structured JSON output for agent consumption
./target/release/ae --json -c "{cpu: sys.cpu_info().cores, mem: sys.mem_info().total}"

# Safety sandbox
./target/release/ae --agent --workspace /tmp -c "file.read(\"config.toml\")"
```

## Execution Model: Typed Runtime First

VerseShell is a typed functional runtime, not a PowerShell/bash-compatible text
shell. Its `|` operator is a typed VerseShell pipeline that passes values
between functions; it is not an operating-system pipe.

Process execution is intentionally explicit:

```bash
# Preferred: argv form, no command-shell parsing
ae --json -c "shell.exec([\"rg\", \"--files\", \".\"])"

# Convenience only: whitespace-split shorthand
ae --json -c "shell.exec(\"rg --files .\")"
```

The string shorthand is only for simple `program arg arg` commands. It does not
implement shell quoting, pipes, redirection, `&&`, `$()`, environment
assignment, or glob expansion. For commands that need real shell syntax, choose
the interpreter explicitly and pass the script as one argv item:

```bash
# Windows cmd shell syntax; use the absolute path when agent environments have a narrowed PATH
ae --json -c "shell.exec([\"C:\\\\Windows\\\\System32\\\\cmd.exe\", \"/C\", \"dir /B | C:\\\\Windows\\\\System32\\\\findstr.exe README\"])"

# Git Bash / POSIX shell syntax on Windows
ae --json -c "shell.exec([\"C:\\\\Program Files\\\\Git\\\\bin\\\\bash.exe\", \"-lc\", \"rg --files | rg README\"])"

# PowerShell only when the task specifically requires PowerShell semantics
ae --json -c "shell.exec([\"powershell\", \"-NoProfile\", \"-Command\", \"Get-ChildItem | Select-Object -First 5\"])"
```

Agent rule: do not fall back to PowerShell just because a command has quoting,
pipes, or a `-c` script argument. Prefer VerseShell typed tools and pipelines;
when an external process is required, use argv form. Use an explicit shell
interpreter through argv only when the task truly needs shell language syntax.

MCP rule: `verseshell_shell_exec` is for shell-script compatibility and should
route through an explicit OS shell. For deterministic process execution, expose
or use an argv-shaped tool such as `verseshell_process_exec`, or call
`verseshell_eval` with `shell.exec([...])`.

## CLI Flags

| Flag | Description |
|------|-------------|
| `-c, --command CMD` | Execute a command string |
| `-b, --bash` | Bash transpilation mode |
| `--json` | Output as canonical JSON (alias for `--deterministic`) |
| `--deterministic` | Canonical byte-stable JSON output |
| `--agent` | Agent mode: deny dangerous operations by default |
| `--workspace DIR` | Confine file write operations to DIR |
| `--timeout SECS` | Timeout for http/shell operations (default: 30s) |
| `--budget N` | Token budget for output truncation |
| `--serve` | Start JSON-RPC server mode (stdin/stdout) |
| `--max-concurrency N` | Max concurrent agent sessions in server mode (default: 4) |
| `--transport TRANSPORT` | Server transport (default: stdio) |
| `--cache-ttl-ms N` | Cache TTL in milliseconds (default: 5000) |
| `--rate-limit N` | Per-agent rate limit in requests/sec (0 = unlimited) |
| `--cap CAPS` | Capability grants: `file.read,net.http.get,all` (v2) |
| `--scheduler` | Enable work-stealing scheduler (v2.1) |
| `--scheduler-workers N` | Scheduler worker threads (default: 4) |
| `--cpu-budget N` | Max concurrent ops per agent (default: 8) |
| `--format FORMAT` | Output format: `json`, `compact` (token-efficient), `human` (default) |
| `--compact` | Alias for `--format compact` |
| `[FILE]` | Execute a `.ae` script file |

## Language

AetherShell is a typed functional language with Hindley-Milner type inference.

### Literals & Expressions

```
42                          → 42
3.14                        → 3.14
true                        → true
"hello ${name}"             → hello world         (string interpolation)
[1, 2, 3]                   → [1, 2, 3]           (array)
{a: 1, b: "x"}              → {a: 1, b: x}        (record)
```

### Arithmetic & Logic

```
1 + 2 * 3                   → 7
10 / 3                      → 3.333...
2 ^ 8                       → 256
x > 2 && y < 10             → true
!false                      → true
```

### Variables & Functions

```
let x = 42
let add = fn(a, b) => a + b
add(3, 4)                   → 7
(fn(x) => x * 2)(5)         → 10
```

### Pattern Matching

```
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

### Pipelines

Pipelines pass typed data between functions — no text parsing needed.

```
# Map
[1,2,3] | map fn(x) => x * 2           → [2, 4, 6]

# Filter (where)
[1,2,3,4,5] | where fn(x) => x > 3     → [4, 5]

# Sort
[3,1,4,1,5] | sort                      → [1, 1, 3, 4, 5]

# Chained
[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10
                                        → [30, 40, 50]

# Reduce
[1,2,3,4] | reduce fn(acc,x)=>acc+x 0  → 10

# Parallel Map (multi-threaded)
[1,2,3,4,5,6,7,8] | par_map fn(x) => x * x
                                        → [1, 4, 9, 16, 25, 36, 49, 64]
```

## JSON-RPC Agent Server

Start a long-running server that agents connect to via stdin/stdout:

```bash
ae --serve --agent --workspace /tmp --max-concurrency 4

# With work-stealing scheduler (v2.1)
ae --serve --scheduler --scheduler-workers 8 --cpu-budget 4

# With capability restrictions (v2)
ae --serve --cap file.read,file.write,net.http.get
```

### Protocol

Request (stdin, one JSON per line):
```json
{"id": "req-1", "agent": "planner", "cmd": "sys.cpu_info()", "timeout_ms": 5000}
```

Response (stdout, one JSON per line, v2 streaming protocol):
```json
{
  "type": "done",
  "id": "req-1",
  "ok": true,
  "value": {"cores": 8, "mhz": 3601, "name": "AMD Ryzen 7..."},
  "meta": {
    "elapsed_ms": 12,
    "agent": "planner",
    "cache_hit": true,
    "session_age_ms": 120
  }
}
```

Streaming message types: `done` (complete), `error` (failure). Future: `start`/`chunk`/`progress` for incremental results.

### Compact Token-Efficient Protocol (`--format compact`)

Positional encoding with single-char type tags. Saves 50-70% tokens vs JSON:

```bash
ae --serve --format compact
echo '{"id":"r1","agent":"t","cmd":"sys.cpu_info()"}' | ae --serve --format compact
```

**Format:**
```
D <id> <ok> <value> <elapsed_ms> <cache_hit> <session_age_ms>
E <id> <code> <message> <recoverable>
```

**Value encoding:**
| Type | Encoding | Example |
|------|----------|---------|
| null | `N` | `N` |
| bool | `T` / `F` | `T` |
| int | number | `42` |
| float | number | `3.14` |
| string | `S<len>:<content>` | `S5:hello` |
| array | `L<len> <items>` | `L3 1 2 3` |
| record | `R<len> <k1> <v1> ...` | `R2 x 1 y 2` |

**Token savings:**
| Payload | JSON | Compact | Savings |
|---------|------|---------|---------|
| Simple int | 96 chars | 16 chars | **83%** |
| `sys.cpu_info()` | 178 chars | 115 chars | **35%** |
| Average | — | — | **50-70%** |

### Server Control Commands

| Command (stdin) | Action |
|-----------------|--------|
| `STATS` | Returns cache hit rates, sessions, uptime |
| `GC` | Force garbage-collect idle sessions |
| `REFRESH` | Force-refresh system snapshot cache |
| `SHUTDOWN` | Graceful shutdown |

### Error Handling & Self-Recovery

Every error response includes `code`, `message`, `hint`, and `recoverable` fields for agent self-correction:

| Code | Trigger | Example Hint |
|------|---------|-------------|
| `E_UNKNOWN_BUILTIN` | Typo `srot` | `did you mean 'sort'? (distance 2)` |
| `E_PARSE` | Syntax error | `check syntax: missing parens, quotes, or operator` |
| `E_TYPE` | Type mismatch | `use 'describe' to inspect value types` |
| `E_IO` | File/path error | `check that the file path exists` |
| `E_RATE_LIMIT` | Exceeded rate | `reduce request frequency` |
| `E_TIMEOUT` | Operation hung | `increase timeout_ms` |
| `E_PANIC` | Internal crash | `the request triggered an unrecoverable error` |
| `E_CAPABILITY_DENY` | Missing capability | `builtin 'cat' requires capability 'file.read'` |

### Capability-Based Security (v2)

Explicit capability grants replace implicit deny/allow rules. 27 granular capabilities covering all builtins:

```bash
ae --cap file.read,file.write,net.http.get -c "file.read(\"data.txt\")"
ae --cap all  # grants everything
ae --cap sys.read -c "file.read(\"...\")"  # DENIED — only sys.read granted
```

| Category | Capabilities |
|----------|-------------|
| System | `sys.read`, `sys.uptime`, `sys.env` |
| Files | `file.read`, `file.write`, `file.delete`, `file.lock`, `file.watch` |
| Network | `net.http.get`, `net.http.post`, `net.http.delete`, `net.ping`, `net.dns` |
| Process | `proc.list`, `proc.kill`, `proc.spawn`, `shell.exec` |
| Windows | `win.registry`, `win.service`, `win.env`, `win.admin` |
| Data | `crypto.hash`, `crypto.random`, `db.read`, `db.write`, `git.read`, `git.write` |

Safe functions (math, strings, arrays, json) are always allowed without explicit capability grants.

### Runtime Reliability

- **Panic recovery**: `catch_unwind` per request — one crash never brings down the server
- **Rate limiting**: `--rate-limit N` throttles per-agent requests/sec
- **Lock-free architecture**: Per-session `Mutex<Env>` + `RwLock` session lookup; N agents run without serialization
- **Work-stealing scheduler** (v2.1): `--scheduler --scheduler-workers 8` with priority queues and per-agent CPU budgets
- **Capability system** (v2): 27 fine-grained capabilities, enforced at builtin dispatch level
- **IR layer** (v2): `parser → AST → IR → optimizer → executor` with constant folding and pipeline fusion
- **Unified execution** (v3): All paths converge into single `IREvaluator` (28 match arms). Builtins carry `IREffect` at compile time. Pipeline stages (`Map`/`Filter`/`Sort`/`Reduce`/`Take`) evaluated directly in IR.

### Batch Requests

```bash
echo '[{"id":"1","agent":"b","cmd":"1+1"},{"id":"2","agent":"b","cmd":"sys.os()"}]' | ae --serve
# → [{"id":"1","ok":true,"value":2,...},{"id":"2","ok":true,"value":"windows",...}]
```

### Session Reuse & Caching

- **AST cache**: Identical commands skip re-parsing (`cache_hit: true` in meta)
- **System snapshot cache**: `sys.cpu_info()` etc. cached with 5s TTL
- **Session pool**: Same `agent` ID reuses Env (module registrations, variables)
- **Lock-free**: No global Mutex — N agents execute concurrently on their own sessions
- **Thread pool**: `--max-concurrency` limits concurrent agent execution

## Modules

### sys — System Information

| Function | Returns |
|----------|---------|
| `sys.hostname()` | Hostname string |
| `sys.os()` | `"windows"` / `"linux"` / `"macos"` |
| `sys.arch()` | `"x86_64"` / `"aarch64"` |
| `sys.uptime()` | Seconds since boot |
| `sys.cpu_info()` | `{name, cores, mhz}` |
| `sys.mem_info()` | `{total, free, available}` bytes |
| `sys.disk_info()` | Array of `{filesystem, size, used, available, use_percent, mounted_on}` |
| `sys.load_avg()` | `{1min, 5min, 15min}` |
| `sys.env_all()` | All environment variables |
| `sys.describe()` | Type introspection (pipe a value) |
| `sys.process_info(pid)` | Detailed process info |
| `sys.audit_log(n)` | Recent audit log entries |

### file — File System

| Function | Description |
|----------|-------------|
| `file.ls(path)` | List directory |
| `file.pwd()` | Current working directory |
| `file.read(path)` | Read file content |
| `file.write(path, content)` | Write file |
| `file.exists(path)` | Check existence |
| `file.copy(src, dst)` | Copy file |
| `file.move(src, dst)` | Move/rename file |
| `file.head(path, n)` | First N lines |
| `file.tail(path, n)` | Last N lines |
| `file.grep(pattern, path)` | Search file for pattern |
| `file.wc(path)` | Line/word/char count |
| `file.mkdir(path)` | Create directory |
| `file.lock(path, fn)` | Advisory lock + atomic execute |

### arr — Array Operations

| Function | Description |
|----------|-------------|
| `arr.sort(arr)` | Sort array |
| `arr.filter(arr, pred)` | Filter by predicate |
| `arr.map(arr, fn)` | Transform elements |
| `arr.reduce(arr, fn, init)` | Aggregate |
| `arr.first(arr)` / `arr.last(arr)` | First/last element |
| `arr.take(arr, n)` | First N elements |
| `arr.any(arr)` / `arr.all(arr)` | Boolean tests |
| `arr.unique(arr)` | Deduplicate |
| `arr.flatten(arr)` | Flatten nested arrays |
| `arr.range(start, end)` | Generate range |
| `arr.zip(a, b)` | Zip two arrays |
| `arr.concat(a, b)` | Concatenate arrays |
| `arr.in(needle, haystack)` | Membership test |
| `arr.group_by(prop)` | Group by property |
| `arr.select(prop1, prop2, ...)` | Select record fields |
| `arr.keys(rec)` / `arr.values(rec)` | Record keys/values |
| `arr.uniq(arr)` | Deduplicate |
| `arr.par_map(arr, fn)` | Parallel map (multi-threaded) |

### win — Windows Native

| Function | Description |
|----------|-------------|
| `win.snapshot()` | Full system snapshot (CPU, memory, disks, PATH) |
| `win.registry_get(key, val)` | Read Windows registry |
| `win.service_list()` | List all services |
| `win.service_status(name)` | Service status (e.g. "WlanSvc") |
| `win.env_path()` | PATH entries as array |
| `win.env_get(name)` | Get environment variable |
| `win.env_set(name, val)` | Set environment variable |
| `win.is_admin()` | Check administrator privileges |
| `win.shortcut_resolve(path)` | Resolve .lnk to target |
| `win.process_kill(pid)` | Kill process by PID |

### str — String Operations

| Function | Description |
|----------|-------------|
| `str.upper(s)` / `str.lower(s)` | Case conversion |
| `str.trim(s)` | Trim whitespace |
| `str.split(s, sep)` | Split by separator |
| `str.join(sep, arr)` | Join array with separator |
| `str.replace(s, from, to)` | Replace substring |
| `str.contains(s, substr)` | Substring test |
| `str.length(s)` | String length |
| `str.slice(s, start, end)` | Substring |

### math — Math Functions

| Function | Description |
|----------|-------------|
| `math.abs(n)` | Absolute value |
| `math.min(a,b)` / `math.max(a,b)` | Min/max |
| `math.floor(n)` / `math.ceil(n)` / `math.round(n)` | Rounding |
| `math.sqrt(n)` | Square root |
| `math.pow(b, e)` | Power |
| `math.sum(arr)` / `math.mean(arr)` | Statistics |

### shell — Process Control

| Function | Description |
|----------|-------------|
| `shell.exec([program, ...args])` | Execute a process directly with explicit argv; preferred for agents |
| `shell.exec("program arg")` | Convenience shorthand for simple whitespace-split commands only |
| `shell.sleep(secs)` | Sleep for duration |
| `shell.echo(msg)` | Print message |
| `shell.exit(code)` | Exit with code |

### crypto — Cryptography

| Function | Description |
|----------|-------------|
| `crypto.hash(data, algo)` | SHA-256/MD5 hash |
| `crypto.uuid()` | Generate UUID v4 |
| `crypto.random_bytes(n)` | Random hex bytes |
| `crypto.base64_encode(data)` | Base64 encode |
| `crypto.base64_decode(data)` | Base64 decode |

### json — JSON

| Function | Description |
|----------|-------------|
| `json.parse(str)` | Parse JSON to record/array |
| `json.stringify(val)` | Convert to JSON string |

### http — HTTP Client

| Function | Description |
|----------|-------------|
| `http.get(url)` | HTTP GET |
| `http.post(url, data)` | HTTP POST |
| `http.put(url, data)` | HTTP PUT |
| `http.delete(url)` | HTTP DELETE |
| `http.json_post(url, data)` | POST with JSON content-type |

### Additional Modules

- **proc** — Process listing, info, kill, spawn
- **net** — Network interfaces, ping, DNS, ports, connections
- **hw** — CPU, memory, disk, GPU, battery info
- **platform** — OS/arch/cpu/memory/disks/gpus detection
- **git** — Status, branch, commit, log, diff
- **crypto** — Hash, UUID, random, encode/decode
- **db** — SQLite open/query
- **svc** — Service management (list/start/stop)
- **cron** — Cron job management
- **archive** — Compress/extract tar/zip
- **user** — Current user, groups
- **perm** — File permissions
- **pkg** — Package manager queries
- **input** — Read line, char, password from stdin
- **clip** — Clipboard read/write

## Agent Quick Reference (v0.5.1)

Use `ae --core` or `list_commands(core=true)` for the ~70 most-used builtins.

| Category | Builtins |
|----------|----------|
| **System** | `sys.cpu_info()` `sys.mem_info()` `sys.disk_info()` `sys.hostname()` `sys.os()` `sys.arch()` `sys.load_avg()` `sys.process_info()` `sys.uptime()` `sys.env_all()` `sys.describe()` |
| **Process** | `proc.list()` `proc.kill(PID)` `proc.info(PID)` `proc.grep(NAME)` `proc.spawn([CMD,ARGS])` |
| **File** | `file.ls()` `file.read()` `file.write()` `file.stat()` `file.find()` `file.mkdir()` `file.copy()` `file.move()` `file.remove()` `file.exists()` `file.head()` `file.tail()` `file.grep()` `file.wc()` |
| **Network** | `http.get(URL)` `http.post(URL,BDY)` `net.ping(HOST)` `net.interfaces()` `net.dns_lookup(HOST)` |
| **Shell** | `shell.exec([CMD,ARGS])` |
| **Data** | `str.join()` `str.split()` `str.replace()` `str.grep()` `json.parse()` `json.stringify()` `sort` `map` `where` `reduce` `take` `first` `last` `any` `all` `unique` `flatten` `range` |
| **Math** | `math.abs()` `math.min()` `math.max()` `math.sum()` `math.mean()` |
| **Windows** | `win.snapshot()` `win.registry_get()` `win.env_get()` |
| **Crypto** | `crypto.hash()` `crypto.uuid()` |

## Agent Usage

### One-Shot Commands

```bash
# Get system status as JSON
ae --json -c "{host: sys.hostname(), os: sys.os(), cpu: sys.cpu_info(), mem: sys.mem_info().total}"

# Windows system snapshot
ae --json -c "win.snapshot()"

# Read registry
ae -c "win.registry_get(\"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\", \"ProductName\")"

# Process management
ae -c "sys.process_info(1234)"
```

### JSON-RPC Server (Recommended for Multi-Agent)

```bash
# Start server
ae --serve --agent --workspace /safe --max-concurrency 8

# Agent queries (via stdin)
echo '{"id":"1","agent":"monitor","cmd":"sys.cpu_info()"}' | ae --serve
echo '{"id":"2","agent":"worker","cmd":"[1,2,3] | map fn(x)=>x*2"}' | ae --serve

# Batch query
echo '[{"id":"1","agent":"b","cmd":"sys.hostname()"},{"id":"2","agent":"b","cmd":"sys.os()"}]' | ae --serve

# Check stats
echo STATS | ae --serve
```

### Safety Sandbox

```bash
# Agent mode: deny dangerous operations, confine to workspace
ae --agent --workspace /safe/dir -c "file.read(\"data.txt\")"

# With timeout for network operations
ae --agent --timeout 10 -c "http.get(\"https://api.example.com/data\")"

# Atomic file write (temp → fsync → rename)
ae --agent --workspace /tmp -c "file.write(\"out.txt\", \"content\")"

# Advisory file locking (prevents concurrent writes)
ae -c "file.lock(\"shared.json\", fn(p) => file.write(p, \"{updated: true}\"))"
```

### Data Pipeline

```bash
# List files, filter, transform
ae --json -c "file.ls(\".\") | where fn(f) => f.ext == \"rs\" | map fn(f) => {name: f.name, size: f.size}"

# Parallel processing
ae -c "large_array | par_map fn(x) => expensive_computation(x)"

# Chained operations
ae -c "[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10"
```

### Error Recovery

```bash
ae -c "try { http.get(url) } catch e { {error: \"fetch failed\", detail: e} }"
# Structured error in agent/json mode:
ae --json -c "invalid" 2>&1
# → {"error":{"code":"EVAL_ERROR","message":"..."}}
```

## Building

Requirements: Rust 1.75+

```bash
cargo build --release                        # Release build (~12 MB)
cargo test --test integration_tests           # 50 integration tests
cargo test --test concurrent_performance_tests -- --nocapture  # Concurrency stress tests
cargo bench                                   # 4 performance benchmarks
```

## Capability Summary

| Category | Features |
|----------|----------|
| **Language** | Typed functional, HM inference, pipelines, lambdas, pattern matching, try/catch, string interpolation |
| **System** | CPU, memory, disks, load avg, uptime, hostname, OS/arch, environment variables, process info |
| **Files** | ls, pwd, read, write (atomic), copy, move, exists, head, tail, grep, wc, mkdir, lock |
| **Arrays** | map, filter/where, sort, reduce, take, first/last, any/all, unique, flatten, range, zip, concat, in, group_by, select, keys/values, uniq |
| **Strings** | upper/lower, trim, split, join (auto-detect arg order), replace, contains, starts/ends, length, slice |
| **Math** | abs, min/max, floor/ceil/round, sqrt, pow, sum, mean |
| **HTTP** | GET, POST, PUT, DELETE (reqwest + timeout) |
| **Windows** | Registry, services, PATH, shortcuts, admin detection, process kill, env get/set, snapshot |
| **Safety** | Agent mode, workspace jail, RBAC, audit log, **capability-based security (27 caps)**, timeout, token budget, panic recovery, rate limiting |
| **Server** | JSON-RPC stdio, session pool, AST cache, sys snapshot cache, **work-stealing scheduler**, batch requests, lock-free concurrency |
| **V2 Kernel** | IR layer (canonical + hashable + optimizable), capability system, pipeline unification |
| **V3 Kernel** | **Unified IR-native execution** (single `IREvaluator`), **22 effect types** (compile-time capability annotation), pipeline stage inlining |
| **Errors** | 8 structured error codes with hint suggestions, Levenshtein nearest-builtin matching |
| **Output** | Canonical JSON, **compact token-efficient (50-70% savings)**, clean human format, AECON compact, structured errors |

## Performance

```bash
cargo bench                       # Run all benchmarks
cargo bench -- --quick            # Quick mode
```

Built-in optimizations:
- **Unified IR-native execution** (v3): Single `IREvaluator` replaces 3 divergent execution paths — consistent semantics, unified debugging
- **Effect-aware compilation** (v3): Every `Builtin` node carries `IREffect` at compile time, eliminating runtime string-match capability checks
- **Pipeline stage inlining** (v3): `Map`/`Filter`/`Sort`/`Reduce`/`Take` evaluated directly in IR without builtin dispatch overhead
- **IR optimizer** (v2): Constant folding (`1+2` → `3` at compile time), pipeline fusion (map+map → single composed lambda)
- **Lock-free runtime**: Per-session `Mutex<Env>` — N agents never serialize on a global lock
- **Work-stealing scheduler** (v2.1): Priority queues, per-agent CPU budgets, idle worker stealing
- **AST cache**: Commands parsed once, cached globally (1024 entries)
- **System snapshot cache**: `sys.*` results cached with 5s TTL
- **`par_map`**: Multi-threaded array processing (auto thread count)
- **`--timeout`**: Prevents hung http/shell operations
- **Batch requests**: Send multiple commands in one JSON array
- **Arc-shared modules**: Session creation O(1) — no deep-clone of 26 modules
- **Compact protocol**: Positional + type-tag encoding saves 50-70% tokens vs JSON for agent communication

## Architecture

```
src/
├── main.rs          # CLI entry point (run/serve modes)
├── lib.rs           # Module declarations (34 source files)
├── parser.rs        # Source → AST (recursive descent)
├── eval.rs          # AST evaluator + pipeline engine
├── ir.rs            # V3 IR: IREvaluator, IREffect (22 types), IRCompiler, IROptimizer
├── capability.rs    # V2 capability-based security (27 granular caps)
├── scheduler.rs     # V2.1 work-stealing scheduler + agent quotas
├── compact.rs        # Compact token-efficient protocol (positional+type-tag encoding)
├── builtins.rs       # 650+ builtin function implementations
├── modules.rs       # Namespaced module → builtin mappings (26 modules)
├── value.rs         # Runtime value system (15 variants)
├── types.rs         # Type lattice
├── typecheck.rs     # Hindley-Milner type inference
├── env.rs           # Environment & scope (session state)
├── safety.rs        # Safety model, RBAC, audit, workspace jail
├── repl.rs          # REPL + output formatting + run_eval API
├── runtime.rs       # AgentRuntime: session pool, dispatch, stats
├── server.rs        # JSON-RPC stdio server (v2.1 streaming + scheduler)
├── cache.rs         # GlobalCache: AST, type, sys snapshot
├── config.rs        # Configuration management (TOML)
├── tx.rs            # Transaction engine (begin/commit/rollback)
├── transpile/       # Bash→ae transpiler (bash.rs)
├── benches/         # 4 criterion benchmarks
└── tests/           # 50 integration tests + concurrency stress tests
```

## License

AGPL-3.0-or-later
