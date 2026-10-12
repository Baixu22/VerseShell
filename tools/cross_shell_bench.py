#!/usr/bin/env python3
"""cross_shell_bench: reproducible wall-clock comparison of VerseShell vs
PowerShell vs cmd.exe vs Git Bash for the five operations README advertises.

This is the runner behind claim C11. It replaces the ad-hoc `bench_final.sh`
numbers with raw per-iteration samples stored in `eval/cross_shell.json`.

Pre-registration compliance (`docs/acceptance-criteria.md` §2, 验收区 B). Each
requirement is met by a named part of this file:

  1. **output equivalence is proven BEFORE timing** — `probe_equivalence()`
     reduces each shell's stdout to a normalised semantic key and every measured
     shell must agree. Exit code alone is explicitly not accepted. The probe runs
     with stdout captured; the timed phase discards stdout, exactly as §2 requires.
  2. **execution is interleaved** — `time_interleaved()` runs iteration *i* for
     every shell back-to-back, so a machine that drifts during the run drifts for
     all shells. The old version ran 20 iterations of one shell, then 20 of the
     next.
  3. **paired-to-iteration interval** — the samples are stored per iteration so
     `tools/acceptance_power.py` can bootstrap the ratio by pairing iteration *i*.
  4. **p50/p90/p99 and a real cold-vs-warm split** — `cold_ms` is a spawn measured
     before any warmup; `first_ms` is the first timed iteration; `warm_median_ms`
     excludes it.

The comparator that matters is the shell the baseline arm actually pays for:
`bench/aci/runners/live_agent_loop.py` runs `run_command` through `cmd.exe`
(`shell=True`). PowerShell is kept because the README table advertises it.

Usage:
    python tools/cross_shell_bench.py
    python tools/cross_shell_bench.py --iterations 20 --out eval/cross_shell.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PIPELINE_AE = "range(1,1001) | map fn(x)=>x*2 | where fn(x)=>x>500 | reduce fn(acc,x)=>acc+x 0"
PIPELINE_PWSH = "(1..1000 | ForEach-Object { $_ * 2 } | Where-Object { $_ -gt 500 } | Measure-Object -Sum).Sum"
PIPELINE_BASH = "seq 1 1000 | awk '{v=$1*2; if (v>500) s+=v} END{print s}'"

SHELLS = ("ae", "pwsh", "cmd", "bash")

# The measured surface. Recorded into the artifact so claim_gate (C12) can tell
# whether the stored numbers still describe the current code. `latest_live.json` is
# included because the wall-clock context section reads it.
EVIDENCE_GLOBS = [
    "src/**/*.rs",
    "Cargo.toml",
    "tools/cross_shell_bench.py",
    "bench/aci/results/latest_live.json",
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
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


# ── normalisation / equivalence keys ──────────────────────────────────────────
#
# Each key is a *semantic* projection, not the raw text: the shells emit different
# formats by design (ae emits JSON, PowerShell emits JSON, cmd/bash emit text), so
# byte equality is impossible and would be the wrong test. What must agree is the
# meaning: the same CPU, the same drives, the same directory entries, the same file
# bytes, the same pipeline result. A key of None means "this shell's output could
# not be reduced" — that counts as NOT verified, never as a pass.

def _norm(text: str) -> str:
    return " ".join(str(text).split()).strip().lower()


def _as_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _json_field_list(data, field: str) -> list[str] | None:
    if isinstance(data, list):
        out = [str(item[field]) for item in data
               if isinstance(item, dict) and field in item]
        return out or None
    return None


def _drive_letters(text: str) -> list[str]:
    letters = []
    for token in text.replace(",", " ").split():
        token = token.strip().strip("\\/")
        if len(token) == 2 and token[1] == ":" and token[0].isalpha():
            letters.append(token[0].upper())
    return sorted(set(letters))


def _drive_key(names: list[str]) -> str | None:
    """`C:\\`, `C:` and `C` all normalise to `C:`."""
    letters = sorted({n.strip().rstrip("\\/").upper().rstrip(":") for n in names if n.strip()})
    return "|".join(f"{c}:" for c in letters if c) or None


def key_cpu(shell: str, text: str) -> str | None:
    data = _as_json(text)
    if shell == "ae" and isinstance(data, dict) and data.get("name"):
        return _norm(data["name"]) or None
    if shell == "pwsh":
        # ConvertTo-Json emits a bare object for a single CPU and an array for many.
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _norm(data[0].get("Name", "")) or None
        return None
    if shell == "cmd":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return _norm(lines[1]) if len(lines) > 1 else None
    if shell == "bash":
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                return _norm(line.split(":", 1)[1]) or None
        return None
    return None


def key_disk(shell: str, text: str) -> str | None:
    data = _as_json(text)
    if shell == "ae":
        names = _json_field_list(data, "mounted_on")
        return _drive_key(names) if names else None
    if shell == "pwsh":
        names = _json_field_list(data, "Name")
        return _drive_key(names) if names else None
    if shell == "cmd":
        letters = _drive_letters(text)
        return "|".join(f"{c}:" for c in letters) if letters else None
    return None


def key_listdir(shell: str, text: str) -> str | None:
    data = _as_json(text)
    if shell in ("ae", "pwsh"):
        names = _json_field_list(data, "name" if shell == "ae" else "Name")
        return "|".join(sorted(_norm(n) for n in names)) if names else None
    if shell == "cmd":
        names = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "|".join(sorted(_norm(n) for n in names)) if names else None
    if shell == "bash":
        names = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 9 and parts[0][0] in "-dl":
                name = " ".join(parts[8:])
                if name not in (".", ".."):
                    names.append(name)
        return "|".join(sorted(_norm(n) for n in names)) if names else None
    return None


def key_readfile(shell: str, text: str) -> str | None:
    """sha256 of the content, normalised for line endings and trailing blanks."""
    if shell == "ae":
        data = _as_json(text)
        if isinstance(data, str):
            text = data                      # `file.read` --json emits a JSON string
        elif isinstance(data, dict):
            for field in ("content", "text", "data"):
                if isinstance(data.get(field), str):
                    text = data[field]
                    break
            else:
                if isinstance(data.get("lines"), list):
                    text = "\n".join(str(x) for x in data["lines"])
                else:
                    return None
        else:
            return None
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def key_pipeline(shell: str, text: str) -> str | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits or None


def operations(ae: str, bash: str) -> list[dict]:
    """Five operations, each with the equivalent command per shell."""
    return [
        {
            "name": "CPU info",
            "key": key_cpu,
            "ae": [ae, "--json", "-c", "sys.cpu_info()"],
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Processor | ConvertTo-Json -Compress"],
            "cmd": ["cmd", "/c", "wmic cpu get Name"],
            "bash": [bash, "-lc", "cat /proc/cpuinfo 2>/dev/null | head -40"],
        },
        {
            "name": "Disk info",
            "key": key_disk,
            "ae": [ae, "--json", "-c", "sys.disk_info()"],
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-PSDrive -PSProvider FileSystem | Where-Object Used -gt 0 | ConvertTo-Json -Compress"],
            "cmd": ["cmd", "/c", "fsutil fsinfo drives"],
            "bash": None,  # no cross-platform equivalent in the original table
        },
        {
            "name": "List dir",
            "key": key_listdir,
            "ae": [ae, "--json", "-c", 'file.ls("src")'],
            # No `-File`: `file.ls`, `dir /b` and `ls -la` all list directories too, so
            # `Get-ChildItem -File` was doing strictly less work than the others. The
            # equivalence probe is what caught it.
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-ChildItem src | ConvertTo-Json -Compress"],
            "cmd": ["cmd", "/c", "dir /b src"],
            "bash": [bash, "-lc", "ls -la src"],
        },
        {
            "name": "Read file",
            "key": key_readfile,
            "ae": [ae, "--json", "-c", 'file.read("README.md")'],
            # `-Encoding UTF8`: without it Windows PowerShell 5.1 decodes README.md
            # with the ANSI code page, so the bytes it reads differ from `type`/`cat`.
            # The probe caught that too.
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-Content README.md -Raw -Encoding UTF8"],
            "cmd": ["cmd", "/c", "type README.md"],
            "bash": [bash, "-lc", "cat README.md"],
        },
        {
            "name": "Pipeline 1K",
            "key": key_pipeline,
            "ae": [ae, "-c", PIPELINE_AE],
            "pwsh": ["powershell", "-NoProfile", "-Command", PIPELINE_PWSH],
            "cmd": None,  # cmd has no expression pipeline
            "bash": [bash, "-lc", PIPELINE_BASH],
        },
    ]


def _run(cmd: list[str], capture: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def probe_equivalence(op: dict) -> dict:
    """Requirement 1: prove the shells compute the same thing, before timing."""
    keys: dict[str, str | None] = {}
    exits: dict[str, int | None] = {}
    for shell in SHELLS:
        cmd = op.get(shell)
        if cmd is None:
            continue
        try:
            proc = _run(cmd, capture=True)
        except subprocess.TimeoutExpired:
            keys[shell], exits[shell] = None, None
            continue
        exits[shell] = proc.returncode
        keys[shell] = op["key"](shell, proc.stdout or "")
    measured = [s for s in SHELLS if op.get(s) is not None]
    resolved = {s: keys.get(s) for s in measured if keys.get(s) is not None}
    distinct = sorted(set(resolved.values()))
    return {
        "keys": keys,
        "exit_codes": exits,
        "measured_shells": measured,
        "resolved_shells": sorted(resolved),
        "unresolved_shells": sorted(s for s in measured if keys.get(s) is None),
        "equivalent": bool(resolved) and len(distinct) == 1
                      and len(resolved) == len(measured),
        "distinct_keys": len(distinct),
        "note": "exit code alone is not accepted; a shell whose output cannot be "
                "reduced to a semantic key counts as NOT verified",
    }


def time_interleaved(cmds: dict[str, list[str]], iterations: int, warmup: int) -> dict:
    """Requirements 2 and 4: interleave the shells, and split cold from warm."""
    shells = [s for s in SHELLS if cmds.get(s) is not None]
    cold: dict[str, float] = {}
    for shell in shells:  # cold start, before any warmup
        start = time.perf_counter()
        _run(cmds[shell], capture=False)
        cold[shell] = round((time.perf_counter() - start) * 1000.0, 3)
    for _ in range(warmup):
        for shell in shells:
            _run(cmds[shell], capture=False)
    samples: dict[str, list[float]] = {s: [] for s in shells}
    for _ in range(iterations):          # iteration is the OUTER loop on purpose
        for shell in shells:
            start = time.perf_counter()
            _run(cmds[shell], capture=False)
            samples[shell].append(round((time.perf_counter() - start) * 1000.0, 3))

    out = {}
    for shell in shells:
        s = sorted(samples[shell])
        warm = sorted(samples[shell][1:]) if len(samples[shell]) > 1 else s
        out[shell] = {
            "command": cmds[shell],
            "cold_ms": cold[shell],
            "first_ms": samples[shell][0],
            "samples_ms": samples[shell],
            "median_ms": round(statistics.median(s), 3),
            "warm_median_ms": round(statistics.median(warm), 3),
            "mean_ms": round(statistics.fmean(s), 3),
            "min_ms": s[0],
            "p50_ms": round(_pct(s, 0.50), 3),
            "p90_ms": round(_pct(s, 0.90), 3),
            "p99_ms": round(_pct(s, 0.99), 3),
        }
    return out


def _pct(sorted_values: list[float], q: float) -> float:
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def wall_clock_context() -> dict:
    """Requirement 5's context: how much of an agent run the shell even accounts for.

    Read from the stored live trajectories: `sum(trajectory[].elapsed_ms) / elapsed_ms`
    per row, per arm. A cross-shell speedup that addresses 2% of the wall clock is a
    real but small claim, and the pre-registration says to say so.
    """
    path = ROOT / "bench/aci/results/latest_live.json"
    if not path.exists():
        return {"available": False, "reason": f"missing {path.name}"}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("rows", [])
    out: dict = {"available": True, "source": path.name, "arms": {}}
    for cond in sorted({r.get("condition") for r in rows if r.get("condition")}):
        sub = [r for r in rows if r.get("condition") == cond]
        shares, tool_ms, e2e_ms = [], [], []
        for r in sub:
            total = float(r.get("elapsed_ms") or 0)
            tool = sum(float(t.get("elapsed_ms") or 0) for t in (r.get("trajectory") or []))
            if total > 0:
                shares.append(tool / total)
            tool_ms.append(tool)
            e2e_ms.append(total)
        if not shares:
            continue
        out["arms"][cond] = {
            "n": len(sub),
            "median_tool_share_of_wall_clock": round(statistics.median(shares), 4),
            "mean_tool_share_of_wall_clock": round(statistics.fmean(shares), 4),
            "median_wall_clock_ms": round(statistics.median(e2e_ms), 1),
            "median_tool_ms": round(statistics.median(tool_ms), 1),
        }
    out["note"] = ("tool share = sum(trajectory elapsed_ms) / row elapsed_ms; the rest is "
                   "model latency (the endpoint), which no shell choice can remove")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--ae", default=None)
    ap.add_argument("--bash", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "eval/cross_shell.json")
    args = ap.parse_args(argv)

    ae = args.ae
    if not ae:
        for candidate in ("target/release/ae.exe", "target/release/ae",
                          "target/debug/ae.exe", "target/debug/ae"):
            if (ROOT / candidate).exists():
                ae = str(ROOT / candidate)
                break
    if not ae:
        raise SystemExit("no ae binary found; run `cargo build --release` first")

    bash = args.bash
    if not bash:
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if git_bash.exists() else "bash"

    print(f"cross_shell_bench: ae={Path(ae).name} bash={Path(bash).name} "
          f"iterations={args.iterations} warmup={args.warmup}")

    rows = []
    for op in operations(ae, bash):
        cmds = {s: op.get(s) for s in SHELLS}
        equiv = probe_equivalence(op)
        print(f"  {op['name']:<12} equivalence={equiv['equivalent']} "
              f"keys={equiv['distinct_keys']} unresolved={equiv['unresolved_shells']}")
        if not equiv["equivalent"]:
            print(f"      keys: {equiv['keys']}")
        timings = time_interleaved(cmds, args.iterations, args.warmup)
        row = {"name": op["name"], "equivalence": equiv, "shells": {}}
        for shell in SHELLS:
            if cmds.get(shell) is None:
                row["shells"][shell] = {"ok": False, "skipped": "no equivalent command"}
            elif shell in timings:
                entry = timings[shell]
                entry["ok"] = equiv["exit_codes"].get(shell) == 0
                row["shells"][shell] = entry
        for other in ("pwsh", "cmd", "bash"):
            a = row["shells"].get("ae", {}).get("median_ms")
            b = row["shells"].get(other, {}).get("median_ms")
            row[f"ratio_ae_over_{other}"] = round(a / b, 4) if a and b else None
        rows.append(row)
        print(f"      ae={row['shells']['ae'].get('median_ms')}ms "
              f"pwsh={row['shells']['pwsh'].get('median_ms')}ms "
              f"cmd={row['shells']['cmd'].get('median_ms')}ms "
              f"bash={row['shells']['bash'].get('median_ms')}ms "
              f"ratio_vs_cmd={row['ratio_ae_over_cmd']}")

    def gated(shell: str) -> list[float]:
        return [r[f"ratio_ae_over_{shell}"] for r in rows
                if r[f"ratio_ae_over_{shell}"] is not None]

    pwsh_ratios, cmd_ratios = gated("pwsh"), gated("cmd")
    failures = [
        f"{r['name']}/{shell}"
        for r in rows
        for shell, data in r["shells"].items()
        if not data.get("ok") and not data.get("skipped")
    ]
    not_equivalent = [r["name"] for r in rows if not r["equivalence"]["equivalent"]]
    wall = wall_clock_context()

    report = {
        "schema": "verseshell.cross-shell/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": current_git_rev(),
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "generator": "tools/cross_shell_bench.py",
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": sys.version.split()[0],
            "ae_binary": str(Path(ae).relative_to(ROOT)),
            "bash_binary": bash,
        },
        "method": {
            "iterations": args.iterations,
            "warmup": args.warmup,
            "clock": "time.perf_counter around a real process spawn; process startup included",
            "io": "stdout/stderr to DEVNULL in the TIMED phase; captured in the equivalence probe",
            "interleaved": True,
            "cold_start": "one spawn measured before any warmup (`cold_ms`); `first_ms` is "
                          "the first timed iteration; `warm_median_ms` excludes it",
            "payload_alignment": "VerseShell range(1,1001) == 1000 elements == seq 1 1000",
            "equivalence": "per-operation semantic key; every measured shell must agree "
                           "AND resolve. Exit code alone is not accepted "
                           "(docs/acceptance-criteria.md §2)",
            "comparators": "cmd.exe is the shell the raw-shell baseline arm actually runs "
                           "through (`shell=True` in the live runner); PowerShell is the "
                           "one the README advertises; both are reported",
        },
        "operations": rows,
        "aggregate": {
            "worst_ratio_ae_over_pwsh": max(pwsh_ratios) if pwsh_ratios else None,
            "worst_ratio_ae_over_cmd": max(cmd_ratios) if cmd_ratios else None,
            "gated_operations_vs_pwsh": len(pwsh_ratios),
            "gated_operations_vs_cmd": len(cmd_ratios),
            "all_commands_ok": not failures and len(pwsh_ratios) == len(rows),
            "failed_commands": failures,
            "operations_without_proven_equivalence": not_equivalent,
            "all_outputs_equivalent": not not_equivalent,
        },
        "wall_clock_context": wall,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"report written: {args.out}")
    print(f"worst ratio vs PowerShell: {report['aggregate']['worst_ratio_ae_over_pwsh']}  "
          f"vs cmd: {report['aggregate']['worst_ratio_ae_over_cmd']}")
    print(f"all_outputs_equivalent={report['aggregate']['all_outputs_equivalent']} "
          f"all_commands_ok={report['aggregate']['all_commands_ok']}")
    return 0 if report["aggregate"]["all_commands_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
