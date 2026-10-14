# Agent Shell 横向对比汇总：VerseShell D 层 vs 对照，以及与竞品的位置（2026-10-14）

本文把当前所有轮次的 L4 证据横向汇总，回答三件事：
1. VerseShell observation 层（arm D）相对 raw shell（A）与 matched raw（A prime）到底有没有收益；
2. 收益在 5 轮里稳不稳定；
3. 这个结果相对 agentsh / microsandbox / SWE-ReX 等同类产品处在什么位置。

口径提醒：本文所有数字都是**单机、单 seed、诊断级**，不是正式 benchmark，也不与 Codex/Claude Code 等完整 harness 混做同系结论。

## 一、L4 全部 5 轮横向表（20 题 x 3 臂 = 60 格/轮）

| 轮次 | ae / 预算 | A | A prime | D | D-A prime | D obs | Ap obs | 裁决 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| l4-final-20261012 | 64c59cbf / 16c-300s | 0.70 | 0.60 | 0.55 | -0.05 | 4716 | 1639 | INVALID |
| l4-final-20261012-r2 | 64c59cbf / 32c-600s | 0.80 | 0.80 | 0.60 | -0.20 | 5433 | 1657 | NO_EVIDENCE |
| l4-slim-r3-20261013 | afe227ca / 32c-600s | 0.80 | 0.75 | 0.80 | **+0.05** | 3491 | 1892 | POSITIVE |
| l4-envelope-r4-20261013 | 12b427a9 / 32c-600s | 0.75 | 0.75 | 0.70 | -0.05 | 5445 | 3269 | INVALID |
| l4-budget48-r5-20261013 | 12b427a9 / 48c-900s | 0.60 | 0.75 | 0.80 | **+0.05** | 5901 | 3104 | POSITIVE |

**关键读数**：5 轮里 D-A prime 分别是 -5 / -20 / +5 / -5 / +5 pp。两次 POSITIVE 各只有 +5pp（净 +1 题）。

## 二、统计显著性：没有一轮显著

对每轮做 A prime vs D 的配对 McNemar 精确二项检验（win = 只有该臂成功的题）：

| 轮次 | D 独赢 | A prime 独赢 | 精确 p |
|---|---|---|---|
| l4-final | T402, T414, T417 (3) | T404, T405, T409, T418 (4) | 1.000 |
| l4-final-r2 | T416 (1) | T401, T405, T406, T408, T409 (5) | 0.219 |
| l4-slim-r3 | T407, T409 (2) | T402 (1) | 1.000 |
| l4-envelope-r4 | T409, T417 (2) | T402, T404, T408 (3) | 1.000 |
| l4-budget48-r5 | T408, T411 (2) | T405 (1) | 1.000 |

**合并 5 轮 x 20 题 = 100 次配对：D 独赢 10 次，A prime 独赢 14 次。**
也就是说，把轮次噪声平均掉之后，D 相对 matched raw **没有净优势，甚至略负**。
两次 POSITIVE 都建立在"净 +1 题"这种量级上（二项 sd 约 1.4-1.9 题），属于噪声敏感结果。

## 三、逐题稳定性：哪些题真的偏向 D

5 轮里同一题 D/A prime 各自成功次数：

| 题 | D 成功/5 | A prime 成功/5 | 倾向 |
|---|---:|---:|---|
| T407 | 1 | 0 | 略偏 D（唯一解决者） |
| T411 | 4 | 3 | 略偏 D |
| T417 | 4 | 2 | 略偏 D |
| T414 | 5 | 4 | 略偏 D |
| T416 | 5 | 4 | 略偏 D |
| T405 | 2 | 5 | **明显偏 A prime** |
| T404 | 3 | 5 | 偏 A prime |
| T401 | 4 | 5 | 偏 A prime |
| T418 | 4 | 5 | 偏 A prime |
| T403/T410/T412/T415/T419 | 5 | 5 | 双饱和，无区分度 |
| T420 | 0 | 0 | 双失败，无区分度 |

