#!/usr/bin/env python3
"""readme_claims_check: verify that what README promises is actually true.

Two kinds of promise are checked:

  A. Documented REPL examples. Every entry below must still appear in README
     and must produce the documented output when run through the real binary.
     (`reduce` and `reverse` were both documented and both broken.)
  B. Implementation numbers. Every number README states about the codebase
     (cache size, TTL defaults, suite counts, ...) is re-derived from its source
     of truth and compared.

Exit code is 0 only when every check passes.

Usage:
    python tools/readme_claims_check.py
    python tools/readme_claims_check.py --json eval/readme_claims.json
    python tools/readme_claims_check.py --ae target/debug/ae.exe
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── A. documented examples (expr -> documented stdout) ──────────────────────
EXAMPLES = [
    {"expr": "[1,2,3] | map fn(x) => x * 2", "expect": "[2, 4, 6]"},
    {"expr": "[1,2,3,4,5] | where fn(x) => x > 3", "expect": "[4, 5]"},
    {"expr": "[3,1,4,1,5] | sort", "expect": "[1, 1, 3, 4, 5]"},
    {"expr": "[5,2,4,1,3] | sort | where fn(x)=>x>2 | map fn(x)=>x*10", "expect": "[30, 40, 50]"},
    {"expr": "[1,2,3,4] | reduce fn(acc,x)=>acc+x 0", "expect": "10"},
    {"expr": "[3,1,4,1,5] | sort | reverse | take(3)", "expect": "[5, 4, 3]"},
    {"expr": "[1,2,3] | any fn(x) => x > 2", "expect": "true"},
]


def norm(text: str) -> str:
    """Collapse whitespace so README alignment padding does not matter."""
    return re.sub(r"\s+", " ", text)


def pick_binary(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"--ae path does not exist: {path}")
        return path
    for candidate in ("target/debug/ae.exe", "target/debug/ae", "target/release/ae.exe", "target/release/ae"):
        path = ROOT / candidate
        if path.exists():
            return path
    raise SystemExit("no ae binary found; run `cargo build` first")


def check_examples(ae: Path, readme: str) -> list[dict]:
    results = []
    for example in EXAMPLES:
        expr = example["expr"]
        documented = norm(expr) in norm(readme)
        proc = subprocess.run([str(ae), "-c", expr], capture_output=True, text=True, cwd=ROOT)
        actual = proc.stdout.strip()
        results.append({
            "kind": "example",
            "name": expr,
            "source": "README.md",
            "expected": example["expect"],
            "actual": actual,
            "documented_in_readme": documented,
            "pass": documented and proc.returncode == 0 and actual == example["expect"],
        })
    return results


# ── B. implementation numbers (README statement <- source of truth) ─────────

def first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.M)
    return int(match.group(1)) if match else None


def count_matches(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, re.M))


def check_numbers(readme: str) -> list[dict]:
    results: list[dict] = []

    def record(name: str, readme_pattern: str, expected: int | None, source: str, note: str) -> None:
        stated = [int(m) for m in re.findall(readme_pattern, readme)]
        ok = expected is not None and bool(stated) and all(value == expected for value in stated)
        results.append({
            "kind": "number",
            "name": name,
            "source": source,
            "expected": expected,
            "actual": stated,
            "note": note,
            "pass": ok,
        })

    runtime = (ROOT / "src/runtime.rs").read_text(encoding="utf-8")
    main_rs = (ROOT / "src/main.rs").read_text(encoding="utf-8")
    artifact = (ROOT / "src/artifact.rs").read_text(encoding="utf-8")
    cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    integration = (ROOT / "tests/integration_tests.rs").read_text(encoding="utf-8")

    record(
        "AST cache entries",
        r"(\d+)-entry global cache",
        first_int(r"max_ast_entries:\s*(\d+)", runtime),
        "src/runtime.rs (max_ast_entries)",
        "README says how many entries the AST cache holds",
    )
    record(
        "snapshot cache TTL (ms)",
        r"default:\s*(\d+)ms",
        first_int(r'default_value = "(\d+)"\)\]\s*\n\s*cache_ttl_ms', main_rs),
        "src/main.rs (--cache-ttl-ms default)",
        "README documents the CLI default",
    )
    # `DEFAULT_TTL: Duration = Duration::from_secs(24 * 60 * 60)`
    ttl_match = re.search(
        r"DEFAULT_TTL:\s*Duration = Duration::from_secs\((\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\)",
        artifact,
    )
    ttl_hours = None
    if ttl_match:
        factors = [int(g) for g in ttl_match.groups()]
        ttl_hours = (factors[0] * factors[1] * factors[2]) // 3600
    record(
        "artifact TTL (hours)",
        r"(\d+)-hour TTL",
        ttl_hours,
        "src/artifact.rs (DEFAULT_TTL)",
        "README states the artifact retention window",
    )
    record(
        "Criterion benchmark suites",
        r"(\d+) Criterion benchmark suites",
        count_matches(r"^\[\[bench\]\]", cargo),
        "Cargo.toml ([[bench]] entries)",
        "README states how many Criterion suites ship",
    )
    record(
        "integration tests",
        r"(\d+) integration tests",
        count_matches(r"^#\[test\]", integration),
        "tests/integration_tests.rs (#[test] functions)",
        "README states the size of the integration suite",
    )
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ae", default=None, help="path to the ae binary")
    ap.add_argument("--json", type=Path, default=None, help="write a machine-readable report")
    args = ap.parse_args(argv)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ae = pick_binary(args.ae)

    checks = check_examples(ae, readme) + check_numbers(readme)
    passed = sum(1 for c in checks if c["pass"])
    all_pass = passed == len(checks)

    print(f"readme_claims_check: {passed}/{len(checks)} checks pass  (ae={ae.relative_to(ROOT)})")
    for check in checks:
        status = "PASS" if check["pass"] else "FAIL"
        if check["kind"] == "example":
            print(f"  [{status}] example  {check['name']}")
            if not check["pass"]:
                print(f"           expected={check['expected']!r} actual={check['actual']!r} "
                      f"documented={check['documented_in_readme']}")
        else:
            print(f"  [{status}] number   {check['name']}: readme={check['actual']} "
                  f"source={check['expected']} ({check['source']})")

    report = {
        "schema": "verseshell.readme-claims/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/readme_claims_check.py",
        "ae_binary": str(ae.relative_to(ROOT)),
        "all_pass": all_pass,
        "checks": checks,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"report written: {args.json}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
