# ACI-Bench LIVE Report

- Generated: 2026-09-24T10:47:53.729763+00:00
- Task set: 1.1.0
- Mode: **LIVE** (real LLM multi-turn tool-calling)
- Model: `sn-glm-5-3-flash`

## Leaderboard

| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |
|---|---|---:|---:|---:|---:|
| sn-glm-5-3-flash | raw_shell | 10 | 0.5 | 2.5 | 148.4 |
| sn-glm-5-3-flash | verseshell_aci | 10 | 0.4 | 3.3 | 96.9 |

## Condition A vs D

### sn-glm-5-3-flash → **PARTIAL** (no clear advantage)

| Metric | Raw Shell (A) | VerseShell ACI (D) | Ratio (D/A) |
|---|---|---:|---:|
| Success rate | 0.5 | 0.4 | — |
| Avg tool calls | 2.5 | 3.3 | 1.32 |
| Avg observation tokens | 148.4 | 96.9 | 0.653 |
| Gate | — | — | **PARTIAL** |

## Per-Task Trajectories

### rust_fix_compile_error [raw_shell] → PASS
- Reason: all ok
- Tool calls: 4, Observation tokens: 92
- Turns: 4, Elapsed: 40692ms
- LLM: 3048 prompt + 206 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type Cargo.toml"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"open(r'src\\lib.rs','w').write('pub fn add(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\""}
  1. `run_command` — {"command": "cargo check"}
  1. `task_complete` — {"success": true, "summary": "Fixed return type in src/lib.rs from String to i32; cargo check passes cleanly."}

### rust_fix_compile_error [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 4, Observation tokens: 111
- Turns: 4, Elapsed: 51869ms
- LLM: 6279 prompt + 182 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.replace_exact` — {"new": "pub fn add(a: i32, b: i32) -> i32 {", "old": "pub fn add(a: i32, b: i32) -> String {", "path": "src/lib.rs"} aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "check"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Changed add() return type from String to i32 in src/lib.rs; cargo check passes cleanly."}

### rust_add_unit_test [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 2, Observation tokens: 178
- Turns: 3, Elapsed: 53105ms
- LLM: 2322 prompt + 460 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type Cargo.toml & echo --- & type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"open(r'src\\lib.rs','a').write('\\n#[cfg(test)]\\nmod tests {\\n    use super::add;\\n\\n    #[test]\\n    fn test_add() {\\n        assert_eq!(add(2, 3), 5);\\n        assert
  1. `task_complete` — {"success": true, "summary": "Added a unit test for add() in src/lib.rs (cfg(test) module with assertions for positive, negative, and zero cases); cargo test passes."}

### rust_add_unit_test [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 0, Observation tokens: 0
- Turns: 1, Elapsed: 71318ms
- LLM: 1388 prompt + 4096 completion tokens
- Trajectory:

### rust_search_and_edit [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 3, Observation tokens: 286
- Turns: 4, Elapsed: 15105ms
- LLM: 3549 prompt + 245 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /s /b && type Cargo.toml && type src\\lib.rs && type TASK.md"}
  1. `run_command` — {"command": "python -c \"open(r'src\\lib.rs','w').write('''pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n''')\" && type src\\lib.rs"}
  1. `run_command` — {"command": "cargo test"}
  1. `task_complete` — {"success": true, "summary": "Implemented sum(a, b) function body (returns a + b) in src/lib.rs; cargo test compiles successfully."}

### rust_search_and_edit [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 4, Observation tokens: 95
- Turns: 4, Elapsed: 32289ms
- LLM: 6070 prompt + 140 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `repo.summary` — {} aci_ok=True
  1. `file.write` — {"content": "pub fn sum(a: i32, b: i32) -> i32 {\n    a + b\n}\n", "path": "src/lib.rs"} aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "test"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Implemented sum(a, b) as a + b in src/lib.rs; cargo test passes."}

### python_fix_pytest_fail [raw_shell] → PASS
- Reason: file_contains mathlib.py
- Tool calls: 3, Observation tokens: 190
- Turns: 4, Elapsed: 29151ms
- LLM: 3048 prompt + 221 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type mathlib.py & type tests\\test_math.py"}
  1. `run_command` — {"command": "python -c \"open('mathlib.py','w').write('def add(a, b):\\n    return a + b\\n')\" && type mathlib.py"}
  1. `run_command` — {"command": "python -m pytest tests/ -v"}
  1. `task_complete` — {"success": true, "summary": "Fixed add(a,b) in mathlib.py to return a+b instead of a*b; pytest passes (1 passed)."}

### python_fix_pytest_fail [verseshell_aci] → FAIL
- Reason: file_contains mathlib.py
- Tool calls: 0, Observation tokens: 0
- Turns: 1, Elapsed: 2373ms
- Trajectory:

### python_edit_and_retest [raw_shell] → FAIL
- Reason: file_contains greet.py
- Tool calls: 0, Observation tokens: 0
- Turns: 1, Elapsed: 2047ms
- Trajectory:

### python_edit_and_retest [verseshell_aci] → PASS
- Reason: file_contains greet.py
- Tool calls: 4, Observation tokens: 108
- Turns: 4, Elapsed: 30290ms
- LLM: 6253 prompt + 199 completion tokens
- Trajectory:
  1. `file.view` — {"path": "greet.py"} aci_ok=True
  1. `file.view` — {"path": "tests/test_greet.py"} aci_ok=True
  1. `file.write` — {"content": "def greet(name):\n    return f\"Hello, {name}!\"\n", "path": "greet.py"} aci_ok=True
  1. `exec.run` — {"argv": ["python", "-m", "pytest", "-q"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Updated greet() in greet.py to return 'Hello, {name}!'; pytest passes (1 passed)."}

### python_noisy_install_summary [raw_shell] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 2, Observation tokens: 181
- Turns: 3, Elapsed: 31034ms
- LLM: 2399 prompt + 317 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir && type requirements.txt && type TASK.md"}
  1. `run_command` — {"command": "pip install -r requirements.txt --quiet && pip show six | findstr /C:\"Name\" /C:\"Version\" && python -c \"open('SUMMARY.txt','w').write('Installed 1 package from requirements.txt: six 1
  1. `task_complete` — {"success": true, "summary": "Installed 1 package (six 1.16.0) from requirements.txt and wrote a one-line dependency summary to SUMMARY.txt."}

### python_noisy_install_summary [verseshell_aci] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 5, Observation tokens: 85
- Turns: 5, Elapsed: 34590ms
- LLM: 7670 prompt + 281 completion tokens
- Trajectory:
  1. `file.view` — {"path": "requirements.txt"} aci_ok=True
  1. `repo.summary` — {} aci_ok=True
  1. `exec.run` — {"argv": ["pip", "install", "-r", "requirements.txt"], "profile": "npm_install"} aci_ok=True
  1. `file.write` — {"content": "Dependencies installed: 1 pinned package (six==1.16.0) from requirements.txt; install completed cleanly with no additional transitive dependencies required.\n", "path": "SUMMARY.txt"} aci_ok=True
  1. `exec.run` — {"argv": ["python", "-c", "import six; print(six.__version__)"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Installed the single pinned dependency (six==1.16.0) from requirements.txt, verified the import works, and wrote a one-line dependency summary to SUMMARY.txt."}

### ts_fix_type_error [raw_shell] → FAIL
- Reason: file_contains src/index.ts
- Tool calls: 4, Observation tokens: 302
- Turns: 4, Elapsed: 17370ms
- LLM: 3719 prompt + 460 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type package.json tsconfig.json src\\index.ts"}
  1. `run_command` — {"command": "dir /s /b src"}
  1. `run_command` — {"command": "python -c \"open('src/index.ts','w').write('export function add(a: number, b: number): number {\\n  const x: number = a + b;\\n  return x;\\n}\\n')\" && npx tsc --noEmit && echo TYPECHECK
  1. `run_command` — {"command": "npm install --no-audit --no-fund && npx tsc --noEmit && echo TYPECHECK_OK"}
  1. `task_complete` — {"success": true, "summary": "Fixed type error in src/index.ts by changing `const x: string` to `const x: number` (a + b is a number); tsc --noEmit now passes."}

### ts_fix_type_error [verseshell_aci] → FAIL
- Reason: file_contains src/index.ts
- Tool calls: 10, Observation tokens: 388
- Turns: 8, Elapsed: 23020ms
- LLM: 14754 prompt + 312 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/index.ts"} aci_ok=True
  1. `file.view` — {"path": "tsconfig.json"} aci_ok=True
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `file.replace_exact` — {"new": "  const x: number = a + b;", "old": "  const x: string = a + b;", "path": "src/index.ts"} aci_ok=True
  1. `exec.run` — {"argv": ["tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["npx", "tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["npx.cmd", "tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm", "install", "--save-dev", "typescript"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm.cmd", "install", "--save-dev", "typescript"]} aci_ok=True
  1. `exec.run` — {"argv": ["npx.cmd", "tsc", "--noEmit"]} aci_ok=True

### ts_package_script_fail [raw_shell] → PASS
- Reason: file_contains package.json
- Tool calls: 3, Observation tokens: 184
- Turns: 3, Elapsed: 39090ms
- LLM: 2425 prompt + 396 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /A && type package.json"}
  1. `run_command` — {"command": "npm test"}
  1. `run_command` — {"command": "python -c \"import json;p='package.json';d=json.load(open(p));d['scripts']['test']='node -e \\\"process.exit(0)\\\"';json.dump(d,open(p,'w'),indent=2);open(p,'a').write('\\n')\" && npm te
  1. `task_complete` — {"success": true, "summary": "Fixed package.json test script from `node -e \"process.exit(1)\"` to exit with 0; verified `npm test` exits 0."}

