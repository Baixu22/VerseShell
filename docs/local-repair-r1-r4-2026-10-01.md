# R1–R4 本地修复回执

本轮执行 `live-recovery-plan-2026-10-01.md` 的本地工作。旧 v3.0.0 任务、fixture、
547 格原始采集、两份旧正式 live JSON、Task Forest 和门禁阈值均保留；未调用模型端点。
新模型尚未提供，因此 R5–R7 的在线兼容性、净 usage 和最终验收仍未执行。

## 最终本地验证

| 检查 | 结果 |
|---|---|
| Python 全回归（配置 MSVC，含实际 Rust 评分控制） | **157 通过，exit 0**，27.057s |
| 实际服务投影契约 | **11/11 通过，exit 0** |
| 故障/恢复/观察专项 | **12 项通过**，包含真实子进程强杀、原子写失败、认证暂停与恢复 |
| 新版本与紧凑提示 dry-run | 35 任务、3 条件的计划生成成功；状态为 planned，没有端点调用 |
| 原始数据保护 | **340 文件哈希一致，保护目录 0 新增** |
| 网络模型请求 | **0** |

未重跑 Rust 项目全套或完整声明门禁；Rust 产品实现未修改，已有 live 证据的指纹不会
被重新盖章。上述测试说明本地工程行为通过，不表示新模型已经验证或全量 C12 已恢复。

## R1：新版本评分

新增 `bench/aci/task_sets/3.1.0.json`，以 SHA-256 固定原 35 任务来源，只覆盖八个
已审查的评分契约。旧任务文件没有修改，新旧成绩不混算。

| 任务 | 新判据 |
|---|---|
| rust_add_unit_test | 原有测试实际执行且通过；函数行为测试通过；新增测试能发现减法、乘法变异 |
| rust_search_and_edit | 编译并执行外加行为测试，接受正确尾表达式 |
| rust_fix_compile_error | 验证公开 add 的实际行为与可编译性 |
| python_fix_pytest_fail | 独立功能断言＋必须通过 pytest，允许等价实现 |
| python_edit_and_retest | 多个姓名的实际输出断言＋必须通过 pytest |
| ts_package_script_fail | 实际执行 npm test，不依赖 process.exit 的某种字符串写法 |
| windows_batch_capture_diag | 精确匹配正确文件与行号，允许两种路径分隔符 |
| python_noisy_install_summary | 默认 Python 的指定依赖版本可用＋单行摘要；验证状态，不宣称证明安装历史 |

原 windows_path_normalize_edit 已用精确产物判据，保持不变。Rust 评分在临时副本内
运行，添加的检查不进入模型工作区。无测试、忽略的测试、恒真测试、错误算子、注释伪装
都有负对照。评分工具缺失、链接器缺失或评分超时返回未知；新 Python 评分也区分 pytest
本身缺失与测试失败。该评分不是恶意代码的安全沙箱，作用是验证这些小型任务的功能契约。

## R2：故障、恢复与状态

- 401/402：保存当前格及请求尝试后返回暂停码 **75**，不再派发下一格。
- 429/5xx/连接失败：每请求最多三次总尝试，退避 1、2 秒，且不越过 900 秒请求总预算；
  每次尝试记录本地 ID、起止时间和状态。三个连续端点失败格触发暂停。
- 真实解题失败不会自动重试。暂停后必须显式 `--resume-paused`；已完成格不重复，原错误格保留。
- checkpoint 使用临时文件＋fsync＋原子替换；部分写入不会覆盖上一份有效快照。
- 每个输出有独占 owner lock、独立线程 heartbeat、当前格和最近完成时间。
  `tools/live_status.py` 同时核对 PID 与 heartbeat，不能把陈旧 running 当成正在采集。
- 格尝试日志保留中断/恢复历史。代码、任务、提示变体、权限、预算不一致时拒绝恢复。
- 旧的就地 splicer 拒绝操作带冻结身份的新集合，避免绕过新记录与恢复规则。

示例（仅在模型/环境问题已处理后使用）：

```powershell
python -B tools/live_status.py <采集目录>
python -B tools/live_status.py <采集目录> --stop
python -B tools/live_round.py --tag <原标签> --env-file <私有配置> --resume-paused
```

stop 在当前有界任务结束后生效；不是强制终止正在执行的工具。暂停记录保留，恢复不会
把失败格抹掉。新默认完整配置为 with，不再默认派发额外 without 消融。

## R3：可复算观察与未知 usage

工具观察单独保存在输出旁的 content-addressed JSON；trajectory 引用文件与哈希。
记录读信封、工具错误代码、call/cell/attempt 身份和时间；逐请求保存返回模型名、响应 ID、
可用服务请求 ID及请求正文哈希。原文脱敏时显式标记，不能宣称脱敏后仍是逐字重放。

`tools/replay_observations.py` 不需要完整 630 格，也不需要原 fixture 还存在对应生成文件；
它验证保存的字节哈希与实际模型可见投影。相同 token 数、不同正文会被拒绝。

usage 未返回或请求失败时，完整累计 usage 字段为 null，已返回的小计另存于 reported 字段。
live_uncertainty、acceptance_power、three_arm_report 和 statistics_crosscheck 的 usage
配对都排除不完整值，并报告排除数；不再把缺失变成零成本。旧记录保持可读。
统计区间仍只解释实际保留的配对，不能因此声称消除了信息性缺失。

显式结束原因包括 task_complete、model_stop、turn_limit、completion_limit、endpoint_error、
harness_error；本轮没有事后修改旧的预算行策或旧成绩。

## R4：一个可对照的紧凑提示候选

保留 baseline；通过 `--prompt-variant compact` 选择一个候选。合并重复说明，读取格式
只解释一次；工具名、参数 schema、权限、正文、摘要和分页能力保持不变。shell 对照不改变。

在固定公共任务提示、排除工作区列表和历史的静态测量中：

| with 配置的系统提示＋工具 schema | baseline | compact |
|---|---:|---:|
| 字符 | 6757 | 5382 |
| 本地缓存 cl100k_base 独立计数 | 1647 | 1298 |

独立计数减少 **21.2%**；它不是指定模型的输入 usage，不宣称真实净成本已下降。
测量入口 `tools/measure_input_prefix.py --out <文件>` 使用离线 tokenizer，不下载、不调用端点。

## 下一步与边界

新模型到位后，按计划先完成协议小探针，再比较 baseline/compact 的真实 usage 和行为。
真实解题失败如实保留，不靠“smoke 必须全部解对”筛选模型。C14 原失败继续保留，C16
已有局部读取收益保留。完整正式门禁、独立重复及对外性能主张仍需要对应新证据。

本地验证日志与保护面检查保存在 `audit-r12-scratch/repair-r1-r4-2026-10-01/`。

最后补充的 dry-run 防覆盖保护已单独通过 12 项故障/恢复专项（exit 0）；已有结果不会被 dry-run 或 --fresh 擦除。
