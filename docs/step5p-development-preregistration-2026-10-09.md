# Step 5 Preview 开发试点预注册（2026-10-09）

## 目的与边界

在新冻结源码上验证 TF-0120/0121/0132 的工具、预算与停止行为，并验证采集/报告链路。它是**已知开发任务的工程诊断**，不是留出实验、三次完整独立重复或效果确证；不把旧 35 题换名为盲评集。

此前旧冻结连接性探针仅发出一个请求，HTTP 200、usage 完整，但中文 nonce 前缀未原样回显；原始失败保留在本轮 connectivity 目录，不算正式样本。明确 JSON 输入和更严格的完整相等校验后，必须在新候选上重新通过探针，不能拿旧版探针凭证放行新源码。

## 冻结设计

- 模型：`step-5-preview`，使用原私有认证/端点配置，不切账号、代理或模型别名。
- 任务（依历史问题预先选定，顺序固定）：`node_envconfig_validate_dd681123`、`js_leaderboard_rank_b1603acf`、`python_csvlite_parse_80d158b2`；来源为现有工具契约修复回执中的三个异常样本，尚未查看本轮任务结果。
- 三条件：raw_shell、raw_shell_coached、verseshell_aci；两变体：baseline、compact_all；seed=42、order_seed=42；只运行 with，不追加消融。
- **18 格；每格最多 24 轮，每轮 completion 上限 16,384，temperature=0。** 与旧 80 轮历史数据是不同配置，不拼接、不据此声称历史截断已消失。
- 最多 432 个逻辑请求；沿用每请求最多 3 次 transport 尝试、900 秒请求预算。整轮有 **2,700 秒（45 分钟）进程树硬上限**。上限不是预计费用，token usage 也不是账单。
- 新候选探针单独限 2 个逻辑请求、每请求 60 秒、completion 上限 16,384；探针用量单列。

## 执行前置与停止规则

1. 用最新脏源码制作独立 D 盘冻结副本，重建真实 ae；完整 readiness 通过后，验证源码完整清单、二进制、外置分析计划及探针源码 SHA。只跑过 focused tests 不可放行。
2. 启动前用回执绑定本计划 SHA、readiness SHA、源码清单/二进制 SHA、精确新探针 SHA、实际命令与输出 tag。小试点使用独立开发计划，不向它附会满足 30 题/5 seed/3 次采集的正式分析计划。
3. 任务列表须冻结到 collection/schedule，并显式传给 child；空、重复、未知任务、换集合续跑以及借底层 35 题绕过正式样本门槛均拒绝。
4. D<15GiB、C<2GiB、认证/配额、既有端点熔断、harness/证据写入故障或身份/源码漂移均保留证据并暂停。45 分钟到期杀掉本次进程树；未完成请求费用/结局仍记未知，不自动重跑。
5. 解题失败、重复调用、turn/completion 截断不触发重试；不按条件增预算/提示，不在看到结果后删题、换题或扩样本。后续开发方案另立版本。

## 分析与判定

逐条件/变体保留全部计划格及端点、轮次、completion 截断率；同时给出 analysable/ITT 与总量比值/逐格等权比值。检查重复调用、相同观察、测试成功后的行为、最终工作区与独立评分，不把模型自称完成或旧测试成功代替最终评分。用量缺失保留 unknown。

完整采集和七文件报告清单通过只表示工程链路完成。既有超过 10% 截断率等严格规则和正式样本门槛不放宽；本试点不产生正式效果/泛化主张。新的困难任务、来源独立性、留出集与完整独立重复仍另行验收。

机器计划：[development-plan.json](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/development-plan.json)。它在首个新候选任务请求前保存；执行前置中的内容摘要由启动回执绑定，运行时不得改写已冻结源码或计划。

## R2 验证副本修订（首次任务采集前）

R1 完整离线 readiness 为 427 项、2 failures/1 error、0 skip，未放行任何新候选探针或任务格。失败来自 venv 启动器 PID 假设与缓存测试未隔离暖缓存；同时补正可信启动屏障使用底层解释器，工作负载仍保留原 venv 命令。原 validation 副本与失败记录保持不动。

[R2 机器计划](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/development-plan-r2.json) 仅更新验证副本/凭证路径和版本标识；3 个任务、18 格、24 轮、16,384 completion、45 分钟以及全部分析/停止规则逐字段保持不变。[修订核验](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/planning-revision-r2.json)。仍须 R2 完整 readiness 与相同候选的严格探针通过才执行，不升级旧失败为通过。

## R3 候选二进制隔离修订（仍在首次任务采集前）

R2 已通过 Python 430 项、Rust 289 项（1 ignored）、35 项 fixture 审计与三组校准，但候选 AE SHA 在检查期间改变，合成链未完成即停止，ready_for_live 保持 false。独立临时 target 的 cargo build → cargo test --no-run 已复现正常 ae 被替换，证明只编译测试也会改写共用 target；未用源码漂移或 mtime 代替该证据。

R3 将 Rust 测试输出隔离到独立 target，同时每阶段和合成链/ACI smoke 边界记录并检查候选摘要；最终 ready 只能对应同一个原候选。原 v1/R2/诊断产物保留。[R3 机器计划](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/development-plan-r3.json) 仅换候选/凭证路径与版本标识，18格/24轮/16,384/45分钟和全部分析规则不变；[逐字段修订核验](D:/VerseShellLive/tf-step5p-live-20261009-01a11efe/planning-revision-r3.json)。R1/R2 都未放行新候选探针或任务数据，不借此扩样本或调预算。
