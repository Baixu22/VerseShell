# 2026-09-30 修复开发与验收回执

本次依据 `docs/repair-test-plan-and-findings-2026-09-30.md` 开发。结论：
**本地修复及回归完成；完整声明门禁 29/31，C12 为 25/25 新鲜；C14/C16 保持 FAIL。**
本次没有调用模型端点，没有产生新的 live 或正式统计验收结论。

## 对报告的判断

报告正确地区分了实际 bug 和声明未达标。C14 的 digest 节省与 C16 的行包装节省
不能支撑既有总量门槛，保留失败是正确行为，不能靠调整阈值或减少模型可见信息刷绿。
但交接里的历史 PASS 和“已修”不能代替当前代码核验：入场 evidence 仍是旧数值，
C12 也为 FAIL；README 同步却已经接入代码，不需要再实现一次。

测试方案的主要问题比多跑几轮更重要：原长度构造不自洽，0/105 不能证明截断率
<=2%，不同 seed 不等于独立完整重复，不显著不能排除原因，按观察到的结果剔除
重复会产生选择偏差。旧 v1 已标为停用，当前使用 `l1-causal-experiment-preregistration-v2.md`。

## 实际改动

| 文件 | 改动与作用 |
|---|---|
| `tools/run_variance.py` | 接上入场代码已有的 source_rows_fingerprint；对分片补齐 merger 的 seed/source_run 默认值后逐行内容校验，自动选择与发布区间一致的采集。显式路径也不能绕过；缺片、重复格、错误 seed、旧无指纹产物或混轮返回 2，保留旧输出。指纹使用实际 `--published` 路径并覆盖共享校验代码。 |
| `tools/refresh_live_artifacts.py` | 首个子步骤非零或无法启动时立即停止，不再用失败上游的旧输出重建下游；with-only 不执行依赖双臂区间的 run_variance。既有 README 同步步骤保留并增加顺序回归。 |
| `tools/live_turn_diagnostics.py` | 缺轮、重复轮、损坏记录或缺少格级轮数不能标为 no_truncation；文本摘要也打印 seed/source_run，区分同任务不同 seed。明确观测到的截断仍保留为正证据。 |
| `.gitignore` | 为 `tests/test_*.py` 增加例外，修复全局 `*.py` 规则让 Python 回归无法随仓库交付的问题。既有测试原本存在于本地，本次没有把它们冒称新写。 |
| 三份回归测试 | 新增 `tests/test_run_variance.py`；扩充刷新链和逐轮诊断测试，共新增 8 个测试方法，包含真实旧轮输入拒绝之外的合成负对照。 |
| 文档 | 修订原测试报告；保留并停用 L1 v1，新增 v2；在正式声明文档补齐 C32/C37 的既有门槛、来源和限制。 |

L1 v2 使用可实现的共同短/长目标，保留原生提示和 schema，仅追加冻结填充；填充可能
产生语义影响，不能直接称为纯 token 长度因果效应。三次完整网格应为 420×3=1260 格，
正式 L5/L6 则另需 630×3=1890 格。二者不能相互充抵。

## 本次验证

| 检查 | 实际结果 |
|---|---|
| 入场 Python 回归 | `python -B -m unittest discover -s tests -p 'test_*.py'`：113 通过，exit 0 |
| 修复后 Python 全回归 | 同命令：121 通过，0 失败，exit 0；19.560s |
| 最后 CLI 帮助文字修订后的 run_variance 回归 | 5 通过，exit 0 |
| Rust 完整测试（完整 claim_gate 的 C7 实际调用） | 16 suites，287 通过，0 失败，1 ignored，exit 0 |
| C6 / C8 单独契约检查 | 4 / 3 通过，各 exit 0；这些测试已包含在完整套件中，不重复累加总数 |
| 真实混轮负对照 | r14 `tf0114` 分片与 r15 发布区间配对：exit 2，拒绝写出产物 |
| r15 逐轮离线诊断 | A 0/105、A′ 2/105、D 0/105；各组 unknown=0；两个 A′ 的摘要身份可区分 |
| 离线派生 | live_uncertainty、acceptance_power、statistics_crosscheck、budget_sensitivity、run_variance、task_design_audit 均 exit 0；未调用端点 |
| 完整声明门禁 | `python -B tools/claim_gate.py --evidence eval/evidence.json`：29/31，exit 1；失败仅 C14=0.045<0.15、C16=0.0789<0.10 |
| C12 | 25/25 新鲜；最后再次直接检查，没有陈旧产物 |
| 保护面 | 321 个文件逐字节 SHA-256 对比：0 变化、0 新增；包含 tasks、fixtures、Task Forest 以及两份 live 基线 |

四份统计派生（live_uncertainty、acceptance_power、statistics_crosscheck、budget_sensitivity）
去掉时间和来源字段后与入场版本完全一致。门禁汇总的 C11/C14/C16/C34 数值更新是
重新读取入场时就已存在的 r15 产物，未修改其测量输入或阈值；C12 从 FAIL 变为 PASS。
刷新 acceptance_power 后，其下游 task_design_audit 也已重建。

完整门禁会重写 metrics/compact_ratio/readme_claims 等文件；本次 readme_claims 的自动
变动已纳入清单。只按本次快照认定归属，不能把整个脏工作树的 git diff 当成本次提交。
本次没有提交、清理工作树或修改 Rust 产品实现。

## 仍未完成的工作

- C14/C16 原声明仍不成立，保留 no-go 和原门槛；本次没有重设计模型可见投影。
- 端点交叉校准、300s 代理约束重测、正式重复采集均未执行。端点请求不能算离线工作。
- L1 v2 是待冻结方案，仍缺逐字提示与长度参数、四臂运行/分析程序、功效/精度论证及 study manifest；当前不能直接开跑或宣称确认性负面结论。
- 任务准入的有限重复只能发现一部分 flakiness，不能把定时器顺序谓词变成确定性契约；冻结任务的谓词重设计需进入新的准入/数据集轮次。本次没有重判或修改冻结任务。

## 可核对文件

所有路径相对仓库根目录：

- `audit-r12-scratch/repair-followup-2026-09-30/before/`：入场文件副本。
- 同目录 `change-list.json` / `session.diff`：相对入场的修改清单与代码/文档 diff。
- 同目录 `verification.json` / `protected-after.json`：退出码、计数、声明变化和保护面核验。
- 同目录 `python-baseline.log` / `python-final.log` / `gate-verified.log`：实际验证日志。
- 同目录 `mixed-round-negative.log` / `r15-diagnostics.json`：混轮负对照与已有 live 数据诊断。
- `eval/evidence.json`：最终完整门禁回执。
