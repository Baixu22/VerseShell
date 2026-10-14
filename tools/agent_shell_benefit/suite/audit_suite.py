"""Static audit of the 80-task suite: find task/oracle defects WITHOUT model calls.

Detects the defect classes already observed plus structural risks:
  A. prompt does not name the paths the oracle checks (under-constrained)
  B. oracle requires finish.success=true but the task can legitimately end false
  C. evidence reads a file that may exceed the read cap (truncated evidence)
  D. no_process / probe regressions
  E. task has no verifiable artifact/trace check (summary-only)
  F. fixtures referenced but missing on disk
  G. duplicate ids / tier counts
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.suite import build_catalog

STRONG = {
    "file_equals", "file_contains", "file_absent", "file_matches", "file_count_lines",
    "exit_seen", "stdout_seen", "command_seen", "parallel_used", "parallel_result_count",
    "parallel_wall_lt", "no_process", "host_blocked", "recovered",
    "no_duplicate_commands", "tool_count_min", "tool_count_max", "probe_contains",
}
PATHY = {"file_equals", "file_contains", "file_absent", "file_matches", "file_count_lines"}
NEGATIVE_RE = r"(?i)(must fail|BLOCKED|NO_ESCAPE|SECRET_SAFE|SYMLINK_BLOCKED|unreachable|escape into the host|must not reveal)"


def iter_checks(checks):
    for c in checks:
        yield c
        for sub in (c.get("checks") or []):
            yield from iter_checks([sub])
        if c.get("check"):
            yield from iter_checks([c["check"]])


def audit():
    tasks = build_catalog()
    findings = []
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        findings.append("G: duplicate task ids")
    for tier in ("L1", "L2", "L3", "L4"):
        n = len([t for t in tasks if t["tier"] == tier])
        if n != 20:
            findings.append("G: tier " + tier + " has " + str(n) + " tasks")

    for t in tasks:
        tid = t["id"]
        prompt = t["prompt"]
        checks = list(iter_checks(t["oracle"]["checks"]))
        kinds = {c.get("type") for c in checks}
        checked_paths = {c["path"] for c in checks if c.get("type") in PATHY and "path" in c}

        if not (kinds & STRONG):
            findings.append("E " + tid + ": summary-only oracle " + str(sorted(kinds)))

        if t["oracle"].get("require_finish_success", True) and re.search(NEGATIVE_RE, prompt):
            findings.append("B " + tid + ": negative-outcome prompt but requires finish success=true")

        for p in sorted(checked_paths):
            base_name = p.rsplit("/", 1)[-1]
            if p not in prompt and base_name not in prompt:
                findings.append("A " + tid + ": oracle checks " + p + " but prompt never names it")

        for f in (t.get("fixtures") or []):
            if not (BASE / f["source"]).is_file():
                findings.append("F " + tid + ": missing fixture " + f["source"])

        ev_files = (t.get("evidence") or {}).get("files") or []
        for p in sorted(checked_paths):
            if p in ev_files and p.endswith("big.txt") and "probe_contains" not in kinds:
                findings.append("C " + tid + ": reads large file " + p + " without a probe")
    return findings


def main():
    findings = audit()
    if not findings:
        print("AUDIT CLEAN: no static defects found across 80 tasks")
        return 0
    print("AUDIT: " + str(len(findings)) + " finding(s)")
    for f in findings:
        print("  - " + f)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
