#!/usr/bin/env python3
"""Contract check: actual `ae` JSON output matches the experiment provider schema."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from tools.agent_shell_benefit.common import OBSERVATION_SCHEMA, validate_observation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ae", required=True)
    args = parser.parse_args(argv)
    ae = str(Path(args.ae).resolve())
    if not Path(ae).is_file():
        print(json.dumps({"ok": False, "error": f"ae not found: {ae}"}))
        return 1
    with tempfile.TemporaryDirectory(prefix="agent-shell-contract-") as workspace:
        argv_command = ["cmd", "/C", "echo CONTRACT"] if os.name == "nt" else ["sh", "-c", "echo CONTRACT"]
        request = {
            "id": "contract",
            "agent": "contract",
            "op": "exec.run",
            "args": {"argv": argv_command, "cwd": ".", "artifact": "auto"},
            "timeout_ms": 5000,
            "budget": {"max_tokens": 4000},
        }
        env = os.environ.copy()
        env["AETHER_APPROVE_ALL"] = "1"
        env["AETHER_WORKSPACE"] = workspace
        proc = subprocess.run(
            [ae, "--serve", "--cap", "shell.exec", "--agent", "--workspace", workspace],
            input=(json.dumps(request, ensure_ascii=False) + "\n").encode(),
            capture_output=True,
            timeout=30,
            env=env,
        )
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    observation = None
    for line in lines:
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if candidate.get("schema") == OBSERVATION_SCHEMA:
            observation = candidate
            break
    result = {
        "ok": observation is not None,
        "ae": ae,
        "returncode": proc.returncode,
        "stderr": proc.stderr.decode("utf-8", "replace")[-2000:],
        "schema": (observation or {}).get("schema"),
        "top_level_keys": sorted((observation or {}).keys()),
        "validation_errors": validate_observation(observation) if observation else ["no observation"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] and not result["validation_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())