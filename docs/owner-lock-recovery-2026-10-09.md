# 所有者锁恢复收尾（2026-10-09）

## 范围与修复

开工 HEAD `a8d4c56`，415 项脏改动；当前 CLI 复核 **141 节点、114 done、27 open**。本轮只改一个生产文件和新增一个测试文件；精确补丁以 `original/` 中 SHA `28f0b58391e8dd303e8719c9f3c548758d0cc2f29ce0739b598674b6b15f0d30` 的真实脏基线为准，**不是 HEAD**。生产文件净增 23 行；未对全部 415 项逐字节核验。

- 原 `RunStatus.__enter__` 的读 PID → 归档旧锁 → O_EXCL 创建存在竞态：A 可把 B 的新锁当作旧锁移动，导致多 owner；PID 无法确认时也不能把活 owner 的锁当作可回收记录。
- 现持有期使用原生 `.guard` 文件锁（Windows msvcrt，POSIX flock）。**guard 路径必须长期保留，避免不同 inode 竞态；其存在不等于有活 owner。** 旧 `.lock` JSON、旧锁归档和状态协议保留。
- 中间实现直接覆盖实例句柄，同实例重入会丢失外层互斥，并在退出时发生 `None.close`。最终以局部临时句柄持有本次尝试，**仅成功进入后绑定实例**；失败/重入只关闭本次局部句柄。回归在 `pid_alive=False` 下验证另一实例仍被拒绝，不能只修复退出症状。

## 原始验证链

| 阶段 | tests | failures / errors / skips | exit | 证据 |
|---|---:|---|---|---|
| 四组基线 | 51 | 0 / 0 / 0 | 四组均 0 | [7 项](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/baseline/test_remaining_node_boundaries.stderr.log) / [19 项](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/baseline/test_live_recovery.stderr.log) / [15 项](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/baseline/test_live_control.stderr.log) / [10 项](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/baseline/test_live_boundary_recovery.stderr.log) |
| 初始旧实现 RED | 3 | 2 / 0 / 0 | 1 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/regression-red/stderr.log) |
| 原三项 / 观察范围问题 | 3 | 0 / 1 / 0 | 1 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification/original-three.stderr.log) |
| 同实例重入 / 中间实现 RED | 4 | 0 / 1 / 0 | 1 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/regression-reentry-red/reentry-four.stderr.log) |
| 最终四项 | 4 | 0 / 0 / 0 | 0 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/final-four.stderr.log) |
| 四用例 × 十轮 | 40 | 0 / 0 / 0 | 0 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/repeat-forty.stderr.log) |
| 本轮唯一完整离线 Python | 412 | 0 / 0 / 0 | 0 | [原始日志](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/all-offline.stderr.log) |
| 两个 CLI --help | — | — | 均 0 | [runner](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/runner-help.stdout.log) / [round](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/round-help.stdout.log) |

观察范围问题是原测试遍历读取了字节锁定的 guard，不属于旧锁归档证据；原始失败未抹去。测试后来只读取 `.lock.abandoned-*`，仍比较完整旧锁 bytes，并把最多一位 owner 强化为恰好一位。重入中间 RED 保留了未拒绝另一实例、`None.close` 及 ResourceWarning 的原始错误链。

本轮在上述局部验证后才首次执行全量，**只执行一次，实际 412 项**，耗时 **202.219 秒**。最终 4 / 40 / 412 均无 ResourceWarning、无 skip；native 用例实际执行。owner 测试创建的 12 个子进程均精确终止并 wait/drain（预期子进程 exit 1，测试进程 exit 0）。[最终汇总](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/summary.json) / [子进程原始输出](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/repeat-forty.stdout.log) / [残留检查](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/verification-final/residual-check.json)。检查时本轮目录 533 个文件独占打开并读取首字节，无失败、无匹配的相关残留进程，最终临时目录为空。

上一轮的[完整测试失败原始日志](D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification/all-offline.stderr.log)仍原处保留，不混入本轮全量计数；本轮所有 RED、观察范围问题和历史包均保留，未删除。

## 还剩哪些（覆盖全部 27 open）

以下为当前森林分组，不将 open 等同于功能尚未编写；状态、进度与验收阈值均未改变。

| 组 | 剩余范围 | 数量 | 节点 |
|---|---|---:|---|
| 1 | 完整独立重复与跑间不确定性 | 1 | TF-0112 |
| 2 | 独立困难/大观察任务、来源和留出 | 3 | TF-0114、TF-0115、TF-0123 |
| 3 | 真实端点预算/停止试点及预注册 | 3 | TF-0120、TF-0121、TF-0132 |
| 4 | 工程新冻结接入、恢复/成本/评分/异常验收（并非功能全未写） | 12 | TF-0122、TF-0128、TF-0129、TF-0130、TF-0131、TF-0133、TF-0134、TF-0135、TF-0136、TF-0137、TF-0138、TF-0139 |
| 5 | 历史声明、主仓库可达性、上层收口 | 8 | TF-0093、TF-0094、TF-0124、TF-0125、TF-0126、TF-0127、TF-0140、TF-0141 |

[全部原字段 inventory/open-nodes.md](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/inventory/open-nodes.md)；本次 CLI 的 [list](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/closeout/nodes-before.stdout.json) / [todo](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/closeout/todo-current.stdout.json) 已复核上述 27 ID 完整、无重复覆盖。部分 next_action 历史滞后：例如 [merge_live_runs.py:99](C:/Users/27933/Desktop/verseshell/verseshell/bench/aci/runners/merge_live_runs.py#L99) 已调用 `row_class`（第 40 行导入），不应照旧文字重复实现。后续优先**新冻结 readiness 与 TF-0121 预注册**，而非重写已存在接口；森林字段本身不构成实现或关闭验收。

## 端点、候选与验收边界

只读核对的[已保存端点探针](D:/VerseShellLive/landing-readiness-20261009-01a11c1d/evidence/endpoint-probe.json)记录 `pass=false`、`records[0].attempts[0].status=403`、`real_name_required`、`requested_model=step-5-preview`。**这是历史保存结果，本轮未重试，不能据此声称当前服务仍返回 403。**

复用现有 D 盘候选 `D:/VerseShellLive/tf-recovery-20261009-01a11efe/verification-final/candidate/debug/ae.exe`，SHA256 为 `8d72549e09b1c87b3bfd7aaaefb6cab5115983c462802f71c56e427633e92044`；**非从当前 Rust 重建**。[候选引用凭证](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/closeout/candidate-reference.json)。本轮未调用研究模型 API，未跑 readiness、claim_gate 或 Rust 全量。上述为 **Windows 实测，POSIX 未实测**；不宣称正式采集、研究或产品验收。

旧冻结采集未迁移，新代码仍需新冻结/readiness；不能升级旧 tag 证据。本轮仅向 TF-0122 / TF-0133 / TF-0134 追加证据来源提案，完整保留旧数组，**只 proposal-save 与 validate，不 apply/export，不改节点状态/进度/阈值**。

[精确补丁](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/implementation.diff) 包含一个生产文件、一个新测试、本文和 repo 提案；[change-manifest](D:/VerseShellLive/tf-owner-lock-20261009-01a11efe/change-manifest.json) 记录前后 SHA、HEAD/index、前轮 runner/round 保留状态及 CLI 回执。上一轮提案未替换。
