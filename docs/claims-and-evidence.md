# 声明-证据矩阵（claims-and-evidence）

> task-forest 节点：TF-0007（步骤6）。上游输入：`eval/manifest.json`（步骤5）、mock bench 结果、README/docs 里的对外主张。
> 机器读取方：`tools/claim_gate.py` → `eval/evidence.json`。**门槛数字以本文件为准**，改门槛必须同时改两处。
> 纪律：任何对外数字（README / docs / 演示）必须能在本文件找到一行声明，且该行带 `门槛 / 复现命令 / source / 失效边界 / 状态`。未过线或未证实的声明**不得**以肯定口吻写进 README。

## 1. 状态定义

| 状态 | 含义 | 允许的措辞 |
|------|------|-----------|
| 已证实 | 确定性指标，仓库内一条命令可复现，样本来源在仓库内 | 可用肯定句，并注明命令 |
| 实验室 | 只在受控/模拟条件下成立（如 mock 轨迹、单机小样本），未在真实模型上复测 | 必须写明「mock/受控条件下」 |
| 未证实 | 无确定性指标或未测量 | 只能写成待验证/未知，不得进 README 主张 |

## 2. 门禁与复现入口

```bash
# 机器门禁：重算指标 + 跑测试 + 写 eval/evidence.json，不过线 exit code != 0
python tools/claim_gate.py

# 只复用已有指标、跳过 cargo test（C6/C7 记为 STALE 并判失败）
python tools/claim_gate.py --skip-tests

# 单项复现入口
python tools/validate_manifest.py                        # 样本来源路径存在性（步骤5）
cargo run --example eval_metrics -- --out eval/metrics.json   # 诊断完备率 + 一步恢复探针 + 剧本探针
python bench/aci/runners/run_suite.py --mode mock        # 重新生成 bench/aci/results/latest.json（C1/C2 产物）
python tools/jev_obs_judge.py                            # L3 观察质检报告（不进 C1–C13 门禁，但是 C12 的产物之一）
cargo test --test process_lifecycle_tests                # C8：进程生命周期契约（Windows）
cargo run --example compact_ratio -- --out eval/compact_ratio.json   # C9：compact 编码 vs JSON
python tools/readme_claims_check.py                      # C10：README 示例、实现数字与跨 shell 表
python tools/cross_shell_bench.py                        # C11：跨 shell 墙钟对比（写 eval/cross_shell.json）
# C12 会在上面五份产物缺少指纹或指纹过期时失败；按提示重跑对应 runner 即可
# C13：live A/D 对比（真实模型，凭据只经环境变量）
python bench/aci/runners/live_agent_loop.py --full --model <model> --base-url <endpoint> --max-turns 8
python bench/aci/runners/merge_live_runs.py --out bench/aci/results/latest_live.json <per-seed runs...>
# C14：批量读取信封的固定轨迹复算（确定性，无 API 调用）
python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json
# C15：D 的额外 token 从哪来（逐 op 分解，确定性，无 API 调用）
python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json
```

## 3. 声明表（C1–C15）

### C1 · 观察 token 比（mock bench）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在 ACI-Bench mock 任务集上，条件 D（verseshell_aci）的单任务平均 observation tokens 不高于条件 A（raw_shell）的一半 |
| 门槛数字 | `token_ratio_D_over_A <= 0.50` |
| 复现命令 | `python tools/claim_gate.py`（数据来源 `bench/aci/results/latest.json`，由 `python bench/aci/runners/run_suite.py --mode mock` 生成） |
| source | `bench/aci/results/latest.json`、`bench/aci/runners/run_suite.py`、`bench/aci/tasks/*.json` |
| 样本量 / 日期 | mock，10 任务/条件，seed 42，task_set_version 1.1.0，数据生成于 2026-07-27 |
| 最近实测 | 0.106（PASS） |
| 失效边界 | **只在 mock 轨迹上成立**：mock 的 A 条件固定发全量日志、D 条件固定走 reducer，比值由脚本内置轨迹决定，不是真实模型实测；换成 live 模型必须重跑 `--mode live` 并重新记录，不得沿用此数字 |
| 状态 | 实验室 |

### C2 · 工具调用次数比（mock bench）

| 维度 | 内容 |
|------|------|
| 主张原文 | 同一 mock 任务集上，条件 D 的平均 tool_calls 不高于条件 A 的 0.70 倍 |
| 门槛数字 | `tool_call_ratio_D_over_A <= 0.70`（与 `docs/v1.1-freeze.md` 的对外目标一致） |
| 复现命令 | `python tools/claim_gate.py`（同 C1 的数据来源） |
| source | `bench/aci/results/latest.json`、`bench/aci/runners/run_suite.py` |
| 样本量 / 日期 | mock，10 任务/条件，seed 42，2026-07-27 |
| 最近实测 | 0.55（PASS） |
| 失效边界 | 同 C1：mock 轨迹决定，非真实模型；门槛已与 `docs/v1.1-freeze.md` 的 ≤0.7 tool calls 对齐（见 §5） |
| 状态 | 实验室 |

