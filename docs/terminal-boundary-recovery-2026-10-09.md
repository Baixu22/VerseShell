# 终止边界恢复收尾（2026-10-09）

## 范围

开工为 **141 节点、114 done、27 open，411 项脏改动**。本轮推进 TF-0122 / TF-0133 / TF-0134，只登记新证据；不改变节点状态或进度。补丁以 D 盘 `original/` 的两份真实脏基线为准，**不是 HEAD**；未对全部 411 项逐字节比对。

## 三处根因与修复

1. runner 最后一格完成或全部格来自 checkpoint 时绕过 STOP/磁盘检查；round 最后 shard/merge 后也可能错报完成。现各自在终止边界复用本地 `pause_at_boundary`：保留已提交格、返回 exit 75；全局 STOP 必须明确 ack，恢复后同身份零新调用。runner 自身 `.stop` 可由 `--resume-paused` 归档。**同身份恢复仅指同一新版内部**。
2. round 匹配已有 `collection.json` 时仍直接覆盖，新建也非原子。现匹配时原 bytes 不写；新建复用 `atomic_json`。在真实 `os.replace` 提交点注入 ENOSPC，验证临时文件清理、无部分目标、不 dispatch。
3. `run_bounded` 先 Close Job 异步终止；随后 `kill()` 抛 OSError 会跳过同一 try 中的 `communicate()`，造成真实 WinError 32 日志占用。现 kill 与 wait/drain 分离，kill 失败仍执行 `communicate(timeout=2)`，保留原始异常。确定性 fake 进程用例及原失败用例 20 次 suite 均通过。

## 验证记录（保留失败回执）

| 阶段 | 结果 | 证据 |
|---|---|---|
| 基线 | 68/68，六组 exit 0 | [live_control](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_live_control.stderr.log) / [live_recovery](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_live_recovery.stderr.log) / [merge_durability](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_merge_durability.stderr.log) / [live_cli_contract](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_live_cli_contract.stderr.log) / [partial_live_merge](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_partial_live_merge.stderr.log) / [live_preflight](D:/VerseShellLive/tf-recovery-20261009-01a11efe/baseline-tests/test_live_preflight.stderr.log) |
| 原五项 RED | 5 tests，15 个 subTest 失败，exit 1 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/regression-tests/stderr.log) |
| 修复后原五项 | 5/5，exit 0 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification/original-five.stderr.log) |
| 首次全量 | 407 tests，errors=1，skipped=5，exit 1 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification/all-offline.stderr.log) |
| 进程清理确定性 RED | 10 tests，1 failure，exit 1 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification/process-cleanup-red.stderr.log) |
| 最终新增回归 | 10/10，errors=0，skips=0，exit 0 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/boundary-ten.stderr.log) |
| 原失败用例连续 suite | 20/20，errors=0，skips=0，exit 0 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/repeat-twenty.stderr.log) |
| 最终完整离线 Python | 408 tests，errors=0，skips=0，exit 0；131.797 秒 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/all-offline.stderr.log) |
| runner --help | exit 0 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/runner-help.stdout.log) |
| round --help | exit 0 | [原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/round-help.stdout.log) |

全量只在相应验证阶段各执行一次，未用 skip 或忽略清理异常掩盖失败。最终两个源码与新测试格式检查无诊断；未跟踪新文件的 `--no-index --check` exit 1 表示相对空文件存在差异。详见 [格式检查结果](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/new-test-diff.result.json)。最终残留扫描无匹配的相关进程，140 个文件独占读取无失败，仅保留 node 编译缓存：[检查范围与结果](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/residual-check.json)。

## 二进制与验收边界

复用现有 `C:/Users/27933/Desktop/verseshell/verseshell/target/debug/ae.exe`，按相同字节复制到 `D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/candidate/debug/ae.exe`，并设置 `CARGO_TARGET_DIR` / `ACI_TEST_AE`。原件、副本及测试后 SHA256 一致：`8d72549e09b1c87b3bfd7aaaefb6cab5115983c462802f71c56e427633e92044`；**不是从当前 Rust 重建**。[候选凭证](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/candidate.json)。

未跑 Rust 全量、完整 readiness、claim_gate，未调用被测模型 API。不宣称正式采集、研究或产品验收。**源码变化要求新的冻结与 readiness，不能把旧 tag 证据升级为新版证据。**

子代理使用 Astra low（无独立小模型可用，none 提供方不支持）；不声明实际费用降低。

## 交付与治理

[精确补丁](D:/VerseShellLive/tf-recovery-20261009-01a11efe/implementation.diff) 包含两源码、新测试、本文及 repo 提案；[变更清单](D:/VerseShellLive/tf-recovery-20261009-01a11efe/change-manifest.json) 记录限定范围 SHA、index 与 pre-edit-manifest 的对比、HEAD 和 CLI 回执。`proposals/TFP-terminal-boundary-recovery-2026-10-09.json` 只追加三个节点的 evidence/source_sessions，完整保留旧数组；仅 proposal-save 并 validate，**不 apply、不改状态/进度、不 export**。保存前后 CLI `list --json` 用于验证全部节点内容相同。
