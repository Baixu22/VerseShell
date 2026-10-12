# Claim / selected-input / version map

Gate predicates and thresholds are unchanged. Status is scoped to the selected evidence; no formal effect claim is granted here.

| claim | gate result | scoped status | recorded n | value / threshold | actual inputs |
|---|---|---|---:|---|---|
| C1 | pass | historical_only | 35 | 0.1086 / <= 0.50 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest.json |
| C2 | pass | historical_only | 35 | 0.5629 / <= 0.70 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest.json |
| C3 | pass | verified_selected_measurement | 4 | 1.0 / >= 0.90 | C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.metrics.json |
| C4 | pass | verified_selected_measurement | 5 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.metrics.json |
| C5 | pass | verified_selected_measurement | 15 | 0.7143 / >= 0.70 (conditional on the agent emitting ops) | C:\Users\27933\Desktop\verseshell\verseshell\eval\aci_learning_probe.json |
| C6 | pass | verified_current_check | 4 | 1.0 / all pass | current source/test receipt or missing binding |
| C7 | pass | verified_current_check | 290 | 1.0 / all pass | current source/test receipt or missing binding |
| C8 | pass | verified_current_check | 3 | 1.0 / all pass | current source/test receipt or missing binding |
| C9 | pass | verified_selected_measurement | 7 | 0.4203 / >= 0.40 | C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.compact-ratio.json |
| C10 | pass | verified_current_check | 19 | 1.0 / all pass | C:\Users\27933\Desktop\verseshell\verseshell\eval\readme_claims.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\cross_shell.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.compact-ratio.json |
| C11 | pass | historical_only | 5 | 0.1834 / <= 0.50 | C:\Users\27933\Desktop\verseshell\verseshell\eval\cross_shell.json |
| C12 | FAIL | not_met | 25 | 0.0 / all artifacts fresh | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\jev_obs_report.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\cross_shell.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\tf45_envelope_replay.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_token_breakdown.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\read_path_breakdown.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\read_usage_audit.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_failure_breakdown.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\step_composition.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\ts_fixture_audit.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_audit.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\aci_learning_probe.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\live_uncertainty.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\budget_sensitivity.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\task_design_audit.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\projection_contract.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\token_proxy_calibration.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\task_admissibility.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_freeze.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\three_arm_report.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_encoding_contract.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_exec_contract.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\statistics_crosscheck.json |
| C13 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\live_ab_without_read_files.json |
| C14 | FAIL | not_met | 141 | 0.045 / >= 0.15 | C:\Users\27933\Desktop\verseshell\verseshell\eval\tf45_envelope_replay.json |
| C15 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_token_breakdown.json |
| C16 | FAIL | not_met | 141 | 0.0789 / >= 0.10 | C:\Users\27933\Desktop\verseshell\verseshell\eval\read_path_breakdown.json |
| C17 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\eval\read_usage_audit.json |
| C18 | pass | historical_only | 3 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_failure_breakdown.json |
| C19 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_failure_breakdown.json |
| C20 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\eval\step_composition.json |
| C21 | not gated | diagnostic_only | None | diagnostic | C:\Users\27933\Desktop\verseshell\verseshell\eval\ts_fixture_audit.json |
| C22 | pass | historical_only | 5 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_failure_breakdown.json |
| C23 | pass | historical_only | 3 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\ts_fixture_audit.json |
| C24 | FAIL | not_met | 35 | 0.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_audit.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\task_sets\3.1.0.json |
| C25 | pass | historical_only | 630 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\live_ab_without_read_files.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\live_uncertainty.json |
| C26 | pass | historical_only | 8 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\projection_contract.json |
| C27 | pass | historical_only | 60 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\token_proxy_calibration.json |
| C28 | pass | historical_only | 105 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\cross_shell.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json |
| C29 | pass | historical_only | 52 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\task_admissibility.json |
| C30 | pass | historical_only | 2 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\projection_contract.json |
| C31 | pass | historical_only | 3 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_encoding_contract.json |
| C32 | pass | historical_only | 7 | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_exec_contract.json |
| C33 | pass | historical_only | None | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\three_arm_report.json |
| C34 | FAIL | not_met | 141 | 0.5736 / >= 0.40 and measured on a fresh artifact from a task set newer than 2.0.0 | C:\Users\27933\Desktop\verseshell\verseshell\eval\read_path_breakdown.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_freeze.json |
| C35 | FAIL | not_met | None | 0.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\live_ab_without_read_files.json |
| C36 | pass | verified_selected_measurement | None | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json |
| C37 | pass | historical_only | None | 1.0 / == 1.00 | C:\Users\27933\Desktop\verseshell\verseshell\eval\statistics_crosscheck.json<br>C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\live_uncertainty.json<br>C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json |

## Input versions

