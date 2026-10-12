# TF-0137：统一严格验收入口

开始：2026-10-08；收尾：2026-10-09（Asia/Shanghai）。续接 TF-0136 后的节点开发。

## 结论与状态

- TF-0137 工程实现、负向测试与旧轮只读回放已完成；仍保持 in_progress，不表示产品验收通过。
- 单 collection 的旧 OR 改善保留为 `descriptive_advantage`；正式字段 `meets_acceptance` / `claimable` 为 false。正式研究仍由已有冻结研究评估器逐假设判断，不是把研究结论一律置 false。
- 旧轮 1050 行、四个比较：描述性改善均为 true，正式资格均为 false。原始 911 成功、139 失败不变，输入 SHA-256 保持 `b78c6934cdb6ce89eb2c2098c5e0ae45a5c3057cc1a26c45205e8c675afc0ec0`。
- 产品门禁 **24/31，exit 1**：C12/C14/C16/C24/C34/C35/C36 未通过。较前序 25/31 新增 C35 红项，是现在能识别旧 canonical 报告的肯定验收标签，不是把旧数据变差，也不是新性能实验。

## 消费点清单

| 消费点 | 本批处理 |
|---|---|
| live_agent_loop.compare_a_vs_d、生产 JSON 和 CLI | 保留描述性指标；附逐行政策、评分、usage、配对及研究未评估的具体原因；变体不合并 |
| merge_live_runs 与 checkpoint 共用刷新 | 传入 max_turns、partial、synthetic 上下文；不覆盖更具体的拒绝原因 |
| live Markdown | 从 rows 重算，不信任旧 comparison 标签；未知评分为 null，不当成 0；明确 NOT CLAIMABLE |
| score.py --require-accept | 拒绝 live/未知模式的单 collection；mock 工程回归保留，明确不是产品验收 |
| three_arm_report JSON / CLI | 独立列出 row_policy_eligible 与正式 acceptance；旧 row_policy_claimable_comparisons 兼容键为空；支持 D 盘外部输入路径 |
| study_inference | 复用同一个数据资格判定；保留既有冻结、样本量、校准、全族校正、双口径和前置假设门槛；输出具体拒绝原因 |
| claim_gate C35 | 扫描原始 collection comparison 及变体中的肯定标签；不把嵌套 row_policy 的局部 eligibility 当正式标签 |
| README / acceptance-criteria | 明确报告命令成功、mock 回归、逐行资格、正式研究结论不是同一件事 |
| run_suite / e2e_effect_eval / Rust mock acceptance | 保留工程 mock 合同，不赋予正式 live 结论；现有 Rust 回归通过 |

嵌套 `row_policy.comparisons[*].claimable` 是旧逐行政策兼容字段；新正式消费者通过 `row_policy_eligible` / `data_eligible` 明确区分，不能从这个局部字段推出正式结论。

## 实测回放（每条件、每变体 n=175）

| 变体 | raw_shell 截断率 | coached 截断率 | ACI 截断率 | 正式比较 |
|---|---:|---:|---:|---|
| baseline | 25.71% | 23.43% | 0.57% | 两个比较均不可主张 |
| compact_all | 18.29% | 11.43% | 1.14% | 两个比较均不可主张 |

四个比较都带 exclusion_rate_above_10pct。三个比较另有 incomplete_usage_rows；全部还明确缺少已评估的独立重复与冻结全族推断。没有提高预算、降低阈值、补零 usage、改写成功评分或追认旧数据。

## 验证与复现

| 检查 | 结果 |
|---|---|
| 修复前负向控制 | exit 1；复现旧 OR 产生 true、score CLI 错误 exit 0、partial 覆盖具体原因 |
| 本批新增测试 | 16 项，通过；含正常正式评估器的正向单元控制、未达重复数、冻结身份、全族 alpha、缺 usage、未知评分、partial、混合变体与配对缺口 |
| 最终 Python 全量 | 276 项：273 通过、3 tokenizer 依赖跳过；exit 0；3 个原生工具合同测试已执行 |
| Rust 全量（C7 回执） | 16 suites，289 通过、0 失败、1 忽略；exit 0 |
| 1050 行原始旧轮消费者回放 | 直接比较、合并刷新、Markdown、三条件 JSON/CLI 与 score 拒绝一致；exit 0；原始哈希未变 |
| 真实 merge CLI（5 个原始 seed 分片） | exit 0；1050 行派生副本写在 D 盘，四个变体/基线比较均明确输出 NOT_CLAIMABLE 和拒绝原因 |
| 原始 score --require-accept | exit 1（预期拒绝） |
| 新诊断报告的 C35 正向控制 | 无肯定标签冲突；exit 0 |
| 当前旧分析计划校验 | exit 1，analysis implementation changed；要求新冻结，不更新原计划摘要 |
| 产品门禁 | 24/31；exit 1，保留七个红项 |

证据目录：[D:/VerseShellLive/strict-acceptance-20261008-01a11c1d](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d)。
关键原件：[旧轮回放](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/evidence/historical-replay.json) · [最终测试](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/logs/python-tests-final-cli.log) · [最终产品门禁](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/evidence/product-claim-gate-final.json) · [本轮改动清单](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/change-manifest.json)。

复现（PowerShell，当前仓库目录；run_checks.py 保留 Windows 环境并使用既有 D 盘构建缓存/临时目录）：

```powershell
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/run_checks.py' tests
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/run_checks.py' tools/claim_gate.py --metrics eval/metrics.json --compact-ratio eval/compact_ratio.json --evidence 'D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/evidence/product-claim-gate-recheck.json'
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/replay_strict_acceptance.py'
```

正式评估器的正向测试使用受控校准/矩阵桩，仅证明代码不会无条件返回 false；不是新研究证据。整个本轮没有发送模型请求。

## 森林和剩余范围

- 按 docs/task-forest-policy.md 的现有授权保存并应用新提案；不关闭任何节点。同步 TF-0136 的既有 85% 进展，并将 TF-0137 登记为 in_progress / 85%。
- TF-0136 的历史快照 0/1050、8/8 可复评分且 2 unknown 来自前序已保存证据，本批只核对回执并同步状态，没有声称重新执行那次独立复评分。前序待确认提案和交接原文保留。
- TF-0140 承接旧报告标签与其余产品声明缺口；TF-0141 承接源码落地与历史完成状态。后续开发可推进 TF-0138 成本口径分歧，不需要为七个产品红项伪造通过。
- git fetch origin 因配置代理 127.0.0.1:7890 不可达而 exit 128。check-landing 基于本地缓存的 origin/master 得到 44 项历史发现、exit 1，不能当成最新远端状态。没有提交、合并、重置或暂存。

## 执行偏差保留

第一次产品门禁未带 --compact-ratio 且使用 C 盘默认构建目录。它重生成了原先干净的 eval/compact_ratio.json；新测量副本已单独保存，再依据会话开始的 clean 状态恢复 HEAD 原始字节，git status 确认为干净。最终门禁已按上述命令在 D 盘缓存重跑，并显式复用两份历史测量。未清理既有构建产物。详见 [恢复回执](D:/VerseShellLive/strict-acceptance-20261008-01a11c1d/evidence/compact-ratio-restoration.json)。
