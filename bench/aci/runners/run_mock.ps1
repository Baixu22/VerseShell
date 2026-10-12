$ErrorActionPreference = "Stop"
$env:AETHER_APPROVE_ALL = "1"
$env:AETHER_MODE = "agent"
python bench/aci/runners/run_suite.py --mode mock
python bench/aci/scorers/score.py bench/aci/results/latest.json --require-accept
Write-Host "OK: report at bench/aci/results/REPORT.md"
