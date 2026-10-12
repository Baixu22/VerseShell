# 采集/恢复故障场景覆盖对照（2026-10-10）

范围：TF-0122 的 AC5——把原恢复验收要求逐条对照最新 readiness 与真实 live，记录
**已覆盖**与**剩余**故障场景。本文件不新增门槛，也不以文字替代验证；每条“已覆盖”
都必须指向一次真实执行或一个测试，未执行的一律列在“剩余”。

## 对照用的两条基线

- 原恢复验收要求：`docs/repair-live-closure-handoff-2026-09-29.md` 的 11 项 backlog
  （P1-1 合并/partial、P1-3 逐格补跑、终止边界、owner lock）以及
  `docs/terminal-boundary-recovery-2026-10-09.md`、`docs/owner-lock-recovery-2026-10-09.md`。
- 最新 readiness：`D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/readiness.json`
  - ready_for_live=true、exit 0、timeout=false
  - Python 462 项无 skip；Rust 289 passed / 1 原样 ignored
  - endpoint_verified=false、empirical_claims_approved=false（离线前提，不是研究结论）
- 本轮真实 live：`D:/VerseShellLive/node-freeze-20261010-01a120ce/workspace/bench/aci/results/step5p-dev-20261010-r2/`
  （18 格，`repeat_call_limit=3`，控制 exit 0）。

## 逐条对照

| # | 恢复验收要求 | 覆盖状态 | 证据 |
|---|---|---|---|
| 1 | partial 合并保留原始失败行，端点失败行 `success=null`、原值存 `raw_success` | 已覆盖 | `bench/aci/runners/merge_live_runs.py`（逐行 `row_class`）；本轮真实 partial 产物含 1 个 `endpoint_failure`、3 个 `cap_truncated`、14 个 `analysable` |
| 2 | 所有行由同一个 `row_class()` 分类，门禁能机检 partial 产物 | 已覆盖 | `tools/claim_gate.py::live_run_composition` 从原始字段重分类并列出受影响行/对比；`tests/test_partial_live_merge.py` 7 项 |
| 3 | 严格模式拒绝错误行且不写产物；`--allow-api-errors` 才落 partial | 已覆盖 | `tests/test_partial_live_merge.py::test_strict_merge_rejects_errors_and_writes_nothing` 等 |
| 4 | 采集中断后恢复**不重复提交**、不丢已提交行、格身份不变 | 已覆盖 | 2026-10-10：venv launcher Job 误杀后 6 行 checkpoint 原样保留，`--resume-paused` 打印 `already in checkpoint` 跳过，格身份 hash 未变 |
| 5 | 中断请求结局未知时不得补造/补零 | 已覆盖 | 同一轮 `success=null` 行保留；独立复评分结论单列 False，未回填原记录 |
| 6 | 终止边界复用 STOP/磁盘检查，保留已提交格并 exit 75 | 已覆盖 | `docs/terminal-boundary-recovery-2026-10-09.md`（408 tests 离线、注入 ENOSPC 于 `os.replace`） |
| 7 | owner lock 独占、陈旧锁恢复、同实例重入不丢互斥 | 已覆盖 | `docs/owner-lock-recovery-2026-10-09.md`（412 项完整离线、40 次重复） |
| 8 | 采集退出码可靠落盘，冲突终态拒绝成功 | 已覆盖 | 本轮 `control/*/collection-exit.json`：`process_exit_code=0` 与 `round.status` 一致，`exit_basis=process_and_terminal` |
| 9 | 逐格补跑拒绝 merged 输入、按原预算/seed 原子落盘 | 已覆盖 | `tools/splice_live_cells.py` + `tests/test_partial_live_merge.py`、`tests/test_splice_live_cells.py` |

## 剩余（本文件不覆盖，继续由后续节点跟踪）

