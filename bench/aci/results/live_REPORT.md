# ACI-Bench LIVE Report

- Generated: 2026-07-19T16:09:44.189836+00:00
- Task set: 1.1.0
- Mode: **LIVE** (real LLM multi-turn tool-calling)
- Model: `deepseek-v4-flash`

## Leaderboard

| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |
|---|---|---:|---:|---:|---:|
| deepseek-v4-flash | raw_shell | 10 | 0.6 | 9.3 | 454.6 |
| deepseek-v4-flash | verseshell_aci | 10 | 0.7 | 5.4 | 293.7 |

## Condition A vs D

### deepseek-v4-flash → **PASS** (ACI advantage detected)

| Metric | Raw Shell (A) | VerseShell ACI (D) | Ratio (D/A) |
|---|---|---:|---:|
| Success rate | 0.6 | 0.7 | — |
| Avg tool calls | 9.3 | 5.4 | 0.5806 |
| Avg observation tokens | 454.6 | 293.7 | 0.6461 |
| Gate | — | — | **PASS** |

## Per-Task Trajectories

### rust_fix_compile_error [raw_shell] → PASS
- Reason: all ok
- Tool calls: 9, Observation tokens: 362
- Turns: 10, Elapsed: 170645ms
- LLM: 15177 prompt + 972 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"\nwith open('src/lib.rs', 'w') as f:\n    f.write('pub fn add(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\n\""}
  1. `run_command` — {"command": "cargo check"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"\nwith open('src/lib.rs', 'w', newline='\\r\\n') as f:\n    f.write('pub fn add(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\n\" && type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"open('src/lib.rs', 'w').write('pub fn add(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\""}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "cargo check"}
  1. `task_complete` — {"success": true, "summary": "Fixed compile error by changing the return type of `add` from `String` to `i32` to match the body expression `a + b`."}

### rust_fix_compile_error [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 3, Observation tokens: 113
- Turns: 4, Elapsed: 69289ms
- LLM: 6744 prompt + 430 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.replace_exact` — {"path": "src/lib.rs", "old": "pub fn add(a: i32, b: i32) -> String {", "new": "pub fn add(a: i32, b: i32) -> i32 {", "expected_hash": "sha256:9fe8852b20a9b6770f58bb12e24d55cb8760ad35ebfeaa92e08d808bb aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "check"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed return type of `add` function from `String` to `i32` in src/lib.rs to match the body expression `a + b`."}

### rust_add_unit_test [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 10, Observation tokens: 500
- Turns: 9, Elapsed: 156109ms
- LLM: 14237 prompt + 1000 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /B /S"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "type Cargo.toml"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "python -c \"\ncontent = '''pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn test_add() {\n        assert_eq!(add(2,
  1. `run_command` — {"command": "cargo test"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"content = open('src/lib.rs').read() + '\\n\\n#[cfg(test)]\\nmod tests {\\n    use super::*;\\n\\n    #[test]\\n    fn test_add() {\\n        assert_eq!(add(2, 3), 5);\\n      
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "cargo test"}
  1. `task_complete` — {"success": true, "summary": "Added a unit test module to src/lib.rs with the test_add function covering positive, negative, and zero cases for the add() function. All tests pass with cargo test."}

### rust_add_unit_test [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 4, Observation tokens: 187
- Turns: 4, Elapsed: 71403ms
- LLM: 7419 prompt + 601 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.replace_exact` — {"path": "src/lib.rs", "old": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}", "new": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[te aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "test"]} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Added unit test for add() in src/lib.rs with 4 assertions (positive, negative, zero, both negative) — cargo test passes (1 test, 0 failures)."}

### rust_search_and_edit [raw_shell] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 19, Observation tokens: 653
- Turns: 15, Elapsed: 258199ms
- LLM: 33502 prompt + 1657 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /s /b"}
  1. `run_command` — {"command": "type Cargo.toml"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "python -c \"\nimport re\nwith open('src/lib.rs', 'r') as f:\n    content = f.read()\ncontent = content.replace('// TODO(fix-me)\\n    0', 'a + b')\nwith open('src/lib.rs', 'w') as f:\n   
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "cd C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-rust_search_and_edit-mqu9gqv3 && cargo check 2>&1"}
  1. `run_command` — {"command": "python -c \"\nwith open('src/lib.rs', 'w') as f:\n    f.write('pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\n\""}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "cd C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-rust_search_and_edit-mqu9gqv3 && cargo check 2>&1"}
  1. `run_command` — {"command": "echo pub fn sum(a: i32, b: i32) -> i32 { a + b } > src\\lib.rs"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"\nwith open('src/lib.rs', 'w') as f:\n    data = 'pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n'\n    f.write(data)\n    print('Wrote:', repr(data))\n\""}
  1. `run_command` — {"command": "python --version"}
  1. `run_command` — {"command": "type src\\lib.rs"}
  1. `run_command` — {"command": "del src\\lib.rs && python -c \"\nwith open('src/lib.rs', 'w') as f:\n    f.write('pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\nprint('done')\n\" && type src\\lib.rs"}
  1. `run_command` — {"command": "del src\\lib.rs"}
  1. `run_command` — {"command": "python -c \"open('src/lib.rs','w').write('pub fn sum(a: i32, b: i32) -> i32 {\\n    a + b\\n}\\n')\""}
  1. `run_command` — {"command": "dir src\\lib.rs"}

