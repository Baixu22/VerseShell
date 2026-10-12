# 再次 live 测试前的修复与准备验收

状态：**最终统一门禁已通过，`ready_for_live=true`。** 以 [readiness.json](../audit-r12-scratch/prelive-2026-10-06/gate-approved/readiness.json) 的 `ready_for_live` 为机器判定。

本目标是完成再次进入 live 测试前的修复与离线准备。本轮验证为 **207 项 Python 测试、287 项 Rust 测试通过（1 个性能基准按原设置 ignored）、35/35 任务评分审计、3150 格完整模拟链路通过**。

真实 Step 5 P 的连通性、服务端版本、模型效果与困难留出集结果，不会在没有相应实测时被预先宣布通过。

## 已落地的完整准备链

| 准备要求 | 实现与验收证据 |
|---|---|
| 固定源码、二进制、工具链、任务和分析范围 | readiness 记录源码/fixture/测试摘要、ae 摘要、Python/Node/Cargo/Rust/npm 路径、版本与摘要；启动器重新核验 |
| 进程开始执行前受管 | trusted launcher 等待许可，绑定 Job 后才启动任务；绑定失败不执行；正常、超时、父进程死亡、管道与句柄测试 |
| 中断恢复不丢已提交行、不无限重试 | 请求、回包、观测、row 提交四个边界注入中断；未知尝试必须显式恢复且有上限；未知历史花费不计作完整 usage |
| 评分与准入使用同一可信环境 | 隔离副本评分、前后完整字节检查、拒绝新增评分钩子与重定向；固定依赖解包后冻结完整编译器及测试选择配置，C24 与 live 一致 |
| 准入来源不混用 | 自定义候选目录逐文件摘要；审计输出放输入之外；空集、旧报告、未知模型家族不能建立准入 |
| 无效或不完整测量不能产生主张 | 三态评分、完整配对、informative cluster 检查、缺失 usage/中断标记、零分母及 partial 守卫 |
| 区间修复且不改变估计量 | `crossed_axis_t_union/v1` 保留原点估计，使用两轴配对贡献与 Student-t 半径；旧百分位区间保留为诊断 |
| 同步变体交互 | 六组合分块调度、变体进入格身份、共同样本范围、同一 run/task 重抽样与 studentized 交互区间 |
| 先注册再做确证分析 | 10 项分析家族在采集前记录分析计划及五个分析实现文件的 SHA256；按家族 Bonferroni 再分配两轴 alpha；旧采集、伪造校准标签和合成数据不获确证资格 |
| 完整链可运行 | 全部 Python 测试、Rust 库/集成测试、35 题真实评分审计、本机 ACI smoke、3150 格合成采集/恢复/合并/分析 |
| 困难任务离线准备 | 18 个开发槽、30 个独立留出槽、来源角色、分组与 A1–A8 配额已提供；没有把模板冒充已生成或已准入数据 |
| 正式启动前再次核验 | prospective live 必须指定模型、readiness、匹配的端点探针和分析计划；源码、二进制、工具链、模型、URL 或预算不匹配时拒绝启动 |

源码和测试的本轮变化会另存精确 diff；旧 c20/c21、Task Forest 状态和原始任务字节不被重写。所有实际模型调用数为 0。

## 区间校准结论

旧百分位 bootstrap 在强跑间相关的合成零效应总体中，3 次运行误报 29%，10 次运行 13.5%。新方法用独立 seed=20261006、每情景 2000 次实验检验：

| 完整运行数 | 强相关情景误报 | CPST 零效应误报 | 成功率差误报 | 交互误报 |
|---:|---:|---:|---:|---:|
| 3 | 35/2000（1.75%） | 21/2000 | 20/2000 | 26/2000 |
| 10 | 26/2000（1.30%） | 20/2000 | 5/2000 | 20/2000 |
| 30 | 15/2000（0.75%） | 13/2000 | 3/2000 | 17/2000 |

独立偏态、重尾任务、缺失/零分母、共享噪声抵消及 Student-t 参考分位数也有检查。
这些是明确合成情景下的校准，不是任意分布的有限样本定理；实际数据仍须满足采集、完整性与推断假设。

没有用无限宽区间换取通过：另一个 seed=20261008 的强相关、真实比值 0.2 情景中，3/10 次运行的 1000 个区间均有限；边际检出率分别为 55.8%/100%。这不是新模型的功效保证，10 项家族校正还会降低功效，实际样本计划仍应根据独立开发试点评估。

## 现在怎样开始 Step 5 P 测试

准备 UTF-8 环境文件，包含 `ACI_BENCH_BASE_URL` 与 `ACI_BENCH_API_KEY`。模型 ID 必须显式提供，不继承旧默认模型。密钥不写入报告或命令示例。

**1. 首先做端点探针。此步才开始真实请求。**

```powershell
python tools/prelive_probe.py --model EXACT_STEP5P_MODEL_ID --env-file PATH_TO_ENV --out NEW_ENDPOINT_PROBE_JSON --max-tokens 16384
```

检查两次工具调用/结果往返、Unicode、usage、截断和协议。请求失败、字段缺失或预算不兼容时停止，先修配置；探针不是 benchmark 样本。

