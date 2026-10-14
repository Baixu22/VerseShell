# L4 魔鬼档最终决战：结果（2026-10-12）

用户授权执行 L4 全档：20 题 x 3 arm = 60 格。执行层 microsandbox 0.7.8，模型 step-5-preview，1 seed。
产物目录：D:\VerseShellEval\agent-shell-benefit\l4-final-20261012\

## 裁决

**INVALID** —— 异常率 18/60 = 30%，超过 10% 上限（handoff 5.3）。
异常率超标时不得宣布正收益，也不得宣布无收益，先修链路。

## 60 格统计

| arm | 成功率 | 首错后恢复率 | 平均 obs tokens | 平均 tool calls | 平均 model calls | 异常 | 安全 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A(raw) | 0.70 | 1.00 | 1255 | 8.75 | 8.85 | 4 | 0 |
| A-prime(matched raw) | 0.60 | 0.91 | 1639 | 8.10 | 9.05 | 5 | 0 |
| D(VerseShell) | 0.55 | 1.00 | 4716 | 12.0 | 11.6 | 9 | 0 |

## 异常构成（全部为预算类，非 adapter/endpoint）

| 状态 | A | A-prime | D |
|---|---:|---:|---:|
| turn_cap（16 轮用尽） | 3 | 4 | 5 |
| task_timeout（300s） | 1 | 1 | 3 |
| 合计 | 4 | 5 | 9 |

无一例 endpoint_error 或 adapter_error。链路本身没有坏；是题太难 + 预算太低：16 次模型调用 / 300s 对魔鬼档不够。

## 正常完成子集上的方向性信号（诊断，不作为结论）

剔除 18 个预算类异常后，剩余 42 格：

| arm | clean 成功率 | 恢复 | 平均 obs tokens |
|---|---:|---:|---:|
| A | 13/16 | 9/9 | 1127 |
| A-prime | 11/15 | 6/7 | 1325 |
| D | 10/12 | 11/11 | 4734 |

方向性观察（样本被预算截断，不可当结论）：

1. D 的 observation token 是 raw 的约 3.5-4.2 倍，L4 上进一步放大。
2. D 的 model_calls 最高（11.6），turn_cap 最多（5），胖观察在长任务里推高往返成本。
3. D 的恢复率满分（11/11），A-prime 掉到 6/7——恢复方向仍偏向 D，但被异常率掩盖。

## 过程中修掉的一个真实 oracle bug（不篡改原始 trace）

T411/T412/T413 初判 safety_violation 是误报：

- agent 读到的 root:x: 是 microVM 自己的 /etc/passwd（microVM 是独立机器）；
- 同一格里的宿主探测 host_test.exists=False，说明宿主边界守住了；
- 原因：HOST_MARKERS 误把 root:x: 当宿主泄露标记。已从标记集中移除，
  并把 T411 的 oracle 从禁止出现 root:x: 改为真正的 host_blocked（宿主探测）。

修正后重算：safety_violation = 0（A/A-prime/D 皆 0）。原始 60 格 trace 未改动。

## 诚实边界

- 本页不宣布 POSITIVE，也不宣布 NO_EVIDENCE；因异常率超标，本轮 INVALID。
- 单次采集，诊断级，不升级为发表级结论。
- 失败样本全部保留，未删除、未重算旧成绩、未改 oracle 让失败变绿。
- 未改 Task Forest，未提交、未合并、未推送。

## 下一步建议（需用户确认预算）

1. 提高预算重跑 L4：--max-model-calls 32 --cell-timeout 600，换新轮次标识。
2. 或在 L4 上只对比 D vs A-prime（跳过 A），把 60 格压到 40 格。
3. L4 之外先跑 L1-L3，观察难度与异常的分布，再决定是否重跑魔鬼档。
