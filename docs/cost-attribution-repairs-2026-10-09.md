# TF-0138：成本统计分歧与请求构成验收

日期：2026-10-09（Asia/Shanghai）。本批推进剩余节点的开发验收；总目标尚未完成。

## 实现与边界

- 新增 tools/cost_attribution.py：复用 usage_audit 的配对身份索引和统一 usage 排除规则，按模型、变体、基线分组。总量比值、cell 等权均值、任务等权敏感性、分位数及长循环贡献使用完全相同的有效配对集。零基线导致逐格比值未定义时，四种估计量都排除该格，并逐项登记原因；零处理组保留。
- 新增 input_profile：在真实请求 JSON 已序列化后，记录 schema、各角色消息及外层 JSON 的字节计数与现有请求摘要。成功和失败 attempt 均记录，不向请求体或提示词添加内容；Chat Completions 和 Responses 的完整请求字节有离线对照。
- 记录的是每次调用 urlopen 前准备的 JSON body 字节，不是实际传输字节、提供方 token、缓存命中、reasoning token、账单或金额。system/user/assistant/tool/other 的消息字节加 schema 和外层开销精确等于 body 大小。
- 成本报告区分首轮与后续轮的 endpoint prompt usage、回合数、工具调用数和观察代理量。后续轮输入总量包含固定前缀等内容，不能全部称为历史重发；只有新 profile 能区分消息角色字节，历史缺失不从当前模板反推。
- 隔离报告收尾链新增成本 JSON/Markdown，并验证二者均存在；退出成功但报告缺件时保持 complete=false。正式研究仍保留既有 usage_token_ratio 与 usage_mean_of_ratios 两估计量及多重比较门槛，不修改旧计划摘要，不后验挑选有利口径。

## 1050 行旧轮只读核对

输入仍为 step5p-d-r1-20261007。四组候选分母均 175；与前序台账的有效数及两种主估计量逐项相符。

| 变体 / 基线 | 有效配对 | 总量比值 | cell 等权 | 任务等权比值均值 | 任务等权总量比值 |
|---|---:|---:|---:|---:|---:|
| baseline / raw | 174 | 0.165479 | 1.295344 | 1.292121 | 0.165894 |
| baseline / coached | 175 | 0.198223 | 1.324927 | 1.324927 | 0.198223 |
| compact_all / raw | 174 | 0.167361 | 1.247022 | 1.239980 | 0.163427 |
| compact_all / coached | 172 | 0.265806 | 1.547065 | 1.525054 | 0.257043 |

总量比值等价于以基线 token 消耗加权的 cell 比值均值，不等于 cell 等权均值。达到冻结轮数上限的基线格分别占对应基线 token 的 89.97%、87.23%、81.57%、76.76%，是算术上的主要集中项，不是因果归因。部分长循环组的净减少贡献超过 100%，因为其他格抵消了部分减少，不应截断为 100%。
旧轮 request input profile 覆盖为 0；报告保留 known_attempts 与缺失数，complete_prepared_bytes=null。首轮/后续 usage 可从已有回合记录核对，但无法把旧输入 token 精确拆成 schema、历史等组件。所有正式 claimable 仍为 false。

## 真实报告链发现的评分缓存问题

第一轮真实收尾链在 task_set_audit 被正确阻断：27/35 fixture 通过，8 个 Rust fixture 不符合 pristine/GOLDEN 期望。单纯的 Python 单元回归没有覆盖这个环境。
同一 rust_config_parse_port GOLDEN 工作区：继承包装器的共享 CARGO_TARGET_DIR 时运行了错误缓存测试，exit 101；使用独立 target 后 exit 0、7 个测试通过。原始 stdout/stderr 已保留。
修复位于共享 grading_environment：command_exit_0 和 rust_behavior 都把构建输出固定到本次评分副本的 target，保留 PATH/PATHEXT/APPDATA 等其他变量，不修改进程全局环境。修复后当前 fixture 审计 35/35 通过。
这不是完整环境沙箱。模型执行工具时的构建环境、旧轮是否曾继承共享目录、以及既有 Rust 成功样本是否受影响，仍由 TF-0139/0134 继续核验。启动脚本里未找到直接 CARGO_TARGET_DIR 赋值，不能据此证明历史运行环境没有继承该变量。本批不改写旧评分；缺最终工作区快照时不能追认其有效性。

## 证据与复现

证据根目录：[D:/VerseShellLive/cost-attribution-20261009-01a11c1d](D:/VerseShellLive/cost-attribution-20261009-01a11c1d)。
- [同配对成本报告](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/evidence/historical-cost.json) 与 [可读表格](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/evidence/historical-cost.md)
- [旧口径交叉检查](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/evidence/historical-crosscheck.json)
- [共享与独立 target 原始对照](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/evidence/rust-environment-repro.json)
- [修复前失败链](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/bundle-baseline/refresh-status.json) 与 [修复后的链](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/bundle-baseline-isolated/refresh-status.json)
- [专项测试](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/logs/cost-tests-with-grading.log)
- 专项 **22 项通过**；最终 Python **298 项：295 通过、3 tokenizer 依赖跳过**，exit 0。
- 产品门禁 **24/31，exit 1**；C12/C14/C16/C24/C34/C35/C36 仍红。C7 中 Rust **289 通过、1 忽略**，exit 0。新的 35/35 fixture 对照没有覆盖或追认 canonical 旧 C24 产物。
- 真实隔离链四阶段均 exit 0，完整性标记 complete=true；这只证明离线报告链完成，不代表正式 live 验收。
- 完整记录见 [最终摘要](D:/VerseShellLive/cost-attribution-20261009-01a11c1d/evidence/final-summary.json)。

```powershell
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/cost-attribution-20261009-01a11c1d/run_checks.py' tests
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/cost-attribution-20261009-01a11c1d/run_checks.py' tools/cost_attribution.py --with-arm 'D:/VerseShellLive/workspace/bench/aci/results/step5p-d-r1-20261007/latest_live.json' --out 'D:/VerseShellLive/cost-attribution-20261009-01a11c1d/recheck/cost.json'
```

输出必须是新的派生报告文件，不能覆盖原始输入或已存在报告。第一次验证包装器缺脚本目录搜索路径，已修正并保留失败日志；它不是成本算法的通过证据。

## 下一节点的真实范围

TF-0139 的基础异常并集是 **143 格**：139 个失败、141 个截断、5 个 usage 缺口；失败与截断交集 138。不是 285 个独立异常。另须对本批新发现的 Rust 构建缓存风险做成功样本反向检查，不能只检查这 143 格。这里只完成分母清点，尚未完成逐格根因归因。
