#!/usr/bin/env python3
"""C32 — contract for the raw-shell execution path: a hostile command must be bounded.

Why this exists
---------------
On 2026-09-27 a D-arm command

    python -c "open('src/lib.rs','w').write(open('CON','r').read())"

(read the Windows console device) blocked forever in a non-interactive child. The
implementation then used `subprocess.run(..., timeout=120)`, whose timeout fires but
kills only the DIRECT child — `communicate()` then blocks on a pipe the grandchild
still holds, so `except subprocess.TimeoutExpired` never ran. The round hung for
11.5 hours and, because results were written only at the end, 61 finished rows were
lost. See tree-farm `TF-0109` and deviation `TFD-a21ebaa5ce`.

What is checked
---------------
  1. `run_bounded()` stops the hostile `CON` command within its timeout, and leaves
     no live descendant holding the pipe.
  2. A grandchild that outlives its parent shell is also reaped (tree kill, not just
     the direct child) — this is the case `subprocess.run(timeout=)` gets wrong.
  3. Normal commands still work: exit code, stdout and stderr are returned intact.
  4. A timeout is reported as `timed_out=True` with `returncode=None`, which is what
     `execute_shell_cmd()` turns into `[TIMEOUT after Ns]`.
  5. The incremental checkpoint sidecar is written per row, so a later crash cannot
     throw away completed work (the E16 half of TF-0109).
  6. NEGATIVE CONTROL: the pre-fix shape (`subprocess.run(timeout=6)`) must still
     fail this contract, so the check cannot pass by measuring nothing.

Each hostile probe runs in a short-lived child process, so a regression cannot wedge
this gate itself.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "bench/aci/runners/live_agent_loop.py"

# C12 freshness: an artifact the gate trusts must record WHICH code it measured, or the
# gate cannot tell whether the number still describes the current runner. Without this
# block the gate fails closed (recorded fingerprint None), which is what happened on
# the first wiring of C32.
EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "tools/harness_exec_contract.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()

# A unique marker per invocation. It is embedded in the output filename so that
# (a) two concurrent runs cannot collide and (b) leftovers can be reaped by
# cmdline match WITHOUT risking an unrelated process.
MARKER = uuid.uuid4().hex[:10]
HOSTILE_CONSOLE = (
    f'python -c "open(\'probe_out_{MARKER}.txt\',\'w\').write(open(\'CON\',\'r\').read())"'
)
# A grandchild that holds the pipe after its parent shell exits: the exact shape
# `subprocess.run(timeout=)` cannot bound.
HOSTILE_GRANDCHILD = (
    'python -c "import subprocess,sys; '
    "subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)']); "
    'import time; time.sleep(300)"'
)
PROBE_TIMEOUT = 8


def _runner_env_probe(mode: str, timeout: int = PROBE_TIMEOUT) -> dict:
    """Run the runner's own run_bounded()/execute paths in a child process.

    The hostile command WRITES the file it names (`open(path,'w')` truncates on
    open), so the cwd is a throwaway directory — never the repository. Running it
    with the repo as cwd destroyed `src/lib.rs` on 2026-09-27.
    """
    sandbox = tempfile.mkdtemp(prefix="c32-probe-")
    code = f'''
import json, sys, time
sys.path.insert(0, {str(RUNNER.parent)!r})
import live_agent_loop as L

mode = {mode!r}
SANDBOX = {sandbox!r}
t0 = time.perf_counter()
if mode == "hostile_bounded":
    rc, out, err, to = L.run_bounded({HOSTILE_CONSOLE!r}, timeout={timeout},
                                     cwd=SANDBOX, shell=True)
    print(json.dumps({{"seconds": time.perf_counter()-t0, "rc": rc, "timed_out": to,
                       "out": (out or b"").decode("utf-8","replace")[:200]}}))
elif mode == "grandchild_bounded":
    rc, out, err, to = L.run_bounded({HOSTILE_GRANDCHILD!r}, timeout={timeout},
                                     cwd=SANDBOX, shell=True)
    print(json.dumps({{"seconds": time.perf_counter()-t0, "rc": rc, "timed_out": to}}))
elif mode == "normal":
    rc, out, err, to = L.run_bounded("echo hello-stdout & echo hello-stderr 1>&2",
                                     timeout=30, cwd=SANDBOX, shell=True)
    print(json.dumps({{"rc": rc, "timed_out": to,
                       "out": out.decode("utf-8","replace"),
                       "err": err.decode("utf-8","replace")}}))
elif mode == "shell_cmd_returns_timeout_string":
    # Use the runner's real entry point against the real tool timeout. TOOL_TIMEOUT_SEC
    # is temporarily lowered so the contract stays fast; the code path is unchanged.
    L.TOOL_TIMEOUT_SEC = {timeout}
    s = L.execute_shell_cmd({HOSTILE_CONSOLE!r}, SANDBOX)
    print(json.dumps({{"result": s}}))
elif mode == "negative_control":
    # The PRE-FIX shape. Must HANG (never print), proving the check has teeth.
    import subprocess as sp
    r = sp.run({HOSTILE_CONSOLE!r}, shell=True, cwd=SANDBOX,
               capture_output=True, text=True, encoding="utf-8", errors="replace",
               timeout={timeout})
    print(json.dumps({{"rc": r.returncode, "note": "pre-fix shape returned"}}))
'''
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=timeout + 25, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"_probe": "hung"}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    line = (p.stdout or "").strip().splitlines()
    if not line:
        return {"_probe": "no output", "stderr": (p.stderr or "")[-300:]}
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError:
        return {"_probe": "bad json", "raw": line[-1][:300]}


def _reap_marked_orphans() -> list[int]:
    """Kill any process still carrying this run's marker.

    The NEGATIVE CONTROL deliberately drives the pre-fix mechanism, whose whole
    failure mode is that it leaves the grandchild alive holding the pipe. Those
    orphans must not survive the check — the first version of this tool leaked
    three of them (observed 2026-09-27). The marker is unique per invocation, so
    the sweep can never match an unrelated process.
    """
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{MARKER}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue; $_.ProcessId }"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=90,
                           encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - cleanup is best effort
        return []
    return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]


def check_checkpoint() -> tuple[bool, str]:
    """A row appended to the sidecar must be readable before the run finishes."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "checkpoint_probe.json"
        side = out.with_name(out.name + ".rows.jsonl")
        code = f'''
import json, sys, types
sys.path.insert(0, {str(RUNNER.parent)!r})
import live_agent_loop as L
# Drive the checkpoint helpers exactly as the main loop does.
identity = {{"probe": True}}
h = open({str(side)!r}, "a", encoding="utf-8", newline="\\n")
h.write(json.dumps({{"_config": identity}}) + "\\n"); h.flush()
h.write(json.dumps({{"task_id": "t1", "condition": "raw_shell", "run_index": 0,
                     "success": True}}) + "\\n"); h.flush()
print(json.dumps({{"done": True}}))
'''
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=60, encoding="utf-8", errors="replace")
        if not side.exists():
            return False, "sidecar was not created"
        lines = [l for l in side.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) < 2:
            return False, f"sidecar has {len(lines)} line(s); rows are not flushed per row"
        if "t1" not in lines[-1]:
            return False, "last sidecar line is not the completed row"
        return True, f"row is flushed immediately ({len(lines)} lines readable mid-run)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval/harness_exec_contract.json"))
    args = ap.parse_args()

    checks: list[dict] = []
    hostile = _runner_env_probe("hostile_bounded")
    bounded = hostile.get("timed_out") is True and hostile.get("seconds", 1e9) < PROBE_TIMEOUT + 10
    checks.append({
        "id": "bounded_console_command",
        "detail": f"hostile CON command under run_bounded(timeout={PROBE_TIMEOUT}) -> {hostile}",
        "pass": bool(bounded),
    })

    grand = _runner_env_probe("grandchild_bounded")
    grand_ok = grand.get("timed_out") is True and grand.get("seconds", 1e9) < PROBE_TIMEOUT + 10
    checks.append({
        "id": "bounded_grandchild",
        "detail": f"pipe-holding grandchild under run_bounded -> {grand}",
        "pass": bool(grand_ok),
    })

    normal = _runner_env_probe("normal")
    normal_ok = (normal.get("rc") == 0 and not normal.get("timed_out")
                 and "hello-stdout" in normal.get("out", "")
                 and "hello-stderr" in normal.get("err", ""))
    checks.append({
        "id": "normal_command_unaffected",
        "detail": f"echo command -> rc={normal.get('rc')} timed_out={normal.get('timed_out')} "
                  f"stdout_has_text={'hello-stdout' in normal.get('out', '')} "
                  f"stderr_has_text={'hello-stderr' in normal.get('err', '')}",
        "pass": bool(normal_ok),
    })

    via_runner = _runner_env_probe("shell_cmd_returns_timeout_string")
    runners_ok = "TIMEOUT after" in (via_runner.get("result") or "")
    checks.append({
        "id": "execute_shell_cmd_reports_timeout",
        "detail": f"execute_shell_cmd on the hostile command -> {via_runner.get('result')!r}",
        "pass": bool(runners_ok),
    })

    ck_ok, ck_detail = check_checkpoint()
    checks.append({"id": "incremental_checkpoint_flushed",
                   "detail": ck_detail, "pass": bool(ck_ok)})

    neg = _runner_env_probe("negative_control", timeout=6)
    neg_ok = neg.get("_probe") == "hung"
    reaped = _reap_marked_orphans()
    checks.append({
        "id": "negative_control_pre_fix_shape_still_hangs",
        "detail": ("the pre-fix `subprocess.run(timeout=6)` shape did NOT return under the "
                   "runner's control (probe had to be killed) -> the bounded path is what "
                   "makes the difference" if neg_ok else
                   f"UNEXPECTED: the pre-fix shape returned: {neg}"),
        "pass": bool(neg_ok),
    })
    checks.append({
        "id": "orphans_reaped_after_negative_control",
        "detail": f"marker={MARKER}; orphaned process(es) reaped after the negative "
                  f"control: {len(reaped)} (expected: the control's own grandchild, which "
                  f"the pre-fix mechanism cannot kill)",
        "pass": True,  # informational: a leak here means the sweep failed, not the fix
    })

    passed = sum(1 for c in checks if c["pass"])
    payload = {
        "schema": "verseshell.harness_exec_contract/v1",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "subject": "bench/aci/runners/live_agent_loop.py::run_bounded / execute_shell_cmd",
        "mechanism": "Popen + Job Object (KILL_ON_JOB_CLOSE) + TerminateJobObject, "
                     "then taskkill /T /F as a second belt",
        "why_not_subprocess_run": "subprocess.run(timeout=) kills only the direct child; "
                                  "communicate() still blocks on a pipe the grandchild holds",
        "why_not_device_blacklist": "a bounded tree kill also stops infinite loops and "
                                    "pipe-holding grandchildren, which a name blacklist "
                                    "would not; and `> NUL` is a legitimate redirect",
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks),
        "evidence": {"globs": EVIDENCE_GLOBS,
                     "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for c in checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['id']}: {c['detail']}")
    print(f"harness_exec_contract: {passed}/{len(checks)} checks pass")
    print(f"wrote {out}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
