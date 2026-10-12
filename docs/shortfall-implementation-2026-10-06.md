# 短板修复第一批落地回执

日期：2026-10-06。对应 [12 项策略](shortfall-remediation-strategy-2026-10-06.md) 的 01–05 核心链路。

本轮已实施代码并完成下列验证；**不表示前五个工作包全部验收，也不表示整个策略完成**。
没有调用模型端点、改写 c20/c21、发布 canonical 报告、提交 Git 或修改 Task Forest 状态。

## 实际落地

| 工作包 | 实施结果 | 状态边界 |
|---|---|---|
| 01 来源与边界 | 保存改动前 77 个 Python 源码/测试文件、初始 Git 状态及 SHA256；生成精确本轮 diff 与文件清单 | 已建立可审核的本轮边界；正式 study 仍待目标模型和协议冻结 |
| 02 进程与恢复 | 受信任启动助手等待许可，父进程绑定 Job 后才发送许可；绑定失败不运行命令；标准流显式继承；中断未知结果暂停，显式恢复也受每格最多 3 次启动限制 | Windows 实机故障测试通过；不承诺远端请求 exactly-once，外部终止来源仍未知 |
| 03 评分链 | C24 缺 GOLDEN 不再跳过；门禁核对实际正/负判词、谓词与覆盖；难度审计支持显式 freeze/admission/live/power 输入及来源匹配 | 35 题当前评分审计通过；全部任务的独立解/强负控与可信评分材料隔离仍需补齐 |
| 04 来源与统计 | C12 实际重算 input_sha256；新增任务聚类 CPST/成功率差区间；重复运行分析增加配对比值均值、CPST 和 usage_complete 检查；隔离刷新目录并最后写完成标志 | 区间是诊断，不自动通过确证门禁；检验校准、家族预注册和正式交互分析尚未完成 |
| 05 分块调度 | live_round 支持 `--prompt-variants baseline,compact_all`；生成六组合平衡轮换计划；runner 执行、格身份、断点恢复、merger 纳入变体；混合报告必须选变体 | 630 格计划 dry-run、六组合模拟执行/续跑通过；尚无真实模型六组合采集 |

新增源码仅为 `managed_launch.py`（启动屏障）、`live_schedule.py`（计划）、`report_inputs.py`（显式选择变体）；复用原有 runner、journal、merger 和统计程序，未新增依赖。

## 验证证据

- **完整 Python：185 项通过，47.082 秒，exit 0**。见 [测试日志](../audit-r12-scratch/implementation-2026-10-06/python-tests.log)。
- **任务集 3.1.0：35/35 审计通过，exit 0**。见 [评分审计](../audit-r12-scratch/implementation-2026-10-06/task_set_audit.json)。
- **真实 ACI：file.view 与 exec.run 经新启动助手均通过**，使用本机已有 ae 二进制，没有模型调用。见 [ACI smoke](../audit-r12-scratch/implementation-2026-10-06/aci-smoke.json)。
- **调度：630 格**，包含 35 任务 × 3 seeds × 3 条件 × 2 变体；见 [schedule](../audit-r12-scratch/implementation-2026-10-06/schedule.json) 与 [单 seed dry-run 身份](../audit-r12-scratch/implementation-2026-10-06/dry-run.json)。其中 `OFFLINE-NOT-ACCEPTANCE` 明确是占位标签，不是实测模型。
- 实机验证包括绑定失败不启动工作负载、二进制 stdin/退出码、父进程死亡后的工作负载退出。模拟验证包括重复恢复不重复记行、中断预算不重置、缺失实际输入/来源变化拒绝、partial 的每个变体都禁止主张。
- [c20 CPST 诊断补算](../audit-r12-scratch/implementation-2026-10-06/c20-power-diagnostic.json) 仍用历史原始分数，不是修复后 live 效果。CPST 区间保持 `claimable=false`，不能据此放开确证声明。

回归中发现并修掉了新助手的标准句柄继承问题：无窗口子进程曾导致 stdin 超时与 Rust 行为验证失败，最终通过显式传递三个标准流解决。上面列的是修复后的最终结果。

## 可用的新入口

准备目标模型配置后，先冻结六组合计划（示例尚未执行）：

```powershell
python tools/live_round.py --tag NEW_STEP5P_BLOCKED_DESIGN --model EXACT_MODEL_ID --env-file PATH_TO_ENV --task-set bench/aci/task_sets/3.1.0.json --prompt-variants baseline,compact_all --order-seed 42 --max-turns 80 --max-tokens 16384 --arms with --dry-run
```

输出 collection 与 schedule。相同参数去掉 `--dry-run` 才会调用端点。完整重复应使用新 tag；不可把旧 c20/c21 接到新代码上续跑。

对六组合输入按变体生成隔离的离线报告：

```powershell
python tools/refresh_live_artifacts.py --collection PATH_TO_COLLECTION --out-dir NEW_REPORT_DIRECTORY --task-set bench/aci/task_sets/3.1.0.json --prompt-variant compact_all
```

该入口只做 with-only 的 C24、三臂与 power 报告；不借用 without 或跨 shell 数据。
输出目录必须为空，生成失败时 `refresh-status.json` 保持 `complete=false`，不改变 canonical 文件。
此完成标志仅表示报告生成链完成，不授予模型效果或产品验收。

完整重复分析可在 study manifest 中指定 `prompt_variant`，选择 baseline 或 compact_all；输入包含多个变体却未选择时拒绝运行。它会先验证完整变体网格，再切片分析。

## 剩余工作与下一优先级

1. **03 评分材料隔离**：进一步统一准入与正式评分契约，为全部能力题补足独立正确解、篡改/硬编码负控及可信测试材料保护，不能只依靠测试文件中的某个子串。
2. **04 检验校准**：完成偏态、强任务相关、少量完整重复、缺失与零分母情景下的覆盖/假阳性校准；新确证家族在正式采集前冻结，现有诊断区间不充当 p 值。
3. **04/05 六组合交互分析**：当前已有分块执行和逐变体分析，还需同步重抽 run/task 的描述处理交互对照；不能靠两张独立 CI 表判断交互。
4. **06 独立困难任务**：准备开发/留出切分、可核验作者来源、A1–A8 和配额；异源模型身份未知时不得补写“异源”。
5. **07 以后**：Step 5 P 精确 ID、端点/协议、认证、限额到位后先做开发探针，再冻结实际采集。完整重复、真实效果、完整产品/跨 shell 门禁仍未验收。

本轮没有修改 Rust 源码，也没有重新构建或执行整个 Rust 项目测试；现有 ae 的本地 smoke 和评分使用到的 Rust 行为测试不等于 Rust 全项目验收。
