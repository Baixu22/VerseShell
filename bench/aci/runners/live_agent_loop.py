#!/usr/bin/env python3
"""
Live multi-turn agent loop for VerseShell ACI-Bench A vs D comparison.

Drives real LLM (DeepSeek via OpenAI-compatible API) with function-calling tools.
Condition A: raw shell (single run_command tool)
Condition D: ae --serve ACI typed ops (file.view, exec.run, file.replace_exact, etc.)

AE operation names use DOT-separated form: file.view, exec.run, file.replace_exact, etc.
The tool-definition names for the LLM use this same naming so the agent loop passes
them directly to AE without name translation.

Outputs: bench/aci/results/latest_live.json (rows + aggregate + comparison)
         bench/aci/results/live_REPORT.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

# ── Paths ──
ROOT = Path(__file__).resolve().parents[3]
BENCH = ROOT / "bench" / "aci"
TASKS_DIR = BENCH / "tasks"
FIXTURES = BENCH / "fixtures"
RESULTS = BENCH / "results"
AE = ROOT / "target" / "debug" / "ae.exe"

# ── Default API config ──
DEFAULT_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"

MAX_TURNS = 15
MAX_OUTPUT_CHARS = 64000
TOOL_TIMEOUT_SEC = 120
API_TIMEOUT_SEC = 180
AE_OP_TIMEOUT_MS = 120000  # cargo check/build can be slow

# Condition D exercises the ACI surface inside the task workspace, so the AE
# server needs the capabilities those ops require. Without this flag the server
# starts with no grants and denies every op with E_CAPABILITY_DENY, which makes
# the D condition measure nothing at all (that is exactly what the first live
# pilot showed). Kept explicit rather than `all` so the benchmark still runs
# under a policy that looks like a real agent's.
ACI_CAPABILITIES = (
    "sys.read,file.read,file.write,file.delete,shell.exec,"
    "git.read,git.write,proc.list,proc.spawn,proc.kill,crypto.hash"
)

# The measured surface, recorded into the artifact so claim_gate (C12) can tell
# whether a stored live run still describes the current code.
EVIDENCE_GLOBS = [
    "src/**/*.rs",
    "Cargo.toml",
    "bench/aci/tasks/*.json",
    "bench/aci/fixtures/**/*",
    "bench/aci/runners/live_agent_loop.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    """Content hash of the measured surface; claim_gate (C12) recomputes it."""
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def current_git_rev() -> str | None:
    """HEAD at generation time; kept for provenance alongside the fingerprint."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None

# ── ACI tool schemas ──
# LLM tool names use underscores (DeepSeek API rejects dots in function names).
# We map LLM name → AE op name (underscore → dot) at execution time.

# Mapping: LLM tool name → AE operation name
# Both old snake_case names and new LLM-friendly names map to the same ops.
ACI_OP_MAP = {
    # LLM-friendly primary names
    "read_file": "file.view",
    "write_file": "file.write",
    "read_files": "file.read_many",
    "run_command": "exec.run",
    "replace_in_file": "file.replace_exact",
    "search_content": "repo.search",
    "list_files": "repo.summary",
    "list_operations": "ops.list",
    # Legacy snake_case aliases (kept for backward compatibility)
    "file_view": "file.view",
    "file_write": "file.write",
    "exec_run": "exec.run",
    "file_replace_exact": "file.replace_exact",
    "repo_search": "repo.search",
    "repo_summary": "repo.summary",
    "ops_list": "ops.list",
}

