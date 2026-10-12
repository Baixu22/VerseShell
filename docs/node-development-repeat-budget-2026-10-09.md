# 节点开发：统一重复预算与安全快照联动

日期：2026-10-09（Asia/Shanghai）。本轮推进 TF-0132，并验证其与 TF-0136 v2 快照的联动；**代码与离线验证完成，独立完整冻结及真实模型行为验收未完成**。

## 范围和预注册

开工为 430 项既有脏改动。仅修改 5 个生产文件，新增 1 个测试文件、本记录及未应用提案，共 8 个仓库文件；精确差分基于本轮 original/ 原字节，不把既有改动算作本轮贡献。

[开发前预注册](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/preregistration.md) SHA256：8a7b726728dd686f3919fca60075c1d12c4cab11136e9078fe0236420130292d。没有修改历史输入、任务集合、fixture、正式阈值或原 max_turns/max_tokens；没有真实模型请求。

## TF-0132：可选、统一、可追溯的停止预算

- 新参数 **--repeat-call-limit**：默认 0 关闭，显式整数 >=2 启用；本次脚本控制固定为 3。默认关闭时，与开工原代码在三条件 × 双变体上的 API 边界消息和工具列表逐项相等。
- 启用时所有条件追加同一条预算说明。共享分支按工具名、解析后的实际参数（JSON 键排序）及完整模型可见观察计算指纹；任一变化都会重置连续计数。**相同观察不证明文件系统没有进展**，这里只是一个显式预算。
- 第 N 次观察先完整记录，再停止本批次剩余工具和后续模型请求；stop_reason=repeat_call_limit，记录本批次未执行工具数。task_complete 保持原有立即停止行为。
- 独立评分和最终快照照常执行，不把重复停止直接改判成功或失败。统计沿用 cap_truncated、原保守 ITT 和 10% 门槛，不能用新停止策略选择有利样本。
- 参数贯穿控制器配置、child CLI、运行身份、行记录、恢复/复用、合并和独立重复研究。混合阈值、缺少启用配置却声称重复停止、非法类型均被拒绝；历史缺字段仅按关闭读取。

生产改动：[live_agent_loop.py](C:/Users/27933/Desktop/verseshell/verseshell/bench/aci/runners/live_agent_loop.py)、[live_identity.py](C:/Users/27933/Desktop/verseshell/verseshell/bench/aci/runners/live_identity.py)、[live_round.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/live_round.py)、[live_uncertainty.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/live_uncertainty.py)、[repeated_run_uncertainty.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/repeated_run_uncertainty.py)。没有新增依赖。

## 回归与保留的失败

| 阶段 | 实际结果 | 证据 |
|---|---|---|
| 原实现上的首轮新测试 | 14 tests，22 failures / 20 errors，exit 1（含 subtest） | [RED](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/red.log) |
| 首轮接线 | 脚本模型夹具错误使用调用签名，14 tests / 15 failures；修正夹具后 14/14 | [保留日志](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/green-first.log) / [14 项通过](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/green.log) |
| 首轮完整 Python | 460/460，exit 0 | [首轮完整日志](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/python-full.log) |
| 反向用例 | 16 tests / 3 failures：未配预算的停止标签被两处统计入口接受；JSON 孤立代理字符使指纹编码失败 | [反向 RED](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/inverse-red.log) |
| 最终定向回归 | 16/16，exit 0 | [最终 GREEN](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/green-final.log) |
| 最终完整 Python | **462/462，无跳过，exit 0、timeout=false**；195.609 秒 | [完整日志](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/python-full-final.log) / [执行回执](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/python-full-final.result.json) |
| 默认关闭兼容性 | 6/6 条件/变体组合，原代码与新代码的消息和工具列表相等 | [兼容性](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/default-off-compatibility-final.json) |

[新测试](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_repeat_call_guard.py) 包含批次内停止、参数/观察/操作变化重置、task_complete、独立失败、v2 源要求、身份与恢复、合并与重复研究、错误停止标签和 JSON 边界。

## TF-0136：12 格联动控制，不是 12 次真实模型成功

使用原 envconfig fixture 的 pristine/GOLDEN 两种状态 × 三条件 × 双变体，共 **12 个离线控制**。模型返回和工具结果均为脚本化；Node 独立评分实际执行，fixture 前后摘要一致。

- 每格在 3 次相同调用后停止，第三次观察保留；原独立评分为 **6 通过 / 6 不通过**。
- 12 份 v2 快照均为 requires_verifier_source；不提供源时 **12 unknown、0 次复评分**。
- 显式提供同一冻结验证器源、核验路径/大小/摘要后，**12/12 复评分与原判定一致**。
- 敏感验证器原文不在 snapshot blob 中，原 v2 安全检查没有关闭。12 格全部按预算截断处理，比较不可主张。

[完整联动证据](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/guard-fixture-matrix/summary.json)、[逐格原始记录](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/guard-fixture-matrix/rows.json)、[显式源复评分](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/guard-fixture-matrix/with-source.json)。这不能证明真实模型已改善，也不能替代或补造 R3 旧六份缺失终态。

## 独立完整冻结：仍未开始

冻结预检 **exit 75**。最后一次正式预检 D 盘约 **14.105 GiB**，低于既定 **15 GiB** 门槛；C 盘通过。没有降低门槛、删除旧证据或启动新的完整克隆/冷构建，ready_for_live=false。

[冻结预检](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/freeze-precheck-final.json) / [回执](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/freeze-precheck-final.result.json)。本地 Python 回归复用前轮已知摘要的 Rust 候选，不是新的独立冻结验收；主 Rust 候选未重建，也没有本轮独立 Rust 289 项门禁。

已准备 [下一份分析计划候选](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/next-analysis-plan.json)，仅刷新分析源码 SHA，假设、阈值与样本量下限均不变；[只读绑定检查](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/analysis-plan-check.result.json) 通过。这仍不是 readiness，也不是模型采集授权。

## 后续与治理

先恢复足够 D 盘空间，重新建立独立冻结副本并运行完整 readiness；然后在明确授权的新开发试点中验证策略是否改善真实重复行为和最终快照覆盖。没有把脚本化结果当作研究结论。

只保存并验证 [节点进度提案](C:/Users/27933/Desktop/verseshell/verseshell/.agent-workbench/task-forest/proposals/TFP-repeat-budget-node-dev-2026-10-09.json)，不修改 status/progress、不 apply/export、不提交或合并。原 27 个开放节点不因本次离线测试自动关闭。

[精确补丁](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/implementation.diff) / [文件与验证清单](D:/VerseShellLive/node-dev-stop-policy-20261009-01a120ce/change-manifest.json)。
