# 恢复尝试次数指标（2026-10-12）

新增只读工具 `tools/recovery_loop.py`：从已存 rows 计算「首次失败 → 恢复」需要几次调用。
失败信号：ACI 臂看 `aci_ok=false`/`error_code`；raw 臂读观察文本里的 `[EXIT: n]`（n≠0）。
恢复 = 同一操作的下一次成功，或成功的 `task_complete`。**零模型调用。**

## 结果 1：105 格 ACI 样本（稳健）

来源 `bench/aci/results/latest_live.json`（sn-glm-5-3-flash）：

| 条件 | runs | 有失败 | 恢复 | 平均恢复步数 | 中位 |
|---|---|---|---|---|---|
| verseshell_aci | 105 | 20 | **14（70%）** | **1.93** | **2** |
| raw_shell | 105 | 0* | — | — | — |
| raw_shell_coached | 105 | 0* | — | — | — |

\* raw 臂显示 0 失败**不是因为它没失败**，而是旧数据集里 raw 的轨迹**根本没存观察文本**
（raw 600 步里 0 步带 `observation.path`；ACI 有 `aci_ok` 422 步）。这本身是信息层的不对称。

## 结果 2：6 格新采集（两臂都存观察，直接可比）

来源 `bench/aci/results/recovery-ab-r1`（step-5-preview）：

| 条件 | runs | 有失败 | 恢复 | 平均恢复步数 |
|---|---|---|---|---|
| verseshell_aci | 3 | 1 | **1** | **3.0** |
| raw_shell | 3 | 1 | **0** | — |

同一任务 `python_csvlite_parse`：ACI 失败一次后 **3 步恢复并完成**；
raw_shell 失败后**未恢复**（撞 completion_limit）。

## 结论

1. **恢复是常态且有量化**：ACI 在 105 格上 70% 的失败能在 **2 步左右**恢复。
2. **失败信封是恢复的支点**：`error.code` + `diagnostics`(文件:行) + `suggested_next`(可执行 op)
   让模型不必猜测下一步。
3. **对比臂缺信号**：旧数据的 raw 臂连观察文本都没留，无法测恢复——这反证了信息层的差距。

## 诚实边界

- 6 格是诊断对照；105 格是**单模型历史采集**，`acceptance_scope` 非正式。
- raw 臂在旧数据的 0 失败是**数据缺失**，不是「raw 从不失败」，已如实标注。
- 未做竞品对照，不能宣称优于同系 agent shell。