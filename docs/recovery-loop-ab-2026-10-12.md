# 失败恢复闭环 A/B（2026-10-12）

按 AGENTS.md 轻量路径：**6 格**诊断对照（3 任务 × raw_shell/verseshell_aci × seed 42），
collection `recovery-ab-r1`，模型 step-5-preview，0 endpoint failure，exit 0。

目的：验证「遇到失败后，agent 能否一步恢复」——即信息层的闭环，而非速度。

## 结果

| 任务 | raw_shell | verseshell_aci |
|---|---|---|
| python_fix_pytest_fail | ✅ task_complete（4 轮/3 工具） | ✅ task_complete（4 轮/3 工具） |
| python_exception_mislabel | ✅ task_complete（5 轮/4 工具） | ✅ task_complete（5 轮/4 工具） |
| **python_csvlite_parse** | ❌ **completion_limit**（3 轮/4 工具） | ✅ **task_complete**（9 轮/8 工具） |

3 任务里 2 个两臂都过；关键差异在 `python_csvlite_parse`：**raw_shell 失败，ACI 成功**。

## 核心证据：ACI 的失败信封带完整恢复方案

ACI 臂在 `exec.run` 上失败一次（`E_PROCESS_EXIT`），观察里直接给出：

```json
{ "error": { "code": "E_PROCESS_EXIT", "message": "process exited with code 1",
             "hint": "...", "recoverable": true },
  "diagnostics": [{ "path": "test_csvlite.py", "line": 98,
                   "severity": "error", "tool": "pytest" }],
  "data": { "exit_code": 1, "stats": {"passed":17,"failed":1,"errors":1} } }
```

并且带 `suggested_next` —— **可执行的下一步动作**，而非死胡同：

```json
[ { "op": "file.view", "args": { "path": "test_csvlite.py", "cursor": 98, "window": 40 } },
  { "op": "test.run_target", "args": { "runner": "pytest", "target": "test_csvlite.py" } },
  { "op": "result.query", "args": { "handle": "result://sha256/...", "mode": "grep",
                                    "pattern": "FAILED|ERROR|Error|assert" } } ]
```

模型据此定位到 `test_csvlite.py:98`，用 `file.replace_exact` 修正，`exec.run` 复跑通过，
最后 `task_complete`。**9 轮内闭环完成**。

## 对比：raw_shell 同一任务

raw_shell 臂用 PowerShell heredoc 写整份文件，**3 轮就撞 completion_limit**；
它的轨迹里**没有任何结构化失败字段**（只有 `observation_tokens`），
模型看不到「哪里错了 / 下一步做什么」，只能整文件重写，很快耗尽预算。

## 结论（信息层，不是速度）

1. **失败不是死胡同**：ACI 的失败信封带 `error.code` + `diagnostics`（文件:行）+ `suggested_next`（可执行动作）。
2. **闭环可完成**：模型据此一步定位、修复、复跑、收尾。
3. **这正是「信息层」收益**：同样的模型、同样的任务，差异来自观察里给的是什么。

## 诚实边界

- 6 格诊断对照，`acceptance_scope` 为单次采集，**不是**跨模型/正式成功率结论。
- 3 任务里 2 个两臂都过，说明差异只在**部分**任务上体现。
- 未做竞品（同系 agent shell）对照，**不能宣称优于它们**。