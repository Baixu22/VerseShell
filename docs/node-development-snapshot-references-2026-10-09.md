# 节点开发：Windows 重复命令复现与安全快照引用

日期：2026-10-09（Asia/Shanghai）。范围：TF-0132（关联 TF-0130）、TF-0136。**本轮是离线工程开发，不是新模型试点、正式研究或产品验收。**

## 开工和改动边界

- 开工 HEAD：a8d4c56c45093d0a7d650d96afe3dd561d80e5b0；分支保持不变。开工 git status --short 为 **427 项既有脏改动**，本轮补丁以保存的原字节为基线，不以 HEAD 冒充本轮贡献，也未逐字节核验整棵脏树。
- 仅修改两个生产文件：[final_workspace.py](C:/Users/27933/Desktop/verseshell/verseshell/bench/aci/runners/final_workspace.py)、[final_workspace_audit.py](C:/Users/27933/Desktop/verseshell/verseshell/tools/final_workspace_audit.py)。修改既有测试的内部 scan 回调参数，新增一个 12 项测试文件；另新增本记录及一个未应用提案，共 6 个仓库文件。
- 没有改动执行器、模型提示、工具 schema、停止规则、预算、任务集合、fixture 或评分谓词。没有真实模型/API 请求，没有提交、合并或清理原有改动。

## TF-0132 / TF-0130：把待验证解释变成可复现证据

上一轮 raw_shell / baseline CSV 样本的同一命令累计出现 14 次，最长连续 13 次。本轮只重放已审阅的、构造字符串并打印长度的命令；AST 检查限定其为一个字符串常量赋值和 print(len(body))，工作目录在本轮 D 盘目录。

- 原命令 1302 字符，SHA256：eaa680033a137026d6823810c73833c4f7f46112f3a1522570f1a36f149d7e14。
- 原观察 SHA256：f8c5247648469f20d8fb45be879989142a79095f0e8deb350041f220190ed312；原观察文本 SHA256：ef9066a89c5d71f4c39870c6e4a3a37cf1520ca44c9ba4e54e4067d895cc759e。

| 离线路径 | 退出码 | 结果 |
|---|---:|---|
| 原命令 / 受管 shell | 1 | stderr 24 bytes，windows-oem-936，lossy=false，未超时 |
| 原命令 / 原生 cmd | 1 | 与受管 shell 的 stderr 完全相同，未超时 |
| 同一 Python 负载 / 直接 argv | 0 | 正确打印字符串长度 |
| 同一负载 / 脚本文件 | 0 | 正确打印字符串长度 |
| Python PATH + 重定向简单对照 | 0 | 排除 Python 不可达 |
| 最小内联双引号 + 小于号对照 | 1 | cmd 将引号后的元字符按 shell 语义解释 |
| 去掉内联双引号 / 去掉小于号 | 0 / 0 | 前者重定向正常；后者的输出去向也显示引号改变了 shell 解析 |
| 原负载去掉小于号 / 原负载脚本经 cmd | 0 / 0 | 与引号及重定向解释一致 |

这是**该命令**的 Windows shell 解析机制证据，不是受管屏障额外引入的失败；既有错误和退出码确实可见。没有据此给所有轮次耗尽样本归因，也没有证明模型已停止重复调用。没有添加某一条件专属提醒或启发式自动停止；后续若调整提示/停止策略，仍须预先定义所有条件一致的规则并使用新冻结方案。

证据：[原命令四路径复现](D:/VerseShellLive/node-dev-20261009-01a120ce/reproduction.json)、[六项机制对照](D:/VerseShellLive/node-dev-20261009-01a120ce/cmd-controls.json)、[离线开发方案](D:/VerseShellLive/node-dev-20261009-01a120ce/development-plan.md)。

## TF-0136：保留安全拦截，而不是忽略测试凭据

新增 **verseshell.final-workspace/v2**：