- bench/aci/results/latest.json: C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest.json
  - sha256: 63c02b164cafc9d3720c86b1513fa7b858658ea6e4858673de3ade174efcc629; currency: historical_or_unverified
  - version: {"schema": "verseshell.aci_bench.results/v1", "generated_at": "2026-09-30T01:03:33.363161+00:00", "task_set_version": "3.0.0", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0", "mode": "mock"}
  - source identity: null
  - binary: {}
- bench/aci/results/latest_live.json: C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\latest_live.json
  - sha256: e73732e9a702ccfa0d5638e708c958773b81673ad4c49aa2dda137b8f822fa86; currency: historical_or_unverified
  - version: {"schema": "verseshell.aci_bench.results/v1", "generated_at": "2026-09-29T21:10:37.484634+00:00", "task_set_version": "3.0.0", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0", "mode": "live"}
  - source identity: null
  - binary: {}
- bench/aci/results/live_ab_without_read_files.json: C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\results\live_ab_without_read_files.json
  - sha256: 61bf357114e495b8b80c3e786f95821fb844e614a9206d272390c2ee659f282d; currency: unverified_source_binding
  - version: {"schema": "verseshell.aci_bench.results/v1", "generated_at": "2026-09-30T00:51:46.993212+00:00", "task_set_version": "3.0.0", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0", "mode": "live"}
  - source identity: null
  - binary: {}
- eval/acceptance_power.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\acceptance_power.json
  - sha256: 27b7aabab0a98cfaadd0d1aa6d68c041b46eb637a9614ef0609efcc944cff632; currency: fresh
  - version: {"schema": "verseshell.acceptance_power/v1", "generated_at": "2026-10-10T05:44:35.986506+00:00", "task_set_version": "3.0.0", "model": "sn-glm-5-3-flash", "prompt_variant": "baseline"}
  - source identity: null
  - binary: {}
- eval/aci_learning_probe.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\aci_learning_probe.json
  - sha256: a40b7ed17424414cf858572aec4ef54c61f7a3b979c40b53d9ee32a5cfd38e7b; currency: fresh
  - version: {"schema": "verseshell.aci_learning_probe/v1", "generated_at": "2026-09-24T21:17:29.856672+00:00", "model": "sn-glm-5-3-flash", "protocol": "quickstart doc only as system prompt; no tool schemas; one shot; every emitted op executed through the real ae --serve --agent"}
  - source identity: null
  - binary: {}
- eval/budget_sensitivity.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\budget_sensitivity.json
  - sha256: 4b542f9f595182ac79267ea2201bdec86f45a83825fc4fd1ff118e93491da225; currency: fresh
  - version: {"schema": "verseshell.budget-sensitivity/v1", "generated_at": "2026-10-10T07:22:55.035919+00:00"}
  - source identity: null
  - binary: {}
- eval/compact_ratio.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.compact-ratio.json
  - sha256: f486dd3979e57efdbed9458ac3ae3be34325862bf50618c1af40cb64a0dbd017; currency: generated_in_this_gate
  - version: {"schema": "verseshell.compact-ratio/v1"}
  - source identity: null
  - binary: {}
- eval/cross_shell.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\cross_shell.json
  - sha256: 9c98156a6b528f9b9e1bc38d97ad7080d023bb95f1ddd493e63163043e6c517d; currency: historical_or_unverified
  - version: {"schema": "verseshell.cross-shell/v2", "generated_at": "2026-09-30T01:05:33.021611+00:00", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0"}
  - source identity: null
  - binary: {}
- eval/exec_failure_breakdown.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_failure_breakdown.json
  - sha256: d937d1f882b97f2f996e3ffadac33cd7c529293e9f3fd647dffbb30db15674ca; currency: historical_or_unverified
  - version: {"schema": "verseshell.exec-failure-breakdown/v1", "generated_at": "2026-09-30T01:07:55.736520+00:00"}
  - source identity: null
  - binary: {}
- eval/exec_token_breakdown.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\exec_token_breakdown.json
  - sha256: 82c79a4bae0c1917177e008da754b15b9c4dc966223ea2e6f386436ebc800dee; currency: fresh
  - version: {"schema": "verseshell.exec-token-breakdown/v1", "generated_at": "2026-09-30T01:07:50.006656+00:00"}
  - source identity: null
  - binary: {}
- eval/harness_encoding_contract.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_encoding_contract.json
  - sha256: 80266a0c96e354407ddd347934598273dd52f8a3435f19d9bf6f691c7c5729b5; currency: historical_or_unverified
  - version: {"schema": "verseshell.harness_encoding_contract/v1", "generated_at": "2026-09-29T13:27:41.457767+00:00"}
  - source identity: null
  - binary: {}
- eval/harness_exec_contract.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\harness_exec_contract.json
  - sha256: 5ac6028c13abb3bd0cb217316cd5cdcf748e1e51b9ef85017cbc27370a84c6f5; currency: historical_or_unverified
  - version: {"schema": "verseshell.harness_exec_contract/v1", "generated_at": "2026-09-29T13:28:39.173446+00:00"}
  - source identity: null
  - binary: {}
- eval/jev_obs_report.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\jev_obs_report.json
  - sha256: 9aa4d7195a3c5b46455c6a20f63a61f8c9759425116f2a3bb3c62b5940c70b29; currency: historical_or_unverified
  - version: {"schema": "verseshell.jev-obs-report/v1", "generated_at": "2026-09-30T02:21:30.603261+00:00", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0", "mode": "heuristic"}
  - source identity: null
  - binary: {}
- eval/live_uncertainty.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\live_uncertainty.json
  - sha256: e4353da4bcda77809fec3fcff71fe15539d63db5aef1b15969751fccbca08daa; currency: historical_or_unverified
  - version: {"schema": "verseshell.aci_live_uncertainty/v1", "generated_at": "2026-10-10T05:43:26.929420+00:00"}
  - source identity: null
  - binary: {}
- eval/metrics.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\evidence.metrics.json
  - sha256: 30b30fff3b09197a3c7bdac7e04232184a439accea3510ea4d76f394a54aa1df; currency: generated_in_this_gate
  - version: {"schema": "verseshell.eval-metrics/v1"}
  - source identity: null
  - binary: {}
- eval/projection_contract.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\projection_contract.json
  - sha256: 451f5be080503cbfeb65e97b2d5d2efbf88478f0ce87d06e4fdace63beba44e2; currency: historical_or_unverified
  - version: {"schema": "verseshell.projection_contract/v1", "generated_at": "2026-09-29T13:27:41.197075+00:00", "protocol": "every check runs a real op through `ae --serve --agent` and inspects the projection format_aci_result hands to the model"}
  - source identity: null
  - binary: {}
- eval/read_path_breakdown.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\read_path_breakdown.json
  - sha256: 19adcbcea47247b38f7041f90ad537babb82f696913ae5ef2a5dba7b3fe82e4e; currency: historical_or_unverified
  - version: {"schema": "verseshell.read-path-breakdown/v1", "generated_at": "2026-09-30T01:06:49.656267+00:00"}
  - source identity: null
  - binary: {}
- eval/read_usage_audit.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\read_usage_audit.json
  - sha256: 3bfe9feffed0e9165c38221af4ba0d5d115ae9dcc7b25967f1507dfcf843894c; currency: historical_or_unverified
  - version: {"schema": "verseshell.read-usage-audit/v1", "generated_at": "2026-09-30T01:07:49.908492+00:00"}
  - source identity: null
  - binary: {}
- eval/statistics_crosscheck.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\statistics_crosscheck.json
  - sha256: 36b074684e90c002b49a3a111d42b74f02ec7e0ac7d75b6ae0a770c15373d611; currency: historical_or_unverified
  - version: {"schema": "verseshell.statistics_crosscheck/v1", "generated_at": "2026-09-30T07:59:06.743894+00:00"}
  - source identity: null
  - binary: {}
- eval/step_composition.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\step_composition.json
  - sha256: 428c809d88388a241b7fe08e0271566b00eecb453c98a7a9bc4bb4776af76f71; currency: historical_or_unverified
  - version: {"schema": "verseshell.step-composition/v1", "generated_at": "2026-09-30T01:07:55.849763+00:00"}
  - source identity: null
  - binary: {}
- eval/task_admissibility.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\task_admissibility.json
  - sha256: 9de489c260a017d971af7137cc90776233c799c93ec66f32355c7f6876028beb; currency: historical_or_unverified
  - version: {"schema": "verseshell.task_admissibility/v1", "generated_at": "2026-09-30T01:03:02.361152+00:00", "protocol": {"repeats": 2, "min_variants": 2, "large_obs_min_tokens": 1000, "admit_confirm_repeats": 16, "verifier_patterns": ["test_*.py", "*_test.py", "conftest.py", "tests/**/*.py", "*_test.rs", "tests/**/*.rs", "*.test.ts", "*.spec.ts", "*.test.js", "*.spec.js", "tests/**/*.ts", "test_*.sh", "*_test.sh"], "note": "A1-A5, A4a and A8 run live_agent_loop.check_success or the predicate's own command, the same evaluator the live runner uses. A4a is the mechanical anti-gaming check; the LLM shortcuts are informational because a passing one is ambiguous. A8 measures the raw-shell observation of the pristine state so `tier=large` is enforced rather than hoped for, counting the dump after the measured-volatile substrings (temp paths, elapsed times, thread ids, object addresses, cargo progress lines) are normalised away and recording the raw count alongside. A3 measures every variant 2 times like A1/A2 and fails closed on an unstable verdict list, so a flaky verifier cannot admit a task; a candidate that would still be admitted is re-measured 16 more times per overlay before it enters the set. When A1/A2/A3/A5 do see conflicting verdicts the predicate is not deterministic, so its pristine dump is not a reproducible measurement either: A8 records pristine_observation_tokens=null with the sample it took and fails closed rather than publishing a number that changes every run"}}
  - source identity: null
  - binary: {}
- eval/task_design_audit.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\task_design_audit.json
  - sha256: 3164b22be2c1d05592d49048f93fd0b25a989266ceb30cc119b791579c40d84b; currency: historical_or_unverified
  - version: {"schema": "verseshell.task-design-audit/v1", "generated_at": "2026-09-30T08:05:45.956349+00:00", "task_set_version": "3.0.0"}
  - source identity: null
  - binary: {}
- eval/task_set_audit.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_audit.json
  - sha256: 5250cf9b43c7b01e12310e6796cc42514d0e7b34cb31f882fb1aa1be6931c3fe; currency: historical_or_unverified
  - version: {"schema": "verseshell.task-set-audit/v1", "generated_at": "2026-09-30T01:07:49.794937+00:00", "task_set_version": "3.0.0"}
  - source identity: null
  - binary: {}
- eval/task_set_freeze.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\task_set_freeze.json
  - sha256: f481564aeea4f1310c56a944f9868eed7442e9722975b09298abd6389c220833; currency: fresh
  - version: {"schema": "verseshell.task_set_freeze/v1", "generated_at": "2026-09-28T04:37:02.706878+00:00", "task_set_version": "3.0.0"}
  - source identity: null
  - binary: {}
- eval/tf45_envelope_replay.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\tf45_envelope_replay.json
  - sha256: ff2cfaa9fed1629f79f96f7a825d11b82fe01dd61d1532fef40f267c47dd5704; currency: historical_or_unverified
  - version: {"schema": "verseshell.tf45-envelope-replay/v1", "generated_at": "2026-09-30T01:06:12.034907+00:00"}
  - source identity: null
  - binary: {}
- eval/three_arm_report.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\three_arm_report.json
  - sha256: cc2a24530e9e3a0d5b9975b0bc628ff93e79b9c83c384ea9f2ca0e017480cff0; currency: historical_or_unverified
  - version: {"schema": "verseshell.three_arm_report/v1", "generated_at": "2026-10-10T05:44:12.376124+00:00", "task_set_version": "3.0.0", "model": "sn-glm-5-3-flash", "prompt_variant": "baseline"}
  - source identity: null
  - binary: {}
- eval/token_proxy_calibration.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\token_proxy_calibration.json
  - sha256: 5124587ac2cf30009a483717145530f81bd1ae73c2b03fa50a54b1f4e0f1dae2; currency: historical_or_unverified
  - version: {"schema": "verseshell.token_proxy_calibration/v1", "generated_at": "2026-09-30T01:48:49.892356+00:00", "git_rev": "a8d4c56c45093d0a7d650d96afe3dd561d80e5b0", "model": "sn-glm-5-3-flash"}
  - source identity: null
  - binary: {}
- eval/ts_fixture_audit.json: C:\Users\27933\Desktop\verseshell\verseshell\eval\ts_fixture_audit.json
  - sha256: 398d743308e1f38c47a20516a7d8767ce13413c0da6a641dd6cda2a1cd7138b1; currency: historical_or_unverified
  - version: {"schema": "verseshell.ts-fixture-audit/v1", "generated_at": "2026-09-30T01:06:49.807385+00:00"}
  - source identity: null
  - binary: {}
- @task_set: C:\Users\27933\Desktop\verseshell\verseshell\bench\aci\task_sets\3.1.0.json
  - sha256: 11d48acf71c30974381176bea549e68e0db1057b8d33dce108ec2fc1b6108376; currency: definition_or_execution_receipt
  - version: {"task_set_version": "3.1.0"}
  - source identity: null
  - binary: {}
- @readme_check: C:\Users\27933\Desktop\verseshell\verseshell\eval\readme_claims.json
  - sha256: 2cc3ffe21bb38ed5409d03a65bf885a1d9ec1588a53990c5378790960913501e; currency: generated_in_this_gate
  - version: {"schema": "verseshell.readme-claims/v1", "generated_at": "2026-10-12T00:27:50.024287+00:00"}
  - source identity: null
  - binary: {"path": "target\\debug\\ae.exe", "sha256": "d2de460585a5a231f3376ffd166be511e345a73d8f1e610612ed36e7c858f95b"}

A current consistency check on historical data does not recertify acquisition, author independence, or product effectiveness.
