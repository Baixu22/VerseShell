$env:AETHER_APPROVE_ALL='1'
Set-Location 'C:\Users\27933\Desktop\verseshell\verseshell'
cargo test --test operation_protocol_tests --test semantic_reducer_tests --test aci_1_0_ops_tests --test aci_1_0_closed_loop_acceptance --test aci_bench_mock_acceptance -- --test-threads=1 1> 'bench\aci\results\test_run.out' 2> 'bench\aci\results\test_run.err'
$ec = $LASTEXITCODE
Set-Content -Path 'bench\aci\results\test_run.done' -Value $ec
