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
import ctypes
import hashlib
import json
import os
import re
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
AE = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target"))) / "debug" / ("ae.exe" if os.name == "nt" else "ae")

# The runner is both a script and an import target (tools/ import it), so make the
# sibling module importable either way.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_deps import materialize_deps  # noqa: E402
from live_identity import validate_rows, validate_repeat_call_limit  # noqa: E402
from live_journal import ObservationStore, RunStatus, atomic_json, atomic_text, redact, utc_now
from live_storage import storage_policy, storage_check
from task_sets import load_tasks
from semantic_checks import rust_behavior
import compact_prompts
from grading_contract import freeze_verifiers, guarded_success, grading_environment
from final_workspace import FinalWorkspaceStore
from input_profile import input_profile

# ── Default API config ──
DEFAULT_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"

MAX_TURNS = 15
# Completion budget per turn. The endpoint serves a *reasoning* model whose
# `reasoning_content` is billed as completion tokens, so a small cap truncates
# the reply before any tool call is emitted. At 4096 that hit 7/30 condition-D
# rows and 0/30 condition-A rows in one round: D carries the larger prompt (tool
# schemas + envelopes), so the truncation was systematically biased against D,
# understating D's success rate and (because a truncated row observes little)
# flattering D's token ratio. Raised so the cap is not what decides the result.
MAX_COMPLETION_TOKENS = 16384
MAX_OUTPUT_CHARS = 64000
TOOL_TIMEOUT_SEC = 120
# Per-request HTTP timeout. It has to accommodate the completion budget: with the
# cap at 4096 a reasoning model could still be truncated mid-thought, and once the
# cap is raised the *same* generation legitimately takes longer, so a 180s timeout
# turned those rows into `api_error: timed out` (three seeds in a row on one task).
# Keep this comfortably above the worst observed generation.
API_TIMEOUT_SEC = 900
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
    "bench/aci/runners/*.py",
    "bench/aci/task_sets/*.json",
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
    "read_result": "result.query",
    "replace_in_file": "file.replace_exact",
    "search_content": "repo.search",
    "list_files": "repo.summary",
    "list_operations": "ops.list",
    # Legacy snake_case aliases (kept for backward compatibility)
    "file_view": "file.view",
    "file_write": "file.write",
    "exec_run": "exec.run",
    "result_query": "result.query",
    "file_replace_exact": "file.replace_exact",
    "repo_search": "repo.search",
    "repo_summary": "repo.summary",
    "ops_list": "ops.list",
}

READ_TEXT_HELP = (
    "read-text/v1: JSON header with text=Unicode character count, then verbatim bodies "
    "in file order separated by one newline. start_line defaults to 1; "
    "omitted total_lines means complete file. "
)

