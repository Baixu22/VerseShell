# TF-0135：重试用量与成本分母开发回执

日期：2026-10-08。范围仅为用量证据与成本配对资格；不改变模型提示、重试预算、任务评分、统计阈值或旧轮结果。TF-0137 的全入口正式验收统一仍是独立开放范围。

## 已落地

- 采集端每个 transport attempt 保存独立 attempt_id、请求体摘要、可获得的 request_id/response_id、收到的 usage 和 usage_complete。无响应尝试保留 usage=null，不猜测为零；JSON/编码损坏的 HTTP 响应也留下该次未知用量记录，不额外重试。
- usage=null 不再使任务循环因读取 .get 而崩溃；评分独立执行，用量缺失只影响成本资格。
- 复用 tools/live_uncertainty.py 的共同入口：所有下游成本统计统一拒绝已知缺失、恢复不确定、无响应重试、回合/总数矛盾。旧 usage_complete=true 不能覆盖相反的逐 attempt 证据。
- 比值结果同时提供 candidate_pairs、n_pairs、excluded_nonfinite_pairs；成本有效对数与评分对数分开，未知值不补零。
- 新增 tools/usage_audit.py，只读输出逐行/逐 attempt 台账、已收到数量、未知尝试及每种变体/对照的有效配对数。输出必须是原输入目录之外的新文件。历史成功返回的最后一个 attempt 可引用同回合 usage，并明确标注来源；不能把该 usage 反向套给失败重试。
- 缺少逐 attempt 记录的旧式行不会伪造记录；已有行级计数仍标为 legacy_row_counters。局部已收到 token 可保留为部分已知数量，但不能取得完整成本资格。

## 成本入口核对

| 入口 | 规则/分母 |
|---|---|
| live_uncertainty：reported_usage、cost_per_success_interval | 共同 usage_exclusion_reasons；未知成本不能进入成对计算 |
| three_arm_report | reported_usage + ratio_bootstrap，成本块独立标记有效对数 |
| acceptance_power | 同一输入规则；bootstrap_ratio 透传候选/有效/排除对数 |
| repeated_run_uncertainty 及其研究分析调用方 | 复用 valid_usage；重复实验中的不完整 endpoint usage 直接拒绝，不插补 |
| claim_gate 与存量 Markdown/JSON/README 消费者 | 不把本次诊断升级为正式通过；完整消费点统一仍由 TF-0137/0140 承接 |

## 旧轮只读核对

输入：D:/VerseShellLive/workspace/bench/aci/results/step5p-d-r1-20261007/latest_live.json。首尾摘要核验另存，不修改输入。

- 1050 行、18,582 个已记录 attempt；1045 行用量有效，5 行因缺口排除。
- 6 个回合中有 7 次未知用量尝试；这些尝试的 usage 继续为未知。
- 已收到的合计为 134,271,140 tokens；这是 received usage，不是完整账单或价格计算。

| 变体 | 对照条件 | 匹配对数 | 成本有效对数 | 因用量缺口排除 |
|---|---|---:|---:|---:|
| baseline | raw_shell | 175 | 174 | 1 |
| baseline | raw_shell_coached | 175 | 175 | 0 |
| compact_all | raw_shell | 175 | 174 | 1 |
| compact_all | raw_shell_coached | 175 | 172 | 3 |

本批没有提供方账单证据，也未访问计费端点；billing.status=unknown、reconciled_billed_tokens=null。此结论不是“提供方不存在账单”，更不是“未知尝试免费”。后续若获得可按请求身份核对的账单，应独立追加证据，不能改写本轮原始计数。

## 复现与证据

```powershell
. 'D:/VerseShellLive/usage-repair-20261008/environment.ps1'
python -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
python -X utf8 tools/usage_audit.py --input D:/VerseShellLive/workspace/bench/aci/results/step5p-d-r1-20261007/latest_live.json --out D:/VerseShellLive/usage-repair-20261008/evidence/historical-usage-audit-new.json
python -X utf8 tools/claim_gate.py --metrics eval/metrics.json --compact-ratio eval/compact_ratio.json --evidence D:/VerseShellLive/usage-repair-20261008/evidence/claim-gate-new.json
```

新回放文件须换名，不能覆盖已有审计。测试临时目录、缓存、构建目标和新增大体积证据均沿用已核验的 D 盘配置；原始模型轮次没有补跑。

- 修复前反例：logs/stale-flag-before.log，记录了旧完整标记掩盖未知重试。
- 新增 11 项离线测试：tests/test_usage_audit.py；覆盖 transport 身份、未知/局部/零用量、解析失败、评分独立性、历史回放保护以及单轮/重复轮成本规则一致性。
- 最终旧轮台账：evidence/historical-usage-audit-final.json；日志：logs/historical-usage-audit-final.log。
- 完整 Python 回归：242 tests，101.306 秒，exit 0；包含新增 11 项用量测试，不重复计数。日志：logs/python-tests-final.log。
- 首次完整回归有两项被旧分析计划摘要提前拦截；仅将测试用计划改为临时目录中的当前源码副本，没有修改生产冻结计划。旧生产计划仍按预期拒绝当前分析源码，证据：evidence/old-plan-rejection.json；失败日志也保留。
- scoped git diff --check：exit 0；usage_audit --help：exit 0。
- 产品门禁：25/31，exit 1；C12/C14/C16/C24/C34/C36 仍红，阈值与历史测量未改。证据：evidence/claim-gate.json。
- 本批 8 文件精确补丁与前后摘要分别保存为 implementation.diff、change-manifest.json；基线是会话开始时的脏工作区，不是 HEAD。原轮输入、生产冻结计划、暂存区未改，见 evidence/change-boundary.json。

## 状态边界

TF-0135 保持 in_progress，等待产品门禁及剩余计费核对边界闭合。不关闭 TF-0124/0126，也不把 TF-0136～0139、真实模型试点或源码默认分支落地标为完成。新采集必须采用包含本次 runner 变更的新冻结身份；不将当前分析器的成功输出用于追认旧轮正式通过。

本批证据根目录：D:/VerseShellLive/usage-repair-20261008/。
