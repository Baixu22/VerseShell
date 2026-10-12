# Raw-shell 闭环定位与离线回归（item 1）

日期：2026-10-12（Asia/Shanghai）。本轮为**零成本**工作：不调用模型、不改 Task Forest 状态、
不重置/提交/合并/清理工作区。开工 HEAD `a8d4c56c45093d0a7d650d96afe3dd561d80e5b0`，
分支 `codex/reproducible-upstream-20260727`。

## 1. 失败根因（已由独立回放证实）

`tools/replay_failure_commands.py` 在 pristine workspace 重放已存 raw-shell 轨迹，末尾执行真实
`check_success`（不是模型自报）：

- `node_envconfig_validate_dd681123 / raw_shell / baseline`：`repeat_call_limit`，replay `success=False`
  （`node check.mjs` -> 1）。模型测试失败后反复读取同一段源码，未形成有效修改闭环。
- `python_csvlite_parse_80d158b2 / raw_shell / baseline`：`turn_limit`，replay `success=False`
  （`python -m pytest` -> 1）。多次 `python -c` 被 cmd 当作重定向（`此时不应有 >`）后陷入字符串实验。

结论：失败发生在**到达可验证通过状态之前**，属 raw-shell 命令构造/编辑闭环问题，
**不是端点故障**，也**不是“测试通过后不停止”**（stop-after-success 护栏修不了它）。

## 2. shell_guided 闭环的独立证据（本轮新增）

对同批 3 个任务的 `shell_guided` 轨迹独立重放（`--include-complete --execute`）：

| 任务 | 记录 stop | replay success | replay reason |
|---|---|---|---|
| node_envconfig_validate_dd681123 | task_complete | **True** | all ok |
| js_leaderboard_rank_b1603acf | task_complete | **True** | all ok |
| python_csvlite_parse_80d158b2 | task_complete | **True** | all ok |

即 shell_guided 的 3/3 是**经独立 `check_success` 复算**通过的，而非模型自称。
产物：`D:/VerseShellLive/freeze-live-20261010-03/replay-guided/replay.json`。

边界：这是 3 格诊断性对照，**不是**正式重复成功率或跨臂结论。

## 3. 离线回归覆盖（本轮新增）

`tools/replay_failure_commands.py` 此前**无任何测试覆盖**。新增
`tests/test_replay_failure_commands.py`（7 项）：

- `load_rows` 读 `.jsonl` 与 `{"rows":[...]}` 两种形态；
- `select_cells` 默认跳过 `task_complete`、`--include-complete` 保留、task/condition/variant/seed 过滤；
- `replay_command` 成功/非零退出码、语法错误标记；
- `main` dry-run 落盘 `replay.json`+`replay.md` 且不执行；无匹配单元时报错。

结果：`7 passed`。相关面 `test_tool_contracts + test_lean_diagnose + test_replay_failure_commands +
test_live_task_selection` = **23 passed, 3 skipped**，exit 0。

## 4. shell_guided 接线核对

- `live_schedule.VARIANTS` 已含 `shell_guided`；
- `prompt_and_tools` 仅替换 `raw_shell`/`raw_shell_coached` 的系统提示，工具 schema 不变，
  `verseshell_aci` 不受影响；
- `tools/lean_diagnose.py --prompt-variant` 可驱动；
- `tests/test_tool_contracts.py::test_shell_guided_variant_only_changes_raw_shell_prompt` 已覆盖。

## 5. 未收口项（不擅自处理）

1. **raw_shell 工具描述仍引导失败模式**：`RAW_SHELL_TOOLS` 的 `run_command` 描述写着
   “editing files (use python -c to write files)”，正是失败主因。修它会改动 baseline 控制臂的
   工具 schema，影响 C1/C2 与 A/A' 可比性，属测量完整性决策，**本轮不改**，待确认。
2. **主仓库交付可达性**：`git rev-list --count origin/master..HEAD` = **44**（落后 0）。
   44 个 done 提交仅在未合并分支上；本轮不合并、不推送。
3. **claim_gate 状态**：本轮 `python tools/claim_gate.py` = **25/31**，exit 1。红项
   C14、C16（历史门槛，TF-0094 已登记）、C24、C34、C35、C12。C12/C34/C35 属**脏工作区**
   导致的“存储产物相对当前源码不新鲜”，非本轮引入；TF-0094 记录的 29/31 对应当时的冻结状态。

## 6. 建议的下一步（需授权）

- 若确认要消除 raw-shell 失败主因：把 `run_command` 描述的“python -c 写文件”改为
  “先写 .py 再 `python file.py`”，并按测量完整性规则**另立控制臂版本**，不就地改冻结基线。