### C3 · 失败诊断 expected/found 完备率

| 维度 | 内容 |
|------|------|
| 主张原文 | 对「输出里本来就含 expected/found 对」的失败类别（pytest assert 断言、cargo E0308 类型不匹配），reducer 抽出的 error 诊断全部带上 expected 与 found |
| 门槛数字 | `完备率 >= 0.90`（范围：`eval/manifest.json` 中 `expect.diff_class=true` 的条目） |
| 复现命令 | `cargo run --example eval_metrics -- --out eval/metrics.json`，再 `python tools/claim_gate.py` |
| source | `eval/manifest.json`、`examples/eval_metrics.rs`、`src/reducers/pytest.rs`、`src/reducers/cargo.rs`、样本文件 `tests/fixtures/reducers/*` |
| 样本量 / 日期 | 4 个 error 诊断（2 个 fixture + 2 个对抗样本），确定性复算 |
| 最近实测 | 1.00（4/4，PASS） |
| 失效边界 | 分母是 `diff_class=true` 的条目；git `fatal:`、npm ENOENT、panic 等失败类别本身不含 expected/found 对，**不计入**本声明（它们只保证 path/line/code 级别字段）。新增失败类别时必须先决定是否进分母 |
| 状态 | 已证实 |

### C4 · 一步恢复结构化字段

| 维度 | 内容 |
|------|------|
| 主张原文 | 编辑失败后，`E_STALE_HASH` 返回 `data.actual_hash` / `data.expected_hash`，`E_AMBIGUOUS` 返回结构化 `data.matches[]`（line/offset/snippet），且照抄失败自带的 `suggested_next` 一次即可重试成功 |
| 门槛数字 | `结构化检查通过率 == 1.00`（5 项检查全过） |
| 复现命令 | `cargo run --example eval_metrics -- --out eval/metrics.json`，再 `python tools/claim_gate.py` |
| source | `src/ops/file.rs`（replace_exact）、`src/ops/common.rs`、`examples/eval_metrics.rs`、`tests/aci_1_0_ops_tests.rs` |
| 样本量 / 日期 | 2 个探针（stale_hash / ambiguous），确定性复算 |
| 最近实测 | 1.00（5/5，PASS） |
| 失效边界 | 探针只覆盖 `file.replace_exact` 两个错误码；`apply_patch` / `edit_range` 的同类错误码未纳入，需扩面时先加探针再改门槛 |
| 状态 | 已证实 |

### C5 · 学习成本可被 coding agent 吸收

| 维度 | 内容 |
|------|------|
| 主张原文 | 一个 coding agent 只读 quickstart 就能正确使用主合同（typed op + 观察信封），无需额外人工辅导 |
| 门槛数字 | 无（暂无确定性指标） |
| 复现命令 | 无 |
| source | `docs/quickstart/`、`README.md`、`docs/1.0-aci.md` |
| 样本量 / 日期 | 未测量 |
| 最近实测 | — |
| 失效边界 | 这是主观声明，`tools/claim_gate.py` **不设门槛**（`pass: null`），只登记状态；若要用它，需先定义可复现指标（例如固定任务集上首次成功率） |
| 状态 | 未证实 |

### C6 · 可撤恢复闭环（trash → restore）

| 维度 | 内容 |
|------|------|
| 主张原文 | agent 模式删除走 trash，返回 `restore_token`，可用 `tx.restore` 还原，且跨进程重启仍可还原 |
| 门槛数字 | 该测试文件全部用例通过 |
| 复现命令 | `cargo test --test aci_1_0_closed_loop_acceptance` |
| source | `tests/aci_1_0_closed_loop_acceptance.rs`、`src/ops/trash.rs`、`src/ops/tx_ops.rs` |
| 样本量 / 日期 | 4 个用例（1 个 suite） |
| 最近实测 | PASS（4 passed / 0 failed） |
| 失效边界 | 只覆盖本机文件系统与单工作区；网络盘/权限拒绝场景未覆盖 |
| 状态 | 已证实 |

### C7 · 不回归门禁（全量测试）

