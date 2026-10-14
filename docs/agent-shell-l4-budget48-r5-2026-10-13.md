# Agent Shell L4 提升预算轮 r5（2026-10-13）

任务：把 L4 的 cell 预算从 32 calls / 600s 提到 **48 calls / 900s**，消除 r4 中由模型轮次长尾造成的 cap/timeout 异常，
再用同一新信封二进制（12b427a9）重跑 20 题 × 3 arms，得到可信裁决。

## 1. 起因

`l4-envelope-r4` 判 INVALID：异常 8/60 = 13.3%。定量归因显示不是端点变慢（r3 14.6s/call vs r4 14.2s/call），
而是模型在同一题上的轮次方差极大（T404/D 12→32、T406/A 13→32），32 calls / 600s 落在长尾之内。
修复动作：只抬预算，不改任务、不改 oracle、不改提示、不换二进制。

## 2. 配置

| 项 | 值 |
|---|---|
| round | l4-budget48-r5-20261013 |
| tasks | L4 全 20 题 |
| arms | A / A prime / D = 60 cells |
| seed | 42 |
| 预算 | **max-model-calls 48 / cell-timeout 900s** / 4096 tok |
| ae sha256 | 12b427a9…（瘦身 + A1–A5，与 r4 相同） |
| 执行层 | microsandbox 0.7.8，1 vCPU / 512 MiB，串行 + 内存闸门 1200 MB / 8s 冷却 |

## 3. 裁决：POSITIVE

- 60/60 格，exit 0，无残留 sandbox。
- 异常 5/60 = **8.3% ≤ 10%**，safety_violation = 0。
- 触发阈值：**success gain >= +5pp**。

| arm | 成功率 | 恢复率 | 恢复分母 | obs tokens | tool calls | model calls | 异常 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0.60 | 1.00 | 14 | 2634.9 | 15.15 | 15.55 | 3 |
| A prime | 0.75 | 1.00 | 16 | 3104.3 | 12.50 | 14.45 | 1 |
| D | **0.80** | 1.00 | 13 | 5900.7 | 14.90 | 12.70 | 1 |

D vs A prime：**0.80 vs 0.75 = +5pp** → POSITIVE。

配对：D 胜 2 题（T408、T411）、A prime 胜 1 题（T405）、平 17 题。即净 +1 题。

## 4. 异常清单（5 个，全部为预算类）

| cell | status | calls | wall |
|---|---|---:|---:|
| T408/A | task_timeout | 18 | 949s |
| T411/A | turn_cap | 48 | 196s |
| T411/A prime | turn_cap | 48 | 150s |
| T420/A | turn_cap | 48 | 318s |
| T420/D | turn_cap | 48 | 433s |

注意：4/5 异常落在 raw 臂。D 只有 1 个。T408/A 是"呼叫少但单 call 慢"（18 calls 用 949s），抬预算无法覆盖。

## 5. 三轮 L4 纵向对比（同一 tier、同 seed）

| 轮次 | ae | 预算 | A | A prime | D | D obs | D tools | 裁决 |
|---|---|---|---:|---:|---:|---:|---:|---|
| l4-slim-r3 | afe227ca（仅瘦身） | 32 / 600 | 0.80 | 0.75 | 0.80 | 3491 | 10.75 | POSITIVE |
| l4-envelope-r4 | 12b427a9（+A1–A5） | 32 / 600 | 0.75 | 0.75 | 0.70 | 5445 | 13.95 | INVALID |
| l4-budget48-r5 | 12b427a9（+A1–A5） | 48 / 900 | 0.60 | 0.75 | **0.80** | 5901 | 14.90 | POSITIVE |

**D vs A prime 在两次独立轮次都是 +5pp**（r3 与 r5），中间那次 INVALID 完全由预算异常造成（r4 换成同一二进制、同一预算时 D 掉到 0.70）。

## 6. 治疗触达

D 本轮 298 次 observation、22 次失败，其中：

- `suggested_next`: 21/22 (95%)
- `status=failed/blocked`: 21/22 (95%)
- `blocked_operation`: 21/22 (95%)
- `substitutions`: 1/22（只在已知工具缺失/权限类失败触发）

## 7. 成本（仍然是短板）

- obs tokens：D **5900.7** vs A prime 3104.3（**+90%**）
- tool calls：D 14.90 vs A prime 12.50（+19%）
- model calls：D **12.70** vs A prime 14.45（D 反而少 12%）

即本轮的 +5pp 是用约 1.9x 的 observation token 换的；效率门槛（obs −20%、tool calls −15%）均未达标。

## 8. 稳定性与内存

- 内存采样 697 点：min **3.4 MB** / max 9001 MB / avg 4105 MB；<1200 MB 占 38 点，<500 MB 占 16 点。
- 低点由外部 llama-server 波动造成；本轮自有上限仍是 512 MiB VM + 串行。
- **全程 0 OOM、0 endpoint_error**；5 个异常均为预算类，非链路或安全事件。
- 墙钟 180.6 min（3h01m），cell 纯执行 164.1 min；已超出 2h 默认上限，系用户本次明确授权抬预算所致。

## 9. 诚实边界

- 单 seed、n=20；配对净差仅 +1 题。二项 sd ≈ 1.9 题，**该 +5pp 属噪声敏感区间**，不能当成稳定效应。
- 预算是在看到 r4 的 INVALID 之后才抬的（自适应选择），必须在结论中声明；r3 的同向 +5pp 是独立证据，但同样只有单 seed。
- A 臂本轮掉到 0.60（r3 0.80 / r4 0.75），提示即便抬预算后 raw 臂方差仍然很大，进一步说明需要多 seed 才能定论。
- obs 成本 +90% 未改善，说明瘦身空间仍在信息层本身，不在信封元数据。
- 未提交 / 未合并 / 未推送；未改 Task Forest；所有旧轮与失败样本保留。

## 10. 结论

1. **抬预算后本轮达到预注册的 POSITIVE**（D 0.80 vs A prime 0.75 = +5pp），且与 r3 独立复现同向同幅。
2. r4 的 D 0.70 / INVALID 应判定为**预算伪影**，不是信封回归：同一二进制在 48/900 下回到 0.80。
3. 仍未解决的两件事：**D 的 observation 成本是 raw 的 1.9x**；**单 seed 无法把 +1 题净差与噪声分开**。
4. 若要升级为可靠结论，下一步应是多 seed（例如 3 seeds）重复 48/900 的 L4，而不是继续加预算。
