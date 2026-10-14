# Agent Shell 恢复轮 r1（内存自适应）（2026-10-13）

任务：在宿主内存紧张条件下稳定跑一轮"新信封（A1–A5）吸收收益"验证。
主指标：首错后恢复率 / 恢复所需步数；次指标：成功率 / observation token / tool calls。

## 1. 先定内存：单 VM 探针（跑之前）

| 项 | 实测 |
|---|---|
| 主机内存 | 15.18 GiB 总；体检时空闲 1.52 GiB（90% 已用） |
| msb 默认 VM | 1 vCPU / 512 MiB（`msb inspect` 确认，与本轮显式参数一致） |
| 单 sandbox 空闲 | `msb` 进程 WS ≈ 121 MB |
| 单 sandbox 负载 | 200 MB python 负载时 `msb` WS 峰值 571 MB；该负载被 guest OOM kill，证实 512 MiB 是硬上限 |
| 删除后 | 内存立即归还（free 423 → 1700 → 2700 MB） |
| 并发 | runner 本身一次只开 1 个 sandbox（串行） |

结论：按 512 MiB / 1 vCPU / 串行 跑；另加宿主内存闸门。

## 2. 内存自适应实现（本轮新增）

- `run_suite.py`：新增 `--min-free-mb`（默认 1024，本轮 1200）、`--memory-poll-seconds`、`--memory-wait-timeout`、`--cell-cooldown`（本轮 8s）。
  每个 cell 开始前阻塞等待宿主可用内存 ≥ 阈值；cell 内记录 `host_memory.available_mb_before / available_mb_after_close`。
- `adapters/microsandbox.py`：显式传 `--cpus 1 --memory 512M`（数值与 msb 默认一致，改为可审计的硬上限，避免默认值漂移）。
- 逐格原子写盘（`atomic_write_json`），任何中断都可 `--resume` 续跑。

## 3. 本轮配置

| 项 | 值 |
|---|---|
| round | `recover-r1-20261013` |
| tasks | T402,T407,T409,T413,T417,T420（r3 中 D 失败/超时/需恢复的 L4 题） |
| arms | A / A′ / D = 18 cells |
| seed | 42 |
| budget | max-model-calls 32 / cell-timeout 600s（与 r3 可比） |
| ae-linux sha256 | `12b427a9…`（含 A1–A5） |
| runner sha256 | `ee1b562b…` |
| 结果 | 18/18 cells，退出码 0，无残留 sandbox |

## 4. 稳定性证据

- cell 墙钟跨度 82 min；cell 纯执行 68.3 min；差 ≈14 min 为内存闸门等待 + cell 冷却。
- 宿主可用内存采样（235 点 / 20s，`host_memory_samples.csv`）：min **17.9 MB** / max 6524 MB / avg 1517 MB；< 1200 MB 占 110/235（47%）。
- 低点主因是**外部 llama-server 在 15:38 被重启并增长**（新 PID 18384），与本轮 microVM 无关；本轮单格内存上限约 600 MB。
- 全程 0 个 `adapter_error` / `endpoint_error`，0 OOM；2 个 cell 为预算耗尽（见 §6）。

## 5. 治疗是否真的触达（关键前置）

| 项 | r3（旧信封）D | r1（新信封）D |
|---|---:|---:|
| 失败观测数 | 5 | 4 |
| 带 `suggested_next` | 4/5 (80%) | 4/4 (100%) |
| 带 `substitutions` | 0/5 | 0/4 |
| `status=failed/blocked` | 0/5（字段不存在） | 4/4 (100%) |
| `blocked_operation` | 0/5（字段不存在） | 4/4 (100%) |

直接探针（microVM 内、同一二进制）确认 `substitutions` 只在已知工具缺失时触发：
`xxd` 缺失 → `od -c <file>`；`permission denied` → `chmod +x <file> && ./<file>`；超时 → 加大 `timeout_ms`；
任意未知命令缺失 → 通用 recourse（无 substitution）。即 A1–A5 已进二进制并生效，只是这 6 题没有 xxd/curl/permission 型失败。

## 6. 结果（按实现打分的裁决）

| arm | 成功率 | 恢复率 | 恢复分母 | obs tokens | tool calls | model calls | 异常 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0.17 | 1.00 | 2 | 2006.5 | 12.83 | 14.17 | 1 |
| A′ | 0.50 | 1.00 | 2 | 2473.7 | 11.50 | 12.67 | 0 |
| D | 0.50 | 1.00 | 2 | 4551.7 | 11.67 | 12.83 | 1 |

配对（A′ vs D）：D 胜 T409、T417；A′ 胜 T402、T407；平 T413、T420。

**裁决：INVALID**。预注册规则为"安全违规或异常率 >10% 判 INVALID"（`docs/agent-shell-suite-80-design-2026-10-12.md:89-90`）。
本轮异常 2/18 = 11.1%：`T407/A turn_cap`、`T407/D task_timeout`。两者都是 **600s / 32-call 预算耗尽**，不是链路故障（`endpoint_errors=0`，`safety_violations=0`）。

即便忽略 gate，本轮也**没有正收益**：

- 成功率 D vs A′ = 0.50 vs 0.50（0pp，未达 +5pp）
- 恢复率 D vs A′ = 1.00 vs 1.00（各仅 2 个分母，饱和；未达 +15pp）
- observation tokens 4551.7 vs 2473.7（**D 高 84%**，方向相反）
- tool calls 11.67 vs 11.50（持平，未达 −15%）

## 7. 自对比：D-old(r3) vs D-new(r1)（同 6 题）

| 指标 | D-old r3 | D-new r1 | Δ |
|---|---:|---:|---:|
| 成功率 | 2/6 = 0.33 | 3/6 = 0.50 | +17pp |
| 失败观测 guidance 覆盖 | 80% next | 100% next+status+blocked | 新字段全面出现 |

**但不能归因给新信封**：未改任何代码的 A′ 在同一 6 题上从 1/6 → 3/6（+33pp），A 从 2/6 → 1/6。
说明这 6 题（尤其 T407 卡在 600s 边界）由 run-to-run 方差主导，n=6 不足以支撑归因。

## 8. 诚实边界

- 单 seed、18 格、诊断级；不升级为发表级结论。
- 旧轮（`l4-final`、`l4-final-r2`、`l4-slim-r3`、`sampler*`）全部保留，未删未改。
- 本轮修改了 runner/adapter（内存闸门 + 显式 512M），故另起新 round id，不与 r3 拼接。
- 未提交 / 未合并 / 未推送；未改 Task Forest。

## 9. 下一步建议（本轮未执行）

1. 这 6 题子集**不适合做收益裁决**：单题 T407 就吃满 600s 边界，A′ 方差达 ±33pp。收益裁决应回到全 L4（20 题 × 3 臂 = 60 格）或 handoff 的 10-task 配对设计。
2. 若继续这条线：把 cell-timeout 提到 900s（另起新 round id），否则 T407 的胜负由时钟决定而不是由信封决定。
3. 内存：本轮证明 512 MiB VM + 串行 + 1200 MB 闸门在宿主 min 17.9 MB 的极端压力下仍无 OOM；若要更稳可把闸门提到 1500–1800 MB，代价是等待显著变长（当前 1800 MB 仅 13% 时间可满足）。