| 维度 | 内容 |
|------|------|
| 主张原文 | 仓库全量测试套件保持绿色，新增改动不得引入回归 |
| 门槛数字 | `cargo test` 全部通过 |
| 复现命令 | `cargo test` |
| source | `Cargo.toml`、`tests/`、`src/` |
| 样本量 / 日期 | 全量（16 个 test binary） |
| 最近实测 | PASS（277 passed / 0 failed / 1 ignored） |
| 失效边界 | 本机平台（Windows）与工具链下通过；不覆盖其它平台与网络/真实模型依赖的用例。2026-09-22 修过一处环境相关失败：`tests/process_lifecycle_tests.rs` 的 `full_environment` 曾把 cmd 的隐藏变量（`=C:` / `=ExitCode`）原样转发，被 `E_PROCESS_ENV` 正确拒绝 |
| 状态 | 已证实 |

### C8 · 进程生命周期契约（typed `process.*`）

| 维度 | 内容 |
|------|------|
| 主张原文 | 长驻进程的五个 typed op 遵守一套可机检的契约：归属回声校验（错误 owner → `E_PROCESS_OWNER`）、输出 cursor 单调不回退、`kill` 幂等且不覆盖首个 `termination_reason`、超时终止整棵进程树（父子都不残留）、Windows ConPTY 可用、重启对账把 `running` 记为 `lost` 且不复活进程 |
| 门槛数字 | `cargo test --test process_lifecycle_tests` 全部用例通过（`>= 1.00`） |
| 复现命令 | `cargo test --test process_lifecycle_tests`，再 `python tools/claim_gate.py` |
| source | `tests/process_lifecycle_tests.rs`、`src/process_lifecycle.rs`、`src/process_lifecycle_windows.rs`、`src/ops/process_ops.rs` |
| 样本量 / 日期 | 3 个用例（1 个 test binary，整文件 `#![cfg(windows)]`），确定性复算 |
| 最近实测 | PASS（3 passed / 0 failed） |
| 失效边界 | **仅 Windows**：测试文件整体 `#![cfg(windows)]`，Unix 的进程组终止路径没有用例覆盖；非 Windows 上 `pty: true` 返回 `E_PROCESS_PTY_UNSUPPORTED`。不覆盖 `max_memory_mb` / `max_processes` 在 lifecycle 路径的语义（该路径静默忽略），也不覆盖网络盘/权限拒绝场景 |
| 状态 | 已证实 |

### C9 · compact 编码 vs JSON（分层口径）

| 维度 | 内容 |
|------|------|
| 主张原文 | compact 编码是无损的；在**小响应信封**（重复键名占比高，JSON ≤300 字节）上把体积降到 JSON 的 60% 以下（节省 ≥40%）。**不**主张它在观察载荷或嵌套大载荷上节省——实测这两类反而略大于 JSON |
| 门槛数字 | 小响应信封节省 `>= 0.40`（取 byte 与 token 代理中更小的一侧）**且** 全部观察载荷 round-trip 通过 |
| 复现命令 | `cargo run --example compact_ratio -- --out eval/compact_ratio.json`，再 `python tools/claim_gate.py` |
| source | `examples/compact_ratio.rs`、`src/compact.rs`、`src/server.rs`、`eval/compact_ratio.json` |
| 样本量 / 日期 | 5 个观察载荷（1 个真实 `ops.list` 观察 + 4 个对抗 fixture 的 reducer 观察）+ 2 个响应信封，确定性复算 |
| 最近实测 | 小响应信封 42.4%（PASS）；观察载荷合计 −3.1%（compact 略大，最差 −4.4%）；嵌套大响应 −2.4%；全部 round-trip 通过 |
| 失效边界 | 字节数与 `ceil(len/4)` 是 token 代理，不是真实 tokenizer；样本是仓库内 fixture 加一次真实 `ops.list`，不代表真实模型负载；响应行没有解码器，未做 round-trip；只覆盖 `--format compact` 的**编码层**，Observation Budget 是另一层（见 C1） |
| 状态 | 已证实（含负向结论：大载荷不节省） |

### C10 · 文档承诺可执行 / 实现类数字与源码一致

| 维度 | 内容 |
|------|------|
| 主张原文 | README 里登记的可执行示例都能跑出文档写的输出；README 里关于代码库的实现类数字都等于其源码真值 |
| 门槛数字 | `python tools/readme_claims_check.py` 全部通过（7 个示例 + 5 个数字 = 12 项） |
| 复现命令 | `python tools/readme_claims_check.py`，再 `python tools/claim_gate.py` |
| source | `README.md`、`tools/readme_claims_check.py`、`tests/integration_tests.rs`、`src/runtime.rs`、`src/main.rs`、`src/artifact.rs`、`Cargo.toml` |
| 样本量 / 日期 | 12 项检查（7 示例 + 5 数字），确定性复算 |
| 最近实测 | 12/12 PASS（2026-09-22）。修复前 9/12：`reduce`、`reverse` 两个文档示例跑不通；README 的「4 Criterion 套件 / 50 integration tests」与源码真值（5 / 52）不一致 |
| 失效边界 | 只覆盖脚本内**显式登记**的条目，不覆盖自由散文；README 中未登记的实现类数字（例如「28-arm match」「~50 builtins」「26 modules」）需先加进 registry 才会被检查 |
| 状态 | 已证实 |

