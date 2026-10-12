# 工具契约节点首批开发回执

日期：2026-10-08。范围：TF-0128～TF-0131 的实现与本机验证，以及 TF-0132 的三个历史异常样本回放。

本批已通过 **217 项 Python、289 项 Rust 测试**；Rust 原有 1 项性能测试保持 ignored。没有调用模型端点。本批证据不构成模型停止行为、收益、完整重复实验或产品正式验收。

## 实现与直接证据

| 节点 | 本批交付 | 验证 |
|---|---|---|
| TF-0128 文件窗口 | 保留 `file.view` 的中心窗口语义，统一产品及模型参数说明；透传真实起止行、总行数和可直接使用的 `next_cursor` | 106 行文件的 `cursor=100, window=10` 返回 95–104；`next_cursor=110` 返回 105–106。首部、尾部、空文件、超范围与连续遍历均通过 |
| TF-0129 输出截断 | 移除客户端额外的 300/200 字符裁剪；成功和失败均保留退出码、超时、统计、正文及流元数据；将现有 `result.query` 接入 `read_result` | 成功/失败、stdout/stderr、full/reduced/truncated/empty 均有回归；本机超长输出保留结尾，按句柄 tail/slice 可读，无需重复执行命令 |
| TF-0130 Windows 调用 | 三条件、baseline/compact_all 及原 compact 变体说明实际平台与 shell；argv 中元字符仍为字面参数；修复共享执行器对显式 cmd 命令字符串的错误转义 | 带空格及中文路径、引号、管道、重定向、显式 PowerShell 均通过；修复前失败日志保留 |
| TF-0131 编码诊断 | raw shell 优先 UTF-8，再按 Windows OEM 回退并记录有损替换；Rust 记录替换标记，输出查询沿用捕获时的编码；两个条件均可保存有界原始字节证据 | 本机 UTF-8、CP936、非法字节、中文路径、Python UTF-8 子进程和 stdout/stderr 均通过 |

`cmd /c` 修复只作用于明确调用 cmd 且提供单个命令字符串的分支。同步执行与过程生命周期共用此解析器；普通程序 argv 与原 `.cmd/.bat` 处理保持原有调用方式。

原始字节证据保存在已有 observation journal 的 `raw_streams` 中：每流最多 65,536 字节，记录输入字节长度及摘要、保存前缀的长度及摘要、截断和脱敏标记。已知凭据在 base64 编码前脱敏。`capture_complete` 只描述此保存动作；ACI 还必须检查原 envelope 的 `raw_complete`，它可能已受运行时 64 MiB 捕获上限限制。超过上限或经过脱敏的记录不能声称可无损还原整个输出。

编码字段表示实际采用的解码规则，不证明识别出了发送方编码。Python 使用本机 OEM codec；Rust 使用既有支持表（65001、936、950、932、949、1250–1258），其他代码页回退为 UTF-8 有损解码。混合编码、历史替换字符均不能自动无损恢复；本批实机证据限于当前 Windows/CP936 主机。

## 三个历史样本

对保留的 `step5p-d-r1-20261007` 采集核验了 **183 个观测**的摘要和格身份，并按原 turn diagnostics 对齐每回合调用。报告包含全部调用、文件哈希/窗口、命令状态、观测引用和停止原因。

- `node_envconfig_validate_dd681123 / seed42 / compact_all`：同一窗口连续调用 77 次，观察文本相同，实际范围一直是 95–104，最终 `turn_limit`、原始评分失败。新算子和客户端的续读检查可到达第 106 行。
- `js_leaderboard_rank_b1603acf / seed43 / baseline`：同一测试命令共调用 66 次，最长连续 65 次，最终 `turn_limit`、原始评分成功。第 12 回合原始 stdout 为 2662 字节；新投影完整保留产品规范化后的 2661 字符、exit 0、`# pass 18` 与 `# fail 0`。记录中的 `>` 和 `2>&1` 是 argv 参数，并非 shell 重定向。
- `python_csvlite_parse_80d158b2 / seed44 / compact_all`：第 19 回合 pytest 18 passed，第 20 回合 doctest 通过，第 21 回合 completion 截断；原始评分成功。保留这一事实，不将先前测试成功当成 loop 已正常停止。

这些回放证明了已观察到的契约问题及新投影内容，没有测量修复后的模型行为。TF-0132 仍需新冻结开发试点；本批未加入自动停止、重复调用提醒或单独给 ACI 增加预算的策略。