### ts_package_script_fail [verseshell_aci] → PASS
- Reason: file_contains package.json
- Tool calls: 5, Observation tokens: 172
- Turns: 5, Elapsed: 48411ms
- LLM: 8004 prompt + 505 completion tokens
- Trajectory:
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `repo.summary` — {} aci_ok=True
  1. `file.replace_exact` — {"new": "    \"test\": \"node -e \\\"process.exit(0)\\\"\"", "old": "    \"test\": \"node -e \\\"process.exit(1)\\\"\"", "path": "package.json"} aci_ok=True
  1. `exec.run` — {"argv": ["npm", "test"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm.cmd", "test"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed package.json test script from \"node -e process.exit(1)\" to exit(0); npm test now passes."}

### windows_path_normalize_edit [raw_shell] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 2, Observation tokens: 13
- Turns: 3, Elapsed: 6332ms
- LLM: 1989 prompt + 112 completion tokens
- Trajectory:
  1. `run_command` — {"command": "python -c \"from pathlib import Path; Path('out').mkdir(exist_ok=True); Path('out/result.txt').write_text('OK')\""}
  1. `run_command` — {"command": "type out\\result.txt"}
  1. `task_complete` — {"success": true, "summary": "Created out/result.txt containing 'OK'"}

### windows_path_normalize_edit [verseshell_aci] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 1, Observation tokens: 10
- Turns: 2, Elapsed: 66778ms
- LLM: 2902 prompt + 4345 completion tokens
- Trajectory:
  1. `exec.run` — {"argv": ["python", "-c", "from pathlib import Path; p = Path('out'); p.mkdir(parents=True, exist_ok=True); (p / 'result.txt').write_text('OK'); print('written:', (p / 'result.txt').read_text())"], "c aci_ok=True

### windows_batch_capture_diag [raw_shell] → PASS
- Reason: all ok
- Tool calls: 2, Observation tokens: 58
- Turns: 3, Elapsed: 27641ms
- LLM: 1994 prompt + 416 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type broken_build.log"}
  1. `run_command` — {"command": "echo src\\main.rs:12> ERR.txt && type ERR.txt"}
  1. `task_complete` — {"success": true, "summary": "Extracted first build error location 'src\\main.rs:12' from broken_build.log and wrote it to ERR.txt."}

### windows_batch_capture_diag [verseshell_aci] → FAIL
- Reason: missing ERR.txt
- Tool calls: 0, Observation tokens: 0
- Turns: 1, Elapsed: 62224ms
- LLM: 1374 prompt + 4096 completion tokens
- Trajectory:

---

**Key**:
- Condition A = raw shell (`run_command` only — full build logs, no reduction)
- Condition D = VerseShell ACI (`file.view`, `exec.run`, `file.replace_exact`, etc. via `ae --serve --agent`, with semantic output reduction)
- `aci_ok` = whether the individual AE op returned success
- `meets_acceptance` gate: D success > A success, OR D tool_calls < 70% of A, OR D obs_tokens < 60% of A