### C11 · 跨 shell 墙钟对比（本机）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在同一台机器上，用各 shell 最廉价的等价命令各跑 20 次（丢弃 3 次预热、丢弃 stdout/stderr）后，VerseShell 五项常用操作的中位耗时都不高于 PowerShell 的 0.5 倍 |
| 门槛数字 | `worst_ratio_ae_over_pwsh <= 0.50` 且所有命令退出码为 0 |
| 复现命令 | `python tools/cross_shell_bench.py`（写 `eval/cross_shell.json`），再 `python tools/claim_gate.py` |
| source | `tools/cross_shell_bench.py`、`eval/cross_shell.json`、`README.md`、`bench_final.sh` |
| 样本量 / 日期 | 5 项操作 × 3 shell（Bash 无 Disk 等价命令，故 4 项）× 20 次 + 3 次预热；2026-09-23 |
| 最近实测 | worst **0.2207**（CPU info，4.5x）；Disk 0.0313（31.9x）、List dir 0.0427（23.4x）、Read file 0.0766（13.1x）、Pipeline 1K 0.0660（15.2x）；`all_commands_ok=true`。2026-09-23 重测（改 `file.read_many` 信封后按 C12 重跑；一次在 live 作业并行时测得的 0.2141 已作废，本行是空载复测）；上一次产物为 0.2484，README 表格已同步 |
| 失效边界 | 墙钟测量，含进程启动开销，只代表本机与当前工具链（AMD Ryzen 7 7745HX / Windows PowerShell 5.1 `-NoProfile` / Git Bash）；不测吞吐、内存、并发；门禁读的是**已存产物** `eval/cross_shell.json`，改动热路径后必须重跑 runner 才会更新（C12 会判陈旧）；每次重跑数字都会小幅漂移，README 表格必须与产物逐行一致（由 C10 检查）；README 里旧的 v0.5.1 数字（3.7x / 14.4x / …）已作废并被本声明取代 |
| 状态 | 已证实（本机单次测量） |

### C12 · 证据新鲜度（产物指纹）

| 维度 | 内容 |
|------|------|
| 主张原文 | 门禁依赖的六份已存测量（ACI-Bench mock 结果、live A/D 结果、L3 观察质检报告、跨 shell 基准、批量读取信封复算、exec token 分解）都记录了生成时被测代码面的 sha256 指纹，且该指纹与当前代码重算结果一致——也就是说这些数字描述的仍是当前实现，而不是两个月前的实现 |
| 门槛数字 | 六份产物的记录指纹与重算指纹全部一致（`>= 1.00`） |
| 复现命令 | `python tools/claim_gate.py`；重跑产物用 `python bench/aci/runners/run_suite.py --mode mock`、`python tools/jev_obs_judge.py`、`python tools/cross_shell_bench.py`、`python bench/aci/runners/live_agent_loop.py`（再 `merge_live_runs.py`）、`python tools/tf45_envelope_replay.py`、`python tools/exec_token_breakdown.py` |
| source | `bench/aci/results/latest.json`、`bench/aci/results/latest_live.json`、`eval/jev_obs_report.json`、`eval/cross_shell.json`、`eval/tf45_envelope_replay.json`、`eval/exec_token_breakdown.json`、`tools/claim_gate.py` |
| 样本量 / 日期 | 6 份产物；2026-09-23 |
| 最近实测 | 6/6 fresh（PASS）。引入本声明前的产物（如 2026-07-27 的 bench 结果）没有指纹字段，会被直接判失败 |
| 失效边界 | 只覆盖登记在 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 的六份产物；`live_ab_without_read_files.json` 是配对对照臂，按设计不进 C12（重跑时机由 C13 记录），但它是 `eval/exec_token_breakdown.json` 的输入，所以那份产物会随它一起更新。指纹是**文件内容哈希**，不含运行环境（OS / 工具链 / CPU），所以换机器重跑不会因环境不同被判陈旧——跨机器可比性仍受 C11 的边界限制；产物未记录指纹时判失败（fail-closed） |
| 状态 | 已证实 |

