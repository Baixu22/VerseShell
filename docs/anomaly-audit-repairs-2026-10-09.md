# TF-0139：全量异常证据与构建环境验收

日期：2026-10-09（Asia/Shanghai）。本批推进全量异常核验；总目标与正式产品验收仍未完成。

## 当前交付

- 新增 tools/anomaly_audit.py，读取原始 collection、摘要固定的任务元数据及已有观测，不执行历史命令，不改写旧评分。按任务、语言、条件、变体、seed 分组，分开记录平台/接口、评分、模型动作、端点、预算和 harness 证据。
- 覆盖全部 1050 行，不限于异常格：143 格基础异常并集与 907 格非异常成功对照。另单列全部 270 格 Rust 行，其中 244 格原始记录为成功。
- 19,350/19,350 个已有观测通过文件/文本摘要、cell 与操作名核验。18,411 个参数绑定完整；908 条旧 task_complete 确认未保存参数，31 条脱敏记录不完整比对参数。哈希通过不等于这些绑定缺口消失，更不等于评分或因果已确认。
- 未来 task_complete 观测补存原始 args，保持模型可见的确认响应不变。首次严格检查把 908 条缺失 args 视为不匹配；核对生产分支后改为明确的 legacy_ack_arguments_not_recorded，仅对精确的历史确认格式成立，错误格式仍拒绝。首次报告保留，不修改旧观测。

## 异常集合与证据含义

| 集合 | 格数 |
|---|---:|
| 原始评分失败 | 139 |
| 依既有 row_class 判为截断 | 141 |
| usage 缺口 | 5 |
| 失败与截断交集 | 138 |
| 失败或截断 | 142 |
| 三者总并集 | 143 |
| 非异常成功对照 | 907 |

冻结预算仍为 80 turns / 16,384 completion tokens。原始成功 911、失败 139 不变。142 格可列出预算或端点计费等已记录机制；底层任务因果不因这些机制或共现而自动确定。所有行保留 underlying_task_cause=unknown，代表未进行反事实或最终工作区独立复评，不代表没有登记每格的具体观测。

观测级记录含 2,482 次非零命令退出、2,202 次文本出现替换字符、136 次结构化工具错误、10 次超时标记。替换字符不是原始字节解码证明；工具拒绝也可能是正确的安全/参数检查。
基础异常格中 143 格出现模型动作模式信号，而成功对照中也有 625 格；平台/接口信号分别出现在 140 格和 664 格。这些不是互斥根因，也不是错误率。重复调用、相同输出或测试输出后的调用（包括协议确认）不能直接证明无意义循环。
唯一不属于截断类的评分失败是 py_region_top_seller_7f713e22 / raw_shell / compact_all / seed 42：60 turns 后 model_stop，最终记录 pytest exit 1。已另存早期失败命令、后续重复读取及其观测引用；没有最终工作区和最终助手文本，不能把它归为预算耗尽或给出未经证明的根因。

## 修复模型工具的共享 Cargo 输出

上一批已隔离评分副本。本批实测确认模型工具仍继承主机全局 CARGO_TARGET_DIR，导致不同 pristine/GOLDEN 工作区借用错误二进制。修复前 5 项针对性测试为 4 failure / 1 error（缺未来配置回执），其中真实 GOLDEN 工具调用 exit 101。
现在 raw、coached、ACI 均复用工作区本地构建环境。保留 PATH/PATHEXT/APPDATA 和 AETHER 的审批/工作区字段，不改变用于启动 AE 的候选二进制路径。三个条件的真实子进程都看到各自 target；六个 pristine/GOLDEN 命令对照均符合预期。
未来行记录 workspace_build_environment：它证明默认配置而不是全环境快照；命令显式覆盖环境或 --target-dir 仍可能改变行为。这不是同用户安全沙箱，也不能消除所有 Cargo、工具链、系统与网络差异。
检查了旧 launch-verified、collection、round.status、readiness 元数据及前序启动脚本证据，未找到运行时继承的 Cargo target 记录。不能把“没有记录”当作“没有继承”。本批反例不证明旧 270 格 Rust 行实际受过污染，也不追认它们。

## 验证

- 新增/加强 23 项控制：17 项异常审计测试、6 项工作区环境测试，全部通过。
- 最终 Python：321 项，318 通过、3 tokenizer 依赖跳过，exit 0。
- 当前进程树/超时/检查点探针：7/7，exit 0；负向控制故意产生并回收 1 个标记子进程，独立 CIM 复查为 0 残留。此结论只覆盖该受控探针，不涵盖历史每一格。
- 五阶段隔离报告链全部 exit 0、complete=true；当前 fixture 对照仍为35/35。Rust全量289通过、1忽略，exit 0。
- 产品门禁24/31、exit 1：C12/C14/C16/C24/C34/C35/C36仍未通过。未用本批新报告覆盖旧canonical产物使其变绿。
- 磁盘低水位、持续写盘失败、未知用量恢复等仍依各自控制测试及 TF-0133/0134/0135 的边界；未测操作系统与历史最终状态缺失不在本批冒充通过。

## 原始证据与复现

[全量机器报告](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/all-cell-audit-complete.json) · [143 格可读清单](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/all-cell-audit-complete.md) · [非截断失败原件](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/non-cap-failure.json)
[修复前工具回归](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/logs/tool-environment-before.log) · [修复后工具回归](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/logs/test_workspace_build_environment.py.log) · [全量 Python](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/logs/python-tests-final.log)
[进程树原件](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/process-tree-contract.json) · [进程复查](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/process-tree-postcheck.json) · [最终摘要](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/evidence/final-summary.json)
[精确改动清单](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/change-manifest.json) · [本轮 diff](D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/implementation.diff)

```powershell
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/run_checks.py' tests
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/run_checks.py' tools/anomaly_audit.py --with-arm 'D:/VerseShellLive/workspace/bench/aci/results/step5p-d-r1-20261007/latest_live.json' --task-set 'D:/VerseShellLive/workspace/bench/aci/task_sets/3.1.0.json' --out 'D:/VerseShellLive/anomaly-audit-20261009-01a11c1d/recheck/audit.json'
```

报告必须写入新的派生目录；保留旧结果与失败日志。不发起模型请求，不更新旧冻结预算/计划，不提交或合并现有脏工作区。后续由 TF-0140/0141 处理声明映射和源码落地，并在新冻结开发试点核验实际模型行为。
