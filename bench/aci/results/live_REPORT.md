# ACI-Bench LIVE Report

- Generated: 2026-09-22T15:45:49.158797+00:00
- Task set: 1.1.0
- Mode: **LIVE** (real LLM multi-turn tool-calling)
- Model: `sn-glm-5-3-flash`

## Leaderboard

| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |
|---|---|---:|---:|---:|---:|
| sn-glm-5-3-flash | raw_shell | 10 | 0.6 | 2.8 | 152.1 |
| sn-glm-5-3-flash | verseshell_aci | 10 | 0.6 | 6.5 | 399.0 |

## Condition A vs D

### sn-glm-5-3-flash → **PARTIAL** (no clear advantage)

| Metric | Raw Shell (A) | VerseShell ACI (D) | Ratio (D/A) |
|---|---|---:|---:|
| Success rate | 0.6 | 0.6 | — |
| Avg tool calls | 2.8 | 6.5 | 2.3214 |
| Avg observation tokens | 152.1 | 399.0 | 2.6233 |
| Gate | — | — | **PARTIAL** |

## Per-Task Trajectories

### rust_fix_compile_error [raw_shell] → PASS
- Reason: all ok
- Tool calls: 2, Observation tokens: 103
- Turns: 3, Elapsed: 27239ms
- LLM: 1181 prompt + 222 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type Cargo.toml & type src\\lib.rs & type TASK.md"}
  1. `run_command` — {"command": "python -c \"open('src/lib.rs','w').write('pub fn add(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\" && cargo check"}
  1. `task_complete` — {"success": true, "summary": "Fixed src/lib.rs return type from String to i32; cargo check succeeds."}