### C13 · live A/D 对比与 read_files A/B（真实模型）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在真实函数调用模型 `sn-glm-5-3-flash`（本地 OpenAI 兼容端点）上跑 ACI-Bench 全量 10 任务 × 2 条件 × 3 次重复（temperature=0，seeds 42/43/44），并做**同期 A/B**（同模型同 seeds，仅隐藏 `read_files` 工具）：①成功率 A 与 D 基本相同（0.60–0.63）；②D 的工具调用数与观察 token 仍都高于 A——有 `read_files` 时 D/A 工具比 **1.64**、token 比 **1.69**；③在本轮客户端（读算子返回 16 位紧凑摘要）下，新增 `file.read_many` 使 D 的工具调用数由 5.93 降到 **5.23**（−11.8%）、D/A 工具比由 1.93 降到 1.64，但观察 token 由 271.8 升到 **333.4**（+22.7%，一次读到更多内容），D/A token 比由 1.42 升到 1.69。**结论：批量读取确实减少步骤，但没有减少 token；ACI 在该模型与该任务集上仍比 raw shell 贵，但读取侧信封改小后 token 差距比上一轮小** |
| 门槛数字 | 无（中性/负向结论，只登记事实，不设通过门槛） |
| 复现命令 | with：`python bench/aci/runners/live_agent_loop.py --full --model sn-glm-5-3-flash --base-url <endpoint> --max-turns 8 --temperature 0 --seed <s>`；without：同命令再加 `--exclude-tools read_files`；各跑 seeds 42/43/44 后合并：`python bench/aci/runners/merge_live_runs.py --out <artifact> <per-seed runs...>`（任一行带 `api_error` 即 exit 2，拒绝合并） |
| source | `bench/aci/runners/live_agent_loop.py`、`bench/aci/runners/merge_live_runs.py`、`bench/aci/results/latest_live.json`（with，3 次合并）、`bench/aci/results/live_ab_without_read_files.json`（同期对照，3 次合并）、`bench/aci/results/tf45/with_seed*.json`、`bench/aci/results/tf45/without_seed*.json`（逐 seed 原始行）、`bench/aci/tasks/*.json` |
| 样本量 / 日期 | 10 任务 × 2 条件 × 3 seeds × 2 臂 = 120 行，`api_error` 0；2026-09-23 |
| 最近实测 | **本轮（紧凑摘要客户端）** 有 `read_files`：A success 0.6333 / tools 3.20 / obs_tok 197.4；D 0.60 / **5.23** / **333.4**（D/A 1.6354 / 1.6888）。无 `read_files`（同期对照）：A 0.60 / 3.07 / 191.1；D 0.60 / **5.93** / **271.8**（D/A 1.9348 / 1.4223）。`read_many` 在 24/30 次 D 运行中被采用。逐 seed 波动很大：with 臂 D/A 工具比 1.36/2.20/1.51、token 比 1.66/2.11/1.43。**上一轮（完整摘要客户端，已被本轮取代）**：有 `read_files` D 5.50 / 411.1（D/A 1.748 / 2.443）；对照 D 6.03 / 300.2（D/A 1.947 / 1.982） |
| 失效边界 | ①**单模型**（`sn-glm-5-3-flash`），不可外推；该模型曾被端点下架又恢复，说明端点会轮换模型，复测前必须先核对 `/v1/models`。②**名义确定性**：端点接受 `seed` 但不严格复现（同 seed 的 tool_call id 与 token 数仍不同），3 次重复给的是经验区间而非确定性复算——本轮 with 臂逐 seed 的 D/A 工具比在 1.36–2.20 之间。③**跨轮比较必须标注口径**：本轮与上一轮之间客户端投影变了（逐文件完整 `sha256` → 16 位紧凑摘要），且 A 侧代码完全未动而 obs_tok 从 168.6 漂到 197.4（+17%），所以「D/A token 比 2.44 → 1.69」**不能**全部归因于信封改动；信封的净效应由确定性复算给出（C14：读取调用 −22.1%），live 侧可对照的干净信号是 `read_many` 单次开销 175.6 → 135.6（−22.8%）。④观察 token 用 `len(text)//4` 估算，不是真实 tokenizer。⑤成功判定是任务自带的文件谓词，不要求真的跑测试（A 常常不跑测试也满足）。⑥本机 `tsc` 缺失、裸 `pytest` 在 Windows 上因 console-script 的 `sys.path` 行为失败（规范形式 `python -m pytest`），两条件同样受限；失败 exec 仍是 D 的最大单项开销。⑦**与 mock 的 C1/C2 不可混用**：mock 的 D 直接套 GOLDEN 补丁，0.106/0.55 是评分管线自检，不是能力测量。⑧上游会间歇性 500（`parse response failed`）：本轮 6 次运行 120 行全部 `api_error` 0，未触发补跑；合并脚本遇到即 exit 2，不会把故障平均成 0 工具/0 token。⑨**逐 op 分解纠正了一个直觉**：`exec.run` 确实是 D 的单项最大开销（50.4%），但它**不是** D 比 A 贵的原因——把 +144.0 tok/run 的差距分桶后 read +84.8（58.9%）、edit +24.8（17.2%）、exec +23.3（16.2%）、meta +3.0（2.1%）。详见 C15 |
| 状态 | 已证实（本机单模型、3 次重复 × 2 臂，中性/负向结论） |