可读的结论：D 在 **T407（超时清理）/T411（安全边界）/T417** 上确实偶有优势，与"失败 envelope 帮模型恢复"的设计意图一致；
但 **T405 等题上 D 明显更差**，整体抵消。且 5 题的饱和（双 5/5）说明该 tier 部分题区分度不足。

## 四、成本：D 始终显著更贵

| 轮次 | obs tokens D/A prime | tool calls D/A prime | model calls D/A prime |
|---|---:|---:|---:|
| l4-final | 2.88x | 1.48x | 1.28x |
| l4-final-r2 | 3.28x | 1.57x | 1.49x |
| l4-slim-r3 | 1.85x | 1.15x | 1.16x |
| l4-envelope-r4 | 1.67x | 1.44x | 1.17x |
| l4-budget48-r5 | 1.90x | 1.19x | **0.88x** |

- 瘦身（r3 的 afe227ca）把 obs 比从 3.28x 压到 1.85x，这是**唯一稳定且明确的改进**。
- 后续 A1-A5（12b427a9）没有进一步降低 obs 比（1.67x / 1.90x）。
- 唯一 D 占优的维度是 r5 的 model calls（0.88x），即 D 让模型少跑了一轮，但每轮观察更贵。
- 效率门槛（obs -20%）**从未达到过**。

## 五、非 L4 的证据

### 10 题主设计（p1，handoff 预注册主设计）

| 轮次 | A | A prime | D | D-A prime | D obs | Ap obs | 裁决 |
|---|---:|---:|---:|---:|---:|---:|---|
| p1-r2 | 0.80 | 0.90 | 0.90 | 0.00 | 1031 | 588 | NO_EVIDENCE |
| p1-r3 | 0.90 | 1.00 | 1.00 | 0.00 | 1002 | 580 | NO_EVIDENCE |
| p1-envelope-r4 | 0.90 | 1.00 | 1.00 | 0.00 | 846 | 504 | NO_EVIDENCE |

D 在 10 题设计上连续 3 轮追平 A prime，但**永远只是追平，从未超过**，且 obs 始终约 1.7-1.9x。

### 分层抽样（L1/L2/L3 各 5 题）

| 轮次 | A | A prime | D | 裁决 |
|---|---:|---:|---:|---|
| sampler | 0.60 | 0.80 | 0.67 | NO_EVIDENCE |
| sampler2 | 0.93 | 1.00 | 0.93 | NO_EVIDENCE |
| sampler3 | 1.00 | 1.00 | 1.00 | NO_EVIDENCE |

简中难层饱和，无区分度。

## 六、与同类产品的位置（引用前轮源码级对比）

### 6.1 能力维度（agent shell / 执行层）

| 能力 | VerseShell D 层 | agentsh 0.20.5 | microsandbox 0.7.8 | SWE-ReX 1.4.0 |
|---|---|---|---|---|
| OS 级隔离 | 无（依赖宿主 runtime） | Landlock/seccomp（WSL2 仅 40/100） | **microVM，最强** | LocalRuntime 无 |
| 策略/网络/凭证治理 | 无 | **最强（policy/approval/audit）** | 中（network 规则） | 弱 |
| 冷启动 | 不适用（叠加层） | 快 | **0.98s** | 快 |
| warm exec P50 | 不适用 | 31.6ms | 59.2ms | 中 |
| stdout/stderr + exit code 契约 | **强（typed observation）** | 强 | 强 | **弱（exit_code 丢失、混流）** |
| 失败 recovery 结构 | **最强（status/blocked/substitutions/suggested_next/diagnostics）** | 强（ExecGuidance） | 弱 | 弱 |
| 大输出处理 | artifact handle | 完整 | 1MB 完整 | 一般 |
| 超时/进程清理 | 一般 | 好 | **正确** | **不杀底层进程** |
| 并行 | 一般 | 20/20 | 20/20 | 设计最好 |

### 6.2 结构差距（吸收后的现状）

VerseShell 相对 agentsh 的信息层结构差距在 2026-10-13 已基本补齐：

