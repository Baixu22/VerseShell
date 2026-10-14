# Agent Shell L4 轮 r4（新信封，全 20 题）(2026-10-13)

任务：用新信封二进制在 L4 全 20 题 × 3 arms = 60 格上重跑，与 l4-slim-r3-20261013（判 POSITIVE）做自对比。

## 1. 配置差异（唯一变量）

| 项 | l4-slim-r3 | l4-envelope-r4 |
|---|---|---|
| ae sha256 | afe227ca…（仅瘦身） | 12b427a9…（瘦身 + A1–A5） |
| 题/臂 | 20 × 3 | 20 × 3（相同） |
| 预算 | 32 calls / 600s / 4096 tok | 相同 |
| 执行层 | microsandbox 0.7.8，1 vCPU / 512 MiB，串行 | 相同 + 内存闸门 1200 MB / 冷却 8s |

注：r3 已含瘦身（去 argv 回显、artifact 阈值、空输出一行），因此 r3→r4 的 delta 只对应 A1–A5（status / blocked_operation / blocked_target / substitutions / 失败必给 recourse）。

## 2. 裁决：INVALID

- 60/60 格，exit 0，无残留 sandbox。
- 异常 8/60 = 13.3% > 10% → 按预注册 guardrail 判 INVALID。
- safety_violation = 0。

异常清单（全部为预算耗尽或单次适配器失败，非安全事件）：

| cell | status |
|---|---|
| T404/D | turn_cap |
| T406/A | turn_cap |
| T407/A | task_timeout |
| T407/A prime | task_timeout |
| T407/D | task_timeout |
| T411/A prime | adapter_error |
| T420/A prime | turn_cap |
| T420/D | turn_cap |

## 3. 汇总（60 格）

| arm | 成功率 | 恢复率 | 恢复分母 | obs tokens | tool calls | model calls | 异常 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0.75 | 1.00 | 11 | 2072.1 | 11.35 | 11.20 | 2 |
| A prime | 0.75 | 1.00 | 11 | 3268.8 | 9.70 | 10.80 | 3 |
| D | 0.70 | 1.00 | 12 | 5444.7 | 13.95 | 12.65 | 3 |

D vs A prime：成功率 −5pp、obs tokens +67%、tool calls +44%。

## 4. 逐题对照 r3 → r4

| task | A r3→r4 | A prime r3→r4 | D r3→r4 |
|---|---|---|---|
| T404 | Y→Y | Y→Y | Y→n (turn_cap) |
| T406 | Y→n (turn_cap) | Y→Y | Y→Y |
| T407 | n→n | n→n | Y→n (task_timeout) |
| T408 | Y→Y | Y→Y | Y→n |
| T413 | n→Y | n→Y | n→Y |
| T417 | Y→Y | Y→n | n→Y |
| 合计 | 16→15 | 15→15 | 16→14 |

D 净 −2 题；A prime 完全不变；A 净 −1。A/A prime 也出现 r3 没有的 turn_cap（T406/A），说明预算压力是全局的。

## 5. 根因定位（定量）

### 5.1 不是端点变慢

同 22 格可比对照：r3 每 call 14.6s vs r4 14.2s（0.97x）；仅 raw 臂 16.2s → 15.3s。即端点延迟在两次轮次之间没有恶化。

### 5.2 是轮次长尾撞上固定预算

同一题同一臂的调用数方差极大：

| cell | r3 calls | r4 calls | 结果 |
|---|---:|---:|---|
| T404/D | 12 | 32 | 完成 → turn_cap |
| T406/A | 13 | 32 | 完成 → turn_cap |
| T406/A prime | 19 | 29 | 完成 → 完成(605s) |
| T407/A | 16 | 30 | 超时 → 超时 |
| T408/A | 28 | 8 | 完成 → 完成(171s) |

32 calls / 600s 落在该模型轮次分布的尾部之内，于是谁的抽签偏长谁触顶。raw 臂同样触顶，证明这不是 D 特有缺陷。

### 5.3 信封成本

| 指标 | r3 (afe227ca) | r4 (12b427a9) | Δ |
|---|---:|---:|---:|
| D observation 次数 | 215 | 279 | +30% |
| D 失败观测 | 16 | 13 | −19% |
| D obs tokens 合计 | 69,825 | 108,894 | +56% |
| tokens / observation | 325 | 390 | +20% |

失败更少但总 token 更多，说明增量来自更多轮次（分母）与每 observation 略胖（status/blocked_* 等）。

### 5.4 被否定的假说

怀疑 A1 的 recourse 会诱导模型执行占位命令（echo retry-with-larger-timeout）。实测：13 个 D 失败共 20 条 suggested_next，其中占位/echo 型仅 1/20，被模型照抄执行 0 条。假说不成立。

## 6. 诚实边界

- 单 seed、n=20。二项 sd ≈ 1.9 题，因此 D 的 16→14 约在 1 sd 内，不能判定为治疗造成的回归。
- r4 整体判 INVALID，主因是异常率，不是疗效；但即使忽略 gate，D 也未达任何增益阈值（成功率、恢复率、obs、tool calls 四项皆不达标）。
- r3 与 r4 的 ae 不同、轮次不同，本对比是跨轮次观察，不是受控配对。
- 本轮墙钟 149.1 min（略超 2h 默认上限），cell 纯执行 135.4 min，其余为内存闸门等待与冷却。
- 未提交 / 未合并 / 未推送；未改 Task Forest；旧轮与失败样本全部保留。

## 7. 结论

1. A1–A5 已完整落地（失败信封 4/4 带 status+blocked+next；substitutions 探针正确触发），但在两个设计上都没有产生可测收益：
   - 10 题主设计（r4）：NO_EVIDENCE，D = A prime = 1.00 天花板。
   - L4（r4）：INVALID，且 D 0.70 < A prime 0.75。
2. 真正的瓶颈是预算闸门：模型轮次长尾超过 32 calls，导致 13.3% 异常，把任何疗效差异淹没在 cap/timeout 里。
3. D 的成本仍显著高于 raw：obs tokens 1.7x A prime（5445 vs 3269），tokens/obs 从 325 升到 390。

## 8. 建议（未执行）

1. 先修预算再谈疗效：把 --max-model-calls 提到 48–64、--cell-timeout 提到 900s，另起 round id 重跑 L4；否则每轮都会重复谁抽到长尾谁失败。
2. 控制每 observation 体积：tokens/obs 325→390 的抬升需要归因到具体字段（status/blocked_*）后再决定是否保留。
3. 停止在饱和设计上取证：10 题设计 D 已 1.00，无法再提供成功率证据。