- 主仓库可达性：由发布方决定是否把 44 个提交合并/推送到默认分支。

## 7. 全量回归与失败归属

`python -m pytest tests -q` = **480 passed, 1 failed, 5 skipped**（119s）。
唯一失败 `test_remaining_node_boundaries.py::RemainingBoundaryTests::test_persistent_receipt_failure_cannot_dispatch_workload`
是 Windows `TemporaryDirectory` 清理竞态（`NotADirectoryError: [WinError 267]` 发生在
`tempfile` teardown，非断言失败）。该用例隔离运行 **1 passed**，整文件 **7 passed**，
与本轮新增文件无关；重跑应恢复绿。


---

# 追加：raw-shell 多行命令静默截断的完整定位与修复（2026-10-12）

## 失败分布（全量真实数据）

数据：`bench/aci/results/step5p-formal-20261010-r1/with_seed42.json.rows.jsonl`（170 有效行，操作者在 170 行后暂停，exit_code=75）。

- 失败 10 个，**全部在 raw_shell 侧**；`verseshell_aci` 0 失败。
- 按条件：raw_shell 7、raw_shell_coached 3。
- 按变体：**baseline 8、compact_all 2**。
- 按停止原因：turn_limit 3、repeat_call_limit 5、completion_limit 1、task_complete 1。

## 根因（最小实验证实）

`run_bounded` -> `managed_launch.py` -> `subprocess.call(cmd, shell=True)` 在 Windows 上经 `cmd.exe` 执行。**cmd 对含内嵌换行的命令只执行第一行**，后续行静默丢弃，并返回第一行的退出码（通常 0）：

| 命令 | 实测结果 |
|---|---|
| `echo one` 换行 `echo two` | 只输出 one，rc=0 |
| `python -c "print(1)` 换行 `print(2)"` | 只输出 1，rc=0 |
| `python -c "open('b.txt','w').write('X')` 换行 `print('done')"` | 只写文件、丢弃 print，rc=0 |

模型反复尝试的正是**多行 `python -c` 写文件**。cmd 悄悄吞掉后续行并返回 0，模型看不到真实错误，以为“成功但文件没变”，于是不断换写法/重试，最终撞 turn_limit / repeat_call_limit。**9/10 个失败单元的轨迹含多行命令**。

这是**测量基础设施缺陷**，不是模型能力问题：同任务在 `verseshell_aci` 下 0 失败。

变体差异解释：`RAW_SHELL_TOOLS.run_command` 的 baseline 描述写着 "editing files (use python -c to write files)"，直接诱导失败模式；`compact_all` 换成中性描述，失败率随之下降（8→2）。

## 修复（机制层，纯附加信息）

`bench/aci/runners/live_agent_loop.py` 新增 `_multiline_shell_note()`，在 `execute_shell_cmd` 观测里追加注解，与既有 `[TIMEOUT]`/`[TRUNCATED]`/`[ENCODING]` 同类：

```
[MULTILINE: cmd /C runs only the FIRST line of a multi-line command and still returns its exit code; the remaining lines were NOT executed. Chain with '&' or write the code to a .py/.cmd file in one line and run it.]
```

边界：仅 Windows；`command.strip()` 后仍含换行才触发（结尾单个换行不触发）；**不改命令、不改退出码、不改工具 schema、不改提示词**。

验证：对 `python_csvlite_parse_80d158b2 / raw_shell / baseline` 真实轨迹重放，**7/12** 个 `run_command` 观测现在带可见提示。

## 回归

- 新增 `tests/test_multiline_shell_note.py`：5 项。
- 相关面 68 passed, 5 skipped。
- 全量 `python -m pytest tests -q` = **486 passed, 5 skipped, exit 0**（150s）。

## 未做 / 待决策

1. 工具描述诱导：`RAW_SHELL_TOOLS.run_command` 仍写 "use python -c to write files"；改它会变更 baseline 控制臂 schema，影响 C1/C2 与 A/A' 可比性，属测量完整性决策，本轮不改。
2. 本修复只让失败可见，不直接提高成功率；是否真正改善 raw-shell 成功率需下一次 live 采集验证（属 TF-0112）。
3. 主仓库交付可达性：origin/master..HEAD = 44，未合并；本轮不动。


---

# 追加：第 2 步 —— shell_safe 变体（2026-10-12）

## 目标

消除 raw-shell 失败诱因（工具描述 "editing files (use python -c to write files)"），
同时不就地改冻结的 baseline 控制臂，以免破坏 C1/C2 与 A/A' 可比性。

