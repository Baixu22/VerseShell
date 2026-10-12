#!/usr/bin/env python3
"""Measure ae vs pwsh7 / Windows PowerShell 5.1 / cmd / Git Bash on the same five
operations, reusing cross_shell_bench's equivalence keys. Read-only diagnostic;
writes nothing except the report path you pass.

This closes the gap that the frozen C11 table never measured pwsh 7.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import cross_shell_bench as b  # reuse keys + _run + timing

# time_interleaved() filters by b.SHELLS; add pwsh7 so it is kept.
b.SHELLS = ("ae", "pwsh7", "pwsh", "cmd", "bash")

def ops_with_pwsh7(ae, bash):
    ops = b.operations(ae, bash)
    # Byte-exact read for BOTH PowerShell versions: Get-Content -Raw keeps the
    # trailing newline, ae's file.read does not, so a fair read comparison must
    # go through bytes. (Frozen C11 used a different README; this keeps parity.)
    for op in ops:
        if op["name"] == "Read file":
            op["pwsh"] = ["powershell", "-NoProfile", "-Command",
                          "[Convert]::ToBase64String([IO.File]::ReadAllBytes('README.md'))"]
        if op.get("pwsh") is not None:
            # same command, but the modern pwsh 7 binary
            pwsh7_scripts = {
                "CPU info": "Get-CimInstance Win32_Processor | Select-Object Name | ConvertTo-Json -Compress -Depth 5",
                "Disk info": "Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" | Select-Object DeviceID | ConvertTo-Json -Compress -Depth 5",
                "List dir": "Get-ChildItem src | Select-Object Name | ConvertTo-Json -Compress -Depth 5",
                "Read file": "[Convert]::ToBase64String([IO.File]::ReadAllBytes('README.md'))",
                "Pipeline 1K": b.PIPELINE_PWSH,
            }
            script = pwsh7_scripts.get(op["name"], op["pwsh"][-1])
            op["pwsh7"] = ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script]
    return ops

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ae", default=str(ROOT / "target/release/ae.exe"))
    ap.add_argument("--bash", default=r"C:\Program Files\Git\bin\bash.exe")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    ops = ops_with_pwsh7(a.ae, a.bash)
    report = {"schema": "verseshell.cross-shell-pwsh7/v1",
              "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "machine": b.platform.platform(),
              "note": "diagnostic only; does not update claim C11",
              "operations": [], "aggregate": {}}
    ratios = []
    for op in ops:
        shells = [s for s in ("ae","pwsh7","pwsh","cmd","bash") if op.get(s) is not None]
        cmds = {s: op[s] for s in shells}
        # equivalence via the op's own key
        keys, exits = {}, {}
        for s in shells:
            try:
                p = b._run(cmds[s], capture=True)
                exits[s] = p.returncode
                raw = p.stdout or ""
                if s == "pwsh7" and op["name"] == "Disk info":
                    raw = raw.replace("DeviceID", "Name")
                if s in ("pwsh", "pwsh7") and op["name"] == "Read file":
                    import base64 as _b64
                    try: raw = _b64.b64decode(raw.strip()).decode("utf-8", "replace")
                    except Exception: pass
                keys[s] = op["key"]("pwsh" if s == "pwsh7" else s, raw)
            except Exception as e:
                keys[s], exits[s] = None, None
        resolved = {s:k for s,k in keys.items() if k is not None}
        equiv = len(resolved) == len(shells) and len(set(resolved.values())) == 1
        timing = b.time_interleaved(cmds, a.iterations, a.warmup)
        entry = {"name": op["name"], "equivalent": equiv, "keys": keys,
                 "exit_codes": exits, "shells": timing}
        if timing.get("ae") and timing.get("pwsh7"):
            r = timing["ae"]["warm_median_ms"] / timing["pwsh7"]["warm_median_ms"]
            entry["ae_over_pwsh7"] = round(r, 4)
            ratios.append(r)
        report["operations"].append(entry)
    report["aggregate"] = {
        "worst_ratio_ae_over_pwsh7": round(max(ratios),4) if ratios else None,
        "operations_ae_faster_than_pwsh7": sum(1 for r in ratios if r < 1),
        "operations_compared": len(ratios),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