| agentsh ExecGuidance 字段 | VerseShell 现状 |
|---|---|
| Status (ok/failed/blocked) | 已有（A4） |
| Retryable | 已有（recoverable，A3 改为有依据推导） |
| Substitutions[] | 已有（A2，已知工具映射） |
| Suggestions[] | 已有（suggested_next，原有且更结构化） |
| BlockedOperation / BlockedTarget | 已有（A5） |
| PolicyRule | **仍缺**（安全模型不同，不强求） |
| Diagnostics[] | VerseShell **独有且更强** |

实测触达（r5，D 的 298 次观察 / 22 次失败）：status、blocked_operation、suggested_next 覆盖率 21/22 = 95%；substitutions 1/22（只在已知工具缺失触发）。

### 6.3 但结构补齐没有转成收益

这是本轮最重要的负面发现：**把 agentsh 的 guidance 形状吸收完之后，成功率没有改善**。
5 轮 100 次配对里 D 10 胜 vs A prime 14 胜。可能的解释（均为待验证假说，非结论）：
1. 模型对结构化 guidance 的利用率低——r5 实测 20 条 suggested_next **0 条被照抄执行**；
2. 该 tier 的失败多来自"模型本身的错误判断"（T402/T420 型），而不是"缺信息"；
3. 部分题双饱和（T403/T410/T412/T415/T419），本来就无法产生区分度。

## 七、与完整 harness 的关系（不要混淆）

前轮 harness 对比（3 题、同模型 sn-glm-5-3-flash）显示：

| 产品 | 判分 | 平均 wall | 平均 tokens | 工具失败 |
|---|---:|---:|---:|---:|
| OpenCode | 3/3 | 69.0s | 25.6k | 1 |
| VerseShell ACI | 3/3 | 59.4s | 27.3k | 0 |
| Codex CLI | 3/3 | 101.3s | 194.1k | 18 |
| Qwen Code | 3/3 | 长尾，1 次撞 600s | 中等 | 0 |

该对比里 VerseShell ACI 与 OpenCode 同档，但 raw shell 在 2 个完成任务上更省 token。**这与 l4 的结论一致：VerseShell 的收益不在 token 效率上。**

## 八、总结（一句话版）

1. **收益**：L4 上测得 +5pp 两次，但配对检验 p=1.000，合并 100 次配对后 D 反输 A prime（10 vs 14）。**目前没有可复现的净正收益证据。**
2. **成本**：唯一稳定结论是 **D 的 observation token 约 1.7-1.9x raw**（瘦身后从 3.3x 降下来）；效率门槛从未达标。
3. **产品位置**：执行层上 microsandbox 最强（我们已采用它做执行层）；治理层 agentsh 最强；VerseShell 的价值应定位为**可插在它们之上的 typed observation / failure-recovery 层**，其结构（diagnostics、substitutions、blocked_*）已基本对齐或超过 agentsh，但**尚未证明能提升任务成功率**。
4. **方法论收获**：r4 的 INVALID 证明固定 32c/600s 预算会制造 13% 假异常；抬到 48c/900s 后异常降到 8.3%。任何后续测量都必须先保证预算不成为混淆项。

## 九、下一步建议

1. **多 seed 验证**：单 seed 下 +5pp 与噪声不可分。建议 48c/900s x 3 seeds 跑 L4（约 9h，需授权）。
2. **换测量视角**：成功率已在部分题饱和，建议改为测量"首错后恢复所需步数"与"失败后模型是否采用 guidance"（当前 0/20 采纳率是明确的改进靶点）。
3. **接受成本定位**：若 obs token 无法压到 raw 的 0.8x，就应把 VerseShell 的卖点明确为"信息质量"而非"token 效率"。
4. **不要继续加预算**：r5 已证明再加预算不会修复成功率差异，只会抬高墙钟。

## 十、诚实边界

- 单机、单 seed、诊断级；不构成对外结论。
- 所有横比均为跨轮次观察，ae 二进制、预算、端点状态在各轮间不完全相同；已逐条标注。
- 公开榜单与其他产品数据来自 2026-10-12 前轮抓取，可能已过时。
- 未提交 / 未合并 / 未推送；未改 Task Forest；全部旧轮与失败样本保留。