ACI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file with line numbers and a content_hash. "
                "Path is relative to workspace root. Returns lines array, total_lines, and content_hash "
                "which you use later with replace_in_file for safe editing. "
                "When NOT to use: to run shell commands (use run_command), to search code (use search_content)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "cursor": {"type": "integer", "description": "Start line (1-based, default 1)"},
                    "window": {"type": "integer", "description": "Max lines (default 80)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_files",
            "description": (
                "Read SEVERAL files in ONE call: every entry returns lines, total_lines and "
                "content_hash. Prefer this over calling read_file once per file when the task "
                "touches a known set of files (source + test + task file). A missing file is "
                "reported in its own entry and does not fail the batch. "
                "When NOT to use: when you do not yet know which file matters (use search_content)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths relative to workspace root (max 8)",
                    },
                    "window": {
                        "type": "integer",
                        "description": "Max lines per file (default 80)",
                    },
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "CREATE or OVERWRITE a file with exact content. "
                "Use this to create new files (e.g. SUMMARY.txt, ERR.txt). "
                "Returns content_hash you can use with replace_in_file later. "
                "Path is relative to workspace root. "
                "When NOT to use: to edit existing files (use replace_in_file), to append (use run_command)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "content": {"type": "string", "description": "Exact file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a command with SEMANTIC OUTPUT REDUCTION. "
                "Output is automatically reduced: cargo errors become structured diagnostics, "
                "pytest failures show file:line, npm install shows package counts. "
                "NO raw build spam. Use for ALL build/test/install commands. "
                "On failure, you get recoverable error + structured diagnostics + suggested_next. "
                "When NOT to use: to read files (use read_file), to edit files (use replace_in_file or write_file)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Command + args, e.g. ["cargo","check"], ["dir","."], ["pytest","-q"]',
                    },
                    "cwd": {"type": "string", "description": "Working directory (relative to workspace, default '.')"},
                    "profile": {"type": "string", "description": "Reducer: auto/cargo/pytest/git/npm_install/none. Default auto."},
                },
                "required": ["argv"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": (
                "Replace EXACT old text with new text in a file. Old string must match exactly once. "
                "Use after read_file to see current content. "
                "Optional: expected_hash from read_file for optimistic concurrency. "
                "When NOT to use: to create new files (use write_file), to replace multiple occurrences (use file.apply_patch)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "old": {"type": "string", "description": "EXACT text to replace (must be unique in file)"},
                    "new": {"type": "string", "description": "Replacement text"},
                    "expected_hash": {"type": "string", "description": "Optional: sha256:... from read_file for safety"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_content",
            "description": (
                "Search workspace files for text or regex. Returns matching files and lines. "
                "When NOT to use: to read file contents (use read_file), to get repo overview (use list_files)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex to search for"},
                    "path": {"type": "string", "description": "Subdirectory (default: workspace root)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Quick repo overview: branch, dirty files, top-level directory listing.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_operations",
            "description": "List all available typed operations with descriptions, input schemas, and examples. Use if unsure what tools are available.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Signal task completion. Call EXACTLY ONCE when done (or giving up).",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "True if task completed successfully"},
                    "summary": {"type": "string", "description": "One-line summary of what was done"},
                },
                "required": ["success", "summary"],
            },
        },
    },
]

RAW_SHELL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command and get its FULL raw output. "
                "Use for ALL actions: listing files (dir), reading files (type), "
                "running builds (cargo check), editing files (use python -c to write files), "
                "running tests (pytest), installing packages (pip install), git commands, etc. "
                "Output may be very long for build tools — read carefully. "
                "Window path separator is backslash (\\)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run (cmd /C syntax on Windows)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Signal task completion. Call EXACTLY ONCE when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "True if task completed successfully"},
                    "summary": {"type": "string", "description": "One-line summary of what was done"},
                },
                "required": ["success", "summary"],
            },
        },
    },
]

# ── Task-specific system prompts ──

TASK_SPECIFIC_PROMPTS = {
    "rust_fix_compile_error": (
        "You are in a Rust workspace. src/lib.rs has a compile error: "
        "the function returns String but the body returns i32 (a + b). "
        "Fix the return type to i32 and verify with cargo check."
    ),
    "rust_add_unit_test": (
        "You are in a Rust workspace. Add a unit test for add() in src/lib.rs "
        "and make cargo test pass."
    ),
    "rust_search_and_edit": (
        "You are in a Rust workspace. Find TODO(fix-me) markers and implement the unfinished function body."
    ),
    "python_fix_pytest_fail": (
        "You are in a Python workspace. Fix the failing pytest: "
        "mathlib.py has add(a,b) returning a*b instead of a+b. "
        "Fix the return and run pytest to verify."
    ),
    "python_edit_and_retest": (
        "You are in a Python workspace. Update greet() to return 'Hello, {name}!' "
        "instead of whatever it currently does, then re-run tests."
    ),
    "python_noisy_install_summary": (
        "You are in a Python workspace. Install requirements from requirements.txt "
        "and write a one-line dependency summary to SUMMARY.txt (mention package count). "
        "Do NOT paste full install logs — just the summary file."
    ),
    "ts_fix_type_error": (
        "You are in a TypeScript workspace. Fix the type error so tsc --noEmit succeeds."
    ),
    "ts_package_script_fail": (
        "You are in a Node.js workspace. Fix package.json scripts so npm test exits 0."
    ),
    "windows_path_normalize_edit": (
        "You are on Windows. Create out/result.txt with content 'OK' (just those two letters). "
        "Use shell commands to make the directory and write the file. "
        "Hint: use python -c \"from pathlib import Path; ...\" to create dirs and write files."
    ),
    "windows_batch_capture_diag": (
        "You are on Windows. broken_build.log contains build errors. "
        "Extract the FIRST error location as 'path:line' and write it to ERR.txt."
    ),
}

