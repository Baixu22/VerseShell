# Step 5 Preview 真实开发试点收尾（2026-10-09）

> 终版：已纳入主代理核对的离线审计。仅为已知开发任务的工程诊断，不是正式研究、产品门禁或默认分支落地验收。本次打包没有新增 API 调用、测试或编译。

## 1. 范围与实现

开工 HEAD `a8d4c56`，原有 **419 项脏改动**不计作本轮贡献。精确补丁依据本轮 `original/` 原字节，而非 HEAD；只含 **4 生产文件、6 修改测试、4 新测试、预注册文档、本总结与 repo 提案，共 17 文件**。未对整棵 419 项脏树逐字节核验。

- `live_round` 新增有序 `--tasks`，冻结实际子集、六组合 schedule 和显式 child 参数；默认整集也不再传 `--full`，更换集合拒绝复用，formal floor 按实际选中任务计数，防止意外全量。
- `prelive_probe` 用 JSON nonce 输入，严格复制完整 Unicode/标点；工具参数、最终回复均要求完整相等。成功/失败保留 expected nonce，readiness 同时绑定探针源码 SHA，拒绝旧版探针凭证。
- Windows 可信屏障使用 base interpreter；工作负载原有 venv 命令、`-I`、Job/on_start/permit 次序不变。既有 fixture 修正真实输入形状、局部缓存隔离和真实 owner PID，未放宽断言、关闭缓存 resolver 或改账号/代理。
- `prelive_check` 的 Rust 测试通过 env 与 `--target-dir` 使用独立 `out/rust-tests-target`，保留其它环境变量；固定候选路径及初始 SHA，每 stage、synthetic 后及 ACI smoke 后核验，ready 只发布原候选摘要。

生产文件：[tools/live_round.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/live_round.py)、[tools/prelive_probe.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/prelive_probe.py)、[bench/aci/runners/live_agent_loop.py](C:/Users/27933/Desktop/verseshell/verseshell/bench/aci/runners/live_agent_loop.py)、[tools/prelive_check.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/prelive_check.py)。

新增测试：[tests/test_live_task_selection.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_live_task_selection.py)、[tests/test_probe_nonce_contract.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_probe_nonce_contract.py)、[tests/test_managed_launch_interpreter.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_managed_launch_interpreter.py)、[tests/test_readiness_binary_integrity.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_readiness_binary_integrity.py)。

修改测试（均有本轮原字节备份）：[tests/test_readiness_sources.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_readiness_sources.py)、[tests/test_endpoint_probe_evidence.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_endpoint_probe_evidence.py)、[tests/test_prelive_repairs.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_prelive_repairs.py)、[tests/test_live_cli_contract.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_live_cli_contract.py)、[tests/test_live_recovery.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_live_recovery.py)、[tests/test_live_owner_lock.py](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_live_owner_lock.py)。

设计依据：[预注册文档](C:/Users/27933/Desktop/verseshell/verseshell/docs/step5p-development-preregistration-2026-10-09.md)；R1/R2/R3 只修订候选/绑定路径，没有结果驱动地改变三任务、三条件、双变体或预算。

## 2. 保留的失败与最终验证链

