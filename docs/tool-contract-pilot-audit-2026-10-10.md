# 工具契约节点：2026-10-10 开发试点审计与最小修复

日期：2026-10-10（Asia/Shanghai）。范围为 TF-0128～TF-0131 在已冻结 18 格真实开发试点上的只读复核，以及 TF-0129 暴露的 `result.query` handle 兼容修复。本轮没有新增模型请求，没有把开发试点包装成正式研究、产品门禁或默认分支落地。

## 证据身份

- 试点：`D:/VerseShellLive/node-freeze-20261010-01a120ce/workspace/bench/aci/results/step5p-dev-20261010-r2/latest_live.json`
- 试点 SHA256：`615099fab32954b40e239cdd01d56d5b176ef4371144436576c10b8827f315ff`
- 只读重放：`D:/VerseShellLive/tf0128-0131-dev-pilot-audit-20261010/pilot-tool-contract-replay.json`
- 汇总：`D:/VerseShellLive/tf0128-0131-dev-pilot-audit-20261010/pilot-tool-contract-summary.json`
- 覆盖：18 格、242 个观测；`partial=true`，这是开发诊断，不是完整研究。

## TF-0128 文件窗口

- `file.view` 共 23 次，覆盖 6 个 ACI 格；全部 `ok=true`。
- `start_line`、`end_line`、`total_lines`、`cursor`、`next_cursor` 与返回行号逐项一致。
- 15 次调用使用 cursor 继续；10 次在到达 EOF 时返回 `next_cursor=null`。
- 106 行的 `envConfig.mjs` 在真实试点中被以 `cursor=75/80/95/100`、不同窗口连续读取并到达文件末尾，没有再出现历史同窗口无限重复。
- 本机 106 行窗口回归、首尾、空文件、超范围和连续遍历测试通过。

## TF-0129 输出截断与取回

- 170 次 `run_command` 全部带 `[EXIT: n]`；stdout/stderr 原始流都没有截断标记。
- 4 个 stdout 因凭据脱敏而 `capture_complete=false`、`redacted=true`；这是保护性省略，不是字节静默截断，不能当作无损原文。
- 13 次 ACI `exec.run` 覆盖 full/reduced/truncated/empty；9 次返回 `ok=true`，所有被缩减流都保留 artifact handle 和遗漏字节数。
- 试点中唯一一次 `result.query` 使用了 `result://sha256:<digest>`，旧候选返回 `E_RESULT_HANDLE`。这说明模型可见 handle 语法不够明确，也暴露了仅接受 `/` 的接口过窄。
- 最小修复：`src/artifact.rs::parse_handle` 仅额外接受上述 exact colon alias，仍要求 64 位十六进制摘要；`live_agent_loop.py` 与 `compact_prompts.py` 明确展示 `result://sha256/<64 hex>`。
- 新增 Rust 单元回归和本机端到端回归；10 项 `test_tool_contracts.py`、4 项 artifact Rust 测试均通过。修复后的新候选已完成完整 offline readiness，但尚未经过新的真实模型轮。

## TF-0130 Windows shell 与 argv

- 170 次 raw shell 调用使用命令字符串；其中显式 PowerShell 5 次。
- 13 次 ACI `exec.run` 全部使用 `argv` 数组，没有一次把 `command` 字符串偷偷塞进 argv 路径。
- ACI 中 cmd 直调 0 次、显式 PowerShell 4 次；argv 字面量、显式 cmd、PowerShell、管道和重定向的本机测试通过。
- 历史执行失败的逐调用轨迹仍保留在 `D:/VerseShellLive/tf0128-0131-dev-pilot-audit-20261010/pilot-tool-contract-replay.json`。

## TF-0131 编码与原始字节诊断

- raw shell 的编码标记：stdout 为 163×utf-8、7×windows-oem-936；stderr 为 162×utf-8、8×windows-oem-936；没有 `lossy=true`。
- 170 次 raw shell 的 stdout/stderr 均未截断；最大原始流 17,333 字节，低于 65,536 字节保存上限。
- ACI 13 次执行的双流均为 `encoding=utf-8`、`decoding_lossy=false`、`raw_complete=true`；0 个有损流、0 个原始流不完整。
- 本机 UTF-8、GBK/CP936、非法字节和 stdout/stderr 回归通过；混合编码与历史丢失字节仍不能自动无损恢复。

## 回归与身份

- `test_tool_contracts.py`：10/10，exit 0（日志：`D:/VerseShellLive/tf0128-0131-dev-pilot-audit-20261010/test_tool_contracts.py.log`）。
- `test_live_turn_diagnostics.py`：26/26，exit 0。
- `test_prelive_repairs.py`：15/15，exit 0。
- `test_read_text_projection.py`：7/7，exit 0。
- Rust `artifact::tests`：4/4，exit 0（日志：`D:/VerseShellLive/tf0128-0131-dev-pilot-audit-20261010/rust-artifact-tests.log`）。
- 当前源码摘要：`artifact.rs=39694d0efa5a0247613741770e3115e3e8917d8e11defb0d9627da39a7fc9a51`；`live_agent_loop.py=1a82fb49d7b6cd3767f4b10328ce12df28a7e7367406ee9b6348cb02588223eb`；`compact_prompts.py` 最终值见 `change-manifest.json`；`test_tool_contracts.py=0a11f7d07343dedb0561c6ce50439852ecfe05e8508fdd898a70c9b165d692de`。
- 本机新二进制：`target/debug/ae.exe` SHA256 `e62452be1f7335416391b694faf234914cbe3512aa2bad656379cbd5ac07ca74`。

## 新候选完整 offline readiness

- `D:/VerseShellLive/prelive-20261010-04/readiness.json`：`ready_for_live=true`，`endpoint_verified=false`，无模型请求。
- Python 全量 **472/472 exit 0**；Rust **290 passed / 1 ignored**；35/35 任务审计通过。
- 3/10/30 运行校准均通过；3150 格合成采集/恢复/合并/推断完成；原生 ACI smoke 通过；候选摘要全程未漂移。
- 候选二进制 SHA256：`e62452be1f7335416391b694faf234914cbe3512aa2bad656379cbd5ac07ca74`。
- 新分析计划 `bench/aci/studies/prelive-v1/analysis-plan-2026-10-10.json` SHA256：`9e134b67301394502bd5a13737f805e74cbd2dcc061a1b4b26ec4b7b3e28a48d`；只更新分析实现哈希，未改 30/5/3、阈值或假设族。
- 仍需显式端点探针和新冻结的真实开发/正式采集；本回执不授予端点和正式效果结论。

## 边界

- 这些是开发试点和本机工程证据，不是正式效果、能力、重复性或产品成本结论。
- `TF-0129` 的 handle 修复是在观察到的真实模型调用之后完成的；没有用新模型轮追认新提示效果。
- 新源码和新分析实现改变了候选身份；完整 offline readiness 仅覆盖工程前提，仍需显式端点探针和新的真实轮，不能把旧 18 格与新候选拼接。