| 场景 | 现状 | 归属 |
|---|---|---|
| D/C 阈值、非法策略、不可用盘 | **已覆盖**（注入读数，不填满真实磁盘） | TF-0134 已完成 |
| 强制终止控制器时的跨进程回收（collection/round/report 三阶段） | **已覆盖**：`test_forced_controller_death_kills_collection_and_report_trees` 断言无孤儿进程树 | TF-0134 已完成 |
| 持续写盘失败（磁盘一直满） | **已覆盖**：`test_sustained_write_failure_stays_failed_and_never_dispatches_more` —— 不产出成功产物、不派发后续格、状态保持 failed | TF-0134 已完成 |
| TEMP/缓存/构建/**评分副本**落 D 盘 | **已覆盖**：`runtime-path-verification.json` —— 18/18 构建目录与 18/18 评分副本在 D，C 盘无该 tag 残留 | TF-0134 已完成 |
| POSIX 上的锁/终止语义 | 未实测（本轮全为 Windows 实测） | 未分配 |
| 完整独立重复与跑间不确定性 | 只有单次采集 | **TF-0112** |
| 产品声明与默认分支落地 | 未对齐 | **TF-0140 / TF-0141** |

## 边界

本文件只登记“哪些故障路径真的被执行过”。它不证明模型效果、不替代正式研究、
不改变 §0.6 的任何比例阈值，也不把 partial 产物升级为可主张的完整研究。

## 本轮发现的测试隔离缺陷（已修）

组合运行 11 个恢复/合并测试文件时，
`tests/test_live_control.py::ControlTests::test_finalize_rejects_incomplete_tampered_and_extra_manifests`
稳定失败：`ValueError: collection owner is still alive; refusing report recovery`。
单独运行该文件 15/15 通过；同一组重复运行 102 passed / 1 failed 复现两次。

根因不是生产语义错误：`live_control.finalize()` 的「记录 PID 仍存活则拒绝恢复」
是刻意 fail-closed 契约（由 `test_new_generation_and_live_owner_cannot_finalize` 钉住，
本轮未改）。失败来自**该用例把「子进程已退出」当作环境事实**：Windows 会复用 PID，
同一次 pytest 会话里其它用例新建的进程可能恰好拿到那个已退出子进程的 PID，
于是一次只检验 manifest 校验的用例被无关进程的存活状态干扰。

修复限于测试隔离：给该用例加 `@patch.object(control, 'pid_alive', return_value=False)`，
并注明它检验的是 manifest 校验、owner 存活契约另有测试覆盖。生产代码未改。

| 阶段 | 结果 | 证据 |
|---|---|---|
| 修复前（11 文件组合） | 102 passed, 1 failed（连续两次复现） | `D:/VerseShellLive/freeze-live-20261010/recovery-coverage-tests-rerun.log` |
| 失败用例单跑 | 1 passed | `D:/VerseShellLive/freeze-live-20261010/live-control-fail.log` |
| 单文件整跑 | 15 passed | 本轮 `pytest tests/test_live_control.py` |
| 修复后（11 文件组合） | **103 passed** | `D:/VerseShellLive/freeze-live-20261010/recovery-coverage-tests-afterfix.log` |

## TF-0134 收尾补记（2026-10-10）

`docs/collection-control-repairs-2026-10-08.md` 曾写明两处「不在本批已证明范围」：
控制器/整机强制终止时的跨进程回收，以及持续写入故障下的边界。前者已由
`tests/test_remaining_node_boundaries.py` 的三阶段强制终止用例覆盖；后者本轮补上
`test_sustained_write_failure_stays_failed_and_never_dispatches_more`，
断言持续写盘失败时不产出成功产物、不再派发后续格、状态保持 failed（写不出的诊断
以失败收场，而不是假装当前格可无损恢复）。

旧的 `control-repair-20261008/evidence/runtime-paths.json` 自述
`future frozen scoring copies not certified`；本轮 `runtime-path-verification.json`
对该项做了实测认证（18/18 构建目录、18/18 评分副本在 D 盘，C 盘无同 tag 残留）。
原始 C 盘失败证据（`D:/VerseShellLive/control/run-live.ps1` 与
`D:/VerseShellLive/control/`）未被改写。
