# TF-0136 独立冻结验收与完成提案

日期：2026-10-10（Asia/Shanghai）。**此前的磁盘前置已解除，完整离线工程验收通过；按 TF-0136 原有三条标准建议工程收口，完成提案尚未应用。** TF-0132 的真实模型停止行为仍待明确授权的新试点。

## 本轮范围

- 主库开工 HEAD 为 a8d4c56c45093d0a7d650d96afe3dd561d80e5b0，433 项既有脏改动。没有新增生产代码修复，也未重置、暂存、提交、合并或清理旧证据；只新增本记录和完成提案。
- 新验证副本：[workspace](D:/VerseShellLive/node-freeze-20261010-01a120ce/workspace)。本地 Git clone 禁用 hooks、无对象 hardlinks，按当前源码清单覆盖原字节，不从 HEAD 猜测当前改动。
- **399 个源码文件 + 58 个辅助输入**分别冻结并核对；Cargo 仅复制依赖缓存，编译 target 从空目录开始。测试、构建、评分副本及主要缓存位于 D 盘，保留 Windows 必需环境变量。
- [预定验收方案](D:/VerseShellLive/node-freeze-20261010-01a120ce/validation-plan.md)、[源码/辅助输入清单](D:/VerseShellLive/node-freeze-20261010-01a120ce/copy-manifest.json)、[环境](D:/VerseShellLive/node-freeze-20261010-01a120ce/environment.json)、[缓存来源](D:/VerseShellLive/node-freeze-20261010-01a120ce/cache-provenance.json)。

## 完整工程门禁结果

| 项目 | 结果 | 证据 |
|---|---|---|
| 候选冷构建 | exit 0、未超时，353.078 秒；没有复制编译 target | [回执](D:/VerseShellLive/node-freeze-20261010-01a120ce/cold-build.result.json) |
| Python 全量 | **462/462，无跳过**，exit 0 | [日志](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/python-tests.log) |
| Rust 全量 | **289 passed，1 ignored**，exit 0；原有 ic_verseshell_benchmark 保持忽略 | [日志](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/rust-tests.log) |
| 现有任务评分审计 | **35/35**；不是新生成的困难/留出任务 | [报告](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/task-audit.json) |
| 运行间区间校准 | 3/10/30 运行配置，均通过，各 2000 次校准模拟 | [r3](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/calibration-r3.json) / [r10](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/calibration-r10.json) / [r30](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/calibration-r30.json) |
| 合成采集/恢复/合并/推断 | **3150 个合成格、3 个合成运行、0 重复派发、10 项假设；合成主张被拒绝** | [readiness](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/readiness.json) |
| 原生 ACI smoke | 文件读取与 argv 执行通过 | [原始回执](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness/aci-smoke.json) |
| 整体 readiness | exit 0、timeout=false，789.204 秒 | [执行回执](D:/VerseShellLive/node-freeze-20261010-01a120ce/readiness.result.json) |

新的候选 SHA256：**0192c5cf21787603e4a7392ae1cb35e3965cc9957eec37f39a94dcf641cffebe**。Rust 测试使用独立 target；每阶段及 synthetic/smoke 后的候选摘要保持一致。[最终身份核对](D:/VerseShellLive/node-freeze-20261010-01a120ce/final-verification.json) 全部通过，主库源码、冻结副本、辅助输入、候选和分析计划均无漂移。

readiness 的 ready_for_live=true **仅表示离线工程前提通过**；endpoint_verified=false、empirical_claims_approved=false。没有发起端点探针或真实模型请求；3150 个合成格不是三次真实独立研究。

## 快照及独立复评分

使用原 envconfig fixture 的 pristine/GOLDEN × 三条件 × 双变体，重新执行 **12 个脚本化控制**；模型与工具响应被替换，Node 评分器真实执行。原评分为 **6 通过 / 6 不通过**，全部在第三次重复调用后停止，第三次观察已保存。

