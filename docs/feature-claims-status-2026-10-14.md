# 功能宣称正收益定位：agent-shell 信息层（2026-10-14）

理念依据见 [AGENTS.md](../AGENTS.md)：VerseShell 是子模块，**每个功能宣称只要有可复现的正收益即可**，
不追求对外发表级的重复研究。

本文只覆盖 **agent-shell 信息层**这一批宣称（观察层/失败信封/运行时边界），
与 `feature-claims-status-2026-10-12.md`（`eval/evidence.json` 的 C1–C37）不是同一批。

## 一句话结论

- **成功率：未证明正收益。** 5 轮 L4 合并 100 组配对，配对差 +2.0pp、95% CI [-6.3, +10.3]、p=0.815。
  该区间跨过 0，**结论已冻结，不再为它跑长周期采集**（理由见 §A）。
- **信息质量：9 项可复现正收益**，全部是确定性不变量，每项都有一条秒级检查命令（见 §B）。

## A. 成功率宣称：未证明正收益（为何不再跑）

| 轮次 | ae / 预算 | A | A prime | D | D - A prime |
|---|---|---:|---:|---:|---:|
| l4-slim-r3 | afe227ca 32c/600s | 16 | 15 | 16 | +5pp |
| l4-envelope-r4 | 12b427a9 32c/600s | 15 | 15 | 14 | -5pp |
| l4-budget48-r5 | 12b427a9 48c/900s | 12 | 15 | 16 | +5pp |
| l4-lean-r6 | lean 48c/900s | 19 | 13 | 14 | +5pp |
| l4-statedir-r7 | r7 48c/900s | 16 | 16 | 16 | 0pp |

合并 5 轮 100 组配对（D 独赢 10 / A prime 独赢 8）：

```
paired diff = +2.0 pp     95% CI = [-6.3, +10.3] pp     exact two-sided p = 0.815
```

**成本核算**：按当前不一致率（18/100），要把区间压到 ±5pp 需约 **277 组配对**，
即约 **14 轮 L4 ≈ 42 小时**。而观测到的效应量级是"净 +1 题"。
结论：**用 42 小时去判定 ±1 题量级的效应，代价与结论价值不成比例**，且与 AGENTS.md 的
"不要求大样本重复研究"冲突。因此该宣称维持"未证明正收益"，不再追加轮次。

单轮成本参考（r7 实测）：60 格、cell 执行合计 107.6 min（均值 108s / 中位 52s），
其中 4 个慢格占 33%；串行 + 内存闸门 + sandbox 建销使整体墙钟约 3 小时。

## B. 信息质量：可复现正收益（每项附检查）

| # | 宣称 | 可复现检查 | 观测 |
|---|---|---|---|
| 1 | 失败信封带 agent 可读分类与可执行 recourse | `cargo test --lib failure_recourse` | `failure_recourse_replays_the_real_command`、`failure_recourse_has_no_fabricated_commands` 均通过；recourse 回放真实 argv，无占位命令 |
| 2 | 诊断消息有上界（不再产生 KB 级单条） | `cargo test --lib diagnostic_message_is_clamped` | 240 字符上限；r5 语料里单条 `strings` 行曾是 11,886 字符、占成功观察 12.5% |
| 3 | 空流不携带九字段元数据 | `cargo test --lib empty_stream_serializes_to_status_only` | 空流由 `{status,encoding,decoding_lossy}` 表示；r7 实测 stderr 由 9 键降到 3 键 |
| 4 | 成功流只发有信息量的字段 | `cargo test --lib successful_stream_omits_default_metadata` | 默认值不再重复发送；实测 0 条冗余 `returned_bytes` |
| 5 | 截断流仍保留尺寸/句柄（可恢复性不丢） | `cargo test --lib truncated_stream_keeps_size_metadata` | `raw_bytes`/`omitted_bytes`/`artifact` 在真正省略时保留 |
| 6 | 运行时状态不落在 agent 可见工作区 | `cargo test --lib state_dir_override` + microVM 探针 | 设 `AETHER_STATE_DIR` 后 `ls -A /workspace` 为空；默认路径不变 |
| 7 | 控制面变量不泄漏给任务命令 | `cargo test --lib control_plane` | 同一 microVM A/B：改前 6 个 `AETHER_*`/`AE_*`，改后 **0**，PATH/HOME 完好 |
| 8 | 观察体积：成功路径瘦身 | 见 §C 的前后对照 | 成功观察组成：正文 57.8% / stream 元数据 25.6% / meta 9.3% / envelope 7.3% |
| 9 | ae 二进制不在沙箱 PATH 上 | microVM 探针：`command -v ae` 与 `ls /usr/local/bin` 均查不到 | 安装到 `/opt/verseshell/ae` 并绝对路径调用；contract 校验仍通过 |

契约回归（全绿，均为秒级）：

```
cargo test --lib                                  # 167 passed
cargo test --test operation_protocol_tests        # 9 passed
cargo test --test integration_tests               # 53 passed
cargo test --test aci_1_0_ops_tests               # 13 passed
cargo test --test aci_1_0_closed_loop_acceptance  # 4 passed
```

## C. 本轮修掉的缺陷（含前后数值）

| 缺陷 | 改前 | 改后 | 依据 |
|---|---|---|---|
| 单条诊断无上界 | 11,886 字符 / 占成功观察 12.5%（r5） | ≤240 字符 | r5 语料离线归因 + 单测 |
| 空流仍发九字段 | 264/272 成功观察的 stderr 是 `empty` 却全字段 | 3 键 | r6 语料统计 |
| 成功流发默认值 | stream 元数据占成功观察 25.6% | 只发有信息量字段 | r6 语料统计 |
| 运行时状态泄漏到工作区 | 19.7% 的 D 调用在侦察自己（17/20 题） | 2/20 题（仅主动搜索才找到） | r6 对 r7 同口径统计 |
| 控制面变量泄漏 | `env` 暴露 6 个 `AETHER_*`/`AE_*`（r7 有 9 条观察命中） | 0 | microVM A/B 探针 |
| 占位式 recourse 命令 | `echo retry-with-larger-timeout` 等 3 处 | 回放真实 argv | 语料里 20 条 suggested_next 被照抄执行 0 条 |

## D. 与旧文档的关系

- `feature-claims-status-2026-10-12.md`：`eval/evidence.json` 的 C1–C37 定位，仍然有效，本文不覆盖它。
- `docs/acceptance-criteria.md` / `docs/claims-and-evidence.md`：面向对外发表的严格机制，
  **仅当用户明确要求发表/发布时才启用**。
- L4 各轮原始记录：`docs/agent-shell-l4-*.md`、`docs/agent-shell-lean-envelope-r6-*`、
  `docs/agent-shell-state-isolation-r7-*`、`docs/agent-shell-heavy-tail-env-leak-*`。

## E. 诚实边界

- 成功率结论基于 5 轮单 seed 汇总（每轮 20 题 × 3 臂）；区间宽（±8pp），故表述为"未证明正收益"，
  不是"证明无收益"。
- §B 的 8 项都是确定性不变量或单次探针结果，不依赖模型随机性，因此单次即可复现。
- 成功率之外的成本结论：D 的 observation token 仍是 raw 臂的 1.7-2.3 倍，效率门槛（-20%）未达标。
- `/usr/local/bin/ae` 的同类泄漏已修（见 §B 第 9 项），本轮仅用确定性探针验证，未跑 L4 r8。
