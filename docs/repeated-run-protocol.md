# 完整重复运行的不确定性协议（P2-4）

> 2026-10-06 历史校准：旧百分位交叉 bootstrap 在预定强跑间相关合成总体中，3 次运行
> 的零效应误报为 58/200，10 次为 27/200。至少 3 次只是完整性下限，不是区间覆盖
> 保证。新增同步描述变体交互与 CPST 仍仅作诊断，确证继续关闭。完整证据见
> [第二批回执](shortfall-wave2-2026-10-06.md)。

> 后续修复：主区间现使用 `crossed_axis_t_union/v1`，保留同一估计量，以配对贡献的
> run/task 两轴标准误分别构造 Student-t 半径并相加，每轴分配一半 alpha。比值在
> log 尺度上构造区间，交互保持声明的差值尺度。独立合成校准覆盖 3/10/30 次运行、
> CPST、成功率差与交互；这是经过校准的近似，不是任意分布下的有限样本保证。
> 旧百分位结果保存在 `legacy_percentile_ci95`。普通分析仍不自动批准主张；
> 新 study 必须在采集前冻结分析家族，经 `tools/study_inference.py` 才能评价校正后的主张。

本文件为后续独立采集定义分析输入和方法；本次没有采集模型数据。
现有42/43/44三个seed文件不是三次相同seed集合的完整重跑，不足以验收本项。

## 输入

先冻结任务清单和配置，再由测试方独立采集至少3次完整运行。每次包含同样的任务、
条件、seed集合和run_index集合，预算、模型、端点、权限、排除工具、代码版本及证据
指纹一致。原始文件分别保存，不能把同一个文件复制三份或改时间戳冒充独立采集。
完整性检查只能验证结构与文件身份，不能证明服务商调用真的独立；需保留采集日志。

manifest示例（路径相对于manifest所在目录，必须替换为真实新采集数据）：

    {
      "task_manifest": "frozen-task-manifest.json",
      "seeds": [42, 43, 44],
      "conditions": ["raw_shell", "raw_shell_coached", "verseshell_aci"],
      "run_indices": [0],
      "runs": [
        {"run_id": "collection-1", "artifact": "collection-1.json"},
        {"run_id": "collection-2", "artifact": "collection-2.json"},
        {"run_id": "collection-3", "artifact": "collection-3.json"}
      ]
    }

with和without配置分别建立manifest，不混在同一个重复集合里。原始单seed文件可从
live_config.seed恢复行seed，但它仍必须覆盖manifest声明的完整网格。

    python tools/repeated_run_uncertainty.py --manifest <study.json> --out <report.json>

## 方法

默认4000次bootstrap用于诊断，分析随机种子42。每次独立重抽“完整运行”和“任务”两个轴，
同一份任务抽样用于所有选中的运行，保留条件配对和固定seed/run_index层。
不能在每个运行里独立打乱任务身份，不能把seed当作完整运行重复。

分别输出analysable主口径和ITT口径，包含D对A及D对A′的成功率差、工具比、观察代理
token比及端点usage总/输入/输出比。ITT按§0.6把被排除的成功行也保守计为失败；
不能将旧的全部已评分行成功率点估计拼上新ITT区间。缺失成本不补零；若某些bootstrap
样本分母为零，报告次数并将该区间标为不可用，不悄悄丢弃这些样本。

报告给出上述 studentized 主区间，以及交叉 bootstrap、仅重抽任务、仅重抽运行的诊断区间。另对每个
运行×任务单元的线性化贡献做平衡双向随机效应矩估计，报告run/task/interaction三个
分量和均值方差的贡献。比值采用delta-method线性化。负分量截为0，同时保留未截断值。
这些分量是另一种近似诊断，不是把三个bootstrap方差简单相加得到的结果。

## 限制与主张边界

运行和任务的独立、可交换性是模型假设。仅3次完整运行时跑间维度只有2个自由度，
bootstrap覆盖率和方差大小都不因此得到保证。样本方差可能高于或低于总体方差，
“2个自由度所以是下界”不成立；现有不同seed的差异也不能分离seed效应与采集噪声。

输出提供区间，不自动批准主张：保留各次§0.6行策略检查及partial状态，claimable为false，
仍须经过预注册功效、多重比较和独立验收。当前没有完整重复数据，旧头条数字不替换，
也不生成一份看起来真实的模拟测量报告。模型结果的现有比值区间是任务聚类口径，
Wilson和配对t区间各有其假设，均未包含独立完整重跑的不确定性。

run_variance.py继续保留不同seed的描述性数字，旧字段名保留兼容但不再称为真实跑间
分量或置信区间偏窄的证明。新的方法在实际数据到位前只有合成控制验证，不能宣称
完成P2-4的实测验收。

修复核查还确认：原row_policy曾把最终成功的被排除行计入ITT，并在排除比例/方向判断前四舍五入。现按原§0.6定义修正，以原始计数和精确分数判定，仅显示时舍入；阈值本身未变。相关负对照见tests/test_repeated_run_uncertainty.py。