SYSTEM_PROMPT = """You are a coding agent. Complete the task in the workspace directory.

{task_hint}

CRITICAL RULES:
0. TRUST tool output: "ok": true means the operation SUCCEEDED CORRECTLY.
   One successful build/test run is sufficient — do NOT re-run with variant
   arguments to confirm. read_file output IS the authoritative file state.
1. Explore workspace state FIRST before editing
2. Make MINIMAL changes — only what the task requires
3. VERIFY your changes ONCE: one successful test/build run is enough
4. Call task_complete(success=bool, summary="...") when done
5. If you get errors, debug — don't give up immediately. Check the error's
   "fix" field for suggested corrective actions.
6. Max {max_turns} tool calls total — be efficient
7. run_command is for BUILD/TEST/INSTALL only. Use read_file to read files."""


# ── Success checking ──

def check_success(pred: dict, workspace: Path) -> tuple[bool, str]:
    t = pred.get("type")
    if t == "all":
        for child in pred.get("of", []):
            ok, reason = check_success(child, workspace)
            if not ok:
                return False, reason
        return True, "all ok"
    if t == "file_equals":
        p = workspace / pred["path"]
        if not p.exists():
            return False, f"missing {pred['path']}"
        body = p.read_text(encoding="utf-8-sig", errors="replace").strip()
        exp = str(pred.get("equals", "")).strip()
        return (body == exp, f"file_equals {pred['path']}")
    if t == "file_contains":
        p = workspace / pred["path"]
        if not p.exists():
            return False, f"missing {pred['path']}"
        body = p.read_text(encoding="utf-8-sig", errors="replace")
        needle = pred.get("contains", "")
        return (needle in body, f"file_contains {pred['path']}")
    if t == "file_not_contains":
        p = workspace / pred["path"]
        if not p.exists():
            return True, f"missing file ok for not_contains {pred['path']}"
        body = p.read_text(encoding="utf-8-sig", errors="replace")
        needle = pred.get("contains", "")
        return (needle not in body, f"file_not_contains {pred['path']}")
    if t == "command_exit_0":
        argv = pred.get("argv") or []
        try:
            r = subprocess.run(
                argv, cwd=str(workspace), capture_output=True, text=True,
                timeout=int(pred.get("timeout_sec", 120)),
            )
            return (r.returncode == 0, f"command_exit_0 {argv} -> {r.returncode}")
        except FileNotFoundError:
            return False, f"command not found: {argv}"
        except subprocess.TimeoutExpired:
            return False, f"timeout: {argv}"
    return False, f"unknown predicate {t}"


# ── Workspace prep ──

def prepare_workspace(fixture_name: str) -> Path:
    src = FIXTURES / fixture_name
    td = Path(tempfile.mkdtemp(prefix=f"aci-live-{fixture_name}-"))
    if src.exists():
        for item in src.iterdir():
            if item.name == "GOLDEN":
                continue
            dest = td / item.name
            if item.is_dir():
                shutil.copytree(item, dest,
                                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            else:
                shutil.copy2(item, dest)
    return td


# ── Chat API ──

def chat_completion(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int = 4096,
    temperature: float = 0.1,
    seed: int | None = None,
) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if seed is not None:
        payload["seed"] = seed
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=API_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:1000]
            if e.code == 429 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
    return {}  # unreachable


# ── Tool execution ──

def execute_aci_op(op_name: str, args: dict, workspace: str,
                   caps: str = ACI_CAPABILITIES) -> dict:
    """Run a single ACI op via ae --serve --agent."""
    op = {
        "id": uuid.uuid4().hex[:12],
        "agent": "live_bench",
        "op": op_name,
        "args": args,
        "timeout_ms": AE_OP_TIMEOUT_MS,
        "budget": {"max_tokens": 4000},
    }

    env = dict(os.environ)
    env["AETHER_APPROVE_ALL"] = "1"
    env["AETHER_MODE"] = "agent"
    env["AETHER_WORKSPACE"] = str(workspace)
    for k in list(env.keys()):
        if env[k] is None:
            del env[k]

    try:
        proc = subprocess.Popen(
            [str(AE), "--serve", "--agent", "--cap", caps],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        stdin_data = json.dumps(op, ensure_ascii=False).encode("utf-8") + b"\n"
        stdout, stderr = proc.communicate(input=stdin_data, timeout=TOOL_TIMEOUT_SEC)

        if proc.returncode != 0:
            return {
                "ok": False,
                "error": {
                    "code": "AE_CRASH",
                    "message": f"ae exited {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:300]}",
                },
            }

        lines = [l.strip() for l in stdout.decode("utf-8", errors="replace").split("\n") if l.strip()]
        if not lines:
            return {"ok": False, "error": {"code": "AE_EMPTY", "message": "no output from ae"}}
        return json.loads(lines[0])
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"ok": False, "error": {"code": "E_TIMEOUT", "message": f"ae op timed out after {TOOL_TIMEOUT_SEC}s"}}