### C14 · 批量读取信封（紧凑摘要 + 批量预算，固定轨迹复算）

| 维度 | 内容 |
|------|------|
| 主张原文 | 把 live 运行里模型**真实发出**的读取调用固定下来、用当前二进制重跑，并对**同一份**观察信封做两次投影（旧口径：逐文件完整 `sha256:<64 hex>`；新口径：16 位十六进制紧凑摘要，可直接当 `expected_hash` 前缀回传），模型可见的 observation tokens 下降；同时 `file.read_many` 新增的 `max_total_lines` 预算把最坏情况（8 个 300 行文件）限制在预算之内且仍可分页续读 |
| 门槛数字 | `token_savings >= 0.15`；且 `legacy_comparison_exact == true`、`budget.bounded == true`、`budget.pagination_roundtrip == true`、`coverage > 0` 必须同时成立 |
| 复现命令 | `python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json`，再 `python tools/claim_gate.py` |
| source | `tools/tf45_envelope_replay.py`、`bench/aci/runners/live_agent_loop.py`、`src/ops/file.rs`、`src/ops/common.rs`、`eval/tf45_envelope_replay.json` |
| 样本量 / 日期 | 37 次冻结读取调用（24 次 `file.read_many` + 13 次 `file.view`），其中 33 次可忠实复现；2026-09-23 |
| 最近实测 | 合计 **4738 → 3690 tokens（−22.1%）**；`file.read_many` 24/24 次复现、4176 → 3254（−22.1%）——其中「新口径」一侧 3254 与 live 实测的 read_many 合计**逐位相同**；`file.view` 9/13 次复现、562 → 436（−22.4%）。预算：默认 8×300 行 → 返回 240 行（上限 240），`max_total_lines=40` → 返回 40 行（上限 40）；分页：250 行文件按 window=100 逐页读回，3 页 250/250 行逐行一致。**排除的 4 次调用**是读 live 运行期自己产生的状态（`.ae/audit.log`、`ERR.txt`、`out/result.txt`），pristine fixture 无法重建，报告里逐条给出「复算值 vs live 记录值」。live 侧的独立印证：`read_many` 单次开销 175.6 → 135.6 tok（−22.8%，上一轮 vs 本轮），与复算的 −22.1% 一致 |
| 失效边界 | ①这是**客户端信封效应**，不是模型行为测量：调用集合被冻结，所以它说不出「模型会不会因此换别的调用」。②只有「stored live 那次运行所用的投影能复现其记录的 token 数」的调用才计入（本轮 `matched={'current': 33}`，`coverage=33/37`）；这条判据同时保证基线确实是模型当时看到的东西，并让工具在「改了客户端却没重跑 live」时直接判失败而不是悄悄给出跨口径比较。③`file.read_many` 24/24 全部精确匹配，且「新口径」合计与 live 实测合计相同，是最强的保真度交叉验证。④token 用 `len(text)//4` 估算，不是真实 tokenizer。⑤预算与分页那一半是结构性事实（返回行数 ≤ `max_total_lines`、分页可逐行复原），与模型无关，但**只在 `file.read_many` 上成立**；`file.view` / `file.read_range` 仍是单文件窗口。⑥本声明的数字**不能**与 C13 的 live D/A 比值相加或相减来解释：C13 的 D 侧同时含 `exec.run` 等非读取开销 |
| 状态 | 已证实 |

