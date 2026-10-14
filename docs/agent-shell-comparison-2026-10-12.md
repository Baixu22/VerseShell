> **类别说明（2026-10-12 修订）**：本文比较的是完整 agent harness。专门面向 agent 的 shell/执行层产品对比见 [agent-shell-products-comparison-2026-10-12](agent-shell-products-comparison-2026-10-12.md)。本文仅作为 harness 参考，不与 agent shell 混做同系结论。

# Agent Harness 多维参考对比：VerseShell / Codex CLI / Claude Code / Gemini CLI / OpenCode / Qwen Code（2026-10-12）

本文记录的是完整 agent harness 的产品级对照，**不是同系 agent shell 产品对比**。真正的执行层对比见新报告。
按 `AGENTS.md`，本文是**单次、可复现的诊断级对比**，不是对外发表或正式验收。

## 0. 一句话结论

在这轮 3 任务、同模型（`sn-glm-5-3-flash`）的直测里：

- **OpenCode 的综合处理效率最好**：3/3 成功、平均 69.0s、平均 25.6k tokens、1 次工具失败、3/3 干净退出。
- **Codex CLI 的任务完成能力同样强**，但代价最高：3/3 成功、平均 101.3s、平均 194.1k tokens、18 次命令失败；它靠强恢复能力完成，不是靠少走弯路。
- **Qwen Code 在短任务上很省步骤**，但在 CSV 大任务上出现严重长尾：判分通过，但 CLI 在 **600s wall cap** 时以 exit 55 中止，没有输出最终 result。
- **VerseShell ACI 与 OpenCode 同档**：3/3 成功、平均 59.4s、平均 27.3k tokens、0 次工具失败、3/3 干净退出。这个样本不足以证明它全面优于 raw shell；raw shell 在 2 个完成任务上反而更省 tokens。
- **Claude Code 默认态**另跑了 1 个小任务：成功，但 714s、173.8k tokens、报告成本 $1.50。它使用的不是同一模型，只能作补充，不能并入同模型排名。
- 官方 Terminal-Bench 2.0 数据也说明：**模型和 harness 强耦合**。同一个 Claude Opus 4.6 下，Claude Code 58.0%，而 Droid 69.9%、Mux 66.5%、Terminus 2 62.9%。因此不能把产品榜单分数全部归因给 shell 实现。

一句话概括：**agent 处理性能的瓶颈主要是回合/工具循环、上下文和终止控制，不是 shell 命令本身的毫秒数。**

## 1. 评测口径

### 1.1 两类证据严格分开

1. **同模型产品级直测**：`sn-glm-5-3-flash`，3 个任务，1 seed，1 repeat。
   - Codex CLI
   - OpenCode
   - Qwen Code
   - VerseShell `verseshell_aci`
   - VerseShell `raw_shell`（对照）
2. **产品默认态补充**：Claude Code 使用其本机默认 `claude-opus-5[1m]`；只跑 1 个任务，用于补充默认产品体验，不参与同模型聚合。

### 1.2 统一任务

- `python_exception_mislabel_0816896a`：小型 Python 异常语义修复。
- `node_envconfig_validate_dd681123`：Node/JS 配置校验修复。
- `python_csvlite_parse_80d158b2`：较大 CSV 状态机实现。

三者都使用仓库现有 task set 3.1.0、冻结 fixture、同一判分器；外部产品只替换 agent shell，不改题目和 verifier。

### 1.3 统一约束

- 同一台 Windows 机器。
- 同一本机 OpenAI-compatible 端点 `http://127.0.0.1:3065/v1`。
- Codex：`danger-full-access`，`approval_policy=never`，`responses` wire API。
- OpenCode：`--pure`，`--dangerously-skip-permissions`，隔离 XDG 配置/数据目录。
- Qwen：`--bare`，OpenAI-compatible，`--approval-mode yolo`，`--max-wall-time 10m`。
- VerseShell：`max_turns=24`，`max_tokens=16384`，`repeat-call-limit=3`。
- 外部产品保留各自默认 system prompt、工具集和上下文策略；因此这是**同一模型下的产品级对比**，不是“只换 shell、完全同提示”的接口消融。

## 2. 同模型直测结果

### 2.1 逐任务明细

