# TF-0140：声明、实际输入与版本路由

日期：2026-10-09（Asia/Shanghai）。本批完成声明路由与范围核验的工程部分；不等于正式研究或总目标已完成。

## 实际修复

1. 门禁新增版本化 artifact-map；逻辑键只允许既有测量项。CLI 与 map 选择冲突时拒绝。C12、新鲜度检查、31 个门禁及嵌套 README 检查使用同一组选定路径，不复制或覆盖旧 canonical 文件。
2. 每次输出 claim_inventory 和 `.claims.md`：31 个门禁加6个无阈值诊断共37项，包含实际文件、摘要、源/二进制版本、样本量、原数值/原阈值与限定状态。C3/C4补上实际metrics文件，C24补上审计和任务集，C10补上实际README检查回执及其输入。
3. 复用既有 readiness 的源码清单，门禁开始/结束核对源码和已消费输入。变化使C12失败；通过的数值谓词若仍只有历史/未验证来源，也不能让C12绿灯。生成于本次门禁的原生metrics/compact结果在独立输出旁落盘，带实际命令，不冒充旧测量。
4. native测试退出0但没有执行测试不再视为通过。README检查记录实际AE摘要及输入摘要，读取所选择的cross-shell/compact文件。compact百分比取C9的保守侧42.0%，不是字节侧约42.4%。
5. 读取重放器不再硬编码C盘旧AE：沿用当前CARGO_TARGET_DIR/候选选择，并复用有界进程执行。产物记录实际二进制、冻结调用输入的摘要与版本，前后变化则拒绝出具报告。
6. C34不仅看“冻结版本标签不是2.0.0”：实际被读取数据须严格新于2.0.0，且报告摘要、任务清单、版本与所选择的冻结/数据一致。只改标签、读旧数据、版本回退都被拒绝。0.40原阈值没有变化。

## 清单状态不是新的效果授权

| 状态 | 含义 |
|---|---|
| verified_current_check | 该次门禁执行并通过的当前控制检查，源/输入在执行期间稳定 |
| verified_selected_measurement | 所选证据的限定检查通过；可能来自历史采集，必须连同版本、样本和边界读取 |
| historical_only | 数值谓词虽过，但来源对当前树已陈旧 |
| unverified | 缺少当前绑定等必要证据 |
| not_met | 原数值或一致性谓词未过 |
| diagnostic_only | 六项无阈值诊断，不产生PASS |

完整重复、独立任务/作者来源、计费完整性、冻结版本和正式推断仍须各自验收。矩阵不授予科学效果结论；森林状态本身也不是统计证据。

## 本轮真实重验

- 默认旧输入：最终默认门禁及37项清单见下方原件。旧报告未覆盖。
- 路由到此前真实35/35 fixture审计：C24通过，且回执确实指向D盘新原件；这不是替换旧C24报告或仅改它的布尔标签。
- 以当前候选重新执行C14读取重放：只有6/144个调用匹配原保存的token计数，2502→2379代理tokens，约4.9%，低于原15%门槛。预算控制仍通过：8×300行，默认240行、tight40行，250/250分页往返。
- 重新执行C16：仅3/144匹配，980→901代理tokens，约8.1%，低于原10%门槛。C34命名开销在这3个匹配调用中474→150字符，约68.4%；是否满足绑定和新鲜度由真实门禁独立判定。
- 这两份重放使用canonical历史3.0.0调用集，而不是Step5p的3.1.0采集；运行的是当前候选与当前fixture。token计数匹配不证明原始内容/最终工作区相同，排除项也不都意味着“live生成了文件”。工具表述已纠正，旧数值和初次输出仍保留。
- README计时表明确为历史机器基线；检查表格抄录正确不代表当前版本重测，更不代表当前模型任务加速。

## 验证与原件

- 本批17项路由/README/重放测试后补充了C12未绑定来源负对照，共18项专项控制。
- 最终Python全量：339项，336通过、3 tokenizer依赖跳过，exit0。
- 最终默认旧输入门禁24/31，显式选定新证据26/31，两者均exit1且源/输入稳定。新增通过为C24的35/35当前fixture与C34的限定3调用命名开销；C12/C14/C16/C35/C36仍未通过。
- 两套门禁中的Rust全量均289通过、1忽略，exit0；完整原件见[最终摘要](D:/VerseShellLive/claim-routing-20261009-01a11c1d/evidence/final-summary.json)。
[默认最终门禁](D:/VerseShellLive/claim-routing-20261009-01a11c1d/default-verified/evidence.json) · [默认37项清单](D:/VerseShellLive/claim-routing-20261009-01a11c1d/default-verified/evidence.claims.md)
[新证据最终门禁](D:/VerseShellLive/claim-routing-20261009-01a11c1d/selected-verified/evidence.json) · [新证据37项清单](D:/VerseShellLive/claim-routing-20261009-01a11c1d/selected-verified/evidence.claims.md)
[最终artifact-map](D:/VerseShellLive/claim-routing-20261009-01a11c1d/final-inputs.json) · [C14重放](D:/VerseShellLive/claim-routing-20261009-01a11c1d/fresh-final/tf45_envelope_replay.json) · [C16/C34重放](D:/VerseShellLive/claim-routing-20261009-01a11c1d/fresh-final/read_path_breakdown.json)
[全量回归](D:/VerseShellLive/claim-routing-20261009-01a11c1d/logs/python-tests-verified.log) · [精确改动清单](D:/VerseShellLive/claim-routing-20261009-01a11c1d/change-manifest.json)

```powershell
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 'D:/VerseShellLive/claim-routing-20261009-01a11c1d/run_checks.py' tools/claim_gate.py --artifact-map 'D:/VerseShellLive/claim-routing-20261009-01a11c1d/final-inputs.json' --evidence 'D:/VerseShellLive/claim-routing-20261009-01a11c1d/new-check/evidence.json'
```

输入map只选文件，不改阈值、不授予有效性。每次复验使用新的输出目录，保留原始来源与失败日志。

## 源码落地与剩余范围

本批用仅限单次git命令的空proxy配置完成fetch（未改全局配置），故默认分支检查不再只依赖旧缓存。已刷新origin/master后check-landing仍有44项历史发现、exit1。没有暂存、提交、合并或重置工作区。
TF-0141继续逐项解释这些历史发现；真实完整重复和独立任务证据仍由TF-0112/0114/0115等开放节点完成。本批不得用当前本机控制、低覆盖重放或37项表格替代那些工作。
