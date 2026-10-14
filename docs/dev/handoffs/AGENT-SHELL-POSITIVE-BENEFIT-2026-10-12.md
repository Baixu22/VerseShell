# HANDOFF — Agent Shell 正收益验收实验体系

- 日期：2026-10-12
- 状态：可执行，不再需要补充规划
- 目标：验收 VerseShell 的信息层是否能在真实 agent shell 执行层上带来**可复现正收益**
- 默认执行规模：10 tasks × 3 arms × 1 seed = **30 cells**
- 默认上限：≤12 tasks、≤60 cells、≤2h；不启动发表级重复研究

## 1. 先固定边界

本实验**不是** harness 排名，也**不是** agent shell 产品排名。

- 执行层只允许使用一个主运行环境：`microsandbox 0.7.8`
- `agentsh`、`SWE-ReX` 只作为第二阶段/参考，不进入主验收。
- Codex CLI、Claude Code、OpenCode、Qwen Code 是 harness，禁止进入本验收主矩阵。
- 验收对象是：**相同执行层、相同模型、相同任务、相同工具集合下，VerseShell observation/provider 是否带来正收益**。
- 不允许用“产品本身更强/更弱”替代“VerseShell 接口有正收益”。

## 2. 三条 arm

所有 arm 使用相同：

- Step 5P：`step-5-preview`
- system prompt（除 A 的匹配提示外）
- `run_shell`/`run_parallel`/`finish` 工具名和参数
- 任务、预算、shell 命令、oracle

### A：raw shell

- 直接返回：`exit_code`、`stdout`、`stderr`、`elapsed_ms`、`timed_out`
- stdout/stderr 只做固定 8KB 截断
- 无 artifact handle、无 recovery hint、无 diagnostics 结构

### A′：raw shell + matched prompt

- observation 与 A 完全相同
- prompt 改成与 D 同等信息量的 matched prompt
- 唯一用途：把“提示词收益”从“接口收益”里剥掉

### D：VerseShell observation

- 同一个 microsandbox 执行层
- 同一个命令和原始 stdout/stderr
- 唯一差异：返回 `verseshell.observation/v1` 信息层：
  - `ok`
  - `op` / `command`
  - `exit_code`
  - bounded stdout/stderr
  - `artifact`/`result_handle` for oversized output
  - `error.code`
  - `error.message`
  - `error.retryable`
  - `error.next_actions` / `suggestion`
  - `diagnostics`（expected/found、缺失/歧义位置、可执行恢复动作）
  - `observation_tokens` / truncation metadata

**强制要求**：D 的 observation schema 必须与当前 VerseShell `verseshell.observation/v1` 对齐；不能发明只在 experiment harness 里存在的私有格式。至少增加契约测试，证明实际 `ae` JSON 输出和实验 provider 字段一致。

## 3. 任务矩阵（10 项）

每个任务都必须有：

- 固定 prompt
- 固定 oracle
- 可确定复现的成功标准
- 不允许模型自述代替 oracle

| ID | 任务 | 覆盖 |
|---|---|---|
| T01 | `persist_write_read` | 基本写/读、成功 observation |
| T02 | `missing_file_recover` | 首个工具失败后一步恢复 |
| T03 | `exit_stream_contract` | 非零 exit、stdout/stderr 分离 |
| T04 | `stale_hash_recover` | expected_hash 不匹配后恢复 |
| T05 | `ambiguous_edit_recover` | 多匹配/歧义后恢复 |
| T06 | `large_output_artifact` | 大输出截断 + artifact/tail 查询 |
| T07 | `timeout_cleanup` | timeout、进程树、残留检查 |
| T08 | `process_lifecycle` | start/poll/write/kill/owner |
| T09 | `parallel_commands` | 4 个独立 session/命令 |
| T10 | `isolation_boundary` | 宿主/越界路径读取必须失败 |

不要先跑更多任务。先把这 10 个任务全部打通，30 格一次完成。

## 4. 主要指标

### 4.1 主指标

- `task_success`
- `recovered_after_first_error`
- `cap_or_endpoint_failure`
- `safety_violation`

### 4.2 次指标

- `observation_tokens`
- `total_input_tokens`
- `total_output_tokens`
- `model_calls`
- `tool_calls`
- `wall_ms`
- `duplicate_tool_calls`
- `timeout_cleanup_ms`
- `artifact_recovery_ok`
- `final_answer_matches_trace`

### 4.3 失败分类

每格必须归入以下之一，不能只记 `success=false`：

- `model_error`
- `endpoint_error`
- `adapter_error`
- `task_timeout`
- `turn_cap`
- `tool_failure_unrecovered`
- `verifier_failure`
- `safety_violation`

任何 `adapter_error` 或 `endpoint_error` 都不能事后静默丢弃；必须保留 raw trace 并计入异常率。

## 5. 通过/失败判定

### 5.1 可归因对照

默认使用 **D vs A′** 作为可归因主对照。

- A vs D 只报告，不作为主结论。
- A′ 必须与 D 使用等量 prompt；否则实验直接判无效。

### 5.2 默认验收规则

D 在 10 个配对任务中满足以下任一条件，且无安全回退、无异常率恶化，则记为“有正收益”：

1. **成功提升**：D 成功率至少 +1/10，或
2. **恢复提升**：首错后恢复率至少 +15 个百分点，或
3. **效率提升**：成功率不降，`observation_tokens` 至少 -20%，或
4. **调用收敛**：成功率不降，平均 tool calls 或 model calls 至少 -15%。

### 5.3 硬性 guardrail

- `safety_violation > 0` → 判失败
- `endpoint_error + cap + adapter_error > 10%` → 判无效，先修实验链路
- D 的 oracle 失败率高于 A′ → 判失败
- 任何任务在 arm 之间缺格 → 判无效

### 5.4 结论只允许三种

- `POSITIVE`：满足 5.2 且 guardrail 全过
- `NO_EVIDENCE`：指标未达到或样本不足
- `INVALID`：链路/缺口/安全/异常率问题

不允许用 `PASS` 覆盖 `NO_EVIDENCE`。

## 6. 运行协议

### 6.1 P1 默认验收

- 10 tasks
- 3 arms
- 1 seed
- 1 repeat
- 30 cells
- 预计 ≤2h

### 6.2 执行顺序

1. 先跑 T01/T02/T03 的 3×3=9 格 smoke
2. smoke 只要有 adapter/harness 错误，先修 harness，不进入全量
3. 跑完 T04–T10 的剩余 21 格
4. 任何格子失败都保留原样
5. 最后统一 rescore 和 report

### 6.3 禁止事项

- 不删除失败样本
- 不重算旧轮成绩
- 不用新 provider 拼接旧数据
- 不修改 task/oracle 让失败变绿
- 不在未确认时改 Task Forest 状态

## 7. 需要创建的文件

主目录建议：

```text
tools/agent_shell_benefit/
  README.md
  task_manifest.json
  run_round.py
  rescore.py
  report.py
  adapters/
    microsandbox.py
    agentsh.py            # 第二阶段
  providers/
    raw.py
    matched.py
    verseshell.py
  tasks/
    T01_persist_write_read.json
    ...
    T10_isolation_boundary.json
```

实验产物统一放仓库外：

```text
D:\VerseShellEval\agent-shell-benefit\<round-id>\
  manifest.json
  preregistration.md
  rows.jsonl
  cells/
    <task>__<arm>__<seed>.json
  summary.json
  report.md
```

仓库只留轻量摘要和报告指针。

## 8. 当前已有证据

Step 5P 18 格执行层实验：

- `microsandbox`：6/6 任务成功，错误契约 3/3，isolation 通过
- `agentsh`：4/6，failure/parallel 通过；`sh -c` timeout 约 10s
- `SWE-ReX LocalRuntime`：2/6，exit_code/stream/timeout/parallel/isolation 均暴露问题

报告：

- `docs/agent-shell-step5p-experiment-2026-10-12.md`
- `docs/agent-shell-products-comparison-2026-10-12.md`

这些证据只说明**执行层选择**，不证明 VerseShell 正收益。下一步必须做 D vs A′。

## 9. 第一轮实施任务

### P0：实现

1. 写 `microsandbox` adapter，提供 `run/run_parallel/read_file`。
2. 写 raw provider 和 verseshell provider；字段对齐 `verseshell.observation/v1`。
3. 写 matched prompt provider；A′ 的 prompt 和 D 系统提示信息量匹配。
4. 落 10 个任务 JSON 和 oracle。
5. 写 runner，按 `(task, seed, arm)` 落盘，保存完整模型消息和工具 observation。
6. 写 rescore/report，禁止人工改 verdict。

### P1：验收

1. 跑 30 格。
2. 产出 `summary.json` 和 `report.md`。
3. 给出 `POSITIVE / NO_EVIDENCE / INVALID` 最终裁决。
4. 如果 `POSITIVE`，只关闭对应功能宣称，不自动改 Task Forest，不自动提交。

### P2：仅在明确授权后

- 12 tasks × 3 seeds × 3 arms × 2 repeats
- 或 D 与 A′ 的配对 bootstrap/区间
- 该阶段才属于正式研究，不进入默认路径

## 10. 验收定义与下一步

本 handoff 完成后，默认验收不是“跑出好看的案例”，而是：

- 30/30 格都有原始 trace；
- D vs A′ 的配对结果可复算；
- `POSITIVE / NO_EVIDENCE / INVALID` 三选一有唯一裁决；
- 任何正收益结论都能指到具体 task、seed、arm、原始 observation 和 oracle。

当前没有待用户决策的阻塞问题。下一步直接实现 runner 并跑 P1。

## 11. 后继 agent 的启动指令

直接执行，不要重新设计：

1. 创建 `tools/agent_shell_benefit/` 骨架。
2. 先实现 `microsandbox` + raw/verseshell provider。
3. 落 T01/T02/T03 的 3×3 smoke，先修 adapter，再跑 T04–T10。
4. 使用 `D:\VerseShellLive\secrets\stepfun-step5p-20261010.env` 的 `step-5-preview`。
5. 产物写 `D:\VerseShellEval\agent-shell-benefit\p1-20261012\`。
6. 最终只输出：`POSITIVE`、`NO_EVIDENCE` 或 `INVALID`，附 30 格统计、配对结果、原始 trace 路径。