- 无外置验证器源：**12 unknown、0 次复评分**。
- 显式提供新冻结副本中的验证器源：**12/12** 恢复与复评分匹配，仍为 **6 通过 / 6 不通过**。
- 另启动独立 CLI 进程，工作区原件已清理后，从保存的快照及明确的验证器源再次恢复：**12/12 一致**，exit 0。
- fixture 摘要不变，敏感验证器原文不在 snapshot blob 中。没有关闭安全拦截，也没有以旧 fixture 推测学生修改后的文件。

[联动控制](D:/VerseShellLive/node-freeze-20261010-01a120ce/guard-fixture-matrix/summary.json)、[无源结果](D:/VerseShellLive/node-freeze-20261010-01a120ce/guard-fixture-matrix/without-source.json)、[独立 CLI 结果](D:/VerseShellLive/node-freeze-20261010-01a120ce/cli-independent-rescore.json)、[CLI 命令与退出码](D:/VerseShellLive/node-freeze-20261010-01a120ce/cli-independent-rescore.result.json)。这些是工程控制，不是模型成功率或收益证据。

## 历史缺失仍明确保留

| 输入 | 本轮只读核验 | 不能推出的结论 |
|---|---|---|
| 原 Step 5，1050 格 | **0/1050 有最终快照**；1050 个唯一格逐项列明未记录终态。原记录 911 成功/139 失败不变 | 不是原评分正确性的追认，更不是全量独立重评分 |
| R3 开发试点，18 格 | **12/18** 旧快照当前仍可验；6 格因凭据保护缺失，保持 unknown。原记录13/5不变 | 本轮未重评分旧 R3；保留的旧独立审计12/12一致不冒充本轮新评分 |
| 本次新离线控制，12 格 | 有明确冻结源时 **12/12** 独立复评分一致 | 不与上面两组混合分母，不补造旧六格 |

[1050 格清单](D:/VerseShellLive/node-freeze-20261010-01a120ce/historical-step5-final-workspaces.json)、[原记录边界](D:/VerseShellLive/node-freeze-20261010-01a120ce/historical-step5-boundary.json)、[R3 当前完整性清单](D:/VerseShellLive/node-freeze-20261010-01a120ce/historical-r3-current-inventory.json)、[R3 原审计绑定](D:/VerseShellLive/node-freeze-20261010-01a120ce/historical-boundary.json)。旧 TypeScript 17/30 单文件候选仍只是轨迹解析候选，不是完整工作区重建证明。

## TF-0136 收口判断

[逐条验收对照](D:/VerseShellLive/node-freeze-20261010-01a120ce/acceptance-review.json) 使用原有三条标准，没有删改条款或降低阈值：

1. 已逐格记录不可重建样本及具体原因，区分原记录与独立复核能力。
2. 已明确未来评分输入的最小冻结范围、外置源要求和可信边界，并在 D 盘冻结、核对摘要。
3. 已对可重建控制做独立 CLI 复评分并报告完整分母；历史缺失保留，不伪造覆盖。

因此建议 **TF-0136=done / 100%（工程工作完成，不是100%历史数据覆盖）**。仅保存 [完成提案](C:/Users/27933/Desktop/verseshell/verseshell/.agent-workbench/task-forest/proposals/TFP-tf0136-frozen-closeout-2026-10-10.json)，等待用户确认；正式森林状态尚未改变。TF-0132 只更新冻结证据与下一步，不关闭。

真实端点/模型行为、独立困难/来源/留出任务、正式重复研究、产品门禁及默认分支落地，继续由 TF-0120/0132、TF-0112/0114/0115/0123、TF-0140/0141 跟踪。没有把这些后继验收包装为通过。

后续使用本冻结副本及其 [分析计划](D:/VerseShellLive/node-freeze-20261010-01a120ce/analysis-plan.json)；源码变化后须重新冻结。请保留快照 blobs/manifests 和明确的外置验证器源，不能只保留报告 JSON。编译缓存也不在本轮自动清理范围内。