### rust_search_and_edit [verseshell_aci] → FAIL
- Reason: file_contains src/lib.rs
- Tool calls: 7, Observation tokens: 337
- Turns: 6, Elapsed: 105300ms
- LLM: 11572 prompt + 681 completion tokens
- Trajectory:
  1. `repo.summary` — {} aci_ok=True
  1. `exec.run` — {"argv": ["dir", ".", "/b", "/s"], "cwd": ".", "profile": "none"} aci_ok=False
  1. `file.view` — {"path": "Cargo.toml"} aci_ok=True
  1. `file.view` — {"path": "src/lib.rs"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.replace_exact` — {"path": "src/lib.rs", "old": "pub fn sum(a: i32, b: i32) -> i32 {\n    // TODO(fix-me)\n    0\n}", "new": "pub fn sum(a: i32, b: i32) -> i32 {\n    a + b\n}", "expected_hash": "sha256:b1082c89bc558ea aci_ok=True
  1. `exec.run` — {"argv": ["cargo", "check"], "cwd": ".", "profile": "auto"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Implemented sum(a, b) in src/lib.rs to return a + b instead of 0."}

### python_fix_pytest_fail [raw_shell] → PASS
- Reason: file_contains mathlib.py
- Tool calls: 11, Observation tokens: 881
- Turns: 10, Elapsed: 175794ms
- LLM: 18157 prompt + 977 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir"}
  1. `run_command` — {"command": "type mathlib.py"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "type tests\\test_math.py"}
  1. `run_command` — {"command": "python -c \"\nwith open('mathlib.py', 'w') as f:\n    f.write('def add(a, b):\\n    return a + b\\n')\n\""}
  1. `run_command` — {"command": "pytest"}
  1. `run_command` — {"command": "python -m pytest -v"}
  1. `run_command` — {"command": "type mathlib.py"}
  1. `run_command` — {"command": "python -c \"open('mathlib.py', 'w').write('def add(a, b):\\n    return a + b\\n')\""}
  1. `run_command` — {"command": "type mathlib.py"}
  1. `run_command` — {"command": "python -m pytest -v"}
  1. `task_complete` — {"success": true, "summary": "Fixed mathlib.py: changed add(a,b) return from a * b to a + b. All tests pass."}

### python_fix_pytest_fail [verseshell_aci] → PASS
- Reason: file_contains mathlib.py
- Tool calls: 5, Observation tokens: 349
- Turns: 5, Elapsed: 90422ms
- LLM: 9816 prompt + 579 completion tokens
- Trajectory:
  1. `file.view` — {"path": "mathlib.py"} aci_ok=True
  1. `file.view` — {"path": "tests/test_math.py"} aci_ok=True
  1. `file.replace_exact` — {"path": "mathlib.py", "old": "    return a * b", "new": "    return a + b", "expected_hash": "sha256:4fb46b3507c096aece05e92b88ce528ab2ee3c2c42657ba218d09dfdf5c02418"} aci_ok=True
  1. `exec.run` — {"argv": ["pytest", "-q"]} aci_ok=False
  1. `exec.run` — {"argv": ["python", "-m", "pytest", "-q"], "cwd": "."} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed mathlib.py add(a,b) to return a+b instead of a*b; verified with pytest (1 passed)."}

### python_edit_and_retest [raw_shell] → PASS
- Reason: file_contains greet.py
- Tool calls: 11, Observation tokens: 851
- Turns: 10, Elapsed: 174581ms
- LLM: 16382 prompt + 832 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir /b"}
  1. `run_command` — {"command": "type greet.py"}
  1. `run_command` — {"command": "type tests\\test_greet.py"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "python -c \"\nwith open('greet.py', 'w') as f:\n    f.write('def greet(name):\\n    return f\\\"Hello, {name}!\\\"\\n')\n\""}
  1. `run_command` — {"command": "cd tests && python -m pytest test_greet.py -v"}
  1. `run_command` — {"command": "python -m pytest tests\\test_greet.py -v"}
  1. `run_command` — {"command": "type greet.py"}
  1. `run_command` — {"command": "python -c \"content = 'def greet(name):\\n    return f\\\"Hello, {name}!\\\"\\n'; open('greet.py', 'w').write(content)\""}
  1. `run_command` — {"command": "type greet.py"}
  1. `run_command` — {"command": "python -m pytest tests\\test_greet.py -v"}
  1. `task_complete` — {"success": true, "summary": "Updated greet() to return 'Hello, {name}!' and all tests pass."}

### python_edit_and_retest [verseshell_aci] → PASS
- Reason: file_contains greet.py
- Tool calls: 7, Observation tokens: 589
- Turns: 7, Elapsed: 127952ms
- LLM: 15906 prompt + 768 completion tokens
- Trajectory:
  1. `file.view` — {"path": "greet.py"} aci_ok=True
  1. `file.view` — {"path": "tests/test_greet.py"} aci_ok=True
  1. `file.replace_exact` — {"path": "greet.py", "old": "    return f\"Hi {name}\"", "new": "    return f\"Hello, {name}!\"", "expected_hash": "sha256:3ab4a6cd647afe331b3f14443f8e612f820d5ac9aa50380f608306859defb964"} aci_ok=True
  1. `exec.run` — {"argv": ["pytest", "-q", "tests/"]} aci_ok=False
  1. `exec.run` — {"argv": ["pytest", "-q", "--rootdir=.", "tests/"], "cwd": "."} aci_ok=False
  1. `exec.run` — {"argv": ["python", "-m", "pytest", "-q", "tests/"], "cwd": "."} aci_ok=True
  1. `file.view` — {"path": "greet.py"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Updated greet() to return 'Hello, {name}!' instead of 'Hi {name}'. Tests pass."}

### python_noisy_install_summary [raw_shell] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 6, Observation tokens: 244
- Turns: 6, Elapsed: 106171ms
- LLM: 6966 prompt + 526 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir"}
  1. `run_command` — {"command": "type requirements.txt"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "pip install -r requirements.txt"}
  1. `run_command` — {"command": "python -c \"with open('SUMMARY.txt', 'w') as f: f.write('1 package installed/verified: six==1.16.0\\n')\""}
  1. `run_command` — {"command": "type SUMMARY.txt"}
  1. `task_complete` — {"success": true, "summary": "Installed requirements (1 package: six==1.16.0) and wrote one-line dependency summary to SUMMARY.txt"}

### python_noisy_install_summary [verseshell_aci] → FAIL
- Reason: file_contains SUMMARY.txt
- Tool calls: 5, Observation tokens: 164
- Turns: 4, Elapsed: 74318ms
- LLM: 6979 prompt + 475 completion tokens
- Trajectory:
  1. `repo.summary` — {} aci_ok=True
  1. `file.view` — {"path": "requirements.txt"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `exec.run` — {"argv": ["pip", "install", "-r", "requirements.txt"], "profile": "npm_install"} aci_ok=True
  1. `file.write` — {"path": "SUMMARY.txt", "content": "Installed 1 dependency from requirements.txt (six==1.16.0)."} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Installed 1 dependency (six==1.16.0) from requirements.txt and wrote one-line summary to SUMMARY.txt."}

### ts_fix_type_error [raw_shell] → FAIL
- Reason: file_contains src/index.ts
- Tool calls: 13, Observation tokens: 721
- Turns: 11, Elapsed: 207209ms
- LLM: 25491 prompt + 1801 completion tokens
- Trajectory:
  1. `run_command` — {"command": "cd c:\\Users\\szhao\\cursor\\new_workspace_2 & dir /s"}
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\src\\index.ts\""}
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\tsconfig.json\""}
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\package.json\""}
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\TASK.md\""}
  1. `run_command` — {"command": "cd \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && python -c \"\ncontent = '''export function add(a: number, b: number): number {\n  const x: number = a
  1. `run_command` — {"command": "cd \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && npx tsc --noEmit"}
  1. `run_command` — {"command": "cd \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && npm install"}
  1. `run_command` — {"command": "cd \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && npx tsc --noEmit"}
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\src\\index.ts\""}
  1. `run_command` — {"command": "cd /d \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && echo export function add(a: number, b: number): number { > src\\index.ts && echo   const x: number
  1. `run_command` — {"command": "type \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\\src\\index.ts\""}
  1. `run_command` — {"command": "cd /d \"C:\\Users\\27933\\AppData\\Local\\Temp\\aci-live-ts_fix_type_error-ydqbk8xh\" && npx tsc --noEmit"}
  1. `task_complete` — {"success": true, "summary": "Fixed type error in src/index.ts: changed `const x: string = a + b;` to `const x: number = a + b;` since `a + b` produces a number, not a string."}

### ts_fix_type_error [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 11, Observation tokens: 633
- Turns: 9, Elapsed: 162919ms
- LLM: 23520 prompt + 1226 completion tokens
- Trajectory:
  1. `file.view` — {"path": "src/index.ts"} aci_ok=True
  1. `file.view` — {"path": "tsconfig.json"} aci_ok=True
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `file.view` — {"path": "TASK.md"} aci_ok=True
  1. `file.replace_exact` — {"path": "src/index.ts", "old": "export function add(a: number, b: number): number {\n  const x: string = a + b;\n  return x;\n}", "new": "export function add(a: number, b: number): number {\n  return aci_ok=True
  1. `exec.run` — {"argv": ["npx", "tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["tsc", "--noEmit"]} aci_ok=False
  1. `exec.run` — {"argv": ["dir", ".", "/b"]} aci_ok=False
  1. `exec.run` — {"argv": ["npm", "install"]} aci_ok=False
  1. `exec.run` — {"argv": ["which", "tsc"]} aci_ok=False
  1. `file.view` — {"path": "src/index.ts"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Fixed TypeScript type error in src/index.ts by removing the incorrect string-typed variable and returning a + b directly as a number."}

### ts_package_script_fail [raw_shell] → PASS
- Reason: file_contains package.json
- Tool calls: 9, Observation tokens: 261
- Turns: 8, Elapsed: 138938ms
- LLM: 10783 prompt + 835 completion tokens
- Trajectory:
  1. `run_command` — {"command": "dir"}
  1. `run_command` — {"command": "type package.json"}
  1. `run_command` — {"command": "type TASK.md"}
  1. `run_command` — {"command": "python -c \"\nimport json\nwith open('package.json', 'r') as f:\n    data = json.load(f)\ndata['scripts']['test'] = 'node -e \\\"process.exit(0)\\\"'\nwith open('package.json', 'w') as f:
  1. `run_command` — {"command": "type package.json"}
  1. `run_command` — {"command": "npm test"}
  1. `run_command` — {"command": "python -c \"import json; d=json.load(open('package.json')); d['scripts']['test']='node -e \\\"process.exit(0)\\\"'; open('package.json','w').write(json.dumps(d,indent=2)+'\\n')\""}
  1. `run_command` — {"command": "type package.json"}
  1. `run_command` — {"command": "npm test"}
  1. `task_complete` — {"success": true, "summary": "Fixed package.json test script: changed process.exit(1) to process.exit(0), so npm test exits with code 0."}

### ts_package_script_fail [verseshell_aci] → PASS
- Reason: file_contains package.json
- Tool calls: 7, Observation tokens: 322
- Turns: 7, Elapsed: 123770ms
- LLM: 14181 prompt + 803 completion tokens
- Trajectory:
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `repo.summary` — {} aci_ok=True
  1. `file.replace_exact` — {"path": "package.json", "old": "    \"test\": \"node -e \\\"process.exit(1)\\\"\"", "new": "    \"test\": \"node -e \\\"process.exit(0)\\\"\"", "expected_hash": "sha256:3c340a008ea26464ad97fee11dfd8e aci_ok=True
  1. `exec.run` — {"argv": ["npm", "test"]} aci_ok=False
  1. `exec.run` — {"argv": ["node", "-e", "console.log('ok')"]} aci_ok=True
  1. `exec.run` — {"argv": ["node", "-e", "process.exit(0)"]} aci_ok=True
  1. `file.view` — {"path": "package.json"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Changed test script from process.exit(1) to process.exit(0) so npm test exits with code 0"}

### windows_path_normalize_edit [raw_shell] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 2, Observation tokens: 13
- Turns: 3, Elapsed: 51397ms
- LLM: 2450 prompt + 250 completion tokens
- Trajectory:
  1. `run_command` — {"command": "python -c \"from pathlib import Path; Path('out').mkdir(parents=True, exist_ok=True); Path('out/result.txt').write_text('OK')\""}
  1. `run_command` — {"command": "type out\\result.txt"}
  1. `task_complete` — {"success": true, "summary": "Created out/result.txt with content 'OK'"}

### windows_path_normalize_edit [verseshell_aci] → PASS
- Reason: file_equals out/result.txt
- Tool calls: 2, Observation tokens: 50
- Turns: 3, Elapsed: 51599ms
- LLM: 4553 prompt + 253 completion tokens
- Trajectory:
  1. `exec.run` — {"argv": ["python", "-c", "from pathlib import Path; Path('out').mkdir(parents=True, exist_ok=True); Path('out/result.txt').write_text('OK')"]} aci_ok=True
  1. `file.view` — {"path": "out/result.txt"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Created out/result.txt with content 'OK'"}

### windows_batch_capture_diag [raw_shell] → PASS
- Reason: all ok
- Tool calls: 3, Observation tokens: 60
- Turns: 4, Elapsed: 68083ms
- LLM: 3442 prompt + 322 completion tokens
- Trajectory:
  1. `run_command` — {"command": "type broken_build.log"}
  1. `run_command` — {"command": "echo src\\main.rs:12 > ERR.txt"}
  1. `run_command` — {"command": "type ERR.txt"}
  1. `task_complete` — {"success": true, "summary": "Extracted first error location src\\main.rs:12 from broken_build.log and wrote it to ERR.txt"}

### windows_batch_capture_diag [verseshell_aci] → PASS
- Reason: all ok
- Tool calls: 3, Observation tokens: 193
- Turns: 4, Elapsed: 71015ms
- LLM: 7115 prompt + 557 completion tokens
- Trajectory:
  1. `file.view` — {"path": "broken_build.log"} aci_ok=True
  1. `file.write` — {"path": "ERR.txt", "content": "src\\main.rs:12"} aci_ok=True
  1. `file.view` — {"path": "ERR.txt"} aci_ok=True
  1. `task_complete` — {"success": true, "summary": "Extracted first error location `src\\main.rs:12` from broken_build.log and wrote it to ERR.txt."}

---

**Key**:
- Condition A = raw shell (`run_command` only — full build logs, no reduction)
- Condition D = VerseShell ACI (`file.view`, `exec.run`, `file.replace_exact`, etc. via `ae --serve --agent`, with semantic output reduction)
- `aci_ok` = whether the individual AE op returned success
- `meets_acceptance` gate: D success > A success, OR D tool_calls < 70% of A, OR D obs_tokens < 60% of A