def compact_lines(lines: list) -> list:
    """[{line, text}, ...] -> [text, ...]; the start line is carried separately."""
    out = []
    for entry in lines:
        if isinstance(entry, dict):
            out.append(entry.get("text", ""))
        else:
            out.append(str(entry))
    return out


def format_aci_result(response: dict) -> str:
    """Extract model-relevant fields from the AE observation envelope.

    On SUCCESS: minimal output — ok + content essentials. The model
    only needs to confirm the op worked; verbose metadata wastes tokens.
    On FAILURE: top 5 diagnostics + summary + error code — trim noise.
    """
    ok = response.get("ok")
    clean: dict[str, Any] = {"ok": ok}
    data = response.get("data", {})

    if not ok:
        # Failure — keep only actionable diagnostics (top 5)
        if "diagnostics" in response and response["diagnostics"]:
            clean["diagnostics"] = response["diagnostics"][:5]
        if "error" in response and response["error"]:
            err = dict(response["error"])
            # `hint` usually repeats the first diagnostic message verbatim.
            diag_messages = {d.get("message") for d in (response.get("diagnostics") or [])}
            if err.get("hint") in diag_messages:
                err.pop("hint", None)
            clean["error"] = err
        if "summary" in data:
            # The reduced summary usually restates the diagnostic message and
            # the counts that `stats` already carries. Keep it only when it adds
            # something the structured fields do not already say.
            messages = [d.get("message") for d in (response.get("diagnostics") or [])]
            subsumed = bool(messages) and all(m and m in data["summary"] for m in messages)
            if not (subsumed and "stats" in data):
                clean["summary"] = data["summary"]
        if "exit_code" in data:
            clean["exit_code"] = data["exit_code"]
        # Keep short text snapshots from each stream if present. A stream summary
        # that is byte-identical to `summary` (the common case for pytest) is
        # pure duplication and is dropped.
        if "stdout" in data:
            s = data["stdout"]
            if s.get("text"):
                clean["stdout_text"] = s["text"][:200]
            elif s.get("summary") and s["summary"] != data.get("summary"):
                clean["stdout_summary"] = s["summary"]
        if "stderr" in data:
            s = data["stderr"]
            if s.get("text"):
                clean["stderr_text"] = s["text"][:200]
            elif s.get("summary") and s["summary"] != data.get("summary"):
                clean["stderr_summary"] = s["summary"]
        if "content_hash" in data:
            clean["content_hash"] = data["content_hash"]
        if "total_lines" in data:
            clean["total_lines"] = data["total_lines"]
        if "stats" in data:
            clean["stats"] = data["stats"]
        return json.dumps(clean, ensure_ascii=False)

    # SUCCESS: silence — return only what the model needs to proceed
    if "summary" in data:
        clean["summary"] = data["summary"]
    if "content_hash" in data:
        clean["content_hash"] = data["content_hash"]
    if "total_lines" in data:
        clean["total_lines"] = data["total_lines"]

    # Small files: include lines so model can read without re-viewing.
    # `data.lines` is [{line, text}, ...]; the per-line object wrapper is pure
    # structural overhead (a 2-line file spent 80 chars on 39 chars of text), so
    # the projection flattens it and carries the starting line number once.
    if "lines" in data:
        lines = data["lines"]
        if isinstance(lines, list) and len(lines) <= 10:
            clean["lines"] = compact_lines(lines)
            if "start_line" in data:
                clean["start_line"] = data["start_line"]
        elif "content_hash" not in data:
            clean["total_lines"] = len(lines) if isinstance(lines, list) else 0

    # file.read_many: per-file projection, same flattening as file.view, plus
    # per-file errors so a missing path does not hide the readable ones.
    if "files" in data and isinstance(data["files"], list):
        compact: list[dict] = []
        for entry in data["files"]:
            if not isinstance(entry, dict):
                continue
            item = {
                key: entry[key]
                for key in ("path", "content_hash", "total_lines", "start_line", "error")
                if key in entry
            }
            if isinstance(entry.get("lines"), list) and len(entry["lines"]) <= 10:
                item["lines"] = compact_lines(entry["lines"])
            compact.append(item)
        clean["files"] = compact
        if "errors" in data:
            clean["errors"] = data["errors"]

    # Non-reduced stdout/stderr: include text so model can see dir/list output
    if "stdout" in data:
        s = data["stdout"]
        if s.get("text") and s.get("status") != "reduced":
            clean["stdout_text"] = s["text"][:300]
    if "stderr" in data:
        s = data["stderr"]
        if s.get("text") and s.get("status") != "reduced":
            clean["stderr_text"] = s["text"][:200]

    # ops.list: keep only op names (descriptions are noise on success)
    if "operations" in data:
        clean["available_ops"] = [o["name"] for o in data["operations"]]

    # repo.meta: keep branch + entries on success (useful orientation)
    if "branch" in data:
        repo_fields = {k: data[k] for k in ["branch", "dirty_files", "entries"] if k in data}
        if repo_fields:
            clean["repo"] = repo_fields

    return json.dumps(clean, ensure_ascii=False)