ACI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a workspace-relative file window centered on cursor. "
                + READ_TEXT_HELP +
                "Use returned next_cursor with the same window to continue. "
                "Reuse content_hash as expected_hash for safe editing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "cursor": {"type": "integer", "minimum": 1, "description": "Center line, NOT start line (1-based, default 1). Use next_cursor to continue; beyond EOF returns the last window."},
                    "window": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Max lines (default 80); keep unchanged when using next_cursor"},
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
                "Read up to 8 workspace-relative files in one call. Prefer a batch for known source/test paths. "
                + READ_TEXT_HELP +
                "Each entry retains path and content_hash. Missing files report per-entry errors. "
                "Use windows for ranges; truncated/deferred entries carry next_start_line for continuation. "
                "For unknown paths, use search_content."
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
                    "windows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_line": {
                                    "type": "integer",
                                    "description": "First line to return (1-based, default 1)",
                                },
                                "window": {
                                    "type": "integer",
                                    "description": "Max lines to return for this file",
                                },
                            },
                        },
                        "description": (
                            "Optional per-file overrides aligned by index with paths "
                            "(index 0 = paths[0]); omit an entry to use the defaults"
                        ),
                    },
                    "max_total_lines": {
                        "type": "integer",
                        "description": (
                            "Budget for the whole batch, in returned lines (default 240). "
                            "Keep the default unless you need more."
                        ),
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
                "Use for ALL build/test/install commands. "
                "Output includes exit status and stream metadata; read_result retrieves saved output by artifact handle. "
                "On failure, you get recoverable error + structured diagnostics + suggested_next. "
                "When NOT to use: to read files (use read_file), to edit files (use replace_in_file or write_file)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Direct program + arguments, not shell syntax. Spaces stay inside one argument; do not add shell quotes. On Windows use ["cmd","/d","/c","dir ."] for built-ins/pipes/redirection, or ["powershell","-NoProfile","-Command","..."] for PowerShell. Bare > and | are literal arguments. .cmd/.bat launch via cmd with quoted arguments.',
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
            "name": "read_result",
            "description": "Read a saved command output artifact without re-running the command. Use the stdout/stderr artifact handle exactly as returned (`result://sha256/<64 hex>`); tail shows test conclusions, slice reads line ranges, grep searches. Capture may be incomplete when raw_complete=false.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "artifact handle from command output"},
                    "mode": {"type": "string", "enum": ["meta", "head", "tail", "slice", "grep", "raw"]},
                    "lines": {"type": "integer", "minimum": 1, "description": "Maximum lines for head/tail (default 40)"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                    "pattern": {"type": "string", "description": "Regex for grep"},
                    "max_matches": {"type": "integer", "minimum": 1},
                    "max_bytes": {"type": "integer", "minimum": 1, "description": "Byte limit for raw (default 65536)"},
                    "max_tokens": {"type": "integer", "minimum": 64},
                },
                "required": ["handle", "mode"],
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
                "Run a shell command and get bounded raw output plus its exit status. "
                "Use for ALL actions: listing files (dir), reading files (type), "
                "running builds (cargo check), editing files (use python -c to write files), "
                "running tests (pytest), installing packages (pip install), git commands, etc. "
                "Output may be very long for build tools — read carefully. "
                "On Windows this is cmd /C, not PowerShell or POSIX. "
                "Use double quotes for paths with spaces; > and | are cmd operators. "
                "Invoke powershell -NoProfile -Command explicitly for PowerShell syntax."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command (cmd /C syntax on Windows, /bin/sh on POSIX). Quote paths with spaces; invoke powershell -NoProfile -Command explicitly for PowerShell syntax."},
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

# Description-only variant that removes the raw-shell instruction which drove the
# 2026-10-10 multi-line `python -c` failures. `cmd /C` runs only the FIRST line of a
# command containing an embedded newline and silently returns that line's exit code,
# so "editing files (use python -c to write files)" led models into a silent no-op and
# then into retry/turn-limit thrash. This is an OPT-IN arm: the frozen `baseline`
# description is left byte-for-byte unchanged so C1/C2 and the A/A' control stay
# comparable. It only replaces the raw-shell `run_command` description.
SHELL_SAFE_RUN_COMMAND_DESCRIPTION = (
    "Run a shell command and get bounded raw output plus its exit status. "
    "Use for ALL actions: listing files (dir), reading files (type), "
    "running builds (cargo check), running tests (pytest), installing packages "
    "(pip install), git commands, etc. To create or edit a file, run a SHORT "
    "one-line command, or write the code into a .py file and then run that file. "
    "Do NOT pass a multi-line program to `python -c`: cmd /C executes only the "
    "FIRST line of a multi-line command and silently ignores the rest, so it "
    "looks successful while changing nothing. Chain steps with '&' on one line. "
    "Output may be very long for build tools — read carefully. "
    "On Windows this is cmd /C, not PowerShell or POSIX. "
    "Use double quotes for paths with spaces; > and | are cmd operators. "
    "Invoke powershell -NoProfile -Command explicitly for PowerShell syntax."
)

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
7. run_command is for BUILD/TEST/INSTALL only. Use read_file to read files.
8. TASK.md only restates the task given above, in less detail — do not spend a
   tool call reading it. Read the source and test files instead."""

# Condition A's prompt. It must NOT mention tools A does not have: condition A is
# `run_command` only, and the shared ACI prompt used to tell it "run_command is
# for BUILD/TEST/INSTALL only. Use read_file to read files" — instructing it to
# use a tool that does not exist and forbidding its only tool for reading. That
# handicapped the baseline and biased the D/A comparison in D's favour, which is
# precisely the unfair control the acceptance criteria forbid. Same rule count and
# comparable length as the ACI prompt, so the two arms are equally well briefed.
SHELL_SYSTEM_PROMPT = """You are a coding agent. Complete the task in the workspace directory.

{task_hint}

CRITICAL RULES:
0. TRUST command output: exit code 0 means the command SUCCEEDED CORRECTLY.
   One successful build/test run is sufficient — do NOT re-run with variant
   arguments to confirm.
1. Explore workspace state FIRST before editing
2. Make MINIMAL changes — only what the task requires
3. VERIFY your changes ONCE: one successful test/build run is enough
4. Call task_complete(success=bool, summary="...") when done
5. If you get errors, debug — don't give up immediately. Read the error text.
6. Max {max_turns} tool calls total — be efficient
7. Use run_command for everything: list, read, search, edit, build and test.
8. TASK.md only restates the task given above, in less detail — do not spend a
   tool call reading it. Read the source and test files instead."""

# Condition A' — the prompt-matched control for claim C1. It has the same rule
# count and comparable length as the ACI prompt, but its "keep the output small"
# rule is written in SHELL terms instead of ACI terms. Comparing A' with D is what
# separates "the interface saves tokens" from "the prompt was better written";
# without this arm the D/A result cannot be attributed to the interface.
COACHED_SHELL_PROMPT = """You are a coding agent. Complete the task in the workspace directory.

{task_hint}

CRITICAL RULES:
0. TRUST command output: exit code 0 means the command SUCCEEDED CORRECTLY.
   One successful build/test run is sufficient — do NOT re-run with variant
   arguments to confirm.
1. Explore workspace state FIRST before editing
2. Make MINIMAL changes — only what the task requires
3. VERIFY your changes ONCE: one successful test/build run is enough
4. Call task_complete(success=bool, summary="...") when done
5. If you get errors, debug — don't give up immediately. Read the error text.
6. Max {max_turns} tool calls total — be efficient
7. KEEP THE OUTPUT SMALL: redirect long logs to a file, then read one slice
   with Python or search with findstr on Windows (grep on POSIX). PowerShell
   Select-String requires an explicit powershell -NoProfile -Command call.
8. TASK.md only restates the task given above, in less detail — do not spend a
   tool call reading it. Read the source and test files instead."""

# Diagnostic-only variant for the raw-shell command-construction failure seen in
# the 2026-10-10 partial run: the model repeatedly emitted POSIX/PowerShell
# constructs into cmd /C and then kept probing instead of changing approach.
# It only replaces the raw-shell prompt; baseline/coached/ACI are untouched.
SHELL_GUIDED_PROMPT = """You are a coding agent. Complete the task in the workspace directory.

{task_hint}

CRITICAL RULES:
0. TRUST command output: exit code 0 means the command SUCCEEDED CORRECTLY.
   One successful build/test run is sufficient -- do NOT re-run with variant
   arguments to confirm.
1. Explore workspace state FIRST before editing
2. Make MINIMAL changes -- only what the task requires
3. VERIFY your changes ONCE: one successful test/build run is enough
4. Call task_complete(success=bool, summary="...") when done
5. If a command fails with a syntax/quoting error, STOP retrying it. Change the
   command shape instead: use one short command, write the edit to a file with
   Python open(...).write(...), then run the test. Do not paste large
   multi-line programs into the command line.
6. Max {max_turns} tool calls total -- be efficient
7. SHELL IS cmd /C. It is NOT PowerShell and NOT POSIX sh. Do not use
   here-strings, backticks, $(...), single-quoted shell strings, or POSIX
   redirection forms. For a multi-line Python program, write it to a .py file
   first and run python file.py; do not pass a multi-line program to python -c.
8. TASK.md only restates the task given above, in less detail -- do not spend a
   tool call reading it. Read the source and test files instead."""

# condition -> system-prompt template. Recorded per row as `prompt_profile` so a
# result can always be attributed to the briefing that produced it.
PROMPT_BY_CONDITION = {
    "verseshell_aci": ("aci", SYSTEM_PROMPT),
    "raw_shell": ("shell_neutral", SHELL_SYSTEM_PROMPT),
    "raw_shell_coached": ("shell_coached", COACHED_SHELL_PROMPT),
}


# ── Success checking ──

# ── bounded subprocess execution ────────────────────────────────────────────────
#
# `subprocess.run(..., timeout=T)` does NOT bound a Windows command whose child
# keeps the stdout pipe open.  The timeout fires, CPython kills only the DIRECT
# child (cmd.exe), and `communicate()` then blocks forever on a pipe that the
# grandchild still holds — so `except subprocess.TimeoutExpired` never runs.
#
# Measured 2026-09-27: a D-arm command
#     python -c "open('src/lib.rs','w').write(open('CON','r').read())"
# (reading the Windows console device, which blocks forever in a non-interactive
# child) hung an entire ablation round for 11.5 hours and cost the 61 rows that
# were already finished.  The probe `audit-r12-scratch/probe_shell_timeout.py`
# measured the alternatives:
#
#     subprocess.run(timeout=6)              -> hung, orphan left alive
#     + stdin=DEVNULL                        -> hung, orphan left alive
#     + CREATE_NO_WINDOW                     -> hung, orphan left alive
#     Popen + Job Object (KILL_ON_JOB_CLOSE) -> returned in 6.01s   <-- adopted
#     Popen + taskkill /T /F                 -> returned in 6.21s
#
# So every child that runs model-authored or test-authored code goes through
# `run_bounded()`, which puts the child in a job object with KILL_ON_JOB_CLOSE and
# terminates the WHOLE JOB on timeout.  Killing the job reaps anything the command
# spawned, so a wedged descendant cannot outlive the call.
#
# We deliberately do NOT blacklist device names (CON/PRN/AUX/...): a bounded tree
# kill also stops infinite loops and pipe-holding grandchildren, which a name
# blacklist would not; and `> NUL` is a legitimate, common redirect.

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong)]


class _JOB_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_ulong),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", ctypes.c_ulong),
                ("SchedulingClass", ctypes.c_ulong)]


class _JOB_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOB_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _create_kill_on_close_job():
    """Return (kernel32, job_handle); (None, None) off Windows or on any failure."""
    if os.name != "nt":
        return None, None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        from ctypes import wintypes
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None, None
        info = _JOB_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None, None
        return k32, job
    except Exception:  # noqa: BLE001 - a missing job object must not break the run
        return None, None


def _terminate_tree(proc: subprocess.Popen, k32, job) -> None:
    """Kill the direct child AND everything it spawned."""
    if k32 is not None and job:
        try:
            if k32.TerminateJobObject(ctypes.c_void_p(job), 1):
                return
        except Exception:  # noqa: BLE001
            pass
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=2,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception:  # noqa: BLE001 - best effort only
        pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def run_bounded(cmd, *, timeout: int | None, cwd=None, shell: bool = False,
                stdin_data: bytes | None = None, env: dict | None = None,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, on_start=None):
    """Run `cmd`, bounding both the wall clock and the whole process tree.

    Returns `(returncode_or_None, stdout_bytes, stderr_bytes, timed_out)`.
    File-backed stdout/stderr avoid buffering long collection logs in memory.
    on_start runs after Job assignment, before permitting the Windows workload.
    """
    kwargs: dict = {
        "cwd": str(cwd) if cwd is not None else None,
        "shell": shell,
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
    }
    if env is not None:
        kwargs["env"] = env
    k32, job = _create_kill_on_close_job()
    if os.name == "nt":
        if k32 is None or not job:
            raise OSError('E_EXEC_JOB: cannot create managed command Job')
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        kwargs["stdin"] = subprocess.PIPE
        kwargs["shell"] = False
        # Preserve missing-executable grading as UNVERIFIED, before launching
        # the barrier. The helper otherwise inherits cwd and the exact env.
        if not shell and isinstance(cmd, (list, tuple)) and cmd:
            executable = os.fspath(cmd[0])
            resolved = str(Path(cwd or os.getcwd()) / executable) if os.path.dirname(executable) else executable
            if not shutil.which(resolved, path=(env or os.environ).get('PATH')):
                k32.CloseHandle(ctypes.c_void_p(job))
                raise FileNotFoundError(executable)
        command = [os.fspath(part) for part in cmd] if isinstance(cmd, (list, tuple)) else os.fspath(cmd)
        # The stdlib-only barrier must not be a venv redirector that can spawn before Job assignment.
        cmd = [getattr(sys, '_base_executable', None) or sys.executable, '-I', str(Path(__file__).with_name('managed_launch.py')),
               json.dumps([command, shell], ensure_ascii=False)]
        stdin_data = b'\x01' + (stdin_data or b'')
    proc = None
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        if k32 is not None and job:
            from ctypes import wintypes as _wintypes
            if not k32.AssignProcessToJobObject(ctypes.c_void_p(job),
                                                _wintypes.HANDLE(int(proc._handle))):
                raise OSError('E_EXEC_JOB: managed launcher assignment failed')
        if on_start is not None:
            on_start(proc)
        out, err = proc.communicate(input=stdin_data, timeout=timeout)
        return proc.returncode, out or b"", err or b"", False
    except subprocess.TimeoutExpired:
        _terminate_tree(proc, k32, job)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        return None, out or b"", err or b"", True
    except BaseException:
        if k32 is not None and job:
            k32.CloseHandle(ctypes.c_void_p(job))
            job = None
        if proc is not None:
            # No permit was sent on assignment failure. Only our trusted helper
            # exists, so killing it cannot leave an unassigned workload tree.
            try:
                proc.kill()
            except OSError:
                pass
            # Job termination is asynchronous; a failed kill must not skip the
            # wait that releases the child's file-backed stdout/stderr handles.
            try:
                proc.communicate(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise
    finally:
        if k32 is not None and job:
            k32.CloseHandle(ctypes.c_void_p(job))


def check_success(pred: dict, workspace: Path) -> tuple[bool | None, str]:
    """Evaluate a success predicate.

    `None` means **unverified**: the check could not run at all on this machine
    (the command is missing), which must not be recorded as a capability failure.
    `all` propagates it, so a task that requires behaviour cannot be scored as a
    failure just because the toolchain is absent.
    """
    t = pred.get("type")
    if t == 'rust_behavior':
        return rust_behavior(pred, workspace, run_bounded)
    if t == "all":
        for child in pred.get("of", []):
            ok, reason = check_success(child, workspace)
            if ok is None:
                return None, reason
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
    if t == "file_matches":
        # Whole-content regex match (outer whitespace, as in file_equals, is ignored). It lets a
        # predicate describe the shape the prompt asked for — e.g. "one line that
        # names the installed package" — instead of one fixed wording.
        p = workspace / pred["path"]
        if not p.exists():
            return False, f"missing {pred['path']}"
        body = p.read_text(encoding="utf-8-sig", errors="replace").strip()
        pattern = pred.get("pattern", "")
        try:
            matched = re.fullmatch(pattern, body) is not None
        except re.error as error:
            return None, f"unverified: bad pattern {error!r}"
        return (matched, f"file_matches {pred['path']}")
    if t == "command_exit_0":
        argv = pred.get("argv") or []
        if pred.get('resolve_executable') and argv:
            argv=[shutil.which(argv[0]) or argv[0],*argv[1:]]
        try:
            rc, _out, _err, timed_out = run_bounded(
                argv, cwd=workspace, timeout=int(pred.get("timeout_sec", 120)),
                env=grading_environment(workspace))
            if timed_out:
                return (None if pred.get('timeout_is_unverified') else False), f"timeout: {argv}"
            if any(marker in (_out+_err).decode('utf-8','replace') for marker in pred.get('unverified_output_markers',[])):
                return None, f'unverified: missing grading dependency for {argv}'
            return (rc == 0, f"command_exit_0 {argv} -> {rc}")
        except FileNotFoundError:
            return None, f"unverified: command not found: {argv}"
    return False, f"unknown predicate {t}"


def success_verdict(success: bool | None) -> str:
    """`None` is unverified (the check could not run), not a failure."""
    return "UNVERIFIED" if success is None else ("PASS" if success else "FAIL")


# ── Workspace prep ──

def prepare_workspace(fixture_name: str) -> Path:
    src = FIXTURES / fixture_name
    td = Path(tempfile.mkdtemp(prefix=f"aci-live-{fixture_name}-"))
    if src.exists():
        for item in src.iterdir():
            # `GOLDEN` is the reference patch; `deps` is materialised below rather
            # than copied, so the agent sees a workspace that already has its
            # declared toolchain instead of the archive it came in.
            if item.name in ("GOLDEN", "deps"):
                continue
            dest = td / item.name
            if item.is_dir():
                shutil.copytree(item, dest,
                                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            else:
                shutil.copy2(item, dest)
        materialize_deps(src, td)
    return td


# ── Chat API ──

def responses_input(messages: list[dict]) -> list[dict]:
    items = []
    for message in messages:
        if message.get('_responses_output') is not None:
            items.extend(message['_responses_output'])
        elif message['role'] == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                          'output': message['content']})
        else:
            items.append({'role': message['role'], 'content': message.get('content') or ''})
    return items


def responses_result(response: dict) -> dict:
    if response.get('error') or response.get('status') not in ('completed', 'incomplete'):
        raise ValueError('Responses request did not complete: ' + str(response.get('error') or response.get('status')))
    output = response.get('output') or []
    calls = [{'id': item['call_id'], 'type': 'function',
              'function': {'name': item['name'], 'arguments': item['arguments']}}
             for item in output if item.get('type') == 'function_call']
    content = ''.join(part.get('text', '') for item in output if item.get('type') == 'message'
                      for part in item.get('content', []) if part.get('type') == 'output_text')
    message = {'content': content, 'tool_calls': calls, '_responses_output': output}
    reasoning = ''.join(part.get('text', '') for item in output if item.get('type') == 'reasoning'
                        for part in item.get('summary', []))
    if reasoning:
        message['reasoning_content'] = reasoning
    usage = response.get('usage') or {}
    normalized = {dest: usage[src] for src, dest in
                  [('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')]
                  if usage.get(src) is not None}
    reason = (response.get('incomplete_details') or {}).get('reason')
    finish = ('length' if reason == 'max_output_tokens' else 'incomplete') if response['status'] == 'incomplete' else ('tool_calls' if calls else 'stop')
    return {'choices': [{'message': message, 'finish_reason': finish}], 'usage': normalized,
            '_responses_status': response['status'], '_responses_usage': usage}


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
    request_budget: float | None = None,
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
    is_responses = base_url.rstrip('/').endswith('/responses')
    if is_responses:
        payload = {'model': model, 'input': responses_input(messages),
                   'tools': [dict(t['function'], type='function', strict=False) for t in tools],
                   'tool_choice': 'auto', 'max_output_tokens': max_tokens,
                   'temperature': temperature, 'store': False}
    url = base_url.rstrip('/') if is_responses else f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    profile = input_profile(payload, body)
    attempts = []
    budget=API_TIMEOUT_SEC if request_budget is None else request_budget
    if budget<=0:raise ValueError('request budget must be positive')
    deadline = time.monotonic() + budget

    for attempt in range(3):
        attempt_id=uuid.uuid4().hex
        started=utc_now()
        response_status=None; request_id=None
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=max(.001,deadline-time.monotonic())) as resp:
                response_status=resp.status
                request_id=getattr(resp,'headers',{}).get('x-request-id')
                data = json.loads(resp.read().decode("utf-8"))
                if not isinstance(data,dict):raise ValueError("endpoint response must be an object")
                result = responses_result(data) if is_responses else data
                result['_transport_attempts'] = attempts + [{'attempt': attempt + 1, 'attempt_id':attempt_id,
                    'started_at':started,'finished_at':utc_now(),'status': resp.status,
                    'request_id':request_id,'response_id':data.get('id'),
                    'request_body_sha256':hashlib.sha256(body).hexdigest(),
                    'input_profile':profile,
                    'usage':result.get('usage') if isinstance(result.get('usage'),dict) else None,
                    'usage_complete':isinstance(result.get('usage'),dict) and all(
                        type(result['usage'].get(k)) is int and result['usage'][k]>=0
                        for k in ('prompt_tokens','completion_tokens'))}]
                result['_returned_model']=data.get('model')
                result['_response_id']=data.get('id')
                result['_request_id']=getattr(resp,'headers',{}).get('x-request-id')
                result['_request_body_sha256']=hashlib.sha256(body).hexdigest()
                return result
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace").replace(api_key, '[REDACTED]')[:1000]
            status=e.code
            request_id=getattr(e,'headers',{}).get('x-request-id') if getattr(e,'headers',None) else None
            message=f'HTTP {e.code}: {err_body}'
            retryable=status==429 or 500<=status<600
        except (urllib.error.URLError,TimeoutError,OSError) as exc:
            status=None;message=redact(str(exc),(api_key,));retryable=True
        except (ValueError, UnicodeError) as exc:
            status=response_status;message=redact(str(exc),(api_key,));retryable=False
        attempts.append({'attempt':attempt+1,'attempt_id':attempt_id,'started_at':started,
                         'finished_at':utc_now(),'status':status,'error':message,
                         'request_id':request_id,'response_id':None,
                         'request_body_sha256':hashlib.sha256(body).hexdigest(),
                         'input_profile':profile,
                         'usage':None,'usage_complete':False})
        delay=2**attempt
        if retryable and attempt<2 and time.monotonic()+delay<deadline:
            time.sleep(delay)
        else:
            error = RuntimeError(message)
            error.attempts = attempts
            error.status = status
            raise error from None
    return {}  # unreachable


# ── Tool execution ──

def execute_aci_op(op_name: str, args: dict, workspace: str,
                   caps: str = ACI_CAPABILITIES, *, capture: dict | None = None) -> dict:
    """Run a single ACI op via ae --serve --agent."""
    if capture is not None and op_name == "exec.run":
        args = {"artifact": "always", **args}
    op = {
        "id": uuid.uuid4().hex[:12],
        "agent": "live_bench",
        "op": op_name,
        "args": args,
        "timeout_ms": AE_OP_TIMEOUT_MS,
        "budget": {"max_tokens": 4000},
    }

    env = grading_environment(workspace)
    env["AETHER_APPROVE_ALL"] = "1"
    env["AETHER_MODE"] = "agent"
    env["AETHER_WORKSPACE"] = str(workspace)
    for k in list(env.keys()):
        if env[k] is None:
            del env[k]

    stdin_data = json.dumps(op, ensure_ascii=False).encode("utf-8") + b"\n"
    rc, stdout, stderr, timed_out = run_bounded(
        [str(AE), "--serve", "--agent", "--cap", caps],
        timeout=TOOL_TIMEOUT_SEC, stdin_data=stdin_data, env=env)
    if timed_out:
        return {"ok": False, "error": {"code": "E_TIMEOUT",
                                       "message": f"ae op timed out after {TOOL_TIMEOUT_SEC}s"}}
    if rc != 0:
        return {
            "ok": False,
            "error": {
                "code": "AE_CRASH",
                "message": f"ae exited {rc}: {stderr.decode('utf-8', errors='replace')[:300]}",
            },
        }

    lines = [l.strip() for l in stdout.decode("utf-8", errors="replace").split("\n") if l.strip()]
    if not lines:
        return {"ok": False, "error": {"code": "AE_EMPTY", "message": "no output from ae"}}
    response = json.loads(lines[0])
    if capture is not None and op_name == "exec.run":
        artifact_root = (Path(workspace) / '.ae' / 'results').resolve()
        for stream in ('stdout', 'stderr'):
            value = (response.get('data') or {}).get(stream) or {}
            handle = value.get('artifact', '')
            if not value.get('raw_bytes'):
                continue
            try:
                prefix = 'result://sha256/'
                digest = handle.removeprefix(prefix)
                if not handle.startswith(prefix) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('raw artifact unavailable')
                path = (artifact_root / (digest + '.bin')).resolve()
                if (not artifact_root.is_relative_to(Path(workspace).resolve())
                        or not path.is_relative_to(artifact_root)
                        or path.stat().st_size > 64 * 1024 * 1024):
                    raise ValueError('raw artifact outside capture bounds')
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError('raw artifact hash mismatch')
                capture[stream] = raw
            except (OSError, ValueError) as exc:
                response.setdefault('raw_capture_errors', {})[stream] = str(exc)
    return response


def compact_lines(lines: list) -> list:
    """[{line, text}, ...] -> [text, ...]; the start line is carried separately."""
    out = []
    for entry in lines:
        if isinstance(entry, dict):
            out.append(entry.get("text", ""))
        else:
            out.append(str(entry))
    return out


def digest_of(payload: dict) -> str | None:
    """Pick the change-detection digest to show the model.

    Read ops return both `hash` (16 hex chars, accepted as an `expected_hash`
    prefix) and the full `content_hash` (`sha256:` + 64 hex). The model only
    needs a token it can hand back for the stale-write check, and the full form
    costs 71 characters *per file* — measured at 28% of a 3-file batch
    observation before this projection (docs/claims-and-evidence.md, C14). The
    key name stays `content_hash` so the model's existing habit still works.
    """
    return payload.get("hash") or payload.get("content_hash")


READ_TEXT_PREFIX = "read-text/v1 "


def format_read_text(projection: dict) -> str:
    """Frame verbatim windows with JSON metadata and character-count boundaries."""
    header = dict(projection)
    if "files" in header:
        header["files"] = [dict(item) for item in header["files"]]
    bodies = []
    for item in [header, *header.get("files", [])]:
        if "text" in item:
            bodies.append(item["text"])
            item["text"] = len(item["text"])
    if not bodies:
        return json.dumps(projection, ensure_ascii=False)
    return (READ_TEXT_PREFIX + json.dumps(header, ensure_ascii=False, separators=(",", ":"))
            + "\n" + "\n".join(bodies))


def parse_aci_result(text: str) -> dict:
    """Decode JSON or read-text/v1, rejecting truncated or ambiguous frames."""
    if not text.startswith(READ_TEXT_PREFIX):
        return json.loads(text)
    metadata, separator, body = text[len(READ_TEXT_PREFIX):].partition("\n")
    header = json.loads(metadata)
    items = [item for item in [header, *header.get("files", [])] if "text" in item]
    if not separator or not items:
        raise ValueError("read-text frame has no body")
    offset = 0
    for index, item in enumerate(items):
        length = item["text"]
        if type(length) is not int or length < 0 or offset + length > len(body):
            raise ValueError("invalid read-text length or truncated body")
        item["text"] = body[offset:offset + length]
        offset += length
        if index < len(items) - 1:
            if body[offset:offset + 1] != "\n":
                raise ValueError("missing read-text separator")
            offset += 1
    if offset != len(body):
        raise ValueError("unexpected trailing read-text data")
    return header


def format_aci_result(response: dict, *, compact: bool = True) -> str:
    """Extract model-relevant fields from the AE observation envelope.

    On SUCCESS: minimal output — ok + content essentials. The model
    only needs to confirm the op worked; verbose metadata wastes tokens.
    On FAILURE: top 5 diagnostics + summary + error code — trim noise.

    `compact` selects verbatim read-text/v1 instead of JSON line arrays.
    Centered file.view windows retain their exact bounds and next_cursor.
    Command streams are already bounded by the runtime; do not silently cut
    them again or discard the handles needed to inspect omitted output.
    """
    ok = response.get("ok")
    clean: dict[str, Any] = {"ok": ok}
    data = response.get("data") or {}

    if ok and response.get("op") == "result.query":
        clean.update({key: data[key] for key in (
            "handle", "mode", "encoding", "decoding_lossy", "text", "lines",
            "start_line", "end_line", "matches", "pattern", "truncated",
            "returned_bytes", "raw_bytes", "bytes", "digest", "expires_at",
        ) if key in data})
        return json.dumps(clean, ensure_ascii=False)

    for key in ("exit_code", "timed_out", "stats", "end_line", "next_cursor"):
        if key in data:
            clean[key] = data[key]
    if "next_cursor" in data and "start_line" in data:
        clean["start_line"] = data["start_line"]
    for stream in ("stdout", "stderr"):
        value = data.get(stream)
        if not isinstance(value, dict):
            continue
        clean[stream] = {key: value[key] for key in (
            "status", "raw_bytes", "returned_bytes", "omitted_bytes", "raw_complete",
            "encoding", "decoding_lossy", "artifact",
        ) if key in value}
        if value.get("text") is not None:
            clean[stream + "_text"] = value["text"]
        if value.get("summary") and value["summary"] != data.get("summary"):
            clean[stream + "_summary"] = value["summary"]

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
        if "content_hash" in data:
            clean["content_hash"] = data["content_hash"]
        if "total_lines" in data:
            clean["total_lines"] = data["total_lines"]
        # `E_AMBIGUOUS` carries the candidate sites in `data.matches[]`
        # (line/offset/snippet) precisely so the agent can retry in one step
        # instead of re-reading the file to find them. The failure path used to
        # return before this field was projected, so the structured payload the
        # op promises reached the server but never the model. Keep it compact:
        # only the locator fields, and only the head of a long candidate list.
        if "matches" in data and isinstance(data["matches"], list):
            sites = []
            for match in data["matches"][:10]:
                if not isinstance(match, dict):
                    continue
                sites.append({k: match[k] for k in ("path", "line", "offset", "snippet")
                              if k in match})
            if sites:
                clean["matches"] = sites
                clean["match_count"] = data.get("match_count", len(data["matches"]))
        return json.dumps(clean, ensure_ascii=False)

    # SUCCESS: silence — return only what the model needs to proceed
    if "summary" in data:
        clean["summary"] = data["summary"]
    digest = digest_of(data)
    if digest:
        clean["content_hash"] = digest
    if "total_lines" in data:
        clean["total_lines"] = data["total_lines"]

    # Carry the window the tool actually returned.
    #
    # This used to gate on `len(lines) <= 10`, i.e. it emitted content only for
    # windows of ten lines or fewer and otherwise dropped it entirely, leaving just
    # `{ok, content_hash, total_lines}`. `file.view`'s default window is 80, so a
    # plain `file.view` of ANY file longer than ten lines handed the model a hash
    # and nothing else — the tool description promises "a window of lines around a
    # cursor", and the reference client was withholding it. Measured on the v2.0.0
    # live run: 180 of 204 `file.view` calls returned metadata only, 45% of them
    # re-viewed a path the agent had already viewed (because the first look showed
    # nothing), and D fell back to `repo.search` (301 calls / 65.7k tokens) and
    # shell reads to see file content at all. The tool's own `window` clamp (<=500)
    # is the bound; adding a second, hidden one here is what broke the contract.
    # `data.lines` is [{line, text}, ...]; the per-line object wrapper is pure
    # structural overhead, so the projection flattens it and carries the starting
    # line number once.
    if "lines" in data:
        lines = data["lines"]
        if isinstance(lines, list) and lines:
            if compact:
                clean["text"] = "\n".join(compact_lines(lines))
                start = data.get("start_line") or 1
                total = data.get("total_lines")
                if ("next_cursor" not in data and isinstance(total, int)
                        and start <= 1 and len(lines) >= total):
                    # Complete window: `total_lines` is just len(lines).
                    clean.pop("total_lines", None)
                if start > 1:
                    clean["start_line"] = start
            else:
                clean["lines"] = compact_lines(lines)
                if "start_line" in data:
                    clean["start_line"] = data["start_line"]
        elif "content_hash" not in data:
            clean["total_lines"] = len(lines) if isinstance(lines, list) else 0

    # file.read_many: per-file projection, same flattening as file.view, plus
    # per-file errors so a missing path does not hide the readable ones.
    if "files" in data and isinstance(data["files"], list):
        entries: list[dict] = []
        for entry in data["files"]:
            if not isinstance(entry, dict):
                continue
            item = {
                key: entry[key]
                for key in ("path", "total_lines", "start_line", "error")
                if key in entry
            }
            entry_digest = digest_of(entry)
            if entry_digest:
                item["content_hash"] = entry_digest
            shown = entry.get("lines")
            # Same contract fix as `file.view` above: carry the window the tool
            # returned instead of only windows of ten lines or fewer.
            if isinstance(shown, list) and shown:
                if compact:
                    item["text"] = "\n".join(compact_lines(shown))
                    start = entry.get("start_line") or 1
                    total = entry.get("total_lines")
                    if isinstance(total, int) and start <= 1 and len(shown) >= total:
                        item.pop("total_lines", None)
                    if start > 1:
                        item["start_line"] = start
                    else:
                        item.pop("start_line", None)
                else:
                    item["lines"] = compact_lines(shown)
            # Pagination is only surfaced when the entry was actually cut, so a
            # complete read stays exactly as small as before.
            if entry.get("deferred"):
                item["deferred"] = True
            elif entry.get("truncated"):
                item["truncated"] = True
            if (entry.get("truncated") or entry.get("deferred")) and entry.get("next_start_line") is not None:
                item["next_start_line"] = entry["next_start_line"]
            entries.append(item)
        clean["files"] = entries
        if "errors" in data:
            clean["errors"] = data["errors"]

    # repo.search: the matches ARE the answer. This used to fall through to the
    # generic success path, which returned `{"ok": true}` and dropped every
    # match: the tool description promises "matching files and lines", so an
    # agent that called it learned nothing, re-issued the call, and then fell
    # back to a raw `grep` through exec.run. Project each match as
    # path:line + text, and carry `truncated` so a cut search is visible.
    if "matches" in data:
        matches = data.get("matches") or []
        projected_matches: list[dict] = []
        for match in matches[:50]:
            if not isinstance(match, dict):
                continue
            item = {key: match[key] for key in ("path", "line", "text") if key in match}
            projected_matches.append(item)
        clean["match_count"] = data.get("match_count", len(projected_matches))
        clean["matches"] = projected_matches
        if data.get("truncated"):
            clean["truncated"] = True

    # ops.list: keep only op names (descriptions are noise on success)
    if "operations" in data:
        clean["available_ops"] = [o["name"] for o in data["operations"]]

    # repo.summary: keep branch + dirty files + the top-level listing on success.
    # The listing ships as `top_level` (not `entries`), so the previous filter
    # silently dropped the half of the answer the `list_files` description
    # actually promises ("top-level directory listing").
    if "branch" in data or "top_level" in data:
        repo_fields = {k: data[k] for k in ("branch", "dirty_files", "top_level", "entries")
                       if k in data}
        if repo_fields:
            clean["repo"] = repo_fields

    return format_read_text(clean) if compact else json.dumps(clean, ensure_ascii=False)


def decode_shell_output(data: bytes) -> tuple[str, str, bool]:
    """UTF-8 first, then the Windows OEM code page; this is a fallback, not detection."""
    data = data.removeprefix(b"\xef\xbb\xbf")
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    if os.name == "nt":
        cp = ctypes.windll.kernel32.GetOEMCP()
        try:
            return data.decode(f"cp{cp}"), f"windows-oem-{cp}", False
        except UnicodeDecodeError:
            return data.decode(f"cp{cp}", errors="replace"), f"windows-oem-{cp}-lossy", True
        except LookupError:
            pass
    return data.decode("utf-8", errors="replace"), "utf-8-lossy", True


def _multiline_shell_note(command: str) -> str | None:
    """Flag a multi-line command that cmd /C will silently truncate.

    Windows cmd executes only the FIRST line of a command that contains an
    embedded newline and still returns that line's exit code, so every later
    line is dropped without any error.  Models routinely emit a multi-line
    ``python -c "..."`` to write a file, then cannot tell why nothing changed
    and retry variants until the turn/repeat budget is gone (2026-10-10
    partial run: all 10 raw-shell failures were this shape).  The observation
    must not report that as a clean success, so surface the truncation next to
    the other harness annotations.  This is additive information only: it does
    not change the command, the exit code, the tool schema, or the prompt.
    """
    if os.name != 'nt':
        return None
    body = command.strip()
    if '\n' not in body and '\r' not in body:
        return None
    return ("[MULTILINE: cmd /C runs only the FIRST line of a multi-line command and "
            "still returns its exit code; the remaining lines were NOT executed. "
            "Chain with '&' or write the code to a .py/.cmd file in one line and run it.]")


def execute_shell_cmd(command: str, workspace: str, *, capture: dict | None = None) -> str:
    """Run through the bounded process tree; retain exit status after any output cut."""
    rc, out_b, err_b, timed_out = run_bounded(
        command, timeout=TOOL_TIMEOUT_SEC, cwd=workspace, shell=True,
        env=grading_environment(workspace))
    out, out_encoding, out_lossy = decode_shell_output(out_b)
    err, err_encoding, err_lossy = decode_shell_output(err_b)
    if capture is not None:
        capture.update(stdout=out_b, stderr=err_b)
    if err:
        out += "\n[STDERR]\n" + err
    if len(out) > MAX_OUTPUT_CHARS:
        head = MAX_OUTPUT_CHARS // 2
        tail = MAX_OUTPUT_CHARS - head
        out = (out[:head] + f"\n... [TRUNCATED: {len(out) - MAX_OUTPUT_CHARS} middle characters omitted]\n"
               + out[-tail:])
    out += (f"\n[ENCODING stdout={out_encoding} lossy={str(out_lossy).lower()}; "
            f"stderr={err_encoding} lossy={str(err_lossy).lower()}]")
    note = _multiline_shell_note(command)
    if note:
        out += "\n" + note
    if timed_out:
        out += f"\n[TIMEOUT after {TOOL_TIMEOUT_SEC}s]"
    out += f"\n[EXIT: {rc}]"
    return out


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ── Per-turn diagnostics (P0-1) ──
#
# The row carried only totals (`llm_completion_tokens`, `completion_truncated_turns`),
# so a cell that burned the whole completion budget on turn 1 was indistinguishable
# from one that truncated on a later turn, and neither could be told apart from a
# cell whose reasoning the endpoint simply did not return. These helpers only *read*
# what the endpoint already sent. Nothing here is written back into `messages`, the
# tool schemas, the request payload, or any sampling parameter.
#
# `turn_diagnostics` is additive: rows produced before this change have no such key
# and every consumer keeps working (they all read rows with `.get`). A reader tells
# "recorded and zero" from "not recorded at all" by whether the key exists, and, per
# turn, by `fields_missing`.

# Message fields a served reasoning model may return. Recorded by name so a reader
# can tell "the endpoint reported no reasoning" from "we did not look for it".
REASONING_KEYS = ("reasoning_content", "reasoning")

# Per-turn keys documented as the diagnostic surface; used to build `fields_missing`.
TURN_DIAGNOSTIC_FIELDS = (
    "finish_reason", "prompt_tokens", "completion_tokens", "reasoning_returned",
    "reasoning_chars", "content_chars", "tool_call_count", "completion_truncated",
    "request_ms",
)


def _ms_since(start: float) -> int:
    return int((time.time() - start) * 1000)


def _reasoning_text(msg: Any) -> tuple[bool, int | None, list[str]]:
    """(returned, chars, keys) for the reasoning fields the endpoint chose to send.

    `chars` is None when no reasoning field came back. It is never estimated from
    `completion_tokens`: the endpoint bills reasoning as completion tokens, but it
    does not promise that the completion budget was spent on reasoning, so token
    counts cannot stand in for reasoning volume.
    """
    if not isinstance(msg, dict):
        return False, None, []
    keys: list[str] = []
    text = ""
    for key in REASONING_KEYS:
        value = msg.get(key)
        if isinstance(value, str):
            keys.append(key)
            text += value
    return bool(keys), (len(text) if keys else None), keys


def _turn_diagnostic(*, turn: int, finish_reason: Any, usage: Any, msg: Any,
                     request_ms: int) -> dict:
    """One turn's record, built only from the response the endpoint returned."""
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    reasoning_returned, reasoning_chars, reasoning_keys = _reasoning_text(msg)
    content = msg.get("content") if isinstance(msg, dict) else None
    tool_calls = (msg.get("tool_calls") or []) if isinstance(msg, dict) else []
    rec = {
        "turn": turn,
        "finish_reason": finish_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_returned": reasoning_returned,
        "reasoning_chars": reasoning_chars,
        "reasoning_keys": reasoning_keys,
        "content_chars": len(content) if isinstance(content, str) else None,
        "tool_call_count": len(tool_calls),
        "completion_truncated": finish_reason == "length",
        "request_ms": request_ms,
    }
    missing = [k for k in ("prompt_tokens", "completion_tokens") if rec[k] is None]
    if not isinstance(finish_reason, str):
        missing.append("finish_reason (not returned by the endpoint)")
    if not reasoning_returned:
        missing.append("reasoning_content (not returned by the endpoint)")
    rec["fields_missing"] = missing
    return rec


def _record_turn_diagnostics(store: list[dict], *, turn: int, finish_reason: Any = None,
                             usage: Any = None, msg: Any = None, request_ms: int | None = None,
                             request_error: str | None = None) -> None:
    """Append one per-turn record; this must never abort a live cell.

    The whole body is guarded because a diagnostic bug may not cost a live cell, but
    the guard is not allowed to be silent either: when it fires, the record carries
    `record_error` and the offline analyzer reports the turn as unusable instead of
    reading the gap as a clean turn.
    """
    try:
        if request_error is not None:
            missing = [field for field in TURN_DIAGNOSTIC_FIELDS if field != "request_ms"]
            missing.append("reasoning_content (no response)")
            store.append({
                "turn": turn,
                "request_ms": request_ms,
                "request_error": str(request_error),
                "fields_missing": missing,
            })
            return
        store.append(_turn_diagnostic(turn=turn, finish_reason=finish_reason, usage=usage,
                                      msg=msg, request_ms=request_ms))
    except Exception as exc:  # noqa: BLE001 - fail-soft, but visibly (see docstring)
        store.append({"turn": turn, "record_error": f"{type(exc).__name__}: {exc}"})


# ── Agent loop ──

def prompt_and_tools(condition,variant='baseline'):
    if variant not in ('baseline', 'compact', 'compact_all', 'shell_guided', 'shell_safe'):
        raise ValueError(f'unknown prompt variant: {variant}')
    profile,template=PROMPT_BY_CONDITION.get(condition,('shell_neutral',SHELL_SYSTEM_PROMPT))
    if variant == 'shell_guided' and condition in ('raw_shell', 'raw_shell_coached'):
        profile,template = 'shell_guided', SHELL_GUIDED_PROMPT
    tools=ACI_TOOLS if condition=='verseshell_aci' else RAW_SHELL_TOOLS
    if variant == 'shell_safe' and condition in ('raw_shell', 'raw_shell_coached'):
        tools=[{**t, 'function': {**t['function'], 'description': SHELL_SAFE_RUN_COMMAND_DESCRIPTION}}
               if t['function']['name'] == 'run_command' else t for t in tools]
    if variant=='compact' and condition=='verseshell_aci':
        tools=[{**t,'function':{**t['function'],'description':compact_prompts.DESCRIPTIONS[t['function']['name']]}} for t in tools]
    elif variant == 'compact_all':
        tools=[{**t,'function':{**t['function'],'description':compact_prompts.ALL_DESCRIPTIONS[t['function']['name']]}} for t in tools]
    return profile,template,tools


def run_agent_loop(
    task: dict,
    condition: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    max_turns: int = MAX_TURNS,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    caps: str = ACI_CAPABILITIES,
    temperature: float = 0.0,
    seed: int | None = None,
    run_index: int = 0,
    exclude_tools: tuple[str, ...] = (),
    observation_store=None,
    cell_id: str | None = None,
    prompt_variant: str = 'baseline',
    repeat_call_limit: int = 0,
) -> dict:
    validate_repeat_call_limit(repeat_call_limit)
    cell_id=cell_id or uuid.uuid4().hex
    cell_started_at=utc_now()
    workspace = prepare_workspace(task["workspace_fixture"])
    grading_contract = freeze_verifiers(task["success"], workspace)
    prompt_profile,prompt_template,tools=prompt_and_tools(condition,prompt_variant)
    if exclude_tools:
        # Used to A/B a single tool (e.g. read_files) on the same model.
        tools = [t for t in tools if t["function"]["name"] not in exclude_tools]
    tool_names = {t["function"]["name"] for t in tools}

    task_hint = TASK_SPECIFIC_PROMPTS.get(task["id"], task["prompt"])
    system = prompt_template.format(task_hint=task_hint, max_turns=max_turns,read_format=READ_TEXT_HELP)
    system += ("\n\nPLATFORM: Windows; shell commands use cmd /C. Invoke PowerShell explicitly."
               if os.name == "nt" else "\n\nPLATFORM: POSIX; shell commands use /bin/sh.")
    system += " Paths are relative to the supplied workspace; do not assume /workspace exists."

    if repeat_call_limit:
        system += (f"\nREPEAT CALL BUDGET: After {repeat_call_limit} consecutive identical tool calls "
                   "with identical observations, this run stops. Change approach instead of repeating. "
                   "Independent grading and all other budgets remain unchanged.")

    # Add task file listing for context
    ws_files = _list_workspace(workspace)
    system += f"\n\nWORKSPACE FILES:\n{ws_files}"

    messages: list[dict] = [{"role": "system", "content": system},
                          {"role": "user", "content": "Begin the task."}]

    trajectory: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    turn = 0
    task_completed = False
    agent_declared_success = False
    last_error = None
    api_error = False
    endpoint_status = None
    usage_complete = True
    stop_reason = 'turn_limit'
    previous_call = None
    identical_calls = 0
    truncated_turns = 0
    # P0-1: per-turn records, additive to the row schema. Recording only depends on
    # values the endpoint already returned, so it cannot change what the model sees.
    turn_diagnostics: list[dict] = []
    # Set when the loop aborts on an exception raised by the *harness* rather than by
    # the model. A run whose harness died before recording a single tool result used
    # to be indistinguishable from an ordinary task failure; that is how the cp936
    # decoding crash stayed invisible for three rounds (TF-0100).
    harness_fault = None

    start_time = time.time()

    try:
        while turn < max_turns:
            turn += 1
            request_start = time.time()
            try:
                resp = chat_completion(messages, tools, model=model, api_key=api_key,
                                   base_url=base_url, temperature=temperature, seed=seed,
                                   max_tokens=max_tokens)
            except Exception as e:
                last_error = f"API error turn {turn}: {e}".replace(api_key, '[REDACTED]')
                # Marked so an upstream outage can never be averaged into the
                # benchmark as a "0 tools / 0 tokens" data point.
                api_error = True
                endpoint_status=getattr(e,'status',None)
                stop_reason='endpoint_error';usage_complete=False
                # Keep the failed attempt in the per-turn record: a turn that never
                # produced a response must not read as a turn that produced nothing.
                _record_turn_diagnostics(
                    turn_diagnostics, turn=turn, request_ms=_ms_since(request_start),
                    request_error=last_error)
                turn_diagnostics[-1]['transport_attempts'] = getattr(e, 'attempts', [])
                break

            usage = resp.get("usage") if isinstance(resp.get("usage"),dict) else {}
            if any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):
                usage_complete=False
            total_prompt_tokens += usage['prompt_tokens'] if type(usage.get('prompt_tokens')) is int and usage['prompt_tokens']>=0 else 0
            total_completion_tokens += usage['completion_tokens'] if type(usage.get('completion_tokens')) is int and usage['completion_tokens']>=0 else 0
            if len(resp.get('_transport_attempts',[]))>1:usage_complete=False

            choice = resp["choices"][0]
            msg = choice["message"]
            tool_calls = msg.get("tool_calls") or []

            # Record what this turn returned, before any early break can skip it.
            # Nothing here is fed back: `messages` still receives exactly the
            # assistant content / tool_calls assembled below.
            _record_turn_diagnostics(
                turn_diagnostics, turn=turn, finish_reason=choice.get("finish_reason"),
                usage=usage, msg=msg, request_ms=_ms_since(request_start))
            turn_diagnostics[-1]['transport_attempts'] = resp.get('_transport_attempts', [])
            turn_diagnostics[-1].update(request_id=resp.get('_request_id'),response_id=resp.get('_response_id'),
                returned_model=resp.get('_returned_model'),cell_id=cell_id,request_body_sha256=resp.get('_request_body_sha256'))
            if '_responses_status' in resp:
                turn_diagnostics[-1]['responses_status'] = resp['_responses_status']
                turn_diagnostics[-1]['responses_usage'] = resp['_responses_usage']

            # A reply cut off by the completion budget never emits a tool call, so
            # it would otherwise be scored as a plain task failure. Record it so
            # the artifact can report how many rows the cap, not the model,
            # decided — and so a cap that biases one condition is visible.
            if choice.get("finish_reason") == "length":
                truncated_turns += 1
                stop_reason='completion_limit'

            if not tool_calls:
                if stop_reason!='completion_limit':stop_reason='model_stop'
                messages.append({"role": "assistant", "content": msg.get("content") or "",
                                 **({'_responses_output': msg['_responses_output']} if '_responses_output' in msg else {})})
                break

            assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or ""}
            if '_responses_output' in msg:
                assistant_msg['_responses_output'] = msg['_responses_output']
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            for call_index, tc in enumerate(tool_calls):
                aci_response=None
                raw_streams = {}
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
                    if observation_store:
                        trajectory[-1]['observation']=observation_store.save(result_text,cell_id=cell_id,
                            call_id=fn_id,op='task_complete',args=fn_args,recorded_at=utc_now())
                    stop_reason='task_complete'
                    break  # exit inner tc loop

                elif condition == "verseshell_aci":
                    # Map LLM tool name (underscore) → AE operation name (dot)
                    ae_op = ACI_OP_MAP.get(fn_name, fn_name)
                    aci_response = execute_aci_op(ae_op, fn_args, str(workspace), caps,
                                                  capture=raw_streams if observation_store else None)
                    result_text = format_aci_result(aci_response)
                    obs_tok = estimate_tokens(result_text)
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": result_text})
                    trajectory.append({
                        "op": ae_op, "args": fn_args,
                        "observation_tokens": obs_tok, "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                        "aci_ok": aci_response.get("ok"),
                        "error_code": (aci_response.get('error') or {}).get('code'),
                    })

                else:  # raw_shell
                    cmd = fn_args.get("command", "")
                    raw_output = execute_shell_cmd(cmd, str(workspace), capture=raw_streams)
                    # The shared observation_store block below reads result_text;
                    # raw_shell must bind it too or the loop dies with
                    # UnboundLocalError on every raw_shell/raw_shell_coached cell.
                    result_text = raw_output
                    obs_tok = estimate_tokens(raw_output)
                    messages.append({"role": "tool", "tool_call_id": fn_id, "content": raw_output})
                    trajectory.append({
                        "op": "run_command", "args": {"command": cmd},
                        "observation_tokens": obs_tok, "condition": condition,
                        "elapsed_ms": int((time.time() - obs_start) * 1000),
                    })

                if observation_store:
                    trajectory[-1]['observation']=observation_store.save(result_text,cell_id=cell_id,
                        call_id=fn_id,op=trajectory[-1]['op'],args=fn_args,envelope=aci_response,
                        raw_streams=raw_streams,recorded_at=utc_now())

                if repeat_call_limit:
                    # Exact repetition is a budget condition, not proof of no filesystem progress.
                    fingerprint = hashlib.sha256(json.dumps([fn_name, fn_args, result_text],
                        sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
                    identical_calls = identical_calls + 1 if fingerprint == previous_call else 1
                    previous_call = fingerprint
                    trajectory[-1]['identical_call_run'] = identical_calls
                    if identical_calls >= repeat_call_limit:
                        stop_reason = 'repeat_call_limit'
                        turn_diagnostics[-1]['tool_calls_skipped_by_repeat_limit'] = len(tool_calls) - call_index - 1
                        break

            if task_completed or stop_reason == 'repeat_call_limit':
                break

    except Exception as e:
        stop_reason='harness_error'
        harness_fault = f"{type(e).__name__}: {e}"
        last_error = f"Loop error: {e}\n{traceback.format_exc()[:500]}"
    finally:
        elapsed_ms = int((time.time() - start_time) * 1000)

    # Capture the exact disposable grading input, not a guessed write trajectory.
    final_workspace = {'state': 'unavailable', 'reason': 'grading input not reached'}
    def capture_final(copy):
        nonlocal final_workspace
        if observation_store is None:
            final_workspace = {'state': 'unavailable', 'reason': 'no persistent observation store'}
            return
        try:
            store = FinalWorkspaceStore(observation_store.directory.parent/'final-workspaces', (api_key,))
            final_workspace = store.capture(copy, cell_id=cell_id, task_id=task['id'],
                                             predicate=task['success'], protected_verifiers=grading_contract)
        except (OSError, ValueError) as error:
            final_workspace = {'state': 'unavailable', 'reason': redact(str(error),(api_key,)),
                               'storage_fault': isinstance(error, OSError)}

    # Snapshot availability and original task scoring are separate observations.
    try:
        actual_ok, actual_reason = guarded_success(task["success"], workspace, grading_contract, check_success,
                                                   before_evaluate=capture_final)
    except Exception as e:
        actual_ok, actual_reason = None, f"unverified: check_error: {e}"
    if final_workspace.get('reason') == 'grading input not reached':
        final_workspace['reason'] = redact(f'grading input not reached: {actual_reason}', (api_key,))

    tool_call_count = len([t for t in trajectory if t.get("op") != "task_complete"])
    observation_tokens = sum(int(t.get("observation_tokens", 0)) for t in trajectory)

    notes = ["live"]
    if last_error:
        notes.append(f"error: {last_error[:200]}")
    if harness_fault:
        notes.append(f"harness_fault: {harness_fault[:160]}")
    if actual_ok is None:
        notes.append(f"verify_unavailable: {actual_reason[:160]}")
    notes.append(f"llm_prompt_tokens={total_prompt_tokens}")
    notes.append(f"llm_completion_tokens={total_completion_tokens}")

    try:
        shutil.rmtree(workspace, ignore_errors=True)
    except Exception:
        pass

    return {
        "task_id": task["id"],
        "cell_id": cell_id,
        "started_at": cell_started_at,
        "finished_at": utc_now(),
        "stop_reason": stop_reason,
        "repeat_call_limit": repeat_call_limit,
        "endpoint_status": endpoint_status,
        "prompt_variant": prompt_variant,
        "protected_verifiers": grading_contract,
        "final_workspace": final_workspace,
        "evidence_storage_fault": bool(final_workspace.get("storage_fault")),
        "usage_complete": usage_complete,
        "reported_llm_prompt_tokens": total_prompt_tokens,
        "reported_llm_completion_tokens": total_completion_tokens,
        "condition": condition,
        "prompt_profile": prompt_profile,
        "workspace_build_environment": {
            "policy": "workspace_local_default",
            "cargo_target_dir": grading_environment(workspace)["CARGO_TARGET_DIR"],
            "parent_target_present": bool(os.environ.get("CARGO_TARGET_DIR")),
            "full_environment_captured": False,
            "scope": "configured default for child tools; commands may explicitly override it",
        },
        "model": model,
        "run_index": run_index,
        "success": actual_ok,
        "success_reason": actual_reason,
        "tool_calls": tool_call_count,
        "observation_tokens": observation_tokens,
        "elapsed_ms": elapsed_ms,
        "notes": notes,
        "trajectory": trajectory,
        # Recorded explicitly instead of `None`: the live runner never executes
        # `optional_verify`, so a task whose score must depend on behaviour has to
        # declare that command in `success`.
        "optional_verify": {
            "ran": False,
            "declared": task.get("optional_verify"),
            "note": "the live runner does not execute optional_verify; behaviour-based "
                    "scoring must be declared in `success`",
        },
        "verify_unavailable": actual_ok is None,
        "weight": float(task.get("weight", 1.0)),
        "agent_declared_success": agent_declared_success,
        "llm_prompt_tokens": total_prompt_tokens if usage_complete else None,
        "llm_completion_tokens": total_completion_tokens if usage_complete else None,
        "turns": turn,
        "completion_truncated_turns": truncated_turns,
        # P0-1 diagnostic surface. Additive: the key is absent from older rows and
        # every consumer still reads rows with `.get`, so no consumer is required to
        # know about it. Per turn it holds exactly what the endpoint returned; a
        # field the endpoint did not send is listed in that turn's `fields_missing`
        # instead of being inferred from token counts.
        "turn_diagnostics": turn_diagnostics,
        "last_error": last_error,
        "api_error": api_error,
        # Explicit harness-fault record. `harness_crash` is true only when the harness
        # died before producing any tool result at all — that is the shape that used to
        # be silently averaged in as a task failure.
        "harness_fault": harness_fault,
        "harness_crash": bool(harness_fault) and not trajectory,
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
    variants = {r.get('prompt_variant', 'baseline') for r in rows}
    if len(variants) > 1:
        return {'aggregates': [], 'n_rows': len(rows), 'by_prompt_variant': {
            v: aggregate([r for r in rows if r.get('prompt_variant', 'baseline') == v]) for v in sorted(variants)},
            'note': 'mixed variants are not pooled; select a variant for a report'}
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        key = f"{r.get('model', 'live')}::{r['condition']}"
        by_key.setdefault(key, []).append(r)
    table = []
    for key, items in sorted(by_key.items()):
        n = len(items)
        # An unverified row (`success is None`) is excluded from the success rate:
        # the check could not run, so it is not evidence about capability.
        scored = [x for x in items if x.get("success") is not None]
        wsum = sum(float(x.get("weight", 1.0)) for x in scored) or 1.0
        succ_w = sum(float(x.get("weight", 1.0)) for x in scored if x.get("success"))
        tools = sum(x.get("tool_calls", 0) for x in items) / max(n, 1)
        toks = sum(x.get("observation_tokens", 0) for x in items) / max(n, 1)
        elapsed = sum(x.get("elapsed_ms", 0) for x in items) / max(n, 1)
        model, condition = key.split("::", 1)
        table.append({
            "model": model, "condition": condition, "tasks": n,
            "success_rate": round(succ_w / wsum, 4) if scored else None,
            "scored_rows": len(scored),
            "unverified_rows": n - len(scored),
            "avg_tool_calls": round(tools, 2),
            "avg_observation_tokens": round(toks, 2),
            "avg_elapsed_ms": round(elapsed, 1),
        })
    return {"aggregates": table, "n_rows": len(rows)}


def compare_a_vs_d(rows: list[dict], *, context: dict | None = None) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
    from live_uncertainty import single_collection_verdict
    context = context or {}
    cap = (context.get('live_config') or {}).get('max_turns')
    variants = {r.get('prompt_variant', 'baseline') for r in rows}
    if len(variants) > 1:
        return {'comparisons': [], 'claimable': False,
                'acceptance_scope': 'single_collection_diagnostic', 'by_prompt_variant': {
            v: compare_a_vs_d([r for r in rows if r.get('prompt_variant', 'baseline') == v],
                              context=context) for v in sorted(variants)}}
    from collections import defaultdict

    by_model: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_model[r.get("model", "live")][r["condition"]].append(r)

    comparisons = []
    for model, conds in sorted(by_model.items()):
        d = conds.get("verseshell_aci") or []
        if not d:
            continue

        def rate(items: list[dict]) -> float | None:
            # Unverified rows are excluded: the check could not run at all.
            scored = [x for x in items if x.get("success") is not None]
            if not scored:
                return None
            w = sum(float(x.get("weight", 1.0)) for x in scored) or 1.0
            return sum(float(x.get("weight", 1.0)) for x in scored if x.get("success")) / w

        def avg(items: list[dict], key: str) -> float:
            return sum(x.get(key, 0) for x in items) / max(len(items), 1)

        # Two contrasts:
        #   D_over_A         D vs the neutral shell baseline (the status quo)
        #   D_over_A_coached D vs the prompt-matched shell baseline (claim C1).
        # Only the second one can attribute a difference to the INTERFACE, because
        # both arms were briefed with equal detail. The first one mixes in the
        # prompt-quality difference.
        for baseline, contrast in (("raw_shell", "D_over_A"),
                                   ("raw_shell_coached", "D_over_A_coached")):
            a = conds.get(baseline) or []
            if not a:
                continue
            ra, rd = rate(a), rate(d)
            ta, td = avg(a, "tool_calls"), avg(d, "tool_calls")
            oa, od = avg(a, "observation_tokens"), avg(d, "observation_tokens")
            comparisons.append({
                "model": model,
                "contrast": contrast,
                "baseline_condition": baseline,
                "success_rate_A": round(ra, 4) if ra is not None else None,
                "success_rate_D": round(rd, 4) if rd is not None else None,
                "success_advantage_D": round(rd - ra, 4) if ra is not None and rd is not None else None,
                "avg_tool_calls_A": round(ta, 2), "avg_tool_calls_D": round(td, 2),
                "tool_call_ratio_D_over_A": round(td / ta, 4) if ta else None,
                "avg_observation_tokens_A": round(oa, 2), "avg_observation_tokens_D": round(od, 2),
                "token_ratio_D_over_A": round(od / oa, 4) if oa else None,
                "descriptive_advantage": bool(
                    (ra is not None and rd is not None and rd > ra) or (td < ta * 0.7) or (od < oa * 0.6)
                ),
                **single_collection_verdict(a + d, baseline, cap,
                    partial=bool(context.get('partial')),
                    synthetic=bool(context.get('synthetic_test_only'))),
            })
    return {"comparisons": comparisons, "claimable": False,
            "acceptance_scope": "single_collection_diagnostic",
            "policy_blocked_reasons": sorted({reason for c in comparisons
                for reason in c['policy_blocked_reasons']}) if comparisons else ['no_comparable_arms']}


def write_report(payload: dict, path: Path) -> None:
    rows = payload.get("rows", [])
    agg = aggregate(rows)
    cmp_ = compare_a_vs_d(rows, context=payload)

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
    blocks = cmp_.get('by_prompt_variant', {'selected': cmp_})
    lines += ['**NOT CLAIMABLE** — single-collection diagnostics; not formal acceptance.', '']
    for variant, c in ((variant, c) for variant, block in blocks.items()
                       for c in block.get('comparisons', [])):
        verdict = "**NOT CLAIMABLE** (single-collection diagnostic)"
        lines += [
            f"### {c['model']} / {variant} / {c['baseline_condition']} → {verdict}",
            f"- Descriptive advantage (old OR): {c['descriptive_advantage']}",
            f"- Refusal reasons: {', '.join(c['policy_blocked_reasons'])}",
            "",
            f"| Metric | Raw Shell (A) | VerseShell ACI (D) | Ratio (D/A) |",
            "|---|---|---:|---:|",
            f"| Success rate | {c['success_rate_A']} | {c['success_rate_D']} | — |",
            f"| Avg tool calls | {c['avg_tool_calls_A']} | {c['avg_tool_calls_D']} | {c['tool_call_ratio_D_over_A']} |",
            f"| Avg observation tokens | {c['avg_observation_tokens_A']} | {c['avg_observation_tokens_D']} | {c['token_ratio_D_over_A']} |",
            "| Formal acceptance | — | — | **NOT CLAIMABLE** |",
            "",
        ]
    lines += ["## Per-Task Trajectories", ""]
    for r in rows:
        status = success_verdict(r["success"])
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
        "- Descriptive advantage only: D success > A success, OR D tool_calls < 70% of A, OR D obs_tokens < 60% of A",
        "- Formal claims require tools/study_inference.py with a frozen plan, calibrated multiplicity and complete independent repeats.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


# ── Main ──

def _main(argv: list[str] | None = None, observer=None) -> int:
    ap = argparse.ArgumentParser(description="VerseShell ACI-Bench Live Agent Runner")
    ap.add_argument("--tasks", default="", help="Comma-separated task ids")
    ap.add_argument("--conditions", default="raw_shell,verseshell_aci")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--api-key", default=DEFAULT_API_KEY)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--out", default=str(RESULTS / "latest_live.json"))
    ap.add_argument('--task-set',type=Path,default=None)
    ap.add_argument('--prompt-variant',choices=['baseline','compact','compact_all','shell_guided','shell_safe'],default='baseline')
    ap.add_argument('--schedule', type=Path, help='frozen balanced variant schedule')
    ap.add_argument('--analysis-plan',type=Path)
    ap.add_argument('--resume-paused',action='store_true',help='explicitly resume after addressing the recorded pause')
    ap.add_argument("--collection-id", default="", help="identity of one frozen collection")
    ap.add_argument("--dry-run", action="store_true", help="write a frozen plan without endpoint calls")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore and delete any existing checkpoint sidecar for --out "
                         "(default: resume the rows already recorded)")
    ap.add_argument("--max-turns", type=int, default=MAX_TURNS)
    ap.add_argument("--max-tokens", type=int, default=MAX_COMPLETION_TOKENS,
                    help="completion budget per turn; must exceed the reasoning "
                         "model's reasoning_content or no tool call is emitted")
    ap.add_argument('--repeat-call-limit', type=int, default=0,
                    help='stop after N identical consecutive tool calls and observations; 0 disables, N >= 2')
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
    try:validate_repeat_call_limit(args.repeat_call_limit)
    except ValueError as error:ap.error(str(error))
    exclude_tools = tuple(t.strip() for t in args.exclude_tools.split(",") if t.strip())

    manifest, task_specs = load_tasks(TASKS_DIR,args.task_set)
    all_tasks = manifest.get("tasks", [])

    if args.tasks:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    elif args.full:
        task_ids = all_tasks
    else:
        task_ids = ["rust_fix_compile_error", "python_fix_pytest_fail", "windows_path_normalize_edit"]

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    if not conditions or len(conditions) != len(set(conditions)) or set(conditions) - {'raw_shell','raw_shell_coached','verseshell_aci'}:
        ap.error('invalid/duplicate conditions')
    if not task_ids or len(task_ids) != len(set(task_ids)):
        ap.error('invalid/duplicate tasks')

    api_key = args.api_key or DEFAULT_API_KEY
    if not api_key and not args.dry_run:
        print("ERROR: No API key.", file=sys.stderr)
        return 1
    if not AE.exists():
        print(f"ERROR: ae not found at {AE}", file=sys.stderr)
        return 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"Model: {args.model} | Tasks: {len(task_ids)} | Conditions: {conditions} | Max turns: {args.max_turns}")
    print("=" * 60)

    # ── incremental checkpointing ──────────────────────────────────────────────
    # The output used to be written only after the WHOLE matrix finished, so one
    # wedged command cost every row already completed (2026-09-27: 61 finished rows
    # were lost when a D-arm `open('CON','r')` hung the round).  Every completed row
    # is now appended to a sidecar JSONL immediately, and a re-run with the same
    # `--out` resumes: cells already recorded are skipped.  The sidecar carries a
    # config header, so resuming under different settings is rejected instead of
    # silently mixing two configurations.
    out_path = Path(args.out)
    sidecar = out_path.with_name(out_path.name + ".rows.jsonl")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    identity = {
        "model": args.model, "api_base": args.base_url, "seeds": [args.seed],
        "protocol": "responses" if args.base_url.rstrip('/').endswith('/responses') else "chat_completions",
        "max_turns": args.max_turns, "max_tokens": args.max_tokens,
        "repeat_call_limit": args.repeat_call_limit,
        "temperature": args.temperature, "conditions": list(conditions),
        "repeat": args.repeat, "exclude_tools": list(exclude_tools),
        "tasks": task_ids, "caps": args.caps,
        "collection_id": args.collection_id or str(out_path.resolve()),
        "task_set_version": manifest.get("task_set_version"),
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "storage_reserves": storage_policy(),
        "binary_sha256": hashlib.sha256(AE.read_bytes()).hexdigest(),
        "git_rev": current_git_rev(),
        "schedule_policy": "rotate_conditions_by_task_and_seed/v1",
        "task_set": str(args.task_set.resolve()) if args.task_set else None,
        "prompt_variant": args.prompt_variant,
        "retry_policy": {'http_attempts':3,'request_budget_seconds':API_TIMEOUT_SEC,'backoff_seconds':[1,2],
                         'fatal_http':[401,402,403],'consecutive_failed_cells':3,'interrupted_cell_attempts':3},
    }
    if set(task_ids) - set(task_specs):
        ap.error('unknown task requested')
    if args.analysis_plan:
        sys.path.insert(0,str(ROOT/'tools'))
        from study_inference import read_plan
        read_plan(args.analysis_plan)
        identity['analysis_plan_sha256']=hashlib.sha256(args.analysis_plan.read_bytes()).hexdigest()
    schedule = None
    if args.schedule:
        from live_schedule import validate_schedule, digest as schedule_digest
        schedule = validate_schedule(json.loads(args.schedule.read_text(encoding='utf-8')))
        if (schedule['tasks'] != task_ids or schedule['conditions'] != conditions
                or args.seed not in schedule['seeds'] or schedule['repeat'] != args.repeat):
            ap.error('schedule task/condition/seed/repeat mismatch')
        identity.update(prompt_variants=schedule['variants'], schedule_sha256=schedule_digest(schedule),
                        schedule_policy='balanced_treatment_rotation/v1')
    if args.dry_run:
        if out_path.exists():
            try:previous_plan=json.loads(out_path.read_text(encoding='utf-8'))
            except ValueError:previous_plan={}
            if not isinstance(previous_plan,dict) or set(previous_plan)!={'run_identity'}:
                print('ERROR: dry-run will not overwrite an existing result',file=sys.stderr);return 2
        atomic_json(out_path,{'run_identity': identity})
        print(f"dry-run plan: {out_path}")
        return 0
    if args.fresh and (sidecar.exists() or out_path.exists()):
        print('ERROR: --fresh cannot erase existing evidence; choose a new output',file=sys.stderr)
        return 2
    if out_path.exists() and not sidecar.exists():
        print('ERROR: existing output has no matching checkpoint; choose a new output',file=sys.stderr)
        return 2
    rows: list[dict] = []
    if sidecar.exists() and sidecar.stat().st_size > 0:
        try:
            prior = [json.loads(ln) for ln in
                     sidecar.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception as exc:
            print(f"ERROR: unreadable checkpoint {sidecar.name}: {exc}; preserved", file=sys.stderr)
            return 2
        head = prior[0].get("_config") if prior and isinstance(prior[0], dict) else None
        if head == identity:
            rows = [r for r in prior if isinstance(r, dict) and "_config" not in r]
            try:
                validate_rows(rows, identity, complete=False)
            except ValueError as exc:
                print(f"ERROR: invalid checkpoint: {exc}", file=sys.stderr)
                return 2
            print(f"resuming from {sidecar.name}: {len(rows)} row(s) already recorded")
        else:
            print(f"ERROR: {sidecar.name} has missing/different frozen identity; use a new output", file=sys.stderr)
            return 2
    resumed_keys = {(r.get("task_id"), r.get("condition"), r.get("run_index"), r.get("prompt_variant", args.prompt_variant)) for r in rows}
    pause_path=out_path.with_name(out_path.name+'.pause.json')
    storage = storage_check(identity['storage_reserves'])
    if not storage['ok']:
        atomic_json(out_path.parent/'STOP', {'reason': 'storage_reserve', **storage, 'at': utc_now()})
        atomic_json(pause_path, {'blocked': True, 'reason': 'storage_reserve', **storage, 'at': utc_now()})
        return 75
    if pause_path.exists():
        pause=json.loads(pause_path.read_text(encoding='utf-8'))
        if pause.get('blocked') and not args.resume_paused:
            print('PAUSED: address recorded fault, then use --resume-paused',file=sys.stderr)
            return 75
        if pause.get('blocked'):
            if pause.get('reason')=='operator_stop':
                marker=out_path.with_name(out_path.name+'.stop')
                if marker.exists():marker.replace(marker.with_name(marker.name+'.acknowledged-'+uuid.uuid4().hex))
            pause.update(blocked=False,resumed_at=utc_now());atomic_json(pause_path,pause)
    attempt_path=out_path.with_name(out_path.name+'.attempts.json')
    history=json.loads(attempt_path.read_text(encoding='utf-8')) if attempt_path.exists() else {'run_identity':identity,'attempts':[]}
    if history.get('run_identity')!=identity:
        print('ERROR: attempt history belongs to another candidate',file=sys.stderr);return 2
    for previous in history['attempts']:
        if previous['state']=='started':
            previous['state']='recorded' if any(r.get('cell_id')==previous['cell_id'] for r in rows) else 'interrupted'
    store=ObservationStore(out_path.with_name(out_path.name+'.observations'),(api_key,))

    def save_checkpoint():
        atomic_text(sidecar,'\n'.join(json.dumps(r,ensure_ascii=False) for r in [{'_config':identity},*rows])+'\n')
    save_checkpoint();atomic_json(attempt_path,history)
    if any(a.get('state') == 'interrupted' and not any(r.get('cell_id') == a.get('cell_id') for r in rows)
           for a in history['attempts']) and not args.resume_paused:
        atomic_json(pause_path, {'blocked': True, 'reason': 'interrupted_attempt_outcome_unknown', 'at': utc_now()})
        print('PAUSED: interrupted request outcome unknown; explicit resume required', file=sys.stderr)
        return 75

    def record(row: dict) -> None:
        """Append a completed row to memory AND to the checkpoint, immediately."""
        row['seed'] = args.seed
        row['collection_id'] = identity['collection_id']
        row=dict(row);changed=False
        for field in ('trajectory','notes','last_error','harness_fault','success_reason','turn_diagnostics','optional_verify'):
            if field in row:
                text=json.dumps(row[field],ensure_ascii=False);clean=redact(text,(api_key,))
                row[field]=json.loads(clean);changed=changed or clean!=text
        row['evidence_redacted']=changed
        rows.append(row)
        save_checkpoint()

    def pause_at_boundary():
        storage = storage_check(identity['storage_reserves'])
        if not storage['ok']:
            atomic_json(out_path.parent/'STOP', {'reason': 'storage_reserve', **storage, 'at': utc_now()})
            atomic_json(pause_path, {'blocked': True, 'reason': 'storage_reserve', **storage, 'at': utc_now()})
            return True
        if out_path.with_name(out_path.name+'.stop').exists() or (out_path.parent/'STOP').exists():
            atomic_json(pause_path, {'blocked': True, 'reason': 'operator_stop', 'at': utc_now()})
            return True
        return False

    if schedule:
        planned_cells = [(t, c, i, v) for t, c, seed, i, v in schedule['cells'] if seed == args.seed]
    else:
        planned_cells = []
        for position, tid in enumerate(task_ids):
            rotation = (position + (args.seed or 0)) % len(conditions)
            for cond in conditions[rotation:] + conditions[:rotation]:
                planned_cells.extend((tid, cond, i, args.prompt_variant) for i in range(args.repeat))
    total = len(planned_cells)
    done = 0
    consecutive_errors = 0
    for tid, cond, run_index, variant in planned_cells:
        task = task_specs[tid]
        if (evidence_fingerprint(EVIDENCE_GLOBS) != identity['evidence']['fingerprint']
                or hashlib.sha256(AE.read_bytes()).hexdigest() != identity['binary_sha256']):
            print('ERROR: candidate changed during collection; checkpoint preserved', file=sys.stderr)
            return 2
        done += 1
        if (tid, cond, run_index, variant) in resumed_keys:
            print(f"\n[{done}/{total}] {tid} [{cond}] run={run_index} ... "
                  f"already in checkpoint", flush=True)
            continue
        print(f"\n[{done}/{total}] {tid} [{cond}] run={run_index} ...", flush=True)
        if pause_at_boundary():
            return 75
        cell_id=hashlib.sha256(json.dumps([identity,tid,cond,run_index,variant],sort_keys=True).encode()).hexdigest()
        if sum(a.get('cell_id') == cell_id for a in history['attempts']) >= 3:
            atomic_json(pause_path, {'blocked': True, 'reason': 'cell_attempt_budget_exhausted', 'cell_id': cell_id, 'at': utc_now()})
            return 75
        attempt={'cell_id':cell_id,'attempt_id':uuid.uuid4().hex,'task_id':tid,'condition':cond,'prompt_variant':variant,
                 'state':'started','started_at':utc_now()}
        history['attempts'].append(attempt);atomic_json(attempt_path,history)
        if observer:observer.update(cell_id=cell_id,task_id=tid,condition=cond,completed=len(rows),planned=total,cell_started_at=attempt['started_at'])
        t0 = time.time()
        try:
            row = run_agent_loop(task, cond, model=args.model, api_key=api_key,
                                 base_url=args.base_url, max_turns=args.max_turns,
                                 max_tokens=args.max_tokens,
                                 caps=args.caps, temperature=args.temperature,
                                 seed=args.seed, run_index=run_index,
                                 exclude_tools=exclude_tools,observation_store=store,
                                 cell_id=cell_id,prompt_variant=variant,repeat_call_limit=args.repeat_call_limit)
            wall = int((time.time() - t0) * 1000)
            status = success_verdict(row["success"])
            print(f"  -> {status}: {row['tool_calls']} tools, {row['observation_tokens']} obs_tok, "
                  f"wall={wall}ms, turns={row['turns']}")
            if row.get("last_error"):
                print(f"  !! {row['last_error'][:200]}")
        except Exception as e:
            print(f"  -> RUNNER ERROR: {e}")
            traceback.print_exc()
            row={
                "task_id": tid, "condition": cond, "model": args.model,
                "run_index": run_index,
                "success": False, "success_reason": f"runner_error: {e}",
                "tool_calls": 0, "observation_tokens": 0, "elapsed_ms": 0,
                "notes": ["runner_crash"], "trajectory": [], "weight": 1.0,
                'harness_fault':redact(str(e),(api_key,)),
                'repeat_call_limit':args.repeat_call_limit,
            }
        row.update(cell_id=cell_id,attempt_id=attempt['attempt_id'],prompt_variant=variant)
        prior_interruptions=sum(a.get('cell_id')==cell_id and a.get('state')=='interrupted' for a in history['attempts'])
        if prior_interruptions:
            row.update(raw_success=row.get('success'),success=None,recovery_uncertain=True,
                       usage_complete=False,measurement_complete=False,interrupted_attempts=prior_interruptions,
                       recovery_note='earlier attempt outcome and billed usage unknown; recovery is diagnostic only')
        record(row)
        attempt.update(state='recorded',finished_at=utc_now(),api_error=bool(row.get('api_error')))
        atomic_json(attempt_path,history)
        if observer:observer.update(completed=len(rows),last_completed_at=utc_now())
        consecutive_errors=consecutive_errors+1 if row.get('api_error') else 0
        if row.get('endpoint_status') in (401,402,403) or consecutive_errors>=3 or row.get('harness_fault') or row.get('evidence_storage_fault'):
            atomic_json(pause_path,{'blocked':True,'reason':'evidence_storage_fault' if row.get('evidence_storage_fault') else 'endpoint_or_harness_fault','at':utc_now(),
                                   'http_status':row.get('endpoint_status'),'cell_id':cell_id})
            print('PAUSED: fault recorded; no further cells dispatched',file=sys.stderr)
            return 75

    # The last cell (or a checkpoint-only resume) has no next dispatch to check.
    if pause_at_boundary():
        return 75

    comparison = compare_a_vs_d(rows)
    payload = {
        "schema": "verseshell.aci_bench.results/v1",
        "task_set_version": manifest.get("task_set_version"),
        "seed": manifest.get("seed"),
        "mode": "live",
        "partial": any(r.get('api_error') or r.get('harness_fault') or r.get('recovery_uncertain') for r in rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": identity['git_rev'],
        "evidence": identity['evidence'],
        "run_identity": identity,
        "live_config": {
            **({'analysis_plan_sha256':identity['analysis_plan_sha256']} if args.analysis_plan else {}),
            'task_set':identity['task_set'],'prompt_variant':args.prompt_variant,
            **({k: identity[k] for k in ('prompt_variants', 'schedule_sha256')} if schedule else {}),
            'retry_policy':identity['retry_policy'],
            'storage_reserves':identity['storage_reserves'],
            "protocol": identity['protocol'],
            "collection_id": identity['collection_id'],
            "seed_sent_to_endpoint": identity['protocol'] == 'chat_completions',
            "model": args.model,
            "api_base": args.base_url,
            "caps": args.caps,
            "max_turns": args.max_turns,
            "max_tokens": args.max_tokens,
            "repeat_call_limit": args.repeat_call_limit,
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

    comparison = compare_a_vs_d(rows, context=payload)
    payload['comparison'] = comparison
    out_path = Path(args.out)
    if args.repeat:
        try:
            if (evidence_fingerprint(EVIDENCE_GLOBS) != identity['evidence']['fingerprint']
                    or hashlib.sha256(AE.read_bytes()).hexdigest() != identity['binary_sha256']):
                raise ValueError('candidate changed during final cell')
            validate_rows(rows, identity, complete=True)
        except ValueError as exc:
            print(f'ERROR: {exc}; checkpoint preserved, final output not written', file=sys.stderr)
            return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(out_path,payload)
    print(f"\nwrote {out_path}")

    report_path = (RESULTS / "live_REPORT.md"
                   if out_path.resolve() == (RESULTS / "latest_live.json").resolve()
                   else out_path.with_suffix(".md"))
    write_report(payload, report_path)
    print(f"wrote {report_path}")

    print("\n=== A vs D Comparison ===")
    blocks = comparison.get('by_prompt_variant', {'selected': comparison})
    for variant, c in ((v, c) for v, block in blocks.items() for c in block['comparisons']):
        print(
            f"[{c['model']}/{variant}/{c['baseline_condition']}] "
            f"success: A={c['success_rate_A']} D={c['success_rate_D']} "
            f"tools: A={c['avg_tool_calls_A']} D={c['avg_tool_calls_D']} (ratio={c['tool_call_ratio_D_over_A']}) "
            f"tokens: A={c['avg_observation_tokens_A']} D={c['avg_observation_tokens_D']} (ratio={c['token_ratio_D_over_A']}) "
            f"descriptive_advantage={c['descriptive_advantage']} accept=NOT_CLAIMABLE "
            f"reasons={c['policy_blocked_reasons']}"
        )

    return 0


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '-h' in args or '--help' in args:return _main(args)
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--out',default=str(RESULTS/'latest_live.json'))
    known,_=parser.parse_known_args(args)
    try:
        with RunStatus(Path(known.out).with_name(Path(known.out).name+'.status.json')) as observer:
            code=_main(args,observer)
            observer.update(state=('planned' if '--dry-run' in args else 'completed') if code==0 else ('paused' if code==75 else 'failed'),
                            exit_code=code,finished_at=utc_now())
            return code
    except RuntimeError as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2


if __name__ == "__main__":
    sys.exit(main())