1. 仍调用既有凭据检测。只有通用检测命中、且文件 SHA256 与运行前 protected_verifiers 中同一路径严格一致时，记录 storage=protected_verifier；**敏感文件原文不写入 snapshot blobs/manifest**。
2. 显式运行凭据、含敏感值的路径、未冻结文件、新生成文件或已漂移的验证器仍拒绝。普通文件仍保存精确 bytes、mode、大小与摘要；双次扫描、路径/重解析点、文件数量与大小限制保留。
3. 引用快照明确标记 state=requires_verifier_source，不是自包含的 available。默认审计仍 unknown，不会自动找原 fixture 补齐。
4. 调用方须用 --verifier-source TASK_ID=DIRECTORY 显式提供冻结源。仅引用条目的路径、大小、SHA256 和 protected 绑定全通过后，才允许完整恢复；普通学生文件只能从已保存 blob 恢复，不能从外置源推断。缺源、错源、源漂移或伪造引用均不触发评分。
5. 新 manifest 同时绑定快照实现与凭据检测源码。v1 普通快照仍可读取，但新旧源码身份不同不能自动重新认证旧评分。

[12 项新回归](C:/Users/27933/Desktop/verseshell/verseshell/tests/test_final_workspace_references.py) 覆盖显式凭据拒绝、普通/外置存储、缺源 unknown、错源/重定向/漂移、引用伪造、旧缺失不升级、清理工作区后的复核、CLI 只读与 v1 读取。

## 本轮验证

| 检查 | 结果 | 回执 |
|---|---|---|
| 修复前新测试 | 12 tests，1 failure / 7 errors，exit 1 | [RED](D:/VerseShellLive/node-dev-20261009-01a120ce/regression-red/references.log) |
| 修复后快照相关测试 | 30/30，exit 0 | [定向 GREEN](D:/VerseShellLive/node-dev-20261009-01a120ce/regression-green/references.log) |
| 全量 Python 回归 | **446/446，无跳过，exit 0**；进程 172.019 秒 | [完整日志](D:/VerseShellLive/node-dev-20261009-01a120ce/python-full-suite.log) / [退出回执](D:/VerseShellLive/node-dev-20261009-01a120ce/python-full-suite.result.json) |
| 真实 envconfig fixture，默认无外置源 | pristine / GOLDEN 两份均 unknown，0 次评分 | [默认审计](D:/VerseShellLive/node-dev-20261009-01a120ce/without-explicit-source.json) |
| 同两份新离线快照，显式提供并核验冻结源 | 2/2 复评分匹配，分别为失败 / 成功；fixture 字节未变 | [显式审计](D:/VerseShellLive/node-dev-20261009-01a120ce/with-explicit-source.json) / [汇总](D:/VerseShellLive/node-dev-20261009-01a120ce/future-fixture-summary.json) |

完整 Python 测试的 TEMP、主要依赖缓存及候选副本位于本轮 D 盘目录。主 Rust 候选没有重新构建：从 R3 候选复制，前后 SHA256 为 0808842a43e50453da759709e0f5c851537ff93dca53c28d51c1e6185030980b；当前全部 src/Rust 与 Cargo 清单摘要和 R3 一致，Python 回归包含原生 ACI 调用。**本轮没有重跑独立 Rust 289 项门禁，也没有发布新的完整 readiness。**

## 不能越过的边界与下一步

- 上一轮 18 格结果与报告保持原样；原记录 13 成功 / 5 失败，已有独立复核 8 成功 / 4 失败 / 6 未知。新格式不能补造那六份已经缺失的终态；本轮两个 fixture 控制不是那六格的恢复或新成绩。
- 新格式需要可持续保留、显式绑定的冻结验证器源，不是自包含的跨机器证据包；运行时环境/工具链/网络仍不在快照证明范围内。
- TF-0132 真实停止行为、TF-0136 新真实试点覆盖、正式重复/独立困难与留出来源、产品门禁、默认分支落地仍未完成。后续真实运行需新冻结和明确授权。
- 只保存并验证 [进度提案](C:/Users/27933/Desktop/verseshell/verseshell/.agent-workbench/task-forest/proposals/TFP-snapshot-references-node-dev-2026-10-09.json)，更新三个节点的 summary/next_action 并完整追加 evidence/source_sessions；不修改 status/progress/阈值，不 apply/export，不关闭节点。

本轮精确补丁与清单：[implementation.diff](D:/VerseShellLive/node-dev-20261009-01a120ce/implementation.diff)、[change-manifest.json](D:/VerseShellLive/node-dev-20261009-01a120ce/change-manifest.json)。
