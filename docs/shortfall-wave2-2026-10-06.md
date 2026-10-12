# 短板修复第二批回执

日期：2026-10-06。承接 [第一批回执](shortfall-implementation-2026-10-06.md)，本轮落地评分文件保护、同步交互分析和可复现的区间校准诊断。

**验证：192 项 Python 测试通过（55.669 秒，exit 0），35/35 任务评分审计通过。未调用模型端点，未改写历史采集或任务森林。**

## 1. 评分文件保护已接入实际调用链

新增共享 `bench/aci/runners/grading_contract.py`，复用准入原有的测试文件/独立验证脚本识别规则。

- 在模型编辑、GOLDEN 或候选 overlay 应用之前，冻结原始验证文件 SHA256。
- live runner、mock runner、C24 和候选准入调用同一保护逻辑；评分前后均核验完整字节。
- 验证文件被改写、删除或重定向到工作区外时，不能被评分为成功。
- C24 门禁重新计算保护清单，报告中的“保护摘要”与 fixture 不符也会失败。
- 当前 35 题共识别 **27 个任务的 27 个验证文件**，已确认 GOLDEN 不修改它们。其余 8 题没有识别出的独立验证文件，不虚报成“全部任务已隔离”。

负控证明：保留原来的断言标记、将其余测试改为空壳仍然失败；评分过程本身留下的测试文件修改也会被检测。正常题解文件允许修改。

边界：这是完整字节完整性检查，**不是操作系统级只读隔离或安全沙箱**。同用户执行的任意题解代码、临时改写后恢复、新增插件/构建钩子等攻击还不能仅靠前后摘要完全排除。新的“修改测试本身”任务也必须明确区分题解文件与可信验证器，不能直接套用当前识别规则。

## 2. 六组合交互分析已实现

`tools/repeated_run_uncertainty.py --interaction` 从同一组完整联合采集中读取 baseline 与 compact_all，要求联合变体网格和冻结 schedule 标识。

- 每一次 bootstrap 对两个变体使用**相同的 run 与 task 抽样索引**。
- 对 raw 和 coached 两个基线分别输出结果。
- 成功率交互为 `(D−A)_compact_all − (D−A)_baseline`。
- 比值交互为 `(D/A)_compact_all − (D/A)_baseline`，不是比值的比值，也不是对数尺度。
- 支持现有工具调用、观察代理、usage、配对比值均值和 CPST 指标；分别报告 analysable 和 ITT。
- analysable 使用两个变体 × 两个条件共同可用的四格范围，避免因剔除不同任务而形成假交互；报告排除数量。
- ITT 中仍然可分析但评分未知的格不再被悄悄记作能力失败。
- 缺格、重复格、来源变化、无联合 schedule 的输入被拒绝。

合成测试验证了“共享噪声完全抵消”“已知交互方向与数值”“缺格拒绝”。所有输出保留 `claimable=false`、无伪造 p 值；实现分析不等于真实交互效果已验收。

```powershell
python tools/repeated_run_uncertainty.py --manifest PATH_TO_JOINT_STUDY --interaction --draws 4000 --seed 42 --out NEW_INTERACTION_REPORT
```

输入为已有 repeated-run study manifest，引用至少 3 份覆盖完整联合变体网格的采集。当前没有 Step 5 P 的真实联合重复数据。

## 3. 校准发现必须保留的红项

新增 `tools/calibrate_repeated_intervals.py`。使用固定随机种子、24 个任务、200 次独立合成实验、每次 400 次 bootstrap，分别检查 3 次与 10 次完整运行。
成本由明确的对数正态模型生成，并作均值校正，使总体 D/A 为 1。下表是零效应却被普通 95% 区间排除的次数。

| 合成情景 | 3 次完整运行 | 10 次完整运行 |
|---|---:|---:|
| 独立偏态 | 1/200（0.5%） | 0/200（0%） |
| 强跑间相关 | **58/200（29%）** | **27/200（13.5%）** |
| 重尾任务 | 14/200（7%） | 10/200（5%） |

强相关情景的 Monte Carlo 95% 区间分别为 **[23.15%, 35.64%]**、**[9.45%, 18.93%]**。这是指定合成总体中的误报诊断，不是 Step 5 P 的实测误报率，也不证明其他未知分布的覆盖率。

两组完整结果都保留，不挑有利情景。增加到 10 次运行仍没有解决该强相关情景的区间偏窄问题；不把“至少 3 次运行”改写为统计可靠性保证，也不把重尾情景的 5% 点估计宣布为校准通过。

**处置：当前重复运行与交互区间继续仅作诊断，不放开任何确证结论。** 下一步应开发/选择适合少量运行与任务相关性的推断方案，再用同一组不利情景及额外缺失/零分母情景重新校准；不能仅靠加采样、降低门槛或换种子宣称修复。

复现：

```powershell
python tools/calibrate_repeated_intervals.py --runs 3 --out NEW_CALIBRATION_R3
python tools/calibrate_repeated_intervals.py --runs 10 --out NEW_CALIBRATION_R10
```

这些命令只生成合成数据并调用统计函数，不触及真实端点或既有结果。

## 4. 证据与改动边界

- [完整测试日志](../audit-r12-scratch/implementation-wave2-2026-10-06/python-tests.log)
- [35 题评分审计](../audit-r12-scratch/implementation-wave2-2026-10-06/task_set_audit.json)
- [逐题保护清单](../audit-r12-scratch/implementation-wave2-2026-10-06/protected-verifiers.json)
- [3 次运行校准](../audit-r12-scratch/implementation-wave2-2026-10-06/calibration-r3.json)
- [10 次运行校准](../audit-r12-scratch/implementation-wave2-2026-10-06/calibration-r10.json)
- [本轮精确 diff](../audit-r12-scratch/implementation-wave2-2026-10-06/implementation.diff)
- [核验汇总](../audit-r12-scratch/implementation-wave2-2026-10-06/verification.json)

本轮修改 10 个 Python 文件（含新增模块、工具与测试），未新增第三方依赖。保护/执行面改变后旧采集指纹依然只能作历史证据；未来必须开新 tag。

下一优先级：**修复区间推断的已测不利情景**，然后补评分执行隔离与独立困难任务。实际模型能力、成本和交互结论仍等待新的冻结采集；本轮不关闭这些任务。
