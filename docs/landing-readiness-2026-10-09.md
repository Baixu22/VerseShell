# TF-0141 与新冻结 readiness：开发验收回执

日期：2026-10-09（Asia/Shanghai）。总目标仍未完成；本批没有合并、强推、重置或暂存当前工作区。

## 一、44 项落地发现的实际含义

- 已刷新 origin/master。默认分支为 15c027d，当前 HEAD 为 a8d4c56；默认分支没有独有提交，当前分支超前44个提交。
- 42个可疑提交引用涉及29个节点、24个不同提交，均存在于当前分支且都不可达默认分支。它们来自同一条 codex/reproducible-upstream-20260727 历史分支，不是42个本轮新增代码缺陷。
- 对每条引用记录了提交存在性、HEAD/default可达性、变更路径、是否仅森林元数据、节点原验收条款和开放后继。这29个节点的条款未明确要求默认分支落地，不能仅凭未合并就推翻其历史本地交付。旧测试本批未重新认证。
- 87个done节点未被现有工具关联到提交；这表示未知，不等于实现缺失。212个分支差异文件也不是212个缺陷。

## 二、需要用新事件纠正的两项状态

| 节点 | 可复核矛盾 | 处置 |
|---|---|---|
| TF-0093 | 明确要求clone后执行的4个verify脚本：本地存在，却被*.py忽略、未跟踪、HEAD/default中均不存在；还硬编码原C盘工作区 | 保留脚本和旧输出，不运行或覆盖；重新打开，补可迁移输入和Git可达性 |
| TF-0094 | 明确要求claim_gate exit0和子项逐条完成，自己的完成证据却为29/31，且4个研究后继仍开放 | 保留TF-0116原阈值决策和历史成果，重新打开未满足的验收范围 |

不会批量重开其余42条引用，不把时间戳当作提交可达性证明，也不改写旧完成事件。

## 三、新冻结验证副本

- 在D盘建立独立本地克隆（no-hardlinks、detached HEAD），再按当前工作源文件覆盖；没有改变C盘checkout。
- 370个运行时源码/测试文件逐字节匹配；工作源覆盖共832个文件。排除了凭据、当前森林、提案和非必要嵌套历史归档。它是验证副本，不是已发布或默认分支落地的提交。
- 单独固定了一份已有历史tokenizer单元测试fixture，保存源与目标摘要并在运行后复查。它不是新模型测量。
- 另存新分析计划，仅更新analysis_code_sha256；样本下限、假设家族和旧计划均未改写。新候选必须使用自己的冻结身份，不能续写旧轮数据。

## 四、验证结果与实际修复

- 失败端点探针现在保留已经收到的usage、错误前的响应、失败attempt和脱敏证据，不再只剩一行异常而失去计费缺口。
- 修复tokenizer下载回退忽略TIKTOKEN_CACHE_DIR的问题；最终用D盘缓存解析真实cl100k_base，无新Python包安装。原有依赖从已安装的C盘Python读取，主要临时目录和构建输出在D盘。
- 最终完整readiness：**Python 345/345，通过且无跳过**；**Rust 289通过、1忽略**；**fixture 35/35**。
- 当前选定输入产品门禁仍26/31、exit1；C12/C14/C16/C35/C36未过。离线ready不替代该产品门禁。
- 3/10/30次运行配置分别完成2000次合成校准；3150格合成采集/恢复/合并完成，恢复重复调用0，合成结果的实证主张保持关闭。不是三次真实重复。
- 前两轮readiness虽然退出0，但有4个测试因缺辅助fixture而跳过，不能当作最终无缺口结果；这些回执保留。检查依赖可见性后确认包并未缺失，最终没有加入不必要的PYTHONPATH改动。
- 首次tokenizer回退仍写入C盘公共缓存，这是发现该实现缺口的证据；已修复配置优先级并验证D盘文件，没有删除全局缓存。最初文件枚举超出缓冲导致覆盖清单不全，也在冻结前被核对发现，完整覆盖和370文件一致性验证通过后才启动构建。

## 五、真实端点的当前阻塞

- 在冻结版本上预先限定2个逻辑请求、每次最多1024 completion tokens、60秒请求预算。实际首请求收到StepFun **403 real_name_required**，第二请求及真实基准均未启动。
- 这是账户持有人需要处理的认证前置条件，agent不会代办、切换账号或绕过。没有usage返回，计费状态未知，不能写成零成本。原始脱敏回执和已知attempt被保留。
- 处理后需复验同一冻结端点和预算，再开始开发集行为试点。当前离线ready不等于端点ready、正式研究完成或产品门禁全绿。

## 六、作者来源暴露面

35个当前任务中，25个声明由sn-glm-5-3-flash生成，10个没有作者声明；有完整family_evidence的0个。与历史GLM被测别名相同的是25个，与当前Step5别名相同的是0个；不同别名不证明底层家族独立。未生成新的能力任务，TF-0115仍开放。

## 原始证据

[逐引用落地审计](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/landing-audit.json) · [源码冻结核验](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/source-freeze-verification.json) · [辅助输入](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/auxiliary-test-inputs.json)
[最终readiness](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/readiness-final/readiness.json) · [Python日志](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/readiness-final/python-tests.log) · [冷构建](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/logs/candidate-build.log)
[失败端点回执](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/endpoint-probe.json) · [探针预算](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/endpoint-probe-plan.json) · [作者来源清单](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/author-exposure.json)
[最终摘要](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/final-summary.json) · [本轮精确改动](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/change-manifest.json)
