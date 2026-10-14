# 观察层瘦身 + L4 纵向对比 r6（2026-10-14）

目标：把"信息层吸收"从**失败路径**转到**成功路径**（实测失败只占 8.7% 体积），并在同一 L4 设计上做纵向对比。

## 1. 本轮实现的 3 项（避免过度设计，只做有证据支撑的）

| # | 改动 | 依据 | 落点 |
|---|---|---|---|
| E1 | 成功流只序列化"有信息量"的字段：值等于默认值的一律不发 | 成功观察里 stream 元数据占 25.6% | `src/operation.rs` `StreamObservation` |
| E2 | 空流折叠为 `{status,encoding,decoding_lossy}` | 264/272 成功观察的 stderr 是 `empty`，却仍发 9 字段 | 同上 `observe_stream` |
| E3 | 诊断消息上限 240 字符（**bug 修复**） | 3 条 `strings` 触发的垃圾 warning 单条 11,886 字符，占全部成功观察 **12.5%** | `clamp_diagnostic_message` |

### 明确不做（避免过度设计）

- 不补 `policy_rule`（安全模型不同）
- 不扩 `substitutions` 映射表（当前命中 1/22，收益未证）
- 不引入 kernel/network policy、credential proxy（属 microsandbox/agentsh 职责）
- 不做剩余预算透传（需改请求协议，本轮不引入）

## 2. 契约与验证证据

**constraint 先查清再改**（避免破坏既有契约）：

- `tests/test_tool_contracts.py:222-223` 断言每条 run_shell 流必须有 `encoding` / `decoding_lossy` → **保留**
- `bench/aci/runners/live_agent_loop.py:1076` 用 `raw_bytes` 判断是否回读 artifact → **保留**
- `tests/operation_protocol_tests.rs` / `tools/tool_contract_replay.py` 只 `.get()`，缺字段安全

| 验证 | 结果 |
|---|---|
| `cargo test --lib` | **162 passed / 0 failed**（含 4 个新增单测） |
| `cargo test --test operation_protocol_tests` | 9 passed / 0 failed |
| 契约（microVM 内 `ae --version` + 校验） | `validation_errors: []` |
| 极端输入 7 类（空/小/单行 4 万字符/含 warning 大 blob/二进制/3000 行/非零退出） | **0 校验错误、0 异常** |
| 真实轮次内字段形状 | stderr 9 键 → **3 键**；stdout 9 键 → **5 键**；0 个冗余 `returned_bytes` |

## 3. L4 纵向对比（同 tier、同 seed=42、20 题 × 3 臂）

| 轮次 | ae / 预算 | A | A prime | D | D obs | Ap obs | 裁决 |
|---|---|---|---:|---:|---:|---:|---:|---|
| l4-slim-r3 | afe227ca / 32c-600s | 16 | 15 | 16 | 3491 | 1892 | POSITIVE |
| l4-envelope-r4 | 12b427a9 / 32c-600s | 15 | 15 | 14 | 5445 | 3269 | INVALID |
| l4-budget48-r5 | 12b427a9 / 48c-900s | 12 | 15 | 16 | 5901 | 3104 | POSITIVE |
| **l4-lean-r6** | **00343d1e / 48c-900s** | **19** | **13** | **14** | **3919** | **1934** | **POSITIVE** |

D vs A prime（按成功题数，非浮点率）：

| 轮次 | D − A prime | obs 比 | tool 比 | D 异常 |
|---|---:|---:|---:|---:|
| r3 | **+5.0pp** (16 vs 15) | 1.85x | 1.15x | 0/20 |
| r4 | −5.0pp (14 vs 15) | 1.67x | 1.44x | 3/20 |
| r5 | **+5.0pp** (16 vs 15) | 1.90x | 1.19x | 1/20 |
| r6 | **+5.0pp** (14 vs 13) | 2.03x | 1.41x | 1/20 |

## 4. 结论

### 4.1 站得住的

1. **D vs A prime = +5pp 在三次独立轮次复现**（r3/r5/r6），且都是"net +1 题"。方向一致，但幅度只有 1 题。
2. **瘦身真实生效**：D 绝对 obs tokens 从 5901（r5）降到 **3919（r6）= −33.6%**；r6 真实 cell 里 stderr 只剩 3 个键。
3. **E3 是真实 bug 修复**：单条诊断无上限曾产生 11.9KB 垃圾 warning。

### 4.2 站不住的（必须诚实说明）

1. **obs 比值没有改善**：r5 1.90x → r6 2.03x。原因是**对照臂 A prime 同期降得更多**（3104 → 1934 = −37.7%），
   而 A prime 完全不走 ae，其体积变化只能来自模型/环境波动。
   → 本 setup 下 obs token 的单 seed 波动约 ±38%，**−20% 效率门槛用单 seed 基本不可测**。
2. **A 臂方差极大**：19/20 → 12/20 跨轮摆动（±7 题）。说明单 seed 的绝对成功率不可比。
3. **E3 在 r6 未触发**：r6 的诊断最长只有 115 字符，垃圾 warning 场景这轮没复现。它是一个防御性修复，
   离线回放显示若复现可省 12.5%，但本轮实际收益为 0。

## 5. 顺带修掉的打分器 bug

`tools/agent_shell_benefit/suite/rescore_suite.py:120` 用浮点比较成功率差：
`0.70 - 0.65 = 0.04999999999999993 < 0.05`，把 r6 的 **+5pp（14/20 vs 13/20）误判为"no threshold met"**。

已改为**整数计数交叉相乘**比较（并给恢复率比较加 epsilon）。修正后 r6 判 **POSITIVE**。
旧轮 summary.json 未被重写（r5 原本也是 +5pp，两种算法一致为 POSITIVE）。

## 6. 诚实边界

- 单 seed、单机、诊断级；+5pp = 净 +1 题，二项 sd≈1.9 题，**不足以作为稳定效应**。
- r3→r6 跨轮次，ae 二进制与预算均变化；已逐轮标注。
- r6 的 T408/D 出现 1 次 `adapter_error`（第 11 次调用只返回 ae banner、无 observation）。
  该题是进程 fanout 题，前 10 次调用正常。**已复验**：用同一新二进制单独复跑 T408/D，
  得到 `completed / success=true`（301s），故该异常是环境性瞬态（fanout 题 guest 内存），
  **不是信封改动引入的缺陷**。
- 未提交 / 未合并 / 未推送；未改 Task Forest；全部旧轮与失败样本保留。

## 7. 下一步建议

1. **多 seed 才能定论**：+5pp 需要 3 seeds 才能与噪声分开（单 seed sd≈1.9 题）。
2. **效率门槛改口径**：obs token 波动 ±38%，应考虑用"同一模型调用序列下的 payload 字符数"做静态对比，
   而不是跨轮 mean。
3. **若要真正压低 obs**：剩下的 49.4% 是 stdout 正文本身，需要按 profile 做内容级规约（测试输出只留失败+汇总等），
   属产品行为改动，需单独评估。