**2. 冻结首轮联合设计。**

```powershell
python tools/live_round.py --tag NEW_STEP5P_R1 --model EXACT_STEP5P_MODEL_ID --env-file PATH_TO_ENV --analysis-plan bench/aci/studies/prelive-v1/analysis-plan.json --preflight audit-r12-scratch/prelive-2026-10-06/gate-approved/readiness.json --probe-report NEW_ENDPOINT_PROBE_JSON --prompt-variants baseline,compact_all --order-seed 42 --seeds 42,43,44,45,46 --max-turns 80 --max-tokens 16384 --arms with --dry-run
```

核对 collection/schedule 后，用相同参数去掉 `--dry-run` 执行。完整重复使用新 tag；42/43/44/45/46 五个 seed 是一轮内部的分片，不是五次完整重复。若服务约束要求调整预算，应重新规划、探针、冻结，而不是混入原 study。

**3. 分开生成描述性报告和预注册分析。**

```powershell
python tools/refresh_live_artifacts.py --collection PATH_TO_COLLECTION --out-dir NEW_REPORT_DIR --task-set bench/aci/task_sets/3.1.0.json --prompt-variant compact_all
python tools/study_inference.py --manifest PATH_TO_COMPLETE_REPEATED_STUDY --plan bench/aci/studies/prelive-v1/analysis-plan.json --calibration audit-r12-scratch/prelive-2026-10-06/gate-approved/calibration-r3.json --out NEW_PROSPECTIVE_REPORT
```

每题每轮至少 5 个 seed、至少三份完整采集才满足上述重复分析入口；实际为 10/30 次时使用对应校准报告。分析家族摘要必须与采集时一致，否则拒绝旧数据的事后认证。

## 保留的边界

- **旧 35 题仍是工程/已看过分布。** 可以重新测试代码与成本；不能据此宣称解决了成功率天花板或外部泛化。困难任务模板需要真实独立作者、变体、准入与留出冻结后才能用于能力声明。
- **评分副本不是操作系统级恶意代码沙箱。** 已覆盖验证字节、固定编译器、已知新增钩子、重定向和评分后污染；不宣称同用户任意恶意程序无法绕过整个操作系统。
- **ready_for_live 不等于产品所有指标通过。** C14/C16 的历史值没有达到原门槛；C12/C34 的历史证据已陈旧；旧 C36 仍因未校正 CPST 主张被拒绝。没有靠改阈值或覆盖历史报告把它们变绿。
- 端点别名不证明底层模型版本；新探针记录实际返回元数据，但不会编造家族身份、价格或缓存规则。
- 真实网络波动、真实模型效果、困难集表现与对外发布验收仍须由新 live 数据完成。此处完成的是进入这些测试前的代码、统计方案和离线准备。

## 原始证据

- [最终 readiness](../audit-r12-scratch/prelive-2026-10-06/gate-approved/readiness.json)
- [门禁执行日志](../audit-r12-scratch/prelive-2026-10-06/gate-approved.log)
- [Python 测试](../audit-r12-scratch/prelive-2026-10-06/gate-approved/python-tests.log)
- [Rust 测试](../audit-r12-scratch/prelive-2026-10-06/gate-approved/rust-tests.log)
- [任务评分审计](../audit-r12-scratch/prelive-2026-10-06/gate-approved/task-audit.json)
- [合成链最终分析](../audit-r12-scratch/prelive-2026-10-06/gate-approved/synthetic/inference.json)
- [分析家族](../bench/aci/studies/prelive-v1/analysis-plan.json)
- [困难任务蓝图](../bench/aci/studies/prelive-v1/task-blueprint.json)

### 完整重复 study manifest 示例

将下列 `study.json` 放在 `bench/aci/results/`，替换三个真实 tag。`collection.json` 本身包含实际任务清单与版本，可作为 task manifest。三个 collection 均需包含同一组 5 个 seed、三条件、两变体；不能复制一份数据冒充重复。

```json
{
  "task_manifest": "NEW_STEP5P_R1/collection.json",
  "seeds": [42, 43, 44, 45, 46],
  "conditions": ["raw_shell", "raw_shell_coached", "verseshell_aci"],
  "run_indices": [0],
  "runs": [
    {"run_id": "r1", "artifact": "NEW_STEP5P_R1/latest_live.json"},
    {"run_id": "r2", "artifact": "NEW_STEP5P_R2/latest_live.json"},
    {"run_id": "r3", "artifact": "NEW_STEP5P_R3/latest_live.json"}
  ]
}
```

最终 [完成审计](../audit-r12-scratch/prelive-2026-10-06/completion-audit.json)、[本目标精确代码 diff](../audit-r12-scratch/prelive-2026-10-06/implementation.diff) 和 [文件变更摘要](../audit-r12-scratch/prelive-2026-10-06/change-manifest.json) 已保存。

[逐项完成审计](../audit-r12-scratch/prelive-2026-10-06/completion-requirements.json) 与 [历史产品门禁快照](../audit-r12-scratch/prelive-2026-10-06/claim-gate-current.json) 分开保存；后者为 26/31，exit 1，保留 C12/C14/C16/C34/C36 红项，不代表离线启动准备失败，也不被包装为产品全绿。
