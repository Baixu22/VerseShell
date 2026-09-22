#!/usr/bin/env python3
"""cross_shell_bench: reproducible wall-clock comparison of VerseShell vs
PowerShell vs Git Bash for the five operations README advertises.

This is the runner behind claim C11. It replaces the ad-hoc `bench_final.sh`
numbers with raw per-iteration samples stored in `eval/cross_shell.json`.

Fairness notes (all recorded in the report):

  * each command is the cheapest equivalent form for that shell, matching
    `bench_final.sh`;
  * warmup runs are discarded, then N iterations are timed with
    `time.perf_counter()` around a real process spawn (process startup is part
    of the measurement, exactly as the README footnote says);
  * stdout/stderr go to DEVNULL in every shell;
  * the pipeline payloads are aligned: `range(1,1001)` in VerseShell is 1000
    elements, matching `seq 1 1000` (the old script mixed 999 vs 1000).

Usage:
    python tools/cross_shell_bench.py
    python tools/cross_shell_bench.py --iterations 20 --out eval/cross_shell.json
"""
from __future__ import annotations

import argparse
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


def operations(ae: str, bash: str) -> list[dict]:
    """Five operations, each with the equivalent command per shell."""
    return [
        {
            "name": "CPU info",
            "ae": [ae, "--json", "-c", "sys.cpu_info()"],
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Processor | ConvertTo-Json -Compress"],
            "bash": [bash, "-lc", "cat /proc/cpuinfo 2>/dev/null | head -5"],
        },
        {
            "name": "Disk info",
            "ae": [ae, "--json", "-c", "sys.disk_info()"],
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-PSDrive -PSProvider FileSystem | Where-Object Used -gt 0 | ConvertTo-Json -Compress"],
            "bash": None,  # no cross-platform equivalent in the original table
        },
        {
            "name": "List dir",
            "ae": [ae, "--json", "-c", 'file.ls("src")'],
            "pwsh": ["powershell", "-NoProfile", "-Command",
                     "Get-ChildItem src -File | ConvertTo-Json -Compress"],
            "bash": [bash, "-lc", "ls -la src"],
        },
        {
            "name": "Read file",
            "ae": [ae, "--json", "-c", 'file.read("README.md")'],
            "pwsh": ["powershell", "-NoProfile", "-Command", "Get-Content README.md -Raw"],
            "bash": [bash, "-lc", "cat README.md"],
        },
        {
            "name": "Pipeline 1K",
            "ae": [ae, "-c", PIPELINE_AE],
            "pwsh": ["powershell", "-NoProfile", "-Command", PIPELINE_PWSH],
            "bash": [bash, "-lc", PIPELINE_BASH],
        },
    ]


def time_command(cmd: list[str], iterations: int, warmup: int) -> dict:
    for _ in range(warmup):
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    probe = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "command": cmd,
        "exit_code": probe.returncode,
        "ok": probe.returncode == 0,
        "samples_ms": [round(s, 3) for s in samples],
        "median_ms": round(statistics.median(samples), 3),
        "mean_ms": round(statistics.fmean(samples), 3),
        "min_ms": round(min(samples), 3),
    }


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
        row = {"name": op["name"], "shells": {}}
        for shell in ("ae", "pwsh", "bash"):
            cmd = op.get(shell)
            if cmd is None:
                row["shells"][shell] = {"ok": False, "skipped": "no equivalent command"}
                continue
            row["shells"][shell] = time_command(cmd, args.iterations, args.warmup)
        ae_ms = row["shells"]["ae"].get("median_ms")
        pwsh_ms = row["shells"]["pwsh"].get("median_ms")
        bash_ms = row["shells"]["bash"].get("median_ms")
        row["ratio_ae_over_pwsh"] = round(ae_ms / pwsh_ms, 4) if ae_ms and pwsh_ms else None
        row["ratio_ae_over_bash"] = round(ae_ms / bash_ms, 4) if ae_ms and bash_ms else None
        rows.append(row)
        print(f"  {op['name']:<12} ae={ae_ms}ms pwsh={pwsh_ms}ms bash={bash_ms}ms "
              f"ratio_vs_pwsh={row['ratio_ae_over_pwsh']}")

    gated = [r["ratio_ae_over_pwsh"] for r in rows if r["ratio_ae_over_pwsh"] is not None]
    failures = [
        f"{r['name']}/{shell}"
        for r in rows
        for shell, data in r["shells"].items()
        if not data.get("ok") and not data.get("skipped")
    ]
    worst = max(gated) if gated else None
    all_ok = not failures and len(gated) == len(rows)

    report = {
        "schema": "verseshell.cross-shell/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
            "io": "stdout/stderr to DEVNULL in every shell",
            "payload_alignment": "VerseShell range(1,1001) == 1000 elements == seq 1 1000",
        },
        "operations": rows,
        "aggregate": {
            "worst_ratio_ae_over_pwsh": worst,
            "all_commands_ok": all_ok,
            "failed_commands": failures,
            "gated_operations": len(gated),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report written: {args.out}")
    print(f"worst ratio vs PowerShell: {worst}  all_commands_ok={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
