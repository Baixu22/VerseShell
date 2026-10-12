# TF-0136：最终工作区冻结与独立评分复核

日期：2026-10-08（Asia/Shanghai）。续接「启动 TF-0124 节点开发」中断前的 TF-0136 改动。

## 当前结论

- **工程链路已接通，不代表全量历史重评分或产品验收通过。** 原 Task Forest 的 TF-0136 仍为 ready；进展更新只保存为待确认提案，不自动应用或关闭节点。
- 旧轮 step5p-d-r1-20261007 的 **1050/1050 行都没有持久化最终评分输入**；最终快照可核验覆盖是 **0/1050**。原始 911 成功、139 失败保持不变，缺失不是成功或失败。
- 只读重解析旧轨迹：TypeScript 单文件候选 **17/30**，Python 汇总文本候选 **30/30**。候选不证明命令成功，也不证明其他文件、删除或副作用已完整恢复，均不是独立 live 重评分。

## 代码边界

1. 复用 guarded_success 的一次性评分副本，在 evaluator 执行前捕获输入；不从模型写入参数猜测最终文件。
2. D 盘持久化内容寻址 blob/manifest：包括文件 SHA-256、大小、模式、空目录、cell/task 身份、谓词、保护验证器与评分器源码摘要。捕获前后两次清点不一致时不发布可用 manifest。
3. 加载/恢复先校验摘要、库存、父目录、路径和类型。本批修复非对象 manifest 中断整批审计、无效保护验证器被计作失败评分、以及根路径“.”在创建目标后才报错的问题；这些情况现在只产生不可复核的行。
4. 评分与证据可用性分开记录。验证器变更导致拒绝评分时补充具体不可冻结原因；写盘故障仍提交当前行并暂停，不派发下一格。
5. 独立审计默认只验哈希，不执行代码。只有显式 --rescore 加 1–20 个唯一 --cell-id 才执行当前可信任务谓词；身份、谓词、评分器源码不匹配时拒绝比较。缺运行依赖返回 unknown，不当作失败或相符。
6. 修正旧候选分析的描述与解析理由，移除误插到调用链报告的“独立复评分”字段。保留旧统计字段兼容性，明确 runs_scored 的历史语义是读取行数，不是独立复评分数量。

继承边界见 [本轮变更清单](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/change-manifest.json) 和 [整个 TF-0136 节点变更清单](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/node-change-manifest.json)。没有重置、暂存、提交或合并既有改动。

## 冻结范围和限制

- 与评分副本共用排除范围：target、__pycache__、.pytest_cache、.ae；其余常规文件和空目录捕获，包含已物化的 node_modules/compiler 文件。
- 上限：10,000 个条目、总量 128 MiB、单文件 64 MiB、manifest 8 MiB。符号链接/重解析点、危险路径、越界、不一致、疑似凭据均拒绝；不截断、不脱敏后冒充原始字节。
- 当前保守凭据检测拒绝了配置测试里的两个样例。本批未放宽策略；未来如需覆盖，须明确审查策略，不能静默跳过文件。
- 不冻结外部 Python/Node/Rust 可执行文件、环境变量、系统、网络或后台进程状态。这是同机独立重评分，不是跨环境确定性保证、同用户安全沙箱或签名认证。
- 快照保存在原始输出目录下的 final-workspaces。审计原始分片或同目录合并输入；迁移时保留整个证据目录，仅拷贝 JSON 不算完整快照。

## 验证结果

| 检查 | 结果 | 原始证据 |
|---|---|---|
| 继承的专项测试 | 15 项，exit 0 | [日志](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/logs/final-workspace-inherited-tests.log) |
| 补充负向用例，修复前 | exit 1，复现类型/路径/原因缺口 | [日志](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/logs/final-workspace-negative-controls.log) |
| 修复后的专项测试 | 18 项全部通过，exit 0 | [日志](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/logs/final-workspace-final-tests.log) |
| 最终 Python 全量回归 | 260 项：257 通过、3 跳过；exit 0 | [日志](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/logs/python-tests-final.log) |
| 真实 fixture + 生产捕获钩子 | 5 题 × pristine/GOLDEN = 10 个对照，评分均符合预期；8/10 有快照，exit 0 | [日志](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/logs/fixture-production-hook.log) |
| 显式独立 CLI 复评分 | 选 10，运行 8，**8/8 与记录评分一致**，0 分歧；另 2 个 unknown，exit 0 | [报告](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/evidence/offline-independent-rescore.json) |
| 旧轮最终快照覆盖 | 0/1050；不执行历史命令、不改写评分，exit 0 | [逐格清单](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/evidence/historical-final-workspaces.json) |
| 旧单文件候选覆盖 | TS 17/30；Python 30/30；独立 live 复评分均为 0，exit 0 | [含 cell/variant 的清单](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/evidence/historical-candidate-coverage.json) |
| 产品门禁 | **25/31，exit 1**；C12/C14/C16/C24/C34/C36 未通过 | [报告](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/evidence/product-claim-gate.json) |

真实工具链样例覆盖 Python、Rust、TypeScript、Node。模型响应被替换为离线 fixture 控制，不发送模型请求；评分器和生产快照钩子真实执行，原始工作区清理后才独立恢复评分。输入明确标注 synthetic_test_only，不能作为 live 能力或收益证据。

配置校验题 node_envconfig_validate_dd681123 的两个样例触发保守凭据检测：pristine 原始评分 false、GOLDEN 原始评分 true 均保留，独立评分都为 null。不能把“8/8 相符”说成“10/10 重评分完成”。

继承的全量测试中，导入 RecoveryTests 类造成 19 个用例重复收集。本批改为模块导入，最终计数以去重后的日志为准；三个真实 tokenizer 相关用例因离线缺少 tokenizer 跳过，未下载安装依赖。

执行异常也保留：第一次直连 capture 探针被凭据检测中止（exit 1），随后改用生产钩子核对评分/证据分离，未绕过检测。首次门禁输出被外部验证封装的同名命令回执覆盖，已分开文件名重新执行；正式证据只采用 product-claim-gate.json 及其独立命令回执。

## 后续与治理

- TF-0136 拟更新为 in_progress，不是 done；历史缺失、保守凭据过滤范围、新冻结版本真实采集均保留为限制。
- TF-0137 全入口严格判定尚未实施；本批快照完整性和离线通过率不能代替统计/产品验收。
- 只保存 [进展提案](C:/Users/27933/Desktop/verseshell/verseshell/proposals/TFP-final-workspace-node-dev-2026-10-08.json)，不执行 proposal-apply。当前 [任务森林](C:/Users/27933/Desktop/verseshell/verseshell/.agent-workbench/task-forest/exports/task-forest.html) 不冒充已应用该提案。
- 无付费模型请求、旧轮样本重跑/替换、生产冻结计划改写或 commit/merge。主输入、旧报告及索引边界见 [最终回执](D:/VerseShellLive/final-state-resume-20261008-01a11b5b/evidence/final-summary.json)。
