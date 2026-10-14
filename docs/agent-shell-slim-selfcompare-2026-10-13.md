# VerseShell 观察层修复与自对比（2026-10-13）

任务：修复 D 的胖观察，吸收 A / A-prime 两个 raw 臂的“轻观察”优点，然后与上一轮验收状态做自对比。

## 一、诊断：D 为什么在 L4 上输给 raw

对 l4-final-20261012-r2 的 279 次 D 调用做字符级归因（总计 453,000 字符）：

| 成分 | 占比 | 是否冗余 |
|---|---:|---|
| stdout/stderr 文本 | ~52% | 有效信息，保留 |
| 流元数据（encoding/raw_bytes/returned_bytes/omitted_bytes/raw_complete/decoding_lossy） | 23% | 高冗余 |
| argv 回显 | 20% | 纯冗余（模型刚发过） |
| meta | 7% | 部分冗余 |

两个功能性缺陷（raw 没有，D 有）：

1. **argv 控制字符误拒**：E_EXEC_BAD_ARG “forbidden control character” 在 L4 触发 33 次，
   命中 16/20 题。agent 用 heredoc 写脚本时必然带换行，raw 能跑，D 直接失败。
2. **微型产物句柄**：234 个 stdout 句柄里有 233 个是因为“只丢了 1 个字节（换行）”，
   每个白付 ~80 字符，还暗示有可恢复内容——实际没有。

## 二、修复（吸收 raw 的优点）

| # | 修复 | 文件 | 依据 |
|---|---|---|---|
| 1 | 允许 argv 内换行（仅 Windows 保留守卫，NUL 仍拒） | src/process_command.rs | raw 接受 heredoc |
| 2 | 不再回显 argv / cwd | src/operation.rs | 模型刚发过 |
| 3 | 仅当省略 > 64 字节才发产物句柄 | src/operation.rs | 消除 1 字节噪声句柄 |
| 4 | 空输出摘要改为一行 “no output” | src/operation.rs | raw 也不发长句 |

行为验证（microVM 内、新 ae 二进制 afe227ca）：

- heredoc：ok=true（此前 E_EXEC_BAD_ARG）
- 小输出：无产物句柄、无 argv 回显
- 大输出：status=truncated 且产物句柄保留（恢复能力未丢）
- 空输出：625 字符（此前约 850）

## 三、自对比：D-old vs D-new（同一 L4、同预算 32 calls / 600s）

| 指标 | D-old (r2) | D-new (r3) | 变化 |
|---|---:|---:|---|
| 成功率 | 0.60 | **0.80** | +20pp |
| 平均 obs tokens | 5433 | **3491** | -36% |
| 平均 tool calls | 13.95 | **10.75** | -23% |
| 平均 model calls | 14.7 | **11.3** | -23% |
| 预算类异常 | 4 | **0** | 消除 |
| 恢复率 | 1.00 | 0.92 | 略降（n 变大） |

## 四、本轮验收裁决：POSITIVE

| arm | 成功率 | 恢复率 | obs tokens | tool calls | model calls | 异常 | 安全 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A (raw) | 0.80 | 1.00 | 1675 | 10.6 | 10.75 | 2 | 0 |
| A-prime (matched raw) | 0.75 | 1.00 | 1892 | 9.35 | 9.75 | 1 | 0 |
| **D (VerseShell)** | **0.80** | 0.92 | 3491 | 10.75 | 11.3 | 0 | 0 |

主对照 D vs A-prime：0.80 vs 0.75 = **+5pp**，达到门槛 → **POSITIVE**。
异常率 3/60 = 5%（<10%），safety_violation = 0，链路有效。

配对：D 胜 2（T407、T409），A-prime 胜 1（T402），平 17。

注：D 的 obs token 仍高于 raw（3491 vs 1892）。本轮靠成功率取胜，
效率门槛（-20%）未达标——瘦身显著但未到 raw 水平。

## 五、三轮 L4 纵向对比

| 轮次 | D 成功率 | D obs tokens | 异常 | 裁决 |
|---|---:|---:|---:|---|
| l4-final (16 calls) | 0.55 | 4716 | 18/60 | INVALID |
| l4-final-r2 (32 calls) | 0.60 | 5433 | 6/60 | NO_EVIDENCE |
| **l4-slim-r3 (32 calls, 修复后)** | **0.80** | **3491** | **3/60** | **POSITIVE** |

## 六、诚实边界

- 单次采集（1 seed），诊断级，不升级为发表级结论。
- 旧轮 l4-final、l4-final-r2 全部保留，未删除、未改写。
- 修复改变了 provider 源码，因此另起 l4-slim-r3，不与旧轮拼接。
- D 的效率仍劣于 raw；本轮 POSITIVE 只由成功率门槛支撑。
- 未改 Task Forest；未提交、未合并、未推送。
