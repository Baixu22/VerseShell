# 观察质检报告（jev_obs_judge）

- 生成时间：2026-09-23T07:51:05.933925+00:00
- 判定模式：`heuristic`（judge=deterministic-heuristic）
- 样本来源：`eval\manifest.json`、`eval\metrics.json`、`bench/aci/results/latest.json`
- 样本数：13；诊断足够：10；剧本可执行：9
- 说明：本脚本只做窄判定（观察是否够修 / 剧本是否可执行），不生成修复代码，不替代正则 reducer。

| 样本 | profile | 诊断足够 | 剧本判定 | 剧本 op | source |
|------|---------|---------|---------|--------|--------|
| fixture_cargo_e0308 | cargo | True | actionable | file.view → file.replace_exact → exec.run | `tests/fixtures/reducers/cargo_e0308.txt` |
| fixture_pytest_fail | pytest | True | actionable | file.view → file.replace_exact → test.run_target | `tests/fixtures/reducers/pytest_fail.txt` |
| fixture_npm_fail | npm_install | False | no_locatable_site | - | `tests/fixtures/reducers/npm_fail.txt` |
| adv_cargo_fail_multi_error | cargo | True | actionable | file.view → file.replace_exact → exec.run → file.view → file.replace_exact | `tests/fixtures/reducers/adversarial/cargo_fail_multi_error.txt` |
| adv_cargo_fail_noisy | cargo | True | actionable | file.view → exec.run | `tests/fixtures/reducers/adversarial/cargo_fail_noisy.txt` |
| adv_cargo_fail_panic | cargo | True | actionable | file.view → exec.run | `tests/fixtures/reducers/adversarial/cargo_fail_panic.txt` |
| adv_cargo_fail_malformed | cargo | True | actionable | file.view → file.replace_exact → exec.run | `tests/fixtures/reducers/adversarial/cargo_fail_malformed.txt` |
| adv_pytest_fail_multi | pytest | True | actionable | file.view → file.replace_exact → test.run_target → file.view → file.replace_exact → test.run_target | `tests/fixtures/reducers/adversarial/pytest_fail_multi.txt` |
| adv_pytest_fail_no_header | pytest | True | actionable | file.view → test.run_target → file.view → test.run_target → file.view → test.run_target | `tests/fixtures/reducers/adversarial/pytest_fail_no_header.txt` |
| adv_git_fail_not_repo | git | False | no_locatable_site | - | `tests/fixtures/reducers/adversarial/git_fail_not_repo.txt` |
| adv_git_fail_conflict | git | False | actionable | file.view → file.replace_exact → exec.run → file.view → file.replace_exact | `tests/fixtures/reducers/adversarial/git_fail_conflict.txt` |
| adv_npm_fail_enoent | npm_install | True | no_locatable_site | - | `tests/fixtures/reducers/adversarial/npm_fail_enoent.txt` |
| adv_npm_fail_network | npm_install | True | no_locatable_site | - | `tests/fixtures/reducers/adversarial/npm_fail_network.txt` |

## 逐条理由

### fixture_cargo_e0308 · tests/fixtures/reducers/cargo_e0308.txt
- 诊断足够：True (value=1.0) — reducer kept 1 error diagnostic(s)；raw output carries path:line anchor；expected/found extracted (1/1)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### fixture_pytest_fail · tests/fixtures/reducers/pytest_fail.txt
- 诊断足够：True (value=1.0) — reducer kept 1 error diagnostic(s)；raw output carries path:line anchor；expected/found extracted (1/1)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### fixture_npm_fail · tests/fixtures/reducers/npm_fail.txt
- 诊断足够：False (value=0.4) — reducer kept 6 error diagnostic(s)；no path:line anchor in raw output；no code or diff evidence in raw output
- 剧本：no_locatable_site — no locatable failure site in the observation; a file-level playbook would be fabricated

### adv_cargo_fail_multi_error · tests/fixtures/reducers/adversarial/cargo_fail_multi_error.txt
- 诊断足够：True (value=1.0) — reducer kept 2 error diagnostic(s)；raw output carries path:line anchor；failure class without expected/found pair (message/code level only)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_cargo_fail_noisy · tests/fixtures/reducers/adversarial/cargo_fail_noisy.txt
- 诊断足够：True (value=1.0) — reducer kept 1 error diagnostic(s)；raw output carries path:line anchor；failure class without expected/found pair (message/code level only)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_cargo_fail_panic · tests/fixtures/reducers/adversarial/cargo_fail_panic.txt
- 诊断足够：True (value=0.7) — reducer kept 1 error diagnostic(s)；raw output carries path:line anchor；no code or diff evidence in raw output
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_cargo_fail_malformed · tests/fixtures/reducers/adversarial/cargo_fail_malformed.txt
- 诊断足够：True (value=1.0) — reducer kept 1 error diagnostic(s)；raw output carries path:line anchor；failure class without expected/found pair (message/code level only)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_pytest_fail_multi · tests/fixtures/reducers/adversarial/pytest_fail_multi.txt
- 诊断足够：True (value=1.0) — reducer kept 2 error diagnostic(s)；raw output carries path:line anchor；expected/found extracted (2/2)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_pytest_fail_no_header · tests/fixtures/reducers/adversarial/pytest_fail_no_header.txt
- 诊断足够：True (value=0.7) — reducer kept 3 error diagnostic(s)；no path:line anchor in raw output；failure class without expected/found pair (message/code level only)
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_git_fail_not_repo · tests/fixtures/reducers/adversarial/git_fail_not_repo.txt
- 诊断足够：False (value=0.4) — reducer kept 1 error diagnostic(s)；no path:line anchor in raw output；no code or diff evidence in raw output
- 剧本：no_locatable_site — no locatable failure site in the observation; a file-level playbook would be fabricated

### adv_git_fail_conflict · tests/fixtures/reducers/adversarial/git_fail_conflict.txt
- 诊断足够：False (value=0.4) — reducer kept 2 error diagnostic(s)；no path:line anchor in raw output；no code or diff evidence in raw output
- 剧本：actionable — view -> edit -> rerun with complete argument keys

### adv_npm_fail_enoent · tests/fixtures/reducers/adversarial/npm_fail_enoent.txt
- 诊断足够：True (value=0.7) — reducer kept 7 error diagnostic(s)；no path:line anchor in raw output；failure class without expected/found pair (message/code level only)
- 剧本：no_locatable_site — no locatable failure site in the observation; a file-level playbook would be fabricated

### adv_npm_fail_network · tests/fixtures/reducers/adversarial/npm_fail_network.txt
- 诊断足够：True (value=0.7) — reducer kept 5 error diagnostic(s)；no path:line anchor in raw output；failure class without expected/found pair (message/code level only)
- 剧本：no_locatable_site — no locatable failure site in the observation; a file-level playbook would be fabricated