| 阶段 | 已确认事实 | 原始证据 |
|---|---|---|
| 旧冻结首次连接性 | 1 请求、HTTP 200、378 tokens；中文 nonce 前缀未保留，probe exit 2。没有丢弃失败。 | [旧探针 JSON](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/connectivity/endpoint-probe.json) / [执行回执](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/connectivity/result.json) |
| 局部 RED | task selection 6 tests/8 failures；nonce 5/8；readiness probe-source pin 14/3；均保留原始断言失败。 | [两个新测试回执](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/regression-red/results.json) / [源码 pin RED](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/regression-red/test_readiness_sources.result.json) |
| v1 readiness | Python 427 tests，2 failures/1 error；venv redirector PID 与 owner PID、暖缓存 fixture 假设不成立，拒绝真实启动。 | [v1 Python 原日志](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation/readiness/python-tests.log) |
| 屏障兼容性 | fake managed-launch 3 tests/1 failure；修正后 base/venv 与受管入口均验证，旧错误保留。 | [RED](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/compatibility-regressions/managed-launch-red.result.json) / [兼容性 GREEN](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/compatibility-green/r2-freeze-ready.json) |
| v2 readiness | Python 430、Rust 289 passed/1 ignored、35 fixture、3 校准通过，但候选 binary 被改写，停止并保留 v2。 | [v2 readiness](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r2/readiness/readiness.json) |
| 独立 Cargo 诊断 | `cargo test --no-run` 的编译本身可替换同 target 的 ae；源码/index 未变，无模型调用，不把它归为模型或他人改源码。 | [独立复现](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/binary-diagnosis/evidence/02-cargo-test-no-run.json) |
| Binary gate | 4 tests/5 failures 的 RED 后，独立 target/漂移拒绝/完整假流程控制通过；fake 数据仅在临时目录，不是真 readiness。 | [RED](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/binary-gate-regressions/red/result.json) / [GREEN](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/binary-gate-regressions/green/r3-freeze-ready.json) |
| R3 完整 readiness | Python **434/0 skip**；Rust **289 passed/1 ignored**；35 fixture；3 校准；3150 synthetic、0 重复调用、0 模型 API；ACI smoke 均完成。 | [R3 readiness](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/readiness/readiness.json) / [ACI smoke](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/readiness/aci-smoke.json) |
| R3 严格 probe | 2 逻辑请求/2 HTTP 200；完整中文 nonce 两轮严格匹配；pass、usage_complete；846 tokens；exit 0。 | [probe](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/candidate-probe-r3/endpoint-probe.json) / [绑定审计](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/candidate-probe-r3/execution-audit.json) |
| R3 pilot | 18 格全提交且唯一；controller 与两个 variant 各七文件报告链均 exit 0；**1689.265 秒 < 2700 秒**；整轮仅执行一次。 | [执行汇总](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/pilot-control-r3/execution-summary.json) / [controller/report 终态](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/workspace/bench/aci/results/step5p-dev-20261009-01a11efe-r3/control/568cde5f119c4e5281e56632c918dc8e/reports-1f483c5e90be40f5856e13558a08a475/reports-status.json) |

各阶段门禁/定向测试不是独立研究样本，不把它们相加为研究重复数。R3 候选从初始、每 stage、synthetic 后、smoke 后、final 到当前都为：

`0808842a43e50453da759709e0f5c851537ff93dca53c28d51c1e6185030980b`

397 项源码、env、计划、探针与 binary 在实际 probe/pilot 前后绑定一致；原始请求尝试及 v1/v2/诊断/原研究资料未写改或删除。旧冻结未迁移为新证据。

## 3. 终版离线审计：不补造未知

输入 [latest_live.json](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/workspace/bench/aci/results/step5p-dev-20261009-01a11efe-r3/latest_live.json)，SHA256：

`d19c71693c1d74750859de284de213393d7a98cd0b6d1eb816e751d96b702d1c`

[analysis-completion.json](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/live-analysis/analysis-completion.json) / [ANALYSIS_SUMMARY.md](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/live-analysis/ANALYSIS_SUMMARY.md)。四个离线命令均 exit 0、未超时，输入、R3 源、extra、binary 和已有 controller 报告均未变：

| 离线命令 | exit | timeout | 秒 |
|---|---:|---|---:|
| turn-diagnostics | 0 | false | 1.015 |
| usage-audit | 0 | false | 1 |
| final-workspace-audit | 0 | false | 14.172 |
| variant-and-stopping-analysis | 0 | false | 1 |

| 口径 | success | failure | unknown |
|---|---:|---:|---:|
| 原评分记录 | 13 | 5 | 0 |
| 独立可重建结论 | 8 | 4 | 6 |

全部 **18 cell 显式选择复评分**；12 份快照可用并全部重评分，**12/12 与原记录匹配**。6 份 node_envconfig 快照因 credential material 不可用，`storage_fault=false`，所以独立终态是 unknown，不能回填为成功。原 fixture [check.mjs:8](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/workspace/bench/aci/fixtures/node_envconfig_validate_dd681123/check.mjs) 的测试凭据字面量本身足以触发通用规则（不展示值）；这不证明六个修改后目录内容相同，不能从旧 fixture 猜造终态。**不能关闭安全检测、补造快照或以原 fixture 替代修改后内容。**