### rust_fix_compile_error [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 9, Observation tokens: 590
- Turns: 8, Elapsed: 244884ms
- LLM: 7578 prompt + 617 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.replace_exact` — {"expected_hash": "sha256:471dfab5b79f216a7cf835a2ef71456800a904f5155774e2a333408ae14a9f51", "new": "pub fn add(a: i32, b: i32) -> i32 {", "old": "pub fn add(a: i32, b: i32) -> String {", "path": "src aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "check"]} aci_ok=False
  1. `exec.run` — {"argv": ["cargo", "--version"], "profile": "none"} aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "check"], "profile": "none"} aci_ok=False
  1. `exec.run` — {"argv": ["cargo", "+stable-x86_64-pc-windows-msvc", "check"], "profile": "none"} aci_ok=False
  1. `exec.run` — {"argv": ["rustc", "--version", "--verbose"], "profile": "none"} aci_ok=True
  1. `exec.run` — {"argv": ["cmd", "/c", "set RUSTUP"], "profile": "none"} aci_ok=True

### rust_add_unit_test [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 3, Observation tokens: 196
- Turns: 4, Elapsed: 36814ms
- LLM: 1839 prompt + 384 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type Cargo.toml & type src\\lib.rs & type TASK.md"}
  1. `run_command` — {"command": "python -c \"open(r'src\\lib.rs','a').write('\\n#[cfg(test)]\\nmod tests {\\n    use super::*;\\n\\n    #[test]\\n    fn test_add() {\\n        assert_eq!(add(2, 3), 5);\\n        assert_e
  1. `run_command` — {"command": "cargo test"}
  1. `task_complete` — {"success": true, "summary": "Added a unit test for add() in src/lib.rs; cargo test passes (1 passed, 0 failed)."}

### rust_add_unit_test [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 9, Observation tokens: 692
- Turns: 8, Elapsed: 109286ms
- LLM: 8912 prompt + 1008 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.replace_exact` — {"expected_hash": "sha256:2551a0f2f738405daa1340ba7e0507f1843dc101231f37ac55b6a31203c28fb6", "new": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::add; aci_ok=False
  1. `file.replace_exact` — {"expected_hash": "sha256:2551a0f2f738405daa1340ba7e0507f1843dc101231f37ac55b6a31203c28fb6", "new": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::add; aci_ok=False
  1. `file.write` — {"content": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::add;\n\n    #[test]\n    fn test_add() {\n        assert_eq!(add(2, 3), 5);\n        assert_ aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "test"]} aci_ok=False
  1. `exec.run` — {"argv": ["cargo", "--version"]} aci_ok=True
  1. `exec.run` — {"argv": ["rustc", "--version"]} aci_ok=True
  1. `exec.run` — {"argv": ["rustup", "run", "stable", "cargo", "test"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Added a #[cfg(test)] unit test module for add() in src/lib.rs (covering positive, negative, and zero cases); cargo test passes (1 passed, 0 failed)."}

### rust_search_and_edit [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 3, Observation tokens: 294
- Turns: 3, Elapsed: 12182ms
- LLM: 1641 prompt + 313 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /s /b && type Cargo.toml && type src\\lib.rs && type TASK.md"}
  1. `run_command` — {"command": "findstr /s /n \"TODO\" src\\*.*"}
  1. `run_command` — {"command": "python -c \"open(r'src\\lib.rs','w').write('pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\" && type src\\lib.rs && cargo test"}
  1. `task_complete` — {"success": true, "summary": "Implemented sum(a, b) in src/lib.rs to return a + b, replacing the TODO(fix-me) stub; cargo test passes."}

### rust_search_and_edit [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 11, Observation tokens: 854
- Turns: 8, Elapsed: 104065ms
- LLM: 9150 prompt + 938 completion tokens
- Trajectory:
  1. `repo.summary` — {} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.replace_exact` — {"expected_hash": "sha256:9e7e6da826ccd2c01e7f734d0e68fc9da196b8f6e8f2bcb43b09dd98f91fb2c6", "new": "pub fn sum(a: i32, b: i32) -> i32 {\n    a + b\n}", "old": "pub fn sum(a: i32, b: i32) -> i32 {\n   aci_ok=False
  1. `file.replace_exact` — {"new": "pub fn sum(a: i32, b: i32) -> i32 {\n    a + b\n}", "old": "pub fn sum(a: i32, b: i32) -> i32 {\n    // TODO(fix-me)\n    0\n}", "path": "src/lib.rs"} aci_ok=False
  1. `file.replace_exact` — {"new": "    a + b", "old": "    // TODO(fix-me)\n    0", "path": "src/lib.rs"} aci_ok=False
  1. `file.write` — {"content": "pub fn sum(a: i32, b: i32) -> i32 {\n    a + b\n}\n", "path": "src/lib.rs"} aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "test"], "profile": "cargo"} aci_ok=False
  1. `exec.run` — {"argv": ["cargo", "build"], "profile": "cargo"} aci_ok=False
  1. `exec.run` — {"argv": ["rustc", "--edition=2021", "--crate-type=lib", "src/lib.rs", "--emit=metadata", "-o", "libcheck.rmeta"], "profile": "none"} aci_ok=False

### python_fix_pytest_fail [raw_shell] → PASS
- Reason: file_contains mathlib.py
- Tool calls: 2, Observation tokens: 72
- Turns: 3, Elapsed: 17956ms
- LLM: 1048 prompt + 191 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type mathlib.py & type TASK.md & type tests\\test_math.py"}
  1. `run_command` — {"command": "python -c \"open('mathlib.py','w').write('def add(a, b):\\n    return a + b\\n')\" && python -m pytest -q"}
  1. `task_complete` — {"success": true, "summary": "Fixed mathlib.add to return a+b instead of a*b; pytest passes (1 passed)."}

### python_fix_pytest_fail [verseshell_aci] → PASS
- Reason: file_contains mathlib.py
- Tool calls: 5, Observation tokens: 302
- Turns: 5, Elapsed: 54024ms
- LLM: 3338 prompt + 398 completion tokens
- Trajectory:
  1. `file.view` — {"path": "mathlib.py"} aci_ok=True
  1. `file.view` — {"path": "tests/test_math.py"} aci_ok=True
  1. `file.replace_exact` — {"expected_hash": "sha256:4fb46b3507c096aece05e92b88ce528ab2ee3c2c42657ba218d09dfdf5c02418", "new": "    return a + b", "old": "    return a * b", "path": "mathlib.py"} aci_ok=True
  1. `exec.run` — {"argv": ["pytest", "-q"]} aci_ok=False
  1. `exec.run` — {"argv": ["python", "-m", "pytest", "-q"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed mathlib.add to return a+b instead of a*b; pytest passes (1 passed) via python -m pytest."}

### python_edit_and_retest [raw_shell] → PASS
- Reason: file_contains greet.py
- Tool calls: 2, Observation tokens: 83
- Turns: 3, Elapsed: 39252ms
- LLM: 1055 prompt + 204 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type greet.py & type TASK.md & type tests\\test_greet.py"}
  1. `run_command` — {"command": "python -c \"open('greet.py','w').write('def greet(name):\\n    return f\\\"Hello, {name}!\\\"\\n')\" && python -m pytest tests -q"}
  1. `task_complete` — {"success": true, "summary": "Updated greet() to return 'Hello, {name}!' and all tests pass (1 passed)."}

### python_edit_and_retest [verseshell_aci] → PASS
- Reason: file_contains greet.py
- Tool calls: 5, Observation tokens: 310
- Turns: 5, Elapsed: 22911ms
- LLM: 3332 prompt + 424 completion tokens
- Trajectory:
  1. `file.view` — {"path": "greet.py"} aci_ok=True
  1. `file.view` — {"path": "tests/test_greet.py"} aci_ok=True
  1. `file.replace_exact` — {"new": "def greet(name):\n    return f\"Hello, {name}!\"", "old": "def greet(name):\n    return f\"Hi {name}\"", "path": "greet.py"} aci_ok=True
  1. `exec.run` — {"argv": ["pytest", "-q"], "profile": "pytest"} aci_ok=False
  1. `exec.run` — {"argv": ["python", "-m", "pytest", "-q"], "profile": "pytest"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Updated greet() in greet.py to return \"Hello, {name}!\" and verified with pytest (1 passed)."}

### python_noisy_install_summary [raw_shell] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 3, Observation tokens: 176
- Turns: 4, Elapsed: 32458ms
- LLM: 1846 prompt + 261 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type requirements.txt & type TASK.md & dir"}
  1. `run_command` — {"command": "pip install -r requirements.txt --quiet --no-input && python -c \"import six; print(six.__version__)\""}
  1. `run_command` — {"command": "python -c \"open('SUMMARY.txt','w').write('Installed 1 package from requirements.txt (six==1.16.0) via pip; import verified successfully.')\" & type SUMMARY.txt"}
  1. `task_complete` — {"success": true, "summary": "Installed requirements (1 package: six==1.16.0), verified import, and wrote one-line dependency summary to SUMMARY.txt."}

### python_noisy_install_summary [verseshell_aci] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 6, Observation tokens: 173
- Turns: 5, Elapsed: 17888ms
- LLM: 2906 prompt + 464 completion tokens
- Trajectory:
  1. `repo.summary` — {} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.view` — {"path": "requirements.txt"} aci_ok=True
  1. `exec.run` — {"argv": ["pip", "install", "-r", "requirements.txt"], "profile": "npm_install"} aci_ok=True
  1. `file.write` — {"content": "Installed 1 package from requirements.txt: six 1.16.0 (pure-Python Python 2/3 compatibility utilities; no transitive dependencies).\n", "path": "SUMMARY.txt"} aci_ok=True
  1. `exec.run` — {"argv": ["python", "-c", "import six; print(six.__version__)"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Installed requirements (1 package: six 1.16.0, verified importable) and wrote one-line dependency summary to SUMMARY.txt."}

### ts_fix_type_error [raw_shell] → FAIL
- Reason: file_contains src/index.ts
- Tool calls: 5, Observation tokens: 290
- Turns: 4, Elapsed: 57752ms
- LLM: 2579 prompt + 452 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type TASK.md & type package.json & type tsconfig.json & type src\\index.ts"}
  1. `run_command` — {"command": "npx tsc --noEmit"}
  1. `run_command` — {"command": "npm install"}
  1. `run_command` — {"command": "python -c \"open('src/index.ts','w').write('export function add(a: number, b: number): number {\\n  const x: number = a + b;\\n  return x;\\n}\\n')\""}
  1. `run_command` — {"command": "npx tsc --noEmit"}
  1. `task_complete` — {"success": true, "summary": "Fixed type error in src/index.ts (changed `const x: string` to `const x: number`) so tsc --noEmit succeeds."}

### ts_fix_type_error [verseshell_aci] → FAIL
- Reason: file_contains src/index.ts
- Tool calls: 10, Observation tokens: 535
- Turns: 8, Elapsed: 163182ms
- LLM: 9169 prompt + 767 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/index.ts"} aci_ok=True
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `file.view` — {"path": "tsconfig.json"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.replace_exact` — {"expected_hash": "sha256:d99b13deba072b7fd4b5907edec8b5cab9e3e744888d8dcb1ed7573d41de55bc", "new": "  const x: number = a + b;", "old": "  const x: string = a + b;", "path": "src/index.ts"} aci_ok=True
  1. `exec.run` — {"argv": ["npx", "tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["npx.cmd", "tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm", "install", "--save-dev", "typescript"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm.cmd", "install", "--save-dev", "typescript"]} aci_ok=True
  1. `exec.run` — {"argv": ["npx.cmd", "tsc", "--noEmit"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed type error in src/index.ts (string→number annotation) and installed typescript; tsc --noEmit passes."}

### ts_package_script_fail [raw_shell] → PASS
- Reason: file_contains package.json
- Tool calls: 2, Observation tokens: 71
- Turns: 3, Elapsed: 19046ms
- LLM: 1006 prompt + 237 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type package.json & type TASK.md"}
  1. `run_command` — {"command": "node -e \"const fs=require('fs');const p=JSON.parse(fs.readFileSync('package.json','utf8'));p.scripts.test='node -e \\\"process.exit(0)\\\"';fs.writeFileSync('package.json',JSON.stringify
  1. `task_complete` — {"success": true, "summary": "Changed package.json test script from `node -e \"process.exit(1)\"` to `node -e \"process.exit(0)\"`; npm test exits 0."}

### ts_package_script_fail [verseshell_aci] → PASS
- Reason: file_contains package.json
- Tool calls: 5, Observation tokens: 271
- Turns: 5, Elapsed: 164138ms
- LLM: 3136 prompt + 378 completion tokens
- Trajectory:
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.replace_exact` — {"new": "    \"test\": \"node -e \\\"process.exit(0)\\\"\"", "old": "    \"test\": \"node -e \\\"process.exit(1)\\\"\"", "path": "package.json"} aci_ok=True
  1. `exec.run` — {"argv": ["npm", "test"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm.cmd", "test"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Changed test script from `node -e \"process.exit(1)\"` to `node -e \"process.exit(0)\"`; verified npm test exits 0."}

### windows_path_normalize_edit [raw_shell] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 2, Observation tokens: 146
- Turns: 3, Elapsed: 24416ms
- LLM: 1278 prompt + 203 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type README.md & type TASK.md & dir"}
  1. `run_command` — {"command": "python -c \"from pathlib import Path; p = Path('out') / 'result.txt'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('OK'); print(p.read_text())\""}
  1. `task_complete` — {"success": true, "summary": "Created out/result.txt containing 'OK' and verified its contents."}

### windows_path_normalize_edit [verseshell_aci] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 2, Observation tokens: 50
- Turns: 3, Elapsed: 45801ms
- LLM: 1039 prompt + 212 completion tokens
- Trajectory:
  1. `exec.run` — {"argv": ["python", "-c", "from pathlib import Path; p = Path('out'); p.mkdir(parents=True, exist_ok=True); (p / 'result.txt').write_text('OK')"]} aci_ok=True
  1. `file.view` — {"path": "out/result.txt"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Created out/ directory and wrote out/result.txt containing 'OK'"}

### windows_batch_capture_diag [raw_shell] → PASS
- Reason: all ok
- Tool calls: 4, Observation tokens: 90
- Turns: 4, Elapsed: 37077ms
- LLM: 1567 prompt + 264 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type broken_build.log"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "echo src/main.rs:12> ERR.txt && type ERR.txt"}
  1. `run_command` — {"command": "python -c \"open('ERR.txt','w').write('src/main.rs:12')\" && type ERR.txt"}
  1. `task_complete` — {"success": true, "summary": "Extracted first error location from broken_build.log (src/main.rs:12) and wrote it to ERR.txt"}

### windows_batch_capture_diag [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 3, Observation tokens: 213
- Turns: 3, Elapsed: 64378ms
- LLM: 1529 prompt + 237 completion tokens
- Trajectory:
  1. `file.view` — {"path": "broken_build.log"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.write` — {"content": "src\\main.rs:12\n", "path": "ERR.txt"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Extracted first error location 'src\\main.rs:12' from broken_build.log and wrote it to ERR.txt."}

---

**Key**:
- Condition A = raw shell (`run_command` only — full build logs, no reduction)
- Condition D = VerseShell ACI (`file.view`, `exec.run`, `file.replace_exact`, etc. via `ae --serve --agent`, with semantic output reduction)
- `aci_ok` = whether the individual AE op returned success
- `meets_acceptance` gate: D success > A success, OR D tool_calls < 70% of A, OR D obs_tokens < 60% of A
