# Step 5 Preview 新候选开发轮 r3

日期：2026-10-10（Asia/Shanghai）。本回执保留 `TF-0120` 的新候选端点探针与 18 格开发试点结果。它是已知开发任务的工程诊断，不是 30/5/3 正式研究、产品收益结论或默认分支落地。

## 身份

- 新候选二进制：`target/debug/ae.exe`
- 二进制 SHA256：`e62452be1f7335416391b694faf234914cbe3512aa2bad656379cbd5ac07ca74`
- offline readiness：`D:/VerseShellLive/prelive-20261010-04/readiness.json`，`ready_for_live=true`、`endpoint_verified=false`
- 新分析计划：`bench/aci/studies/prelive-v1/analysis-plan-2026-10-10.json`，SHA256 `9e134b67301394502bd5a13737f805e74cbd2dcc061a1b4b26ec4b7b3e28a48d`
- 端点探针：`D:/VerseShellLive/freeze-live-20261010-02/candidate-probe/endpoint-probe.json`，2/2 请求通过、usage 完整
- 采集：`bench/aci/results/step5p-dev-20261010-r3/latest_live.json`，18/18 行、`partial=false`、0 endpoint 错误

## 18 格结果

配置为 3 个开发任务 × 3 条件 × 2 变体 × seed 42；`max_turns=24`、`max_tokens=16384`、`repeat_call_limit=3`。

- success：13 true / 5 false / 0 null。
- stop：13 `task_complete`、2 `repeat_call_limit`、2 `turn_limit`、1 `completion_limit`。
- 逐轮诊断：1 个 `truncated_other_turn`，其余 17 个无截断；没有 endpoint failure。
- `result.query` 在 `python_csvlite_parse_80d158b2 / verseshell_aci / baseline` 被模型使用；handle 是 canonical `result://sha256/<64hex>`，查询成功并取回完整 pytest 输出。这确认了新 handle 提示和兼容修复在新真实轮中可用。

## 预算边界

两份变体报告都已生成：

- `D:/VerseShellLive/freeze-live-20261010-02/reports-baseline/three_arm_report.json`
- `D:/VerseShellLive/freeze-live-20261010-02/reports-compact-all/three_arm_report.json`

baseline：

- raw_shell turn-cap 33%；raw_shell_coached 0%；verseshell_aci 0%。
- 因此 baseline 比较 `NOT_CLAIMABLE`，原因是 `exclusion_rate_above_10pct`。

compact_all：

- raw_shell token-cap 33%；raw_shell_coached turn-cap 33%；verseshell_aci 0%。
- 因此 compact_all 比较同样 `NOT_CLAIMABLE`。

新增诊断回执 `D:/VerseShellLive/freeze-live-20261010-02/budget-sensitivity-r3.json` 按 completion 与 turn 两轴逐任务登记；当前 3 个开发任务中，`python_csvlite_parse_80d158b2` 在该轮被标为预算敏感。这只是派生诊断，不新增豁免、不删除任务、不改变 §0.6 资格规则。

## 边界与剩余

- 这是一轮、一个 seed、3 个已知任务的工程诊断；不是正式重复研究，不是效果/泛化/账单主张。
- 预算已经实际绑定部分臂，不能把原始成功率或 token 比值当接口差异。
- `TF-0120` 仍不能按“任务级预算敏感标签已持久化到生成/准入产物”这一条宣称完全收口；下一步需要把两轴标签写入候选/准入流程，或明确修改验收口径。
- 正式 live 前仍需独立困难任务、来源独立性、大观察组合目标和完整三次重复；它们由 `TF-0115`、`TF-0114`、`TF-0123`、`TF-0112` 承接。