def execute_shell_cmd(command: str, workspace: str) -> str:
    """Run a raw shell command and return stdout+stderr (truncated)."""
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SEC,
        )
        out = r.stdout
        if r.stderr:
            out += "\n[STDERR]\n" + r.stderr
        out += f"\n[EXIT: {r.returncode}]"
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + f"\n... [TRUNCATED at {MAX_OUTPUT_CHARS} chars]"
        return out
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {TOOL_TIMEOUT_SEC}s]"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ── Agent loop ──

def run_agent_loop(
    task: dict,
    condition: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_turns: int = MAX_TURNS,
    caps: str = ACI_CAPABILITIES,
    temperature: float = 0.0,
    seed: int | None = None,
    run_index: int = 0,
    exclude_tools: tuple[str, ...] = (),
) -> dict:
    workspace = prepare_workspace(task["workspace_fixture"])
    tools = ACI_TOOLS if condition == "verseshell_aci" else RAW_SHELL_TOOLS
    if exclude_tools:
        # Used to A/B a single tool (e.g. read_files) on the same model.
        tools = [t for t in tools if t["function"]["name"] not in exclude_tools]
    tool_names = {t["function"]["name"] for t in tools}

    task_hint = TASK_SPECIFIC_PROMPTS.get(task["id"], task["prompt"])
    system = SYSTEM_PROMPT.format(task_hint=task_hint, max_turns=max_turns)

    # Add task file listing for context
    ws_files = _list_workspace(workspace)
    system += f"\n\nWORKSPACE FILES:\n{ws_files}"

    messages: list[dict] = [{"role": "system", "content": system}]

    trajectory: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    turn = 0
    task_completed = False
    agent_declared_success = False
    last_error = None
    api_error = False

    start_time = time.time()

    try:
        while turn < max_turns:
            turn += 1
            try:
                resp = chat_completion(messages, tools, model=model, api_key=api_key,
                                   base_url=base_url, temperature=temperature, seed=seed)
            except Exception as e:
                last_error = f"API error turn {turn}: {e}"
                # Marked so an upstream outage can never be averaged into the
                # benchmark as a "0 tools / 0 tokens" data point.
                api_error = True
                break

            usage = resp.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            choice = resp["choices"][0]
            msg = choice["message"]
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                messages.append({"role": "assistant", "content": msg.get("content") or ""})
                break

            assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_id = tc["id"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                obs_start = time.time()

                if fn_name not in tool_names:
                    result_text = json.dumps({"ok": False, "error": f"Unknown tool: {fn_name}"})
                    obs_tok = estimate_tokens(result_text)
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": result_text})
                    trajectory.append({
                        "op": fn_name, "args": fn_args,
                        "observation_tokens": obs_tok, "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                    })

                elif fn_name == "task_complete":
                    task_completed = True
                    agent_declared_success = fn_args.get("success", False)
                    result_text = json.dumps({"ok": True, "acknowledged": True})
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": result_text})
                    trajectory.append({
                        "op": "task_complete", "args": fn_args,
                        "observation_tokens": estimate_tokens(result_text), "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                    })
                    break  # exit inner tc loop

                elif condition == "verseshell_aci":
                    # Map LLM tool name (underscore) → AE operation name (dot)
                    ae_op = ACI_OP_MAP.get(fn_name, fn_name)
                    aci_response = execute_aci_op(ae_op, fn_args, str(workspace), caps)
                    result_text = format_aci_result(aci_response)
                    obs_tok = estimate_tokens(result_text)
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": result_text})
                    trajectory.append({
                        "op": ae_op, "args": fn_args,
                        "observation_tokens": obs_tok, "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                        "aci_ok": aci_response.get("ok"),
                    })

                else:  # raw_shell
                    cmd = fn_args.get("command", "")
                    raw_output = execute_shell_cmd(cmd, str(workspace))
                    obs_tok = estimate_tokens(raw_output)
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": raw_output})
                    trajectory.append({
                        "op": "run_command", "args": {"command": cmd},
                        "observation_tokens": obs_tok, "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                    })

            if task_completed:
                break

    except Exception as e:
        last_error = f"Loop error: {e}\n{traceback.format_exc()[:500]}"
    finally:
        elapsed_ms = int((time.time() - start_time) * 1000)

    # Check actual workspace state
    try:
        actual_ok, actual_reason = check_success(task["success"], workspace)
    except Exception as e:
        actual_ok, actual_reason = False, f"check_error: {e}"

    tool_call_count = len([t for t in trajectory if t.get("op") != "task_complete"])
    observation_tokens = sum(int(t.get("observation_tokens", 0)) for t in trajectory)

    notes = ["live"]
    if last_error:
        notes.append(f"error: {last_error[:200]}")
    notes.append(f"llm_prompt_tokens={total_prompt_tokens}")
    notes.append(f"llm_completion_tokens={total_completion_tokens}")

    try:
        shutil.rmtree(workspace, ignore_errors=True)
    except Exception:
        pass

    return {
        "task_id": task["id"],
        "condition": condition,
        "model": model,
        "run_index": run_index,
        "success": actual_ok,
        "success_reason": actual_reason,
        "tool_calls": tool_call_count,
        "observation_tokens": observation_tokens,
        "elapsed_ms": elapsed_ms,
        "notes": notes,
        "trajectory": trajectory,
        "optional_verify": None,
        "weight": float(task.get("weight", 1.0)),
        "agent_declared_success": agent_declared_success,
        "llm_prompt_tokens": total_prompt_tokens,
        "llm_completion_tokens": total_completion_tokens,
        "turns": turn,
        "last_error": last_error,
        "api_error": api_error,
    }


def _list_workspace(ws: Path, max_depth: int = 3) -> str:
    lines = []
    for path in sorted(ws.rglob("*")):
        if path.name == "target" or ".git" in path.parts:
            continue
        rel = path.relative_to(ws)
        if len(rel.parts) > max_depth:
            continue
        if path.is_file():
            try:
                size = path.stat().st_size
                lines.append(f"  {rel} ({size}B)")
            except Exception:
                lines.append(f"  {rel}")
        else:
            lines.append(f"  {rel}/")
    return "\n".join(lines[:50])


# ── Aggregation ──

def aggregate(rows: list[dict]) -> dict:
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        key = f"{r.get('model', 'live')}::{r['condition']}"
        by_key.setdefault(key, []).append(r)
    table = []
    for key, items in sorted(by_key.items()):
        n = len(items)
        wsum = sum(float(x.get("weight", 1.0)) for x in items) or 1.0
        succ_w = sum(float(x.get("weight", 1.0)) for x in items if x.get("success"))
        tools = sum(x.get("tool_calls", 0) for x in items) / max(n, 1)
        toks = sum(x.get("observation_tokens", 0) for x in items) / max(n, 1)
        elapsed = sum(x.get("elapsed_ms", 0) for x in items) / max(n, 1)
        model, condition = key.split("::", 1)
        table.append({
            "model": model, "condition": condition, "tasks": n,
            "success_rate": round(succ_w / wsum, 4),
            "avg_tool_calls": round(tools, 2),
            "avg_observation_tokens": round(toks, 2),
            "avg_elapsed_ms": round(elapsed, 1),
        })
    return {"aggregates": table, "n_rows": len(rows)}


def compare_a_vs_d(rows: list[dict]) -> dict:
    from collections import defaultdict

    by_model: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_model[r.get("model", "live")][r["condition"]].append(r)

    comparisons = []
    for model, conds in sorted(by_model.items()):
        a = conds.get("raw_shell") or []
        d = conds.get("verseshell_aci") or []
        if not a or not d:
            continue

        def rate(items: list[dict]) -> float:
            w = sum(float(x.get("weight", 1.0)) for x in items) or 1.0
            return sum(float(x.get("weight", 1.0)) for x in items if x.get("success")) / w

        def avg(items: list[dict], key: str) -> float:
            return sum(x.get(key, 0) for x in items) / max(len(items), 1)

        ra, rd = rate(a), rate(d)
        ta, td = avg(a, "tool_calls"), avg(d, "tool_calls")
        oa, od = avg(a, "observation_tokens"), avg(d, "observation_tokens")
        comparisons.append({
            "model": model,
            "success_rate_A": round(ra, 4), "success_rate_D": round(rd, 4),
            "success_advantage_D": round(rd - ra, 4),
            "avg_tool_calls_A": round(ta, 2), "avg_tool_calls_D": round(td, 2),
            "tool_call_ratio_D_over_A": round(td / ta, 4) if ta else None,
            "avg_observation_tokens_A": round(oa, 2), "avg_observation_tokens_D": round(od, 2),
            "token_ratio_D_over_A": round(od / oa, 4) if oa else None,
            "meets_acceptance": bool(
                (rd > ra) or (td < ta * 0.7) or (od < oa * 0.6)
            ),
        })
    return {"comparisons": comparisons}


def write_report(payload: dict, path: Path) -> None:
    agg = payload.get("aggregate", {})
    cmp_ = payload.get("comparison", {})
    rows = payload.get("rows", [])

    def model_list() -> str:
        ms = sorted(set(r.get("model", "?") for r in rows))
        return ", ".join(f"`{m}`" for m in ms)

    lines = [
        "# ACI-Bench LIVE Report",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- Task set: {payload.get('task_set_version')}",
        f"- Mode: **LIVE** (real LLM multi-turn tool-calling)",
        f"- Model: {model_list()}",
        "",
        "## Leaderboard",
        "",
        "| model | condition | tasks | success_rate | avg_tool_calls | avg_observation_tokens |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in agg.get("aggregates", []):
        lines.append(
            f"| {row['model']} | {row['condition']} | {row['tasks']} | {row['success_rate']} | "
            f"{row['avg_tool_calls']} | {row['avg_observation_tokens']} |"
        )
    lines += ["", "## Condition A vs D", ""]
    for c in cmp_.get("comparisons", []):
        verdict = "**PASS** (ACI advantage detected)" if c["meets_acceptance"] else "**PARTIAL** (no clear advantage)"
        lines += [
            f"### {c['model']} → {verdict}",
            "",
            f"| Metric | Raw Shell (A) | VerseShell ACI (D) | Ratio (D/A) |",
            "|---|---|---:|---:|",
            f"| Success rate | {c['success_rate_A']} | {c['success_rate_D']} | — |",
            f"| Avg tool calls | {c['avg_tool_calls_A']} | {c['avg_tool_calls_D']} | {c['tool_call_ratio_D_over_A']} |",
            f"| Avg observation tokens | {c['avg_observation_tokens_A']} | {c['avg_observation_tokens_D']} | {c['token_ratio_D_over_A']} |",
            f"| Gate | — | — | **{'PASS' if c['meets_acceptance'] else 'PARTIAL'}** |",
            "",
        ]
    lines += ["## Per-Task Trajectories", ""]
    for r in rows:
        status = "PASS" if r["success"] else "FAIL"
        lines.append(f"### {r['task_id']} [{r['condition']}] → {status}")
        lines.append(f"- Reason: {r['success_reason']}")
        lines.append(f"- Tool calls: {r['tool_calls']}, Observation tokens: {r['observation_tokens']}")
        lines.append(f"- Turns: {r['turns']}, Elapsed: {r['elapsed_ms']}ms")
        if r.get("llm_prompt_tokens"):
            lines.append(f"- LLM: {r['llm_prompt_tokens']} prompt + {r['llm_completion_tokens']} completion tokens")
        lines.append("- Trajectory:")
        for t in r.get("trajectory", []):
            op = t["op"]
            args = t.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)[:200]
            aci_ok = t.get("aci_ok")
            aci_mark = f" aci_ok={aci_ok}" if aci_ok is not None else ""
            lines.append(f"  1. `{op}` — {args_str}{aci_mark}")
        lines.append("")
    lines += [
        "---",
        "",
        "**Key**:",
        "- Condition A = raw shell (`run_command` only — full build logs, no reduction)",
        "- Condition D = VerseShell ACI (`file.view`, `exec.run`, `file.replace_exact`, etc. via `ae --serve --agent`, with semantic output reduction)",
        "- `aci_ok` = whether the individual AE op returned success",
        "- `meets_acceptance` gate: D success > A success, OR D tool_calls < 70% of A, OR D obs_tokens < 60% of A",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


# ── Main ──

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="VerseShell ACI-Bench Live Agent Runner")
    ap.add_argument("--tasks", default="", help="Comma-separated task ids")
    ap.add_argument("--conditions", default="raw_shell,verseshell_aci")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--api-key", default=DEFAULT_API_KEY)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--out", default=str(RESULTS / "latest_live.json"))
    ap.add_argument("--max-turns", type=int, default=MAX_TURNS)
    ap.add_argument("--caps", default=ACI_CAPABILITIES,
                    help="capabilities granted to the AE server in condition D")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="sampling temperature (default 0 for reproducibility)")
    ap.add_argument("--seed", type=int, default=None,
                    help="sampling seed sent to the endpoint (may be ignored by it)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run the whole task x condition matrix N times")
    ap.add_argument("--exclude-tools", default="",
                    help="comma-separated tool names to hide from condition D (A/B a single tool)")
    ap.add_argument("--smoke", action="store_true", help="3-task smoke validation")
    ap.add_argument("--full", action="store_true", help="All 10 tasks")
    args = ap.parse_args(argv)
    exclude_tools = tuple(t.strip() for t in args.exclude_tools.split(",") if t.strip())

    manifest = json.loads((TASKS_DIR / "manifest.json").read_text(encoding="utf-8-sig"))
    all_tasks = manifest.get("tasks", [])

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    elif args.full:
        task_ids = all_tasks
    else:
        task_ids = ["rust_fix_compile_error", "python_fix_pytest_fail", "windows_path_normalize_edit"]

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]

    api_key = args.api_key or DEFAULT_API_KEY
    if not api_key:
        print("ERROR: No API key.", file=sys.stderr)
        return 1
    if not AE.exists():
        print(f"ERROR: ae not found at {AE}", file=sys.stderr)
        return 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"Model: {args.model} | Tasks: {len(task_ids)} | Conditions: {conditions} | Max turns: {args.max_turns}")
    print("=" * 60)

    rows: list[dict] = []
    total = len(task_ids) * len(conditions) * args.repeat
    done = 0

    for tid in task_ids:
        try:
            task = json.loads((TASKS_DIR / f"{tid}.json").read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"SKIP {tid}: {e}")
            continue

        for cond in conditions:
            for run_index in range(args.repeat):
                done += 1
                print(f"\n[{done}/{total}] {tid} [{cond}] run={run_index} ...", flush=True)
                t0 = time.time()
                try:
                    row = run_agent_loop(task, cond, model=args.model, api_key=api_key,
                                         base_url=args.base_url, max_turns=args.max_turns,
                                         caps=args.caps, temperature=args.temperature,
                                         seed=args.seed, run_index=run_index,
                                         exclude_tools=exclude_tools)
                    rows.append(row)
                    wall = int((time.time() - t0) * 1000)
                    status = "PASS" if row["success"] else "FAIL"
                    print(f"  -> {status}: {row['tool_calls']} tools, {row['observation_tokens']} obs_tok, "
                          f"wall={wall}ms, turns={row['turns']}")
                    if row.get("last_error"):
                        print(f"  !! {row['last_error'][:200]}")
                except Exception as e:
                    print(f"  -> RUNNER ERROR: {e}")
                    traceback.print_exc()
                    rows.append({
                        "task_id": tid, "condition": cond, "model": args.model,
                        "run_index": run_index,
                        "success": False, "success_reason": f"runner_error: {e}",
                        "tool_calls": 0, "observation_tokens": 0, "elapsed_ms": 0,
                        "notes": ["runner_crash"], "trajectory": [], "weight": 1.0,
                    })

    comparison = compare_a_vs_d(rows)
    payload = {
        "schema": "verseshell.aci_bench.results/v1",
        "task_set_version": manifest.get("task_set_version"),
        "seed": manifest.get("seed"),
        "mode": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": current_git_rev(),
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "live_config": {
            "model": args.model,
            "api_base": args.base_url,
            "caps": args.caps,
            "max_turns": args.max_turns,
            "temperature": args.temperature,
            "seed": args.seed,
            "repeat": args.repeat,
            "exclude_tools": list(exclude_tools),
            "tasks": task_ids,
            "conditions": conditions,
        },
        "rows": rows,
        "aggregate": aggregate(rows),
        "comparison": comparison,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"\nwrote {out_path}")

    report_path = RESULTS / "live_REPORT.md"
    write_report(payload, report_path)
    print(f"wrote {report_path}")

    print("\n=== A vs D Comparison ===")
    for c in comparison.get("comparisons", []):
        print(
            f"[{c['model']}] "
            f"success: A={c['success_rate_A']} D={c['success_rate_D']} "
            f"tools: A={c['avg_tool_calls_A']} D={c['avg_tool_calls_D']} (ratio={c['tool_call_ratio_D_over_A']}) "
            f"tokens: A={c['avg_observation_tokens_A']} D={c['avg_observation_tokens_D']} (ratio={c['token_ratio_D_over_A']}) "
            f"accept={'PASS' if c['meets_acceptance'] else 'PARTIAL'}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
