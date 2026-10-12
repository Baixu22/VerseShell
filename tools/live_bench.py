"""Live ACI-Bench driver: loads .env.local, then runs a runner with the endpoint config.

Keeps credentials out of the shell history and out of the repo. Every invocation
is a real function-calling model run.

Usage:
  python tools/live_bench.py --smoke --out bench/aci/results/scratch/smoke.json
  python tools/live_bench.py --full --seed 42 --out bench/aci/results/tf88/with_seed42.json
  # any other runner in bench/aci/runners (e.g. the api_error cell splicer):
  python tools/live_bench.py --runner bench/aci/runners/splice_live_cells.py \
      bench/aci/results/tf90/with_seed42.json bench/aci/results/tf90/with_seed43.json
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL = ROOT / ".env.local"
DEFAULT_RUNNER = ROOT / "bench" / "aci" / "runners" / "live_agent_loop.py"


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runner", type=Path, default=DEFAULT_RUNNER,
                    help="runner script to execute (default: live_agent_loop.py)")
    ap.add_argument("--model", default=None, help="override ACI_BENCH_MODEL")
    ap.add_argument("--base-url", default=None, help="override ACI_BENCH_BASE_URL")
    args, rest = ap.parse_known_args()

    env = load_env()
    model = args.model or env["ACI_BENCH_MODEL"]
    base_url = args.base_url or env["ACI_BENCH_BASE_URL"]
    api_key = env["ACI_BENCH_API_KEY"]

    cmd = [sys.executable, str(args.runner)]
    # Only the agent loop accepts the endpoint flags directly; other runners take
    # --api-key and read the rest from the run file they are patching.
    if args.runner.resolve() == DEFAULT_RUNNER.resolve():
        cmd += ["--model", model, "--base-url", base_url, "--api-key", api_key, *rest]
    else:
        cmd += ["--api-key", api_key, *rest]

    print(f"live_bench: runner={args.runner.name} model={model} base={base_url} "
          f"args={' '.join(rest)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
