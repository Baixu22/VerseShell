$env:AETHER_APPROVE_ALL='1'
Set-Location 'C:\Users\27933\Desktop\verseshell\verseshell'
$out = 'bench\aci\results\accept_verify.out'
$err = 'bench\aci\results\accept_verify.err'
$done = 'bench\aci\results\accept_verify.done'
Remove-Item $done -ErrorAction SilentlyContinue
# Core gates + adversarial + compression + mock bench
cargo test --test semantic_reducer_tests --test semantic_reducer_adversarial_tests --test token_compression_tests --test operation_protocol_tests --test aci_1_0_ops_tests --test aci_1_0_closed_loop_acceptance --test aci_bench_mock_acceptance -- --test-threads=1 1> $out 2> $err
$ec1 = $LASTEXITCODE
# Run deep stress e2e phases if present
python tools/deep_stress_eval.py --phases 3,5,6 1>> $out 2>> $err
$ec2 = $LASTEXITCODE
# Mock bench acceptance via scorer
python bench/aci/runners/run_suite.py --mode mock 1>> $out 2>> $err
$ec3 = $LASTEXITCODE
python bench/aci/scorers/score.py bench/aci/results/latest.json --require-accept 1>> $out 2>> $err
$ec4 = $LASTEXITCODE
Set-Content $done -Value "cargo=$ec1 deep=$ec2 suite=$ec3 score=$ec4"