## 做法：新增 opt-in 变体 shell_safe

- bench/aci/runners/live_agent_loop.py
  - 新增常量 SHELL_SAFE_RUN_COMMAND_DESCRIPTION：删除 use python -c to write files，
    改为短单行命令 / 先写 .py 再 python file.py，并显式提示 cmd 只执行多行命令第一行。
  - prompt_and_tools 新增 shell_safe：仅替换 raw_shell/raw_shell_coached 的 run_command
    描述；系统提示文本不变；verseshell_aci 完全不变。
  - --prompt-variant choices 增加 shell_safe。
- bench/aci/runners/live_schedule.py：VARIANTS 增加 shell_safe。
- tools/live_round.py、tools/lean_diagnose.py：choices 同步。

冻结基线不变：baseline 的 run_command 描述仍含 python -c to write files，逐字节保留。

## 验证（离线，无模型调用）

- baseline 描述含原诱导语句：True
- shell_safe 移除诱导、含 FIRST line 警告：True
- shell_safe 只改描述（系统提示与工具集合不变）：True
- verseshell_aci 在 shell_safe 下与 baseline 完全一致：True
- 两个 shell 条件都应用：True
- live_schedule 接受 shell_safe 并拒绝未知变体：通过

新增 tests/test_shell_safe_variant.py（7 项）。

## 回归

- 相关面：test_shell_safe_variant + test_tool_contracts + test_multiline_shell_note +
  test_replay_failure_commands + test_lean_diagnose + test_live_control + test_live_cli_contract +
  test_remaining_node_boundaries = 62 passed, 3 skipped。
- 全量：python -m pytest tests -q = 492 passed, 1 failed, 5 skipped。
  唯一失败 test_persistent_receipt_failure_cannot_dispatch_workload 是 Windows
  TemporaryDirectory teardown 竞态（NotADirectoryError WinError 267）；隔离重跑 3/3 passed，
  与本轮改动无关。

## 边界与下一步

- shell_safe 是新的控制臂版本，与冻结 baseline 并列；正式对比必须把两者当作不同臂，不得拼接。
- 本步只改描述，未验证是否真正提高 raw-shell 成功率；需用 shell_safe 跑一次小规模 live
  （如 9 格 lean 矩阵）确认（属 TF-0112）。


---

# 追加：第 3 步 —— 拓展到 9 任务同日配对（2026-10-12）

## 设计

- collection: step5p-paired-shellsafe-r1
- 9 个曾在 2026-10-10 全量运行中失败的任务 × 2 变体(baseline, shell_safe) × raw_shell × seed 42
- 同一 collection、同一天、同一端点、同一预算(max_turns=24, max_tokens=16384)
- 18 格，0 endpoint failure，0 api_error

## 结果（配对）

| 指标 | baseline | shell_safe |
|---|---|---|
| 通过 | 7/9 | 8/9 |
| FAIL→PASS | — | python_fix_pytest_fail |
| PASS→FAIL | 0 | 0 |
| task_complete 停止 | 8 | 8 |
| 其他停止 | completion_limit 1 | turn_limit 1 |

- 剩余失败：python_csvlite_parse_80d158b2 两臂都失败（baseline=completion_limit, shell_safe=turn_limit）。

## 必须披露的混淆（重要）

[MULTILINE:] 注解是 harness 全局改动，**对 baseline 臂同样生效**：本 collection 中
baseline 有 7 条观测带该注解，shell_safe 有 4 条。因此：

- 本次配对实际对比的是「注解」vs「注解 + 描述」，**不是**原始 baseline vs shell_safe。
- 第 3 步 3 格那次 1/3→2/3 的比较跨了两天/两种改动，**高估了描述的效果**；其中相当部分是
  运行间方差。
- 描述本身的净效果，在本 9 任务样本里是 **+1/9**（仅 python_fix_pytest_fail）。

## 多行命令使用（描述的效果）

- baseline: 7 条多行命令 / 60 总命令
- shell_safe: 4 条多行命令 / 70 总命令
描述把多行命令数从 7 降到 4（约 -43%），但未消除。

## 结论

- 两项改动（让失败可见 + 移除描述诱导）方向正确，但**效应量远小于 3 格信号所示**。
- 9 任务、1 seed 的样本不足以支撑"成功率提升"的主张；acceptance_scope=single_collection_diagnostic、
  claimable=false。
- 3 格与 9 格结果不一致，说明必须做**多次独立重复**才能给出可信效应量（属 TF-0112）。
