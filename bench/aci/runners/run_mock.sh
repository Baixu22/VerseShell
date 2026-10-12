#!/usr/bin/env bash
set -euo pipefail
export AETHER_APPROVE_ALL=1
export AETHER_MODE=agent
python3 bench/aci/runners/run_suite.py --mode mock
python3 bench/aci/scorers/score.py bench/aci/results/latest.json --require-accept
echo "OK: report at bench/aci/results/REPORT.md"