### C15 · D 的额外 token 从哪来（exec token 分解，TF-0058）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物做逐 op 分解（不调用 API）：①`exec.run` 占条件 D 的 observation token **50.4%**（5045/10001，168.2 tok/run，63.1 tok/次）；②其中 **80.1% 的 exec token 来自失败的命令**（42 次失败 @96.2 tok = 4042 tok，只占 52.5% 的调用）；③with/without `read_files` 的 exec 增量 +29.2 tok/run 拆成次数效应 46% / 单次效应 54% / 交互 5%，且增量全部来自失败命令多了 7 次（35→42），单次成功成本反而下降（30.6→26.4）；④**关键纠正**：`exec.run` 不是 D 比 A 贵的原因——+144.0 tok/run 的差距分桶为 read +84.8（58.9%）、edit +24.8（17.2%）、exec +23.3（16.2%）、meta +3.0（2.1%）；D 每个文件引用 48.0 tok（A 的 `type` 是 26.0），且读的文件引用数多约 1.6× |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_token_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_token_breakdown.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行（10 任务 × 3 seeds）/ 80 次 `exec.run`；对照臂 30 次 / 73 次；2026-09-23 |
| 最近实测 | with：D 333.37 tok/run，`exec.run` 80 次 / 5045 tok（50.4%，168.17/run，63.06/次），成功 38 次 @26.39、失败 42 次 @96.24。without：D 271.8 tok/run，`exec.run` 73 次 / 4169 tok（51.1%，138.97/run，57.11/次），成功 38 次 @30.55、失败 35 次 @85.94。差距分桶：read +84.77、edit +24.83、exec +23.33、meta +3.03。读取形状：D 37 次读取 / 3842 tok / 每次 2.16 个文件引用 / 每引用 48.02；A 40 次读取命令 / 1299 tok / 1.25 / 25.98 |
| 失效边界 | ①**纯诊断**，不是对外主张，也不能反过来当作「ACI 省 token」的证据。②A 侧分桶是**启发式**：按命令字符串关键词分成 build_or_test / read_file / write_or_mkdir / other，优先级 build > read > write；一条命令可能同时读和构建，残差进 other（本轮 other 仅 5 次 / 318 tok），所以 A 的桶是近似值。③A 的 trajectory 不记录单次命令成败（只有 D 记 `aci_ok`），因此无法对 A 做成功/失败拆分。④「每个文件引用」在 D 侧由 `file.read_many.paths` 精确计数、在 A 侧由 `type`/`cat` 出现次数近似，两者不是同一种计数单位。⑤token 仍是 `len(text)//4` 估算。⑥结论只对**本模型、本任务集、本轮 120 行**成立；换模型或换任务集必须重跑 |
| 状态 | 已证实（本机单模型、诊断性） |

## 4. 与 README 主张的对应关系

- README 若出现 C1/C2 类数字，必须写成「mock bench，10 任务/条件，seed 42」并指向 `eval/evidence.json`，不得写成真实模型实测。
- C9 是**分层**声明：可以说「小响应信封 ≥40% 节省（实测 42.4%）」，不得把它写成「compact 整体省 50–70%」或「观察载荷省一半」——后者实测为负。
- C5 未证实：README 不得出现「上手成本低」「零学习成本」这类肯定句。
- C10 是**兜底**声明：README 新增任何可执行示例或实现类数字时，先在 `tools/readme_claims_check.py` 的 registry 里加一条，否则它不受门禁保护。它也逐行校验 README 的跨 shell 表格与 `eval/cross_shell.json` 一致——重跑 `tools/cross_shell_bench.py` 后必须同步更新 README 表格。
- C11 是**本机**声明：README 的跨 shell 表格必须与 `eval/cross_shell.json` 的实测一致，不得写成跨机器保证；改动热路径后必须重跑 `tools/cross_shell_bench.py`。
- C12 是**证据新鲜度**声明：改动被测代码后先重跑对应 runner（`run_suite.py` / `jev_obs_judge.py` / `cross_shell_bench.py` / `live_agent_loop.py`）再跑门禁；产物缺少指纹时直接判失败（fail-closed），不允许用旧数字过门禁。
- C13 是 **live** 声明：引用真实模型结果时必须同时给出模型、端点、运行次数与方差边界；不得把 mock 的 C1/C2 数字写成真实模型实测，也不得用 live 的负向结论否定 mock 的管线自检作用（两者口径不同）。
- C14 是**信封**声明：它测的是观察面（同一信封两种投影的 token 差）与批量预算的硬上限，不是模型能力；引用时必须带上 `coverage`（哪些调用无法复现、为什么），不得把它写成「ACI 整体省 22%」或「D/A 比值已降到 X」。
- C15 是**诊断**声明：它回答「D 的额外 token 从哪来」，用来决定下一步该改哪里，不是对外主张。引用时必须带上它的启发式边界（A 侧分桶、A 无成败标记、文件引用计数口径不同），不得写成「ACI 的 exec 更省」这类结论。
- 新增任何对外数字时：先在本文件加一行，再在 `tools/claim_gate.py` 加对应门槛（或显式标注不设门槛），最后跑 `python tools/claim_gate.py`。

## 5. 口径统一规则（已按根策略裁决）

`docs/v1.1-freeze.md` 是**对外承诺**（≤0.7 tool calls / ≤0.6 observation tokens），`tools/claim_gate.py` 是**机器门禁**。按 `docs/task-forest-policy.md` §4「口径冲突取更严一侧」，门禁不得弱于对外承诺：

| 声明 | freeze 对外目标 | claim_gate 门禁 | 关系 |
|------|----------------|----------------|------|
| C1 tokens | ≤ 0.60 | ≤ 0.50 | 门禁更严（保留） |
| C2 calls | ≤ 0.70 | ≤ 0.70 | 已对齐（2026-09-22 由 0.80 收紧） |

