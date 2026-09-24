#!/usr/bin/env python3
"""TF-0072: decompose D's failed `exec.run` calls, and pin the exec launch defects.

Three questions:

  * What are the failed exec calls? Classified as `first_diagnostic` (the first
    failing run of that command in a run — for these tasks seeing the failure *is*
    the work), `repeat` (the same command failing again after an edit), or
    `toolchain_probe` (version/`+toolchain` probing).
  * Does the launcher still hand a name-dispatching shim the name it was invoked
    as? On a rustup install `cargo.exe`/`rustc.exe` are **symlinks** to
    `rustup.exe`, and rustup picks the tool from that name. Canonicalising the
    path before launching silently turns `cargo check` into plain `rustup` — which
    is what this tool caught: `cargo check` returned exit 100 with "0 error(s)",
    `cargo build` was read as the `+build` toolchain, and `cargo --version`
    printed the rustup version. The `shim_probe` section re-runs those commands
    through `exec.run`, so a regression fails this tool (and claim C18) instead of
    quietly corrupting the live numbers again.
  * Does a bare npm-family name resolve to a launchable image? npm-for-Windows
    ships an extensionless `npm` (a `#!/bin/sh` script) beside `npm.cmd`;
    resolving the bare file first made `exec.run(["npm", ...])` fail with
    `E_EXEC_SPAWN` while raw shell (through `cmd`) worked, costing condition D a
    wasted call on every npm task. The `bare_name_probe` section re-runs each
    shadowed name and its `.cmd` control through `exec.run`, so claim C22 is
    machine-checked rather than assumed.

Usage:
    python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
RESULTS = BENCH / "results"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
from tf45_envelope_replay import prepare_workspace  # noqa: E402
from live_agent_loop import ACI_CAPABILITIES, AE, format_aci_result  # noqa: E402

ARMS = {
    "with_read_files": RESULTS / "latest_live.json",
    "without_read_files": RESULTS / "live_ab_without_read_files.json",
}
PROBE_HINTS = ("--version", " version", "+stable", "+1.", "rustup", "where ", "which ")
SHIM_NAMES = ("cargo", "rustc", "cargo-clippy", "rustfmt")
BARE_SHIM_NAMES = ("npm", "npx", "yarn", "pnpm", "corepack")
EVIDENCE_GLOBS = [
    "src/process_command.rs",
    "src/process_runner.rs",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/results/latest_live.json",
    "bench/aci/results/live_ab_without_read_files.json",
    "tools/exec_failure_breakdown.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for pat in globs for p in ROOT.glob(pat)
                       if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def command_key(step: dict) -> str:
    argv = [str(a) for a in (step.get("args", {}).get("argv") or [])]
    return " ".join(argv[:2])


def classify_failure(step: dict, seen: Counter) -> str:
    argv = " ".join(str(a) for a in (step.get("args", {}).get("argv") or [])).lower()
    if any(hint in argv for hint in PROBE_HINTS):
        return "toolchain_probe"
    return "repeat" if command_key(step) in seen else "first_diagnostic"


def failures(rows: list[dict]) -> dict:
    classes = defaultdict(lambda: [0, 0])
    per_task = defaultdict(lambda: [0, 0])
    commands: Counter = Counter()
    ok_calls = ok_tokens = 0
    for row in rows:
        if row["condition"] != "verseshell_aci":
            continue
        seen: Counter = Counter()
        for step in row.get("trajectory", []):
            if step["op"] != "exec.run":
                continue
            tokens = int(step.get("observation_tokens", 0))
            if step.get("aci_ok"):
                ok_calls += 1
                ok_tokens += tokens
                seen[command_key(step)] += 1
                continue
            klass = classify_failure(step, seen)
            classes[klass][0] += 1
            classes[klass][1] += tokens
            per_task[row["task_id"]][0] += 1
            per_task[row["task_id"]][1] += tokens
            commands[" ".join(str(a) for a in (step.get("args", {}).get("argv") or [])[:3])] += 1
    fail_calls = sum(v[0] for v in classes.values())
    fail_tokens = sum(v[1] for v in classes.values())
    return {
        "ok": {"calls": ok_calls, "tokens": ok_tokens,
               "tokens_per_call": round(ok_tokens / ok_calls, 2) if ok_calls else 0.0},
        "failed": {"calls": fail_calls, "tokens": fail_tokens,
                   "tokens_per_call": round(fail_tokens / fail_calls, 2) if fail_calls else 0.0,
                   "share_of_exec_tokens": round(fail_tokens / (fail_tokens + ok_tokens), 4)
                   if (fail_tokens + ok_tokens) else None},
        "classes": {k: {"calls": v[0], "tokens": v[1],
                        "share_of_failure_tokens": round(v[1] / fail_tokens, 4) if fail_tokens else None}
                    for k, v in sorted(classes.items(), key=lambda kv: -kv[1][1])},
        "per_task_failed": {k: {"calls": v[0], "tokens": v[1]}
                            for k, v in sorted(per_task.items(), key=lambda kv: -kv[1][1])},
        "top_failing_commands": commands.most_common(10),
    }


def shim_facts() -> list[dict]:
    """Is the program a symlink shim, and what does it point at?"""
    out = []
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for name in SHIM_NAMES:
        found = None
        for directory in path_dirs:
            for ext in ("", ".exe", ".cmd", ".bat"):
                candidate = Path(directory) / f"{name}{ext}"
                if candidate.is_file():
                    found = candidate
                    break
            if found:
                break
        if found is None:
            out.append({"program": name, "found": False})
            continue
        is_link = found.is_symlink()
        entry = {
            "program": name, "found": True, "path": str(found), "is_symlink": is_link,
            "launch_path_keeps_name": found.name.lower().startswith(name.lower()),
        }
        if is_link:
            try:
                entry["symlink_target"] = os.readlink(found)
            except OSError:
                entry["symlink_target"] = None
            entry["canonical_path"] = str(found.resolve())
            entry["canonical_loses_name"] = not found.resolve().name.lower().startswith(name.lower())
        out.append(entry)
    return out


def run_op(op: str, args: dict, workspace: Path) -> dict:
    env = dict(os.environ)
    env["AETHER_APPROVE_ALL"] = "1"
    env["AETHER_MODE"] = "agent"
    env["AETHER_WORKSPACE"] = str(workspace)
    payload = {"id": "shim", "agent": "probe", "op": op, "args": args,
               "timeout_ms": 120000, "budget": {"max_tokens": 4000}}
    proc = subprocess.Popen([str(AE), "--serve", "--agent", "--cap", ACI_CAPABILITIES],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    out, err = proc.communicate(json.dumps(payload).encode() + b"\n", timeout=180)
    lines = [l for l in out.decode("utf-8", "replace").split("\n") if l.strip()]
    if not lines:
        raise RuntimeError(err.decode("utf-8", "replace")[:300])
    return json.loads(lines[0])


def shim_probe() -> dict:
    """Re-run the commands that the defect broke, through the real exec path."""
    ws = prepare_workspace("rust_fix_compile_error")
    # apply the fixture's golden fix so a working cargo must report success
    golden = BENCH / "fixtures" / "rust_fix_compile_error" / "GOLDEN" / "src" / "lib.rs"
    if golden.exists():
        shutil.copy2(golden, ws / "src" / "lib.rs")
    results = {}
    try:
        for argv in (["cargo", "--version"], ["cargo", "check"], ["rustc", "--version"]):
            env = run_op("exec.run", {"argv": argv, "cwd": ".", "profile": "none"}, ws)
            data = env.get("data") or {}
            text = ""
            for stream in ("stdout", "stderr"):
                value = data.get(stream)
                if isinstance(value, dict) and value.get("text"):
                    text += value["text"]
            results[" ".join(argv)] = {
                "ok": env.get("ok"),
                "exit_code": data.get("exit_code"),
                "output_head": text.strip()[:120],
                # The defect's fingerprint: rustup answering for cargo/rustc.
                "answered_as_rustup": "rustup" in text.lower() and "cargo" not in text.lower(),
            }
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    version_ok = results.get("cargo --version", {}).get("exit_code") == 0
    cargo_ok = results.get("cargo check", {}).get("exit_code") == 0
    no_rustup = not any(r.get("answered_as_rustup") for r in results.values())
    return {
        "commands": results,
        "cargo_dispatches_correctly": bool(version_ok and no_rustup),
        "cargo_check_succeeds_on_fixed_fixture": bool(cargo_ok),
        "pass": bool(version_ok and cargo_ok and no_rustup),
    }


def bare_name_facts() -> dict:
    """Which bare npm-family names are shadowed by an extensionless file on PATH?"""
    names: dict[str, list[dict]] = {}
    for name in BARE_SHIM_NAMES:
        hits = []
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            bare = Path(directory) / name
            if not bare.is_file():
                continue
            siblings = sorted(
                p.name for p in Path(directory).iterdir()
                if p.is_file() and p.name.lower() != name.lower()
                and p.name.lower().startswith(name.lower())
            )
            hits.append({
                "dir": directory,
                "bare_file": str(bare),
                "bare_is_symlink": bare.is_symlink(),
                "siblings": siblings,
                "shadowed": any(s.lower().endswith((".cmd", ".exe", ".bat")) for s in siblings),
            })
        names[name] = hits
    shadowed = sorted(n for n, hits in names.items() if any(h["shadowed"] for h in hits))
    return {
        "names": names,
        "shadowed": shadowed,
        "note": "an extensionless sibling is normally a POSIX shell script that Win32 "
                "cannot launch, so a bare name must resolve through PATHEXT",
    }


def bare_name_probe(shadowed: list[str]) -> dict:
    """Re-run each shadowed bare name, and its `.cmd` control, through `exec.run`.

    The control is the same command spelled with the PATHEXT suffix: if that fails
    too, the tool is broken for another reason and the name is skipped rather than
    blamed on resolution. Fail-closed: if no shadowed-and-working name exists the
    probe reports `triggered=false` and cannot pass vacuously.
    """
    if not shadowed:
        return {
            "triggered": False,
            "pass": False,
            "reason": "no extensionless shim shadows a bare npm-family name on this PATH",
        }
    ws = Path(tempfile.mkdtemp(prefix="verseshell-bare-"))
    commands: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    try:
        for name in shadowed:
            control = run_op("exec.run",
                             {"argv": [f"{name}.cmd", "--version"], "cwd": ".", "profile": "none"},
                             ws)
            control_data = control.get("data") or {}
            if not (control.get("ok") and control_data.get("exit_code") == 0):
                skipped[name] = "the `.cmd` control did not run, so this name is not attributable"
                continue
            bare = run_op("exec.run",
                          {"argv": [name, "--version"], "cwd": ".", "profile": "none"}, ws)
            data = bare.get("data") or {}
            text = ""
            for stream in ("stdout", "stderr"):
                value = data.get(stream)
                if isinstance(value, dict) and value.get("text"):
                    text += value["text"]
            error = bare.get("error")
            commands[name] = {
                "ok": bare.get("ok"),
                "exit_code": data.get("exit_code"),
                "error_code": error.get("code") if isinstance(error, dict) else None,
                "output_head": text.strip()[:80],
            }
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    passed = bool(commands) and all(c["ok"] and c.get("exit_code") == 0 for c in commands.values())
    return {"triggered": bool(commands), "commands": commands, "skipped": skipped, "pass": bool(passed)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    missing = [str(p) for p in ARMS.values() if not p.exists()]
    if missing:
        print(f"ERROR: missing {missing}", file=sys.stderr)
        return 1

    rows = {name: json.loads(path.read_text(encoding="utf-8-sig"))["rows"]
            for name, path in ARMS.items()}
    facts = shim_facts()
    probe = shim_probe()
    bare_facts = bare_name_facts()
    bare_probe = bare_name_probe(bare_facts["shadowed"])

    report = {
        "schema": "verseshell.exec-failure-breakdown/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [str(p.relative_to(ROOT)) for p in ARMS.values()],
            "classes": {
                "first_diagnostic": "first failing run of that command in the run — for these tasks "
                                    "observing the failure is the work itself",
                "repeat": "the same command failing again later in the run (trial and error)",
                "toolchain_probe": "version / `+toolchain` probing",
            },
            "shim_probe": "re-runs `cargo --version` / `cargo check` / `rustc --version` through the "
                          "real exec.run on the fixed rust fixture: a name-dispatching shim that was "
                          "launched by its canonicalised target answers as rustup instead",
            "bare_name_probe": "re-runs each bare npm-family name that PATH shadows with an "
                               "extensionless file, plus its `.cmd` control, through the real "
                               "exec.run: a bare name that resolves to the extensionless script "
                               "cannot start",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "shim_facts": facts,
        "shim_probe": probe,
        "bare_name_facts": bare_facts,
        "bare_name_probe": bare_probe,
        "with_read_files": failures(rows["with_read_files"]),
        "without_read_files": failures(rows["without_read_files"]),
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    for name, payload in (("with", report["with_read_files"]),
                          ("without", report["without_read_files"])):
        ok, bad = payload["ok"], payload["failed"]
        print(f"[{name}] exec.run ok {ok['calls']} calls @{ok['tokens_per_call']} | "
              f"failed {bad['calls']} calls @{bad['tokens_per_call']} "
              f"= {bad['share_of_exec_tokens'] * 100:.1f}% of exec tokens")
        for klass, entry in payload["classes"].items():
            print(f"    {klass:<18} calls={entry['calls']:<4} tok={entry['tokens']:<6} "
                  f"({entry['share_of_failure_tokens'] * 100:5.1f}% of failure tok)")
    print("shim facts:")
    for fact in facts:
        if fact.get("is_symlink"):
            print(f"    {fact['program']}: symlink -> {fact.get('symlink_target')} "
                  f"(canonical loses the name: {fact.get('canonical_loses_name')})")
        elif fact.get("found"):
            print(f"    {fact['program']}: real file (no shim)")
    print("shim probe:")
    for cmd, entry in probe["commands"].items():
        print(f"    {cmd:<20} ok={entry['ok']} exit={entry['exit_code']} "
              f"answered_as_rustup={entry['answered_as_rustup']} out={entry['output_head'][:60]!r}")
    print(f"    cargo dispatches correctly={probe['cargo_dispatches_correctly']} "
          f"cargo check on fixed fixture={probe['cargo_check_succeeds_on_fixed_fixture']} "
          f"pass={probe['pass']}")
    print("bare-name resolution:")
    print(f"    shadowed on PATH: {bare_facts['shadowed'] or 'none'}")
    for name, entry in bare_probe.get("commands", {}).items():
        print(f"    {name:<9} ok={entry['ok']} exit={entry['exit_code']} "
              f"error={entry['error_code']} out={entry['output_head'][:40]!r}")
    for name, reason in bare_probe.get("skipped", {}).items():
        print(f"    {name:<9} skipped: {reason}")
    print(f"    triggered={bare_probe['triggered']} pass={bare_probe['pass']}")
    return 0 if (probe["pass"] and bare_probe["pass"]) else 1


if __name__ == "__main__":
    sys.exit(main())