原记录五个失败全部是 `turn_limit`；completion 截断 0、api_error 0。原 ACI 6/6 只是这三个已知开发任务的小样本记录，不能说成正式优越或历史 bug 全部消失。

## 4. 重复信号与具体反例

[停止行为记录](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/live-analysis/stopping-behavior.json)：csvlite raw_shell 两变体最长均 **13** 次完全相同工具+参数；compact_all coached 为 **9**；leaderboard compact_all ACI 为 **2**；其余各格为 **1**。这是模式信号，不是自动因果或运行时 bug 判定。

主代理逐条核对的 csvlite raw_shell baseline 反例，命令概括为 `python -c "body=...; print(len(body))" > out.txt 2>&1`（不是完整命令转录）。[原观察 f8c524…](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/validation-r3/workspace/bench/aci/results/step5p-dev-20261009-01a11efe-r3/with_seed42.json.observations/f8c5247648469f20d8fb45be879989142a79095f0e8deb350041f220190ed312.json) 中 STDERR 为“系统找不到指定的文件。”，EXIT 1；stderr **24 bytes 完整**，`windows-oem-936`、`lossy=false`。观察文本 SHA256：

`ef9066a89c5d71f4c39870c6e4a3a37cf1520ca44c9ba4e54e4067d895cc759e`

错误与退出码确实可见，仍发生无进展重复。Windows 内联引号/重定向仅是待复现解释，不能仅凭这条轨迹定性执行器缺陷，更不能改写已有结果。下一步应在**独立新开发方案**中复现，并设计对所有条件一致的停止或提示规则，不给某一条件临时加提醒。

## 5. Usage 双口径与禁止越界的结论

18 行 usage_complete；**244 个记录请求尝试，unknown_usage_attempts=0**。Pilot 共 **1,325,465 prompt + 115,951 completion = 1,441,416 tokens**，不含 probe 的 846。没有供应商账单对账，token 不代表金额或实际费用降低。

compact_all 下，D=ACI、A=raw_shell，3 个配对：

| 口径 | 完整值 | 方向 |
|---|---:|---|
| ratio_of_sums = sum(D)/sum(A) | 0.9528803396895095 | 小于 1 |
| cell_equal_mean_of_ratios = mean(D/A) | 1.406016156284289 | 大于 1 |

两个权重口径方向相反，必须并列，**不能报单一“省 token 成功”**。以原始 comparison 为准，baseline 与 compact_all 都 `claimable=false`，`policy_blocked_reasons` 均包括：

- `complete_repeated_study_not_evaluated`
- `exclusion_rate_above_10pct`
- `frozen_family_inference_not_evaluated`

统计/停止分析未改变输入、原评分或 controller 报告；行级策略工具未请求全 comparison 的对象差异不等于各臂指标不一致，审计已分别核对实际指标。

## 6. 下一步与治理

优先处理 csvlite 重复/轮次耗尽的可复现机制，以及“冻结 fixture 测试凭据字面量使精确快照不可用”的安全证据方案。保持安全拦截，不把当前 6 个未知补成成功，不回头改本次条件、预算或结果。

正式三次完整独立重复、新的独立困难/大观察任务与留出来源（TF-0112/0114/0115/0123）、正式产品/默认分支落地均未完成。后续源码或设计变更仍须独立冻结/门禁与明确授权。

本次提案只更新 TF-0120/0121/0132/0133/0134/0136/0137 的 summary、next_action，并在完整旧数组后追加 evidence/source_sessions；**状态、进度、阈值均不变，不新建节点、不 done**。只 proposal-save/validate，不 apply/export，不手编 canonical 或改锁。

[精确补丁](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/implementation.diff) / [最终 manifest](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/change-manifest.json)。本轮真实采集和报告链完成，不与 task success 或正式研究资格混同。