## 复现与产物

全部新构建、测试工作区、缓存和大体积证据位于 `D:/VerseShellLive/node-dev-20261008/`。源码和权威 Task Forest 仍位于本仓库。既有采集、评分、模型配置、提示和原始报告未被改写。

```powershell
. 'D:/VerseShellLive/node-dev-20261008/environment.ps1'
$env:ACI_TEST_AE = 'D:/VerseShellLive/node-dev-20261008/target/debug/ae.exe'
cargo test --locked --offline
python -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
python -X utf8 tools/claim_gate.py --metrics eval/metrics.json --compact-ratio eval/compact_ratio.json --evidence 'D:/VerseShellLive/node-dev-20261008/evidence/claim-gate-final.json'
```

runner 和 README 检查器现在遵循 `CARGO_TARGET_DIR`，以免构建在 D 盘却验证了 C 盘旧二进制。`claim_gate` 的 README 检查回执随 `--evidence` 输出到同一目录。上面的门禁命令明确复用既有 metrics/compact_ratio 输入，以保留原始测量，不把它们冒充修复后的重新测量。

历史回放命令（输出路径必须是输入目录之外的新文件）：

```powershell
python -X utf8 tools/tool_contract_replay.py --input 'D:/VerseShellLive/workspace/bench/aci/results/step5p-d-r1-20261007/latest_live.json' --cell-id baf99a963a49f32936fc9a16601f90f2c0a51b5f83c168ef80d55e47e2103fc9 --cell-id ac2449b3b71fa66165ccf07c5fe5350c3dbbdccee7ac1f350fab406ef807806a --cell-id feed1589d22a03aa81ae277a176536c4d74686ac0e6c2e6b5357771a44d0432d --out 'D:/VerseShellLive/node-dev-20261008/evidence/historical-tool-replay-new.json'
```

- [完整 Python 回归](D:/VerseShellLive/node-dev-20261008/logs/python-tests-final.log)：217 tests，84.474 秒，exit 0。
- [完整 Rust 回归](D:/VerseShellLive/node-dev-20261008/logs/rust-tests.log)：289 passed，1 ignored，exit 0。
- [本机契约回归](D:/VerseShellLive/node-dev-20261008/logs/tool-contracts-native-final.log)：10 tests，13.209 秒，exit 0；也包含在完整 Python 回归中，不重复计数。
- [cmd 修复前失败](D:/VerseShellLive/node-dev-20261008/logs/tool-contracts-before-cmd-fix.log)：10 tests，1 failure，exit 1。
- [历史逐回合回放](D:/VerseShellLive/node-dev-20261008/evidence/historical-tool-replay.json)：3 cells，183 observations，exit 0。
- [最终产品门禁](D:/VerseShellLive/node-dev-20261008/evidence/claim-gate-final.json)：**25/31，exit 1**。C12、C14、C16、C24、C34、C36 未通过；C10 的 D 盘路径异常已修复，README 检查 17/17 通过。C24 报告仍使用历史评分合同，8 项谓词及保护摘要不匹配，不能据其旧 PASS 声称当前评分审计已完成。
- [落地检查](D:/VerseShellLive/node-dev-20261008/evidence/check-landing.json)：刷新远端后检查 `origin/master`，44 条历史发现，exit 1；本批未创建提交、合并或改写历史。仓库本地旧版 CLI 不含该命令，此只读检查使用已安装的新版 CLI，森林写入仍使用仓库本地 CLI。
- [改动边界核验](D:/VerseShellLive/node-dev-20261008/evidence/change-boundary.json)：工作区既有改动及暂存区未被覆盖；首轮合并文件摘要保持一致。
- [本批精确 diff](D:/VerseShellLive/node-dev-20261008/implementation.diff) 与 [逐文件摘要](D:/VerseShellLive/node-dev-20261008/change-manifest.json)：相对于会话开始时的脏工作区基线，不包含先前改动。

## 待闭合范围

TF-0128～TF-0131 的工程实现及本机回归不自动关闭节点。产品门禁由 TF-0140 承接；TF-0132 的开发集停止行为、TF-0133/0134 的收尾和存储保护、TF-0135～0139 的其余证据审计、TF-0141 的逐项落地核对以及 TF-0112/0114/0115/0120～0123 的正式研究范围仍分别保留。

新源码、工具 schema、描述和执行方式需要新的冻结身份；旧轮不能拼接补跑以获得通过。
