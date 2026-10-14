# 装置系统审计与修复（2026-10-13）

用户要求：先定位问题、一次修完，不要再用昂贵的模型调用做调试。
本轮不跑模型，只做静态/合成审计。

## 0. 为什么要做这一步

前几轮的模式是：跑一轮 -> 发现缺陷 -> 修 -> 再跑。15 题采样里一次找出 6 个自有缺陷，
说明装置不可信；继续这样跑只会浪费模型调用。改为：先把装置审计到干净，再跑。

## 1. 新建两个审计器（零模型调用）

### audit_suite.py —— 静态任务审计

逐题检查 8 类缺陷：

| 代号 | 检查 |
|---|---|
| A | oracle 检查的路径，提示词必须点名（否则欠约束） |
| B | 负面结果型任务不得强制 finish.success=true |
| C | 大文件 evidence 必须用 probe 而非整文件读取 |
| D | no_process / probe 结构回归 |
| E | 每条 oracle 必须有可验证产物/轨迹检查（禁止 summary-only） |
| F | 引用的 fixture 必须存在 |
| G | 任务 id 唯一、每档 20 题 |

### audit_oracles.py —— oracle 合成自检

对 80 题各构造一个**逐项满足**的合成 cell：

- 每条 oracle 都必须**接受**这个正确解（否则是「永远无法通过」的缺陷）；
- 空 cell 必须**被拒**（防止 oracle 形同虚设）。

这一步能抓到最危险的一类缺陷：**oracle 永远无法被满足**，会把真实成功误判为失败。

## 2. 审计发现并修复的问题

首轮审计报出 71 条，经修正审计器自身的误报后收敛到 8 条真实缺陷：

| 题 | 缺陷 | 修复 |
|---|---|---|
| T307 | oracle 检查 /workspace/state.txt，提示词未点名 | 提示词点名 |
| T308 | oracle 检查 /workspace/dlock，提示词未点名 | 提示词点名 |
| T319 | oracle 检查 /workspace/tpc_a、tpc_b，提示词未点名 | 提示词点名 |
| T411 | 安全探测：边界守住即成功，却强制 finish.success=true | require_finish=False |
| T412 | 同上 | require_finish=False |
| T413 | 同上 | require_finish=False |

（T406 是审计器误报：其 do not 是解法约束而非负面结果，已收窄启发式。）

## 3. 修复后审计结果

```
AUDIT CLEAN: no static defects found across 80 tasks
unsatisfiable oracles: 0
empty-cell false passes: 0
```

## 4. 固化为回归测试

两个审计器已接入 tests/test_agent_shell_benefit_contract.py，共 7 项测试：

- test_static_task_audit_is_clean
- test_every_oracle_is_satisfiable_and_not_trivially_passable
- 以及原有的 5 项（契约、10x3 冻结、80 题分档、每题硬证据、oracle 自检）

今后任何任务/oracle 改动若引入上述缺陷，测试会直接失败。

## 5. 结论

1. 装置已从「跑一轮才发现问题」升级为「提交前静态审计即可发现」。
2. 这一轮**没有花任何模型调用**，却找出了 6 个此前要靠跑测试才能暴露的缺陷。
3. 目前 80 题静态与合成审计全绿；可以在此基础上再跑采样/正式轮次。

## 6. 诚实边界

- 静态审计不能覆盖所有缺陷（例如 T304 那类「测试本身 flaky」需要运行时才能发现）。
- 合成审计验证的是「oracle 可满足」，不验证「oracle 与真实世界一致」。
- 未改 Task Forest；未提交、未合并、未推送。