mock 实测值（0.106 / 0.55）在两侧都过线。今后新增对外数字一律走同一规则：先写 freeze 目标，再把门禁设成不弱于它的值，两处数字必须一致。

## 6. 未纳入门禁的其它对外数字

| 数字 | 出处 | 现状 |
|------|------|------|
| （无） | — | 2026-09-22：原「compact 协议 50–70% token 节省 vs JSON」已处置。该数字**无法复现**（实测小响应信封 42.4%、观察载荷合计 −3.1%），已按 §4 登记为 C9，并把 README 口径改成 C9 的实测范围。当前没有已知的「已进 README 但未登记」对外数字 |

## 7. L3 观察质检（不进 C1–C15 门禁）

`tools/jev_obs_judge.py`（TF-0012）对每个失败样本问两个窄问题，产出 `eval/jev_obs_report.json` + `eval/jev_obs_report.md`：

| 问题 | 类型 | 含义 |
|------|------|------|
| `diagnostic_sufficient` | Noul | 结构化观察是否带够锚点（path/line/code，diff 类还要 expected/found），agent 不用回读原始日志 |
| `script_actionable` | Choice | reducer 的 `suggested_next` 剧本能否照抄执行（view → edit → rerun） |

`script_actionable` 的四种判定（后两种要分开看，否则会把「按设计不给剧本」误当成缺陷）：

| 判定 | 含义 |
|------|------|
| `actionable` | 剧本合法、参数键齐全、含重跑步骤 |
| `missing_params` / `illegal_op` / `no_rerun` | 有剧本但不可直接执行（缺陷） |
| `no_locatable_site` | 观察里根本没有可定位的失败点（ENOENT 的缺失路径、npm ERESOLVE、git 非仓库等）；此时给 `file.view` 等于编造步骤，**按设计不给剧本** |
| `unrecoverable_anchor` | 原始输出里有 `path:line` 锚点，但 reducer 没能结构化（真实缺口，见 §8） |

- 无 `TYPESAFE_API_KEY` 时用确定性启发式（离线可复现）；有 key 时同一问题走 TypeSafe System One（`jev-latest`）。
- 该报告只做质检，**不设门禁门槛**、不生成修复代码、不替代正则 reducer；结论不得直接当对外数字用（要进 README 仍须按 §4 登记为 Cx）。
- 最近一次（2026-09-22，启发式）：13 个失败样本，诊断足够 10/13，剧本可执行 9/13，`no_locatable_site` 4，`unrecoverable_anchor` 0。

## 8. 锚点恢复（TF-0016 / TF-0017）与剩余缺口

`src/reducers/mod.rs::suggested_from_diagnostics` 现在在诊断没有结构化位置时，从 message 里恢复 `path[:line]`（panic 位置、git 冲突文件、pytest `FAILED file::case`），并显式排除「路径本身不存在」的失败类别（`ENOENT` / `no such file` / `not found` / `not a git repository`），因为这些类别给出 `file.view` 会立刻失败。

| 类别 | 处理 | 证据 |
|------|------|------|
| cargo panic | `src/reducers/cargo.rs` 识别 `thread '…' panicked at <path>:<line>:<col>`，产出带锚点的 error 诊断 → view(panic 点) + `cargo check` | `cargo_adv_fail_panic_is_anchored`；报告中 `adv_cargo_fail_panic` = actionable |
| git 冲突 / pytest 无 header | 从 message 恢复文件路径 → view + 重跑 | 报告中两者 = actionable |
| cargo 位置被拆行（`-->` 与 `path:line` 分行） | `recover_wrapped_location` 把箭头行与后续非空行拼接，仅当整体严格匹配 `path:line[:col]` 才采用（避免误认无关路径） | `cargo_adv_fail_malformed_recovers_wrapped_location`（path=`src/mixed/path.rs`，line=42）；报告中 `adv_cargo_fail_malformed` = actionable |
| npm ENOENT / npm ERESOLVE / npm 网络 / git 非仓库 | 不给剧本（无可定位点） | `anchor_recovery_skips_paths_that_do_not_exist`；报告中 = `no_locatable_site`（4 条） |

结论：13 个失败样本中，9 条给出可直接执行的剧本，4 条属于「按设计无可定位点」，`unrecoverable_anchor` 为 0。仍不足的部分是 `diagnostic_sufficient` 10/13——3 条无锚点类别的观察只有 message 级信息，这是「无可定位点」的必然结果，不是缺陷；若将来要求这类失败也给出下一步，需要先定义「无锚点失败的通用可执行动作」，否则只能靠模型常识而非 reducer 契约。

