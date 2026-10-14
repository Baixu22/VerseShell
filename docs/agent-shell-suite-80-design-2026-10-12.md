# Agent Shell 综合测试套件设计：80 题四档（2026-10-12）

本页记录 `tools/agent_shell_benefit/suite/` 的设计。它是 10 题 P1 的**难度与规模升级**，
核心诉求有两条：**复杂场景下的处理策略**、**高并发下的处理措施**。

## 0. 为什么升级

P1（10 任务 × 3 arm）得到 `NO_EVIDENCE`，根因是**天花板效应**：A′（纯 raw + 匹配提示）
都拿 10/10，信息层无处发挥。本套件用四档难度把 raw 的失败率打开，并显式加入并发轴。

## 1. 规模与分档

| 档 | ID | 名称 | 题数 | 考察重点 |
|---|---|---|---:|---|
| L1 | T101–T120 | simple | 20 | 单步/两步：读写、退出码、流分离、截断、timeout、4 路并行、隔离 |
| L2 | T201–T220 | medium | 20 | 失败恢复、状态、条件分支、原子写、锁、基础并行、幂等 |
| L3 | T301–T320 | hard | 20 | 多阶段流水线、竞争检测、锁争用、背压、saga、2PC、检查点、故障注入 |
| L4 | T401–T420 | devil | 20 | 死锁避免、TOCTOU、脑裂、惊群、级联超时、进程炸弹、逃逸、全轴集成 |

合计 **80 题**；默认 3 arm（A / A′ / D）= **240 格**。

## 2. 覆盖矩阵

每条题目都至少落在一个覆盖轴上，且**每题的 oracle 都必须有可验证产物或轨迹证据**
（禁止只靠 summary 里打印一个 token 就算过）。

| 轴 | 说明 | 代表题 |
|---|---|---|
| strategy | 多步计划、依赖排序、条件逻辑、事务 | T301、T318、T319、T420 |
| recovery | stale hash、歧义、超时、部分失败、故障注入 | T201、T202、T320、T403 |
| concurrency | run_parallel 扇出、写竞争、锁争用、顺序 | T303、T304、T315、T402、T419 |
| lifecycle | 进程 start/poll/kill、清理验证 | T105、T209、T305、T409、T416 |
| safety | 宿主边界、目录穿越、符号链接逃逸、密钥 | T107、T411、T412、T413 |
| artifact | 大输出、截断、tail/grep 恢复 | T104、T106 |

## 3. 声明式任务与 oracle

每个任务是纯数据（`suite/tier_*.py`）：setup 命令、可选 fixture、evidence 规格、oracle 检查树。

```python
task("T201", "L2", "stale_hash",
     "<fixed prompt>",
     [{"type": "file_equals", "path": "/workspace/stale.txt", "value": "NEW"},
      {"type": "recovered"},
      {"type": "summary_contains", "value": "NEW"}],
     setup=["printf 'OLD\\n' > stale.txt"],
     fixtures=[FIX_HASH], files=["/workspace/stale.txt"])
```

检查引擎（`suite/oracles.py`）支持组合：`all_of` / `any_of` / `not`，以及
`file_equals`、`file_contains`、`file_absent`、`file_matches`、`file_count_lines`、
`exit_seen`、`stdout_seen`、`command_seen`、`parallel_used`、`parallel_result_count`、
`parallel_wall_lt`、`no_process`、`host_blocked`、`recovered`、`no_duplicate_commands` 等。

**关键健壮性**：`recovered` / 失败判定同时接受**进程退出码**和**输出里的错误标记**
（`E_STALE_HASH`、`No such file or directory` 等）。因为 agent 常写
`cmd; echo EXIT_CODE=$?`，把真实退出码改写为 0——这一点在 P1 已经踩过一次。

## 4. 并发与复杂场景的具体设计

- **扇出/扇入**：T106、T213、T214、T419 用 `run_parallel`，oracle 同时校验
  `parallel_used`、`parallel_result_count`、`parallel_wall_lt`（真实并行而非串行）。
- **写竞争**：T303（4 写者计数）、T315（加锁 10 次自增）、T402（16 写者 + 锁）。
- **锁语义**：T304（同锁两进程，仅一个进临界区）、T308（分布式锁释放）、T407（锁车队）。
- **超时与级联**：T105、T215、T316、T409、T416 要求超时后**验证无残留进程**。
- **故障恢复**：T320（注入故障）、T403（崩溃后重放）、T312（检查点续跑）。
- **一致性**：T319（2PC）、T404（exactly-once）、T410（脑裂）、T418（并发定序）。
- **安全边界**：T107、T411、T412、T413 在宿主探测为“可见”时直接判失败。

## 5. 运行方式

```powershell
# 单档冒烟（L1）
python tools\agent_shell_benefit\suite\run_suite.py `
  --round-id suite-p1-20261012 --tiers L1 --arms all --seed 42 --resume

# 全量 80 题 × 3 arm = 240 格
python tools\agent_shell_benefit\suite\run_suite.py `
  --round-id suite-p1-20261012 --tiers all --arms all --seed 42 --resume

python tools\agent_shell_benefit\suite\rescore_suite.py `
  --round-dir D:\VerseShellEval\agent-shell-benefit\suite-p1-20261012
```

产物目录与 P1 相同约定，额外含每档（L1–L4）分组统计与并发指标。

## 6. 门槛与裁决

沿用 P1 的三选一裁决（`POSITIVE / NO_EVIDENCE / INVALID`）与 guardrail：
安全违规或异常率 >10% 判 `INVALID`；成功率 +5pp、恢复率 +15pp、
observation token −20%、tool call −15% 任一达标且成功率不降才判 `POSITIVE`。
分档后**必须按 L1–L4 分别报告**，避免用简单档的通过掩盖难档的失败。

## 7. 诚实边界

- 本题库为**诊断级**单次采集设计；240 格属规模升级，不自动升级为发表级。
- 单次全量预计显著超过 2 小时；**执行前需显式确认预算**（见 AGENTS.md §4）。
- 难度是设计意图，实际难度以首轮 raw 臂失败率为准，需实测校准。
- 本页不关闭任何功能宣称，不修改 Task Forest。