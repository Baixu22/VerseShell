# 信息层定位：与 pwsh7 / Git Bash / cmd 及 agent-shell 的对比（2026-10-12）

按 AGENTS.md 的轻量路径：诊断级证据，不对外发表。数据来自仓库既有产物 + 本轮新增 pwsh7 对照。

## 一句话结论

**速度不是重点**（工具时间只占 agent 端到端 1.5%–4.7%）。VerseShell 的价值在**信息层**：
给 agent 更少但更可执行的观察，并在失败时给出可一步执行的恢复方案。这两点有可复现证据。

## 1. 速度层：对 pwsh7 快，但对 cmd 无优势，且不影响端到端

新增对照（`tools/cross_shell_bench_pwsh7.py`，20 次迭代 / 3 次预热，语义等价已校验）：

| 操作 | ae | pwsh7 | pwsh5.1 | cmd | Git Bash | ae/pwsh7 |
|---|---|---|---|---|---|---|
| CPU info | 314.8ms | 1423.0ms | 1323.1ms | 90.8ms | 399.4ms | 0.22x |
| Disk info | 12.3ms | 391.5ms | 401.7ms | 18.3ms | N/A | 0.031x |
| List dir | 12.1ms | 362.1ms | 309.8ms | 8.9ms | 368.6ms | 0.033x |
| Read file | 13.3ms | 294.8ms | 163.1ms | 13.3ms | 401.1ms | 0.045x |
| Pipeline 1K | 12.3ms | 359.9ms | 217.8ms | N/A | 387.0ms | 0.034x |

**对 pwsh7：5/5 更快。对 cmd.exe：无优势**（CPU 3.5x 慢、List dir 1.35x 慢、Read 打平、Disk 1.5x 快）。
**但这些操作只占 agent 端到端 wall clock 的 1.5%–4.7%**，其余是模型延迟。所以速度几乎不影响任务结果。

## 2. 信息层：这才是正收益所在（有证据）

### 2.1 更少的读取调用干同样的事（file.read_many 多路复用）

`eval/step_composition.json`（105 runs/arm）：

| 指标 | with read_many | without | 变化 |
|---|---|---|---|
| 读取调用/run | 1.371 | 2.152 | **-36.3%** |
| 步骤/run | 4.019 | 4.876 | **-17.6%** |
| 观察 token/run | 761.63 | 722.44 | +5.4%（略高，诚实记录） |

结论：批量读取把「读多个文件」压成一次调用，**减少 agent 往返**（36% 读取调用、18% 步骤），
代价是单次观察略大。这属于「干更多事情」而非「更快」。

### 2.2 compact 投影：削掉信封噪声（read_path_breakdown）

`eval/read_path_breakdown.json`（141 次真实调用）：

- 总 token 节省 7.9%（77017 → 70940）
- `line_wrapper` 占比 10.8% → 5.9%（砍掉一半行包装噪声）
- `counts` 占比 2.84% → 0.45%
- 内容本身（`content`）不变（77.5% → 84.2%）——**不删信息，只删包装**

### 2.3 失败信封：错误里带可执行诊断（failure_envelope）

pytest 失败信封 376 字符里，各字段贡献（leave-one-out）：

| 字段 | 占比 |
|---|---|
| diagnostics | 36.2% |
| error | 26.3% |
| stats | 17.0% |
| stderr_summary | 12.8% |
| exit_code | 4.3% |
| ok | 3.5% |

即：失败信息里最大的是**结构化诊断**（expected/found、可定位锚点），而不是原始 stderr 倾倒。

## 3. 闭环：失败之后能一步应对（有证据）

| 宣称 | 值 | 含义 |
|---|---|---|
| C3 diff 完备率 | 1.00 | expected/found 可抽取 |
| C4 一步恢复结构字段 | 1.00 | `E_STALE_HASH` 带 actual_hash；`E_AMBIGUOUS` 带 matches[] |
| C6 可撤恢复闭环 | 12/12 | trash → restore 全链 |
| C30 file.view 给窗口而非哈希 | 1.00 | 默认给可读窗口 |
| C26 投影兑现工具描述承诺 | 1.00 | 描述说的负载真的到达模型 |

这构成「遇到问题 → 有完整应对方案」的闭环证据：错误不是死胡同，而是带下一步动作的结构化响应。

## 4. 诚实的边界

- 速度数字是**单机诊断**，不是可移植保证；对 cmd 无优势。
- ACI live A/B（93.3% vs 90.5% 成功率、0.61x 观察 token）是**单次历史采集、单模型**，不是跨模型结论。
- 未做过任何「同系 agent shell」竞品的直接对照，因此**不能宣称优于它们**。
- 信息层收益的方向清晰且可复现；绝对幅度需要更多样本才能定论（但那属于发表级，默认不做）。