| 任务 | 产品 | 判分 | 退出 | wall | LLM 请求/回合 | 工具调用 | 工具失败 | 报告 tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| exception | Codex | PASS | 0 | 60.3s | 1 | 9 | 4 | 110,209 |
| exception | OpenCode | PASS | 0 | 43.6s | 6 | 6 | 0 | 18,757 |
| exception | Qwen | PASS | 0 | 36.1s | 4 | 4 | 0 | 34,987 |
| exception | ACI | PASS | 0 | 32.5s | 5 | 4 | 0 | 16,300 |
| exception | raw shell | PASS | 0 | 44.7s | 5 | 7 | 0 | 12,143 |
| envconfig | Codex | PASS | 0 | 67.0s | 1 | 10 | 4 | 129,846 |
| envconfig | OpenCode | PASS | 0 | 20.6s | 5 | 5 | 0 | 17,041 |
| envconfig | Qwen | PASS | 0 | 48.1s | 4 | 4 | 0 | 34,544 |
| envconfig | ACI | PASS | 0 | 24.6s | 7 | 6 | 0 | 28,635 |
| envconfig | raw shell | PASS | 0 | 42.4s | 4 | 5 | 0 | 9,592 |
| csvlite | Codex | PASS | 0 | 176.6s | 1 | 19 | 10 | 342,310 |
| csvlite | OpenCode | PASS | 0 | 142.9s | 7 | 7 | 1 | 40,897 |
| csvlite | Qwen | PASS | **55** | **603.4s** | 3 | 3 | 0 | 59,073（部分） |
| csvlite | ACI | PASS | 0 | 121.2s | 6 | 6 | 0 | 36,963 |
| csvlite | raw shell | **FAIL/endpoint_error** | 0 | **904.5s** | 2 | 3 | 0 | 不可用 |

Qwen CSV 的原因不是 final verifier 失败：workspace 已改对并通过判分，但 CLI 在 600s 预算耗尽后退出 55，未给出最终 result。该情形应列为**任务达成、运行未正常收口**。

### 2.2 聚合

| 产品 | 判分成功 | 干净退出 | 平均 wall | 平均回合/请求 | 平均工具 | 工具失败总数 | 平均 tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Codex CLI | 3/3 | 3/3 | 101.3s | 1.0 | 12.7 | 18 | 194.1k |
| OpenCode | 3/3 | 3/3 | 69.0s | 6.0 | 6.0 | 1 | 25.6k |
| Qwen Code | 3/3 | 2/3 | 229.2s | 3.7 | 3.7 | 0 | 42.9k |
| VerseShell ACI | 3/3 | 3/3 | 59.4s | 6.0 | 5.3 | 0 | 27.3k |
| raw shell | 2/3 | 2/3 | 43.5s（仅 2 个成功） | 3.7 | 5.0 | 0 | 10.9k（仅 2 个成功） |

token 口径不完全统一：

- Codex：`turn.completed.usage.input_tokens + output_tokens`；input 包含其上报的 cached input。
- OpenCode：`info.tokens.input + output + reasoning`；cache read 另行报告。
- Qwen：完整任务用 result 的 `usage.total_tokens`；CSV 用 debug/chat 记录的 API usage 求和。
- ACI/raw：`llm_prompt_tokens + llm_completion_tokens`。

因此 token 只能看量级和方向，不能当成完全同口径计费数据。

### 2.3 Windows 专项观察

- Codex 在 3 个任务中累计 18 次非零退出；主要是 PowerShell 下的 `apply_patch` 调用方式反复失败。它能恢复，但工具循环明显偏贵。
- OpenCode 在 CSV 中只有 1 次工具失败，其余 2 个任务 0 失败。
- Qwen 在 3 个任务中没有工具失败，但 CSV 上出现 3 次 API 响应中后两次分别约 118s、469s 的长推理，最后被 wall cap 截断。
- ACI 3 个任务 0 工具失败，CSV 在 121s 内正常 `task_complete`。
- raw shell 的 CSV 失败是 **endpoint_error/api timeout**，不能归因成“raw shell 逻辑一定更差”；但它确实没有完成，而同一端点下 ACI 正常完成。

## 3. 产品默认态补充：Claude Code

| 任务 | 判分 | 退出 | wall | 回合 | tokens | 报告成本 |
|---|---:|---:|---:|---:|---:|---:|
| exception | PASS | 0 | 714.1s | 6 | 173,770 | $1.50456 |

补充说明：

- 模型为默认 `claude-opus-5[1m]`，不是 `sn-glm-5-3-flash`。
- 本机通过 `127.0.0.1:15721` 的 Anthropic-compatible 网关运行。
- 该任务在默认态下非常慢且贵；但这可能是默认模型、网关延迟、产品默认提示/工具循环的联合结果，不能单独归因给 Claude Code。
- 为避免长尾和费用失控，另外 2 个任务未继续跑。本文不把该单点纳入同模型排名。

## 4. 官方公开榜单证据（Terminal-Bench 2.0）

来源：<https://www.tbench.ai/leaderboard/terminal-bench/2.0>，抓取日期 2026-10-12。

| 产品 | 模型 | 分数 |
|---|---|---:|
| Codex CLI | GPT-5.5 | 82.2% ± 2.2 |
| Gemini CLI | Gemini 3.1 Pro | 61.4% ± 4.1 |
| Claude Code | Claude Opus 4.6 | 58.0% ± 2.9 |
| Claude Code | Claude Opus 4.5 | 52.1% ± 2.5 |
| OpenCode | Claude Opus 4.5 | 51.7% ± N/A |
| OpenHands | Claude Opus 4.5 | 51.9% ± 2.9 |
| Terminus 2 | Claude Opus 4.5 | 57.8% ± 2.5 |
| Mux | Claude Opus 4.5 | 58.4% ± N/A |
| Droid | Claude Opus 4.6 | 69.9% ± 2.5 |

可以看出：

- Codex CLI 在 GPT-5.5 下很强，但这是模型 + harness 的联合分数。
- **同模型下换 harness，分数差异很大**：Claude Opus 4.6 上 Claude Code 58.0，而 Droid 69.9；Claude Opus 4.5 上 Claude Code 52.1，而 Mux 58.4、Terminus 2 57.8。
- 公开榜单能证明“harness 很重要”，但不能证明某个 shell 在控制模型一致后一定更好。

## 5. 架构与处理维度对比

| 维度 | VerseShell 1.0.0 | Codex CLI 0.162 | Claude Code 2.1.281 | Gemini CLI 0.48 | OpenCode 1.16.2 | Qwen Code 0.17.0 |
|---|---|---|---|---|---|---|
| 产品定位 | ACI runtime / tool backend，不是完整 agent | 完整 terminal agent | 完整 terminal agent | 完整 terminal agent | 完整 terminal agent | 完整 terminal agent |
| Agent loop | 由宿主/MCP 客户端提供 | 内置 | 内置 | 内置 | 内置 | 内置 |
| 工具结果形态 | `verseshell.observation/v1`，结构化、带预算 | 文本/命令事件 | 文本/权限事件 | 文本/策略事件 | 结构化 tool parts | JSON/function call |
| 上下文治理 | observation budget、compact、result handles | compaction、harness 管理 | auto-compact | context/memory、策略 | context summarization、server | auto-memory、compress、预算 |
| 失败恢复 | 错误码 + 可执行诊断 + recoverable artifacts | 强，但可能多次错用 Windows 工具 | 强，权限/工具反馈完整 | 策略反馈 | 强，状态化 tool parts | 工具反馈好，但长尾终止差 |
| 并行/会话 | JSON-RPC server、多 agent session、并发预算 | resume/fork、worktree、agents | background agents、worktree、ultrareview | sessions、ACP、worktree | server/web、sessions、agents | agent/subagents、worktree |
| 安全控制 | workspace jail、capability、Job Object/process group、ConPTY | 三档 sandbox + approvals | 权限系统 + hooks | sandbox + policy engine | permissions + plugins | sandbox/yolo + 审批模式 |
| 可观测/无头 | JSON-RPC observation、result artifact | `--json` JSONL | `--output-format json` | `text/json/stream-json` | `--format json` + session export | `json/stream-json` + stats |
| 扩展 | MCP / JSON-RPC / typed ops | MCP、plugins、skills | MCP、plugins、skills、hooks | MCP、extensions、hooks | MCP、ACP、plugins | MCP、extensions、hooks、skills |
| Windows 适配 | Job Object、ConPTY、PowerShell 环境处理 | 可运行；本轮多次 apply_patch 失败 | 可运行；默认态单任务 714s | 本机配置有损坏项，未直测 | 本轮最稳 | 可运行；长任务 wall cap |

### 影响 agent 处理性能的关键结论

1. **“一轮内批很多工具调用”不等于高效。**
   Codex 平均 1 个 LLM 回合完成，但代价是 12.7 次工具调用、18 次失败和 194k tokens/任务。
2. **回合数少也不等于延迟低。**
   Qwen 平均 3.7 次请求，但 CSV 单次响应出现严重长尾，最终撞 600s cap。
3. **上下文治理比 shell 冷启动速度更重要。**
   同一模型下，OpenCode 的平均 tokens 约为 Codex 的 13%，wall 约为 68%。
4. **清楚的终止条件很关键。**
   ACI 和 OpenCode 都在 3/3 任务上正常 `task_complete`/`stop`；Qwen 在 1/3 任务上未正常收口。
5. **强恢复能力不等于低代价。**
   Codex 的 18 次工具失败最终都恢复并完成，但处理成本很高。

## 6. 可复现产物

外部实验目录：

- `D:\VerseShellEval\agent-shell-20261012\external_runner.py`
- `D:\VerseShellEval\agent-shell-20261012\direct-r1\summary.json`
- `D:\VerseShellEval\agent-shell-20261012\direct-r1\codex__*\codex-stdout.log`
- `D:\VerseShellEval\agent-shell-20261012\direct-r1\opencode__*\opencode-export.json`
- `D:\VerseShellEval\agent-shell-20261012\direct-r1\qwen__*\qwen-stdout.log`
- `D:\VerseShellEval\agent-shell-20261012\claude-default-r1\claude__python_exception_mislabel_0816896a\claude-stdout.log`

仓库内 VerseShell 对照：

- `D:\VerseShellEval\agent-shell-20261012\veseshell-direct-r1-live\rows.jsonl.rows.jsonl`
- `D:\VerseShellEval\agent-shell-20261012\veseshell-direct-r1-live\rows.md`

命令模板：

```powershell
python -X utf8 D:\VerseShellEval\agent-shell-20261012\external_runner.py `
  --products codex,opencode,qwen `
  --tasks python_exception_mislabel_0816896a,node_envconfig_validate_dd681123,python_csvlite_parse_80d158b2 `
  --out D:\VerseShellEval\agent-shell-20261012\direct-r1 --timeout 900
```

```powershell
$map=@{}; Get-Content .env.local | ForEach-Object {
  if($_ -match '^\s*([^#=]+)=(.*)$'){ $map[$matches[1].Trim()]=$matches[2].Trim() }
}
python -X utf8 bench/aci/runners/live_agent_loop.py `
  --tasks python_exception_mislabel_0816896a,node_envconfig_validate_dd681123,python_csvlite_parse_80d158b2 `
  --conditions raw_shell,verseshell_aci `
  --model $map['ACI_BENCH_MODEL'] --api-key $map['ACI_BENCH_API_KEY'] --base-url $map['ACI_BENCH_BASE_URL'] `
  --out D:\VerseShellEval\agent-shell-20261012\veseshell-direct-r1-live\rows.jsonl `
  --prompt-variant baseline --max-turns 24 --max-tokens 16384 --repeat-call-limit 3 --seed 42 --repeat 1
```

公开榜单复现：直接访问 <https://www.tbench.ai/leaderboard/terminal-bench/2.0>。

## 7. 诚实边界

- 只有 3 个任务、1 个 seed、1 次运行；不能做统计显著性结论。
- 外部产品保留各自默认 system prompt 和工具集，因此比较的是**产品级差异**，不是纯接口层差异。
- Codex 对本机模型收到 `Unknown model ... fallback metadata` 警告；这会影响 harness 行为，是明确混淆项。
- Qwen 使用 `--bare` 以避免用户级 memory/skills 污染；OpenCode 使用 `--pure` 并隔离 XDG；这些设置改善公平性，但仍不是完全相同的环境。
- Claude Code 的单点结果是默认模型 + 本机网关联合结果，不与同模型组比较。
- raw shell 的 CSV 失败带有 endpoint timeout；不能把它升级成“raw shell 必然失败”的结论。
- 公开榜单随时间变化；本文只记录 2026-10-12 抓取到的 **Terminal-Bench 2.0** 页面值。

## 8. 下一步最重要的一项实验

不要再把 VerseShell 当成完整 agent shell 与 Codex/Claude Code 直接比“谁更会做任务”。
对 VerseShell 真正干净的评估是：

> **把同一个 VerseShell ACI MCP backend 接入 Codex CLI、OpenCode、Qwen Code，保持模型、任务、工具和提示不变，只切换底层 shell/observation provider。**

这样能把：

- 模型能力
- 产品自带 agent loop
- VerseShell 的信息层（typed ops + bounded observations + failure recovery）

三者拆开。只有这个实验才能回答“VerseShell 的接口处理性能是否对同系产品有可归因正收益”。

