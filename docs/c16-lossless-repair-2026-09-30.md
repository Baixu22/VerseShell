# C16 无损读取格式修复回执

> 后续状态：前置采集校验与 Responses 适配已完成，指定模型的 630 格采集已启动。
> 本文件下方为较早修复快照；最新状态见 [前置准备回执](pre-live-preparation-2026-09-30.md)。

实现和开发验证完成。当前 r15 固定读取集合上的 C16 从 **7.89% 提升到
12.49%**，超过原 10% 门槛；**正式门禁尚未转 PASS**。C14 仍按原摘要差值
口径计算，候选为 **4.70% < 15%**，保持 FAIL。两项阈值均未修改。

## 实现

- `bench/aci/runners/live_agent_loop.py`：成功读取采用 `read-text/v1`，JSON
  元数据头保存原字段，`text` 数字标记对应原样文本的 Unicode 字符数；各正文
  按顺序用一个换行隔开。长度决定边界，正文内的同名标记、引号、反斜杠和换行
  不会改变解码。新增配套解码函数与工具说明。失败及无正文结果保持普通 JSON；
  `compact=False` 保留原基准。Rust 服务信封未变。
- `tools/projection_contract.py`：使用解码器，验证完整 60 行、混合错误与分页
  批次，以及显示摘要可用于新鲜编辑、过期后拒绝写入。
- `tools/read_path_breakdown.py`：按原样文本的换行计量更新结构开销归因；
  没有修改原匹配规则、读取集合或门禁口径。
- `tests/test_read_text_projection.py`：新增 7 项回归，包含 Unicode、空正文、
  伪头部、畸形边界、分页、摘要回退和输出路径隔离。原摘要归因测试适配解码器。

协议在实现前写入 `docs/c16-read-text-protocol-2026-09-30.md`。没有尝试删除
摘要、缩小窗口、丢弃路径或按候选收益选择样本。

## 实测结果

| 检查 | 结果 |
|---|---|
| Python 全回归 | 131 通过，exit 0，22.081 秒 |
| 真实 `ae --serve --agent` 投影契约 | 11/11 通过，exit 0 |
| 当前 r15 读取重放 | 全部 144 调用；141 匹配，3 排除；与原基线一致 |
| 原语义对象往返 / 旧渲染逐字一致 | 各 144/144 |
| 双渲染归因合计与非负检查 | 288/288 |
| C16 观察字符代理 token | legacy 77017；修复前 70940；候选 67396；节省 12.4920% |
| 相对修复前的额外观察代理节省 | 4.9958% |
| C14 原摘要差值口径 | 70720 → 67396；4.7002%；仍 FAIL |
| 真实模型 smoke | 3/3 成功，exit 0，无 API 错误；实际调用 file.view 和 file.read_many |
| 保护面 | 322 文件 SHA-256 一致，0 变化、0 新增；含任务、fixture、Task Forest、两份正式 live JSON 和 claim_gate.py |

三个排除调用仍是两次运行中创建的 `out/result.txt` 和一次运行中修改的
`csvlite.py`。匹配集合由保存的修复前投影确定，不依赖候选节省或成功与否。

live smoke 使用既有三个 smoke 任务，配置为 `sn-glm-5-3-flash`、seed 42、
temperature 0、8 turns、16384 completion tokens，仅 D 条件。分别成功：
`rust_fix_compile_error`、`python_fix_pytest_fail`、`windows_path_normalize_edit`。
最后一项没有使用读取工具；前两项分别实际使用单文件与批量读取。没有重试失败
来筛选结果。它只证明这次集成探针成功，不能证明成功率无退化或完整研究达标。

12.49% 是原 C16 的观察文本 `len(text)//4` 代理节省，不是模型 tokenizer、
累计输入 usage 或费用节省。新增工具说明也进入模型请求，未在这个观察桶中计量。

## 验证期间的额外修复

runner 原先无论 `--out` 指向哪里都重写公共 `live_REPORT.md`。smoke 暴露此问题；
现已修为非正式输出写同目录同名 `.md`，默认正式输出仍保持原报告路径，同时在
创建 checkpoint 前创建输出目录。新增 CLI 回归验证独立目录不会覆盖公共报告。

公共 Markdown 报告已从未改动的 315 行 `latest_live.json` 重新生成；没有入场
Markdown 哈希，不能声称与入场文件逐字一致。原 smoke Markdown 已另存。live 后
仅改动 `main` 的输出路径/目录处理，所有其他顶层 AST 节点与实际 live 测试版本
一致；保存了该版本，未给旧 live 产物重盖指纹。

## 正式验收边界与后续

未运行完整 630 格网格，未重建受影响的正式证据链，未将 smoke 覆盖到正式 JSON。
当前新鲜度为 **9/25**；16 个旧产物因模型可见面变化而过期，C12 不满足。
历史 `eval/evidence.json` 不能代表当前树的完整验收。正式 C16 PASS 仍需锁定新
候选，完整采集并运行派生链与完整门禁；不得只补有利格或重新标记旧指纹。
C14 继续保留原失败结论。

本次没有重跑 Rust 全套或完整 claim_gate；Rust 实现未改，实际服务契约已经执行。

可复核产物全部在 `audit-r12-scratch/c16-lossless-2026-09-30/`：
`verification.json`、`replay-report.json`、`envelopes.json`、`projection-contract.json`、
`python-final.log`、`live-smoke.json`、`live-smoke.log`、`before/` 和 `session.diff`。
两份重放/汇总脚本保留于同目录，可用 `python -B` 再执行；不调用模型端点或写正式证据。
