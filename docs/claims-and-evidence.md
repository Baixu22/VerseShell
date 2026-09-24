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
# C16：读取桶的紧凑投影（同一信封两种投影，确定性，无 API 调用）
python tools/read_path_breakdown.py --out eval/read_path_breakdown.json
# C17：读取用途审计（读了但之后从未引用的是什么，确定性，无 API 调用）
python tools/read_usage_audit.py --out eval/read_usage_audit.json
# C18/C19/C22：exec 失败分解、shim 启动与裸名解析回归检测（确定性）
python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json
# C20：D 与 A 的步骤构成分解（确定性，无 API 调用）
python tools/step_composition.py --out eval/step_composition.json
# C21：ts fixture 的工具链获取链与成功谓词边界（确定性，无 API 调用）
python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json
```

## 3. 声明表（C1–C22）

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
| 样本量 / 日期 | 5 项操作 × 3 shell（Bash 无 Disk 等价命令，故 4 项）× 20 次 + 3 次预热；2026-09-24 |
| 最近实测 | worst **0.2535**（CPU info，3.9x）；Disk 0.0310（32.3x）、List dir 0.0459（21.8x）、Read file 0.0707（14.2x）、Pipeline 1K 0.0637（15.7x）；`all_commands_ok=true`。2026-09-24 重测（改 `src/process_command.rs::resolve_candidate` 后按 C12 重跑）；上一次产物为 0.2301（CPU info 291.2ms / 4.3x），README 表格已同步。**注意**：本次 D 侧数字与 C13 的 live 基线不是同一次测量，live 证据尚未重跑（见 C12） |
| 失效边界 | 墙钟测量，含进程启动开销，只代表本机与当前工具链（AMD Ryzen 7 7745HX / Windows PowerShell 5.1 `-NoProfile` / Git Bash）；不测吞吐、内存、并发；门禁读的是**已存产物** `eval/cross_shell.json`，改动热路径后必须重跑 runner 才会更新（C12 会判陈旧）；每次重跑数字都会小幅漂移，README 表格必须与产物逐行一致（由 C10 检查）；README 里旧的 v0.5.1 数字（3.7x / 14.4x / …）已作废并被本声明取代 |
| 状态 | 已证实（本机单次测量） |

### C12 · 证据新鲜度（产物指纹）

| 维度 | 内容 |
|------|------|
| 主张原文 | 门禁依赖的十一份已存测量（ACI-Bench mock 结果、live A/D 结果、L3 观察质检报告、跨 shell 基准、批量读取信封复算、exec token 分解、读取桶紧凑投影、读取用途审计、exec 失败分解、步骤构成分解、ts fixture 边界审计）都记录了生成时被测代码面的 sha256 指纹，且该指纹与当前代码重算结果一致——也就是说这些数字描述的仍是当前实现，而不是两个月前的实现 |
| 门槛数字 | 十一份产物的记录指纹与重算指纹全部一致（`>= 1.00`） |
| 复现命令 | `python tools/claim_gate.py`；重跑产物用 `python bench/aci/runners/run_suite.py --mode mock`、`python tools/jev_obs_judge.py`、`python tools/cross_shell_bench.py`、`python bench/aci/runners/live_agent_loop.py`（再 `merge_live_runs.py`）、`python tools/tf45_envelope_replay.py`、`python tools/exec_token_breakdown.py`、`python tools/read_path_breakdown.py`、`python tools/read_usage_audit.py`、`python tools/exec_failure_breakdown.py`、`python tools/step_composition.py`、`python tools/ts_fixture_audit.py` |
| source | `bench/aci/results/latest.json`、`bench/aci/results/latest_live.json`、`eval/jev_obs_report.json`、`eval/cross_shell.json`、`eval/tf45_envelope_replay.json`、`eval/exec_token_breakdown.json`、`eval/read_path_breakdown.json`、`eval/read_usage_audit.json`、`eval/exec_failure_breakdown.json`、`eval/step_composition.json`、`eval/ts_fixture_audit.json`、`tools/claim_gate.py` |
| 样本量 / 日期 | 11 份产物；2026-09-24 |
| 最近实测 | 11/11 fresh（PASS）。引入本声明前的产物（如 2026-07-27 的 bench 结果）没有指纹字段，会被直接判失败 |
| 失效边界 | 只覆盖登记在 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 的十一份产物；`live_ab_without_read_files.json` 是配对对照臂，按设计不进 C12（重跑时机由 C13 记录），但它是 `eval/exec_token_breakdown.json`、`eval/read_usage_audit.json`、`eval/exec_failure_breakdown.json` 与 `eval/step_composition.json` 的输入，所以那四份产物会随它一起更新。`eval/ts_fixture_audit.json` 的指纹额外覆盖 `src/process_command.rs`、`bench/aci/tasks/ts_*.json` 与两个 ts fixture——**改动 ts fixture 或裸名解析会让 live 证据与本产物一起被判陈旧**（C21 的边界因此是机检的，不靠约定）。指纹是**文件内容哈希**，不含运行环境（OS / 工具链 / CPU），所以换机器重跑不会因环境不同被判陈旧——跨机器可比性仍受 C11 的边界限制；产物未记录指纹时判失败（fail-closed） |
| 状态 | 已证实 |

### C13 · live A/D 对比与 read_files A/B（真实模型）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在真实函数调用模型 `sn-glm-5-3-flash`（本地 OpenAI 兼容端点）上跑 ACI-Bench 全量 10 任务 × 2 条件 × 3 次重复（temperature=0，seeds 42/43/44），并做**同期 A/B**（同模型同 seeds，仅隐藏 `read_files` 工具）。**本轮（C18 shim 修复 + 紧凑投影 + 提示规则 8）**：①成功率 A 0.6333 / D 0.6333；②**D 的观察 token 首次低于 A**——D/A token 比 **0.876**、工具比 **1.40**；③`file.read_many` 使 D 的工具调用数由 4.07 升到 **4.53**、观察 token 由 139.5 升到 **177.27**（+27.1%），但两个臂的 D 都低于各自的 A。**结论：修复 C18 之后，ACI 在该模型与该任务集上以多约 40% 的步骤换来更少的观察 token；此前「ACI 贵 1.7–2.4 倍」是在 D 无法运行 cargo/rustc 的缺陷态下测得的，不可与修复后比较** |
| 门槛数字 | 无（中性/负向结论，只登记事实，不设通过门槛） |
| 复现命令 | with：`python bench/aci/runners/live_agent_loop.py --full --model sn-glm-5-3-flash --base-url <endpoint> --max-turns 8 --temperature 0 --seed <s>`；without：同命令再加 `--exclude-tools read_files`；各跑 seeds 42/43/44 后合并：`python bench/aci/runners/merge_live_runs.py --out <artifact> <per-seed runs...>`（任一行带 `api_error` 即 exit 2，拒绝合并） |
| source | `bench/aci/runners/live_agent_loop.py`、`bench/aci/runners/merge_live_runs.py`、`bench/aci/runners/splice_live_cells.py`、`src/process_command.rs`（C18 修复）、`bench/aci/results/latest_live.json`（with，3 次合并）、`bench/aci/results/live_ab_without_read_files.json`（同期对照，3 次合并）、`bench/aci/results/tf72/with_seed*.json`、`bench/aci/results/tf72/without_seed*.json`（逐 seed 原始行）、`bench/aci/tasks/*.json` |
| 样本量 / 日期 | 10 任务 × 2 条件 × 3 seeds × 2 臂 = 120 行，`api_error` 0（3 格上游 500 已用 `splice_live_cells.py` 补跑）；2026-09-24（第五次复测，**C18 修复后**） |
| 最近实测 | **本轮（C18 修复后）** with：A 0.6333 / 3.23 / 202.43；D 0.6333 / **4.53** / **177.27**（D/A **1.4025 / 0.8757**）。without：A 0.60 / 3.23 / 169.20；D 0.5333 / **4.07** / **139.50**（D/A 1.2601 / 0.8245）。`read_files` 净效应：工具 **+11.3%**、观察 token **+27.1%**。**逐轮 with 臂 D 绝对开销**：411.1 → 333.4 → 296.5 → 303.5 → **177.3**；A：168.6 → 197.4 → 170.5 → 168.9 → **202.4**。**本轮 exec 结构变化**：`exec.run` 由 76 次 / 5585 tok（73.49 tok/次）降到 **50 次 / 2121 tok（42.42 tok/次）**；失败 exec 由 45 次 / 4565 tok 降到 **21 次 / 1735 tok，且 Rust 任务归零**。**差距分桶（总 −17.17 tok/run，D 更省）**：exec **−74.63**、read +16.20、edit +27.77、meta +5.50。**上一轮（修复前，已被取代且不可比）**：with D 5.33 / 303.53（D/A 1.7591 / 1.7974）；without D 6.13 / 314.53（D/A 1.9774 / 1.8516） |
| 失效边界 | ①**修复前的 D 侧数字受 C18 污染，不可与修复后比较**：2026-09-24 之前条件 D 在本机无法执行任何 cargo/rustc 命令（`cargo check` → exit 100 且报「0 error(s)」、`cargo build` 被读成 `+build` 工具链、`cargo --version` 打印 rustup 版本），而 A 走 `cmd` 不受影响。这直接解释了此前登记的高失败率、工具链探测与高 exec token；引用任何 2026-09-24 之前的 D 侧 exec 数字时必须同时引用 C18 与 C19。②**单模型**（`sn-glm-5-3-flash`），不可外推；该模型曾被端点下架又恢复，复测前必须先核对 `/v1/models`。③**名义确定性**：端点接受 `seed` 但不严格复现，3 次重复给的是经验区间而非确定性复算。④**D/A 比值受 A 侧漂移主导**：A 的代码五轮未动，其 with 臂 obs_tok 却在 168.6 / 197.4 / 170.5 / 168.9 / 202.4 之间摆动（约 ±9%），比值变化不宜单独作为趋势证据；可读的是 D 的绝对开销与确定性复算（C14 / C16）。⑤观察 token 用 `len(text)//4` 估算，不是真实 tokenizer。⑥成功判定是任务自带的文件谓词，不要求真的跑测试；**修复后** D 才真正具备跑通 cargo/pytest/tsc 的能力。⑦本机 `tsc` 缺失（fixture 声明了 `typescript` 但工作区不带 `node_modules`）、裸 `pytest` 在 Windows 上因 console-script 的 `sys.path` 行为失败（规范形式 `python -m pytest`），两条件同样受限；本轮已把这条边界量化，并把它拆成「裸名 `npm`/`npx` 无法启动」（**产品侧**解析缺陷）与「缺 typescript」两半（C21，修复跟踪在 TF-0083/TF-0085）。⑧**与 mock 的 C1/C2 不可混用**：mock 的 D 直接套 GOLDEN 补丁，0.106/0.55 是评分管线自检，不是能力测量。⑨上游会间歇性 500（`parse response failed`）：本轮 6 次运行有 3 格受影响，已用 `splice_live_cells.py` 按 (task, condition, seed) 补跑后合并；合并脚本遇到 `api_error` 即 exit 2 |
| 状态 | 已证实（本机单模型、3 次重复 × 2 臂；**C18 修复后的口径**） |

### C14 · 批量读取信封（紧凑摘要 + 批量预算，固定轨迹复算）

| 维度 | 内容 |
|------|------|
| 主张原文 | 把 live 运行里模型**真实发出**的读取调用固定下来、用当前二进制重跑，并对**同一份**观察信封做两次投影（旧口径：逐文件完整 `sha256:<64 hex>`；新口径：16 位十六进制紧凑摘要，可直接当 `expected_hash` 前缀回传），模型可见的 observation tokens 下降；同时 `file.read_many` 新增的 `max_total_lines` 预算把最坏情况（8 个 300 行文件）限制在预算之内且仍可分页续读 |
| 门槛数字 | `token_savings >= 0.15`；且 `legacy_comparison_exact == true`、`budget.bounded == true`、`budget.pagination_roundtrip == true`、`coverage > 0` 必须同时成立 |
| 复现命令 | `python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json`，再 `python tools/claim_gate.py` |
| source | `tools/tf45_envelope_replay.py`、`bench/aci/runners/live_agent_loop.py`、`src/ops/file.rs`、`src/ops/common.rs`、`eval/tf45_envelope_replay.json` |
| 样本量 / 日期 | 38 次冻结读取调用（26 次 `file.read_many` + 12 次 `file.view`），其中 33 次可忠实复现；2026-09-23 |
| 最近实测 | 合计 **4181 → 3079 tokens（−26.4%）**；`file.read_many` 26/26 次复现、3844 → 2839（−26.1%）——其中「新口径」一侧 2839 与 C16 的紧凑投影合计**逐位相同**；`file.view` 7/12 次复现、337 → 240（−28.8%）。预算：默认 8×300 行 → 返回 240 行（上限 240），`max_total_lines=40` → 返回 40 行（上限 40）；分页：250 行文件按 window=100 逐页读回，3 页 250/250 行逐行一致。**排除的 5 次调用**是读 live 运行期自己产生的状态（`.ae/audit.log`、`ERR.txt`、`out/result.txt`），pristine fixture 无法重建，报告里逐条给出「复算值 vs live 记录值」。摘要节省比上一轮（−22.1%）更大，因为紧凑投影把别的开销压掉后摘要占比升高 |
| 失效边界 | ①这是**客户端信封效应**，不是模型行为测量：调用集合被冻结，所以它说不出「模型会不会因此换别的调用」。②只有「stored live 那次运行所用的投影能复现其记录的 token 数」的调用才计入（本轮 `matched={'current': 33}`，`coverage=33/37`）；这条判据同时保证基线确实是模型当时看到的东西，并让工具在「改了客户端却没重跑 live」时直接判失败而不是悄悄给出跨口径比较。③`file.read_many` 24/24 全部精确匹配，且「新口径」合计与 live 实测合计相同，是最强的保真度交叉验证。④token 用 `len(text)//4` 估算，不是真实 tokenizer。⑤预算与分页那一半是结构性事实（返回行数 ≤ `max_total_lines`、分页可逐行复原），与模型无关，但**只在 `file.read_many` 上成立**；`file.view` / `file.read_range` 仍是单文件窗口。⑥本声明的数字**不能**与 C13 的 live D/A 比值相加或相减来解释：C13 的 D 侧同时含 `exec.run` 等非读取开销 |
| 状态 | 已证实 |

### C15 · D 的额外 token 从哪来（exec token 分解，TF-0058）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物做逐 op 分解（不调用 API）：①`exec.run` 占条件 D 的 observation token **39.9%**（2121/5318，70.70 tok/run，42.42 tok/次）——**C18 修复前是 61.3%（5585/9106，73.49 tok/次）**；②其中 **81.8% 的 exec token 来自失败的命令**（21 次失败 @82.62 tok，占 42.0% 的调用；成功 29 次 @13.31）；③with/without `read_files` 的 exec 增量 **+5.47 tok/run** 拆成次数效应 76% / 单次效应 24%；④**差距构成（修复后）**：总 **−17.17 tok/run（D 比 A 省）**，分桶为 exec **−74.63**、read +16.20、edit +27.77、meta +5.50——exec 从「最大正贡献」翻转成「最大负贡献」，因为 A 的 raw shell 必须用一条命令同时做读、跑、写，而 D 的 exec 只做执行且失败观察更短；⑤D 每个文件引用 36.65 tok（A 的 `type` 是 34.63），差距已收窄到 1.06× |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_token_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_token_breakdown.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行（10 任务 × 3 seeds）/ 50 次 `exec.run`；对照臂 30 次 / 47 次；2026-09-24（第四次复测，C18 修复后） |
| 最近实测 | with：D 177.27 tok/run，`exec.run` 50 次 / 2121 tok（39.9%，70.70/run，42.42/次），成功 29 次 @13.31、失败 21 次 @82.62（**失败占 81.8% 的 exec token，只占 42.0% 的调用**）。without：D 139.50 tok/run，`exec.run` 47 次 / 1957 tok（46.8%，65.23/run，41.64/次），成功 25 次 @13.12、失败 22 次 @74.05。**exec 增量（with − without）：+5.47 tok/run** = 次数效应 +4.16（76%）+ 单次效应 +1.30（24%）+ 交互 0.08。差距分桶（总 **−17.17** tok/run）：exec **−74.63**、read +16.20、edit +27.77、meta +5.50。读取形状：D 34 次读取 / 1906 tok / 每次 1.53 个文件引用 / **每引用 36.65**；A 37 次读取命令 / 1420 tok / 1.11 / 34.63。**修复前同臂对照（已被取代）**：`exec.run` 76 次 / 5585 tok（61.3%，73.49/次），失败 45 次 @101.44；差距分桶 read +31.83、exec +70.43、edit +28.67、meta +3.73 |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_token_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_token_breakdown.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行（10 任务 × 3 seeds）/ 50 次 `exec.run`；对照臂 30 次 / 47 次；2026-09-24（第四次复测，C18 修复后） |
| 最近实测 | with：D 177.27 tok/run，`exec.run` 50 次 / 2121 tok（39.9%，70.70/run，42.42/次），成功 29 次 @13.31、失败 21 次 @82.62（**失败占 81.8% 的 exec token，只占 42.0% 的调用**）。without：D 139.50 tok/run，`exec.run` 47 次 / 1957 tok（46.8%，65.23/run，41.64/次），成功 25 次 @13.12、失败 22 次 @74.05。**exec 增量（with − without）：+5.47 tok/run** = 次数效应 +4.16（76%）+ 单次效应 +1.30（24%）+ 交互 0.08。差距分桶（总 **−17.17** tok/run）：exec **−74.63**、read +16.20、edit +27.77、meta +5.50。读取形状：D 34 次读取 / 1906 tok / 每次 1.53 个文件引用 / **每引用 36.65**；A 37 次读取命令 / 1420 tok / 1.11 / 34.63。**修复前同臂（已被取代，受 C18 污染）**：`exec.run` 76 次 / 5585 tok（61.3%，73.49/次），失败 45 次 @101.44 |
| 失效边界 | ①**纯诊断**，不是对外主张，也不能反过来当作「ACI 省 token」的证据。②A 侧分桶是**启发式**：按命令字符串关键词分成 build_or_test / read_file / write_or_mkdir / other，优先级 build > read > write；一条命令可能同时读和构建，残差进 other（本轮 other 仅 5 次 / 318 tok），所以 A 的桶是近似值。③A 的 trajectory 不记录单次命令成败（只有 D 记 `aci_ok`），因此无法对 A 做成功/失败拆分。④「每个文件引用」在 D 侧由 `file.read_many.paths` 精确计数、在 A 侧由 `type`/`cat` 出现次数近似，两者不是同一种计数单位。⑤token 仍是 `len(text)//4` 估算。⑥结论只对**本模型、本任务集、本轮 120 行**成立；换模型或换任务集必须重跑 |
| 状态 | 已证实（本机单模型、诊断性） |

### C16 · 读取桶的紧凑投影（客户端渲染，固定轨迹实测）

| 维度 | 内容 |
|------|------|
| 主张原文 | 把 live 运行里模型**真实发出**的读取调用固定下来，对**同一份**观察信封用真实投影器做两次投影（`format_aci_result(compact=False)` 是改动前的渲染，`compact=True` 是当前），模型可见的读取桶 observation token 下降 **21.1%**（2325 → 1834，30 次可复现调用）。紧凑投影做三件事：完整窗口的 `lines` 数组改为单个换行连接的 `text`；窗口从第 1 行开始且覆盖整文件时丢掉 `start_line`；窗口覆盖整文件时丢掉 `total_lines`（此时它等于 `text` 的行数） |
| 门槛数字 | `token_savings >= 0.10`（实测 0.2076）；且 `calls > 0`、至少一次调用的投影与 stored live 记录一致 |
| 复现命令 | `python tools/read_path_breakdown.py --out eval/read_path_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/read_path_breakdown.py`、`bench/aci/runners/live_agent_loop.py`、`tools/tf45_envelope_replay.py`、`eval/read_path_breakdown.json` |
| 样本量 / 日期 | 30 次可复现读取调用（13 次 `file.read_many` + 17 次 `file.view`），另有 4 次读运行期自产状态的调用被排除；2026-09-24（C18 修复后） |
| 最近实测 | 合计 9346 → 7372 字符（−21.1%）、**2325 → 1834 tokens（−21.1%）**；`file.read_many` 13 次 1538 → 1233（−19.8%）、`file.view` 17 次 787 → 601（−23.6%）。改动前归因：content 38.4%、counts 18.0%、residual 14.8%、digest 11.9%、line_wrapper 9.0%、path 7.9%；改动后：content 48.7%、residual 19.0%、digest 15.1%、path 10.0%、line_wrapper 5.7%、counts 1.5% |
| 失效边界 | ①这是**客户端渲染**改动，不是产品契约改动：`compact=False` 与改动前的投影**逐字节一致**（用 git 上一版的投影器对同一批 37 次冻结调用逐条比对，37/37 identical），所以没有任何消费者需要迁移——兼容策略就是「不动契约」。②丢 `total_lines` **只在客户端展示内容时才成立**：>10 行的窗口不展示内容，此时 `total_lines` 是唯一信息、必须保留（改动后 counts 仍占 0.8% 正是这部分）。这也是该优化不能放进产品信封的原因。③作用域是 `file.view` / `file.read_many`；`file.read_range` 在本轮 live 调用集中未被使用，未纳入测量。④只测读取桶，不代表 D 的总 token 变化——总变化由 live 复测给出（C13）。⑤token 仍是 `len(text)//4` 估算。⑥两项更激进的改动被**评估后否决**：摘要从 16 位降到 8 位（约再省 4%，但碰撞界从 2^-64 降到 2^-32），以及让 `start_line > 1` 的完整窗口也丢 `total_lines`（空文件/尾换行边界下推导不可靠） |
| 状态 | 已证实（确定性复算） |

### C17 · 读取用途审计（D 的读取到底用在哪，TF-0067）

| 维度 | 内容 |
|------|------|
| 主张原文 | 对已存 live 产物做读取用途审计（不调用 API），按**代码里定义**的规则给每条读取路径分类：`referenced_in_run`（同一 run 里被编辑、或在 exec 命令里被点名）、`task_subject`（任务 prompt 或成功谓词里点名）、`task_file`（fixture 自带的 `TASK.md`，其内容系统提示已以更详细的版本携带）、`unreferenced`（以上都不是）。**with 臂 D：85 条路径中 referenced 31（35.0%）、task_subject 6（6.8%）、TASK.md 27（33.4%）、unreferenced 21（24.8%）**；同期 A：78 条文件引用中 referenced 34（55.0%）、task_subject 20（19.5%）、TASK.md 16（17.6%）、unreferenced 8（7.9%）。逐条比对 10 个 fixture 的 `TASK.md` 与注入提示：**提示词每条都更详细，`TASK.md` 没有独有信息**，所以「读 `TASK.md`」是可证明的冗余——而且它在两个臂里都存在。据此加了提示规则 8（「`TASK.md` 只是重复上面的任务，不要为它花一次工具调用」），并用 live 复测验证：**改动后 D 的 `TASK.md` 读取从 27 条 / 1064.5 tok 降到 3 条 / 115.3 tok（−89%），读取桶 3183 → 2203 tok（−30.8%），成功率没有下降（A 0.60 / D 0.60）** |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/read_usage_audit.py --out eval/read_usage_audit.json`，再 `python tools/claim_gate.py` |
| source | `tools/read_usage_audit.py`、`bench/aci/tasks/*.json`、`bench/aci/runners/live_agent_loop.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/read_usage_audit.json` |
| 样本量 / 日期 | 改动前（TF-0067 轮产物）：with 臂 38 次 D 读取调用 / 85 条路径；**C18 修复后本轮**：34 次 / 52 条、52 条 A 文件引用；2026-09-23 → 2026-09-24 |
| 最近实测 | **改动前（发现问题的依据）** with：D 85 条路径中 `TASK.md` **27 条 / 1064.5 tok（33.4%）**；A 78 条中 16 条（17.6%）。**C18 修复后本轮** with：D 52 条路径中 `TASK.md` 只剩 **3 条 / 102.3 tok（5.4%）**；A 的 `TASK.md` 占 9.2%（5 条 / 255.5 tok）。D 的 `unreferenced` 占 37.7%（718.3 tok），主要是 `Cargo.toml`（6 次）——工程上下文，不是浪费 |
| 失效边界 | ①**`unreferenced` ≠ 无用**：它只表示「本 run 里没有留下可观察的下游使用」。`Cargo.toml`（9 次）与 `tests/test_math.py`（3 次）都落在这个桶里，但它们分别是工程上下文与失败测试的所在文件——读它们是合理的。能证明冗余的只有 `TASK.md`，因为提示词是它的严格超集。②分类规则是**代码里的启发式**：`referenced_in_run` 靠命令字符串里的路径 token 匹配，路径写法不一致（相对/绝对、反斜杠）会漏判，所以 `unreferenced` 是上界而非精确值。③**批量调用的 token 按路径数均摊**，不是逐文件实测；一次 3 文件 `read_many` 的信封开销也会摊到 `TASK.md` 头上，所以 33.4% 这个份额里含信封开销。④A 侧必须排除「读取命令自身」的自指（A 用 `type` 读文件，命令里自然出现该路径），否则 A 会 100% 落在 `referenced_in_run`；本工具对此有专门处理。⑤结论只对本模型、本任务集、本轮 120 行成立 |
| 状态 | 已证实（本机单模型、诊断性） |

### C18 · exec 按被调用的名字启动「按名字分派」的 shim（rustup 的 cargo/rustc）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在 rustup 用**符号链接**安装 shim 的机器上（`cargo.exe` / `rustc.exe` / `cargo-clippy.exe` / `rustfmt.exe` → `rustup.exe`），`exec.run` 必须按「调用者使用的名字」启动，而不能把最后的软链接 canonicalize 掉：rustup 依据 argv[0] 的文件名选择要代理的工具。`tools/exec_failure_breakdown.py` 的 `shim_probe` 通过**真实 exec.run** 重跑 `cargo --version` / `cargo check` / `rustc --version`，要求三条都 `exit_code == 0` 且输出不再由 rustup 应答 |
| 门槛数字 | `== 1.00`；且本机必须确实存在这种「canonicalize 会丢名字」的 shim（fail-closed，避免在没有 shim 的机器上空过） |
| 复现命令 | `python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json`，再 `python tools/claim_gate.py`；单测：`cargo test --lib process_command` |
| source | `tools/exec_failure_breakdown.py`、`src/process_command.rs`（`resolve_candidate` / `launch_candidate`）、`src/process_runner.rs`、`eval/exec_failure_breakdown.json` |
| 样本量 / 日期 | 3 条命令 + 4 条 shim 事实；2026-09-24 |
| 最近实测 | **缺陷态**：`cargo check` → `exit_code=100` 且 summary 为「cargo: 0 error(s), 0 warning(s); cargo failed」；`cargo build` → 「invalid value 'build' for '[+toolchain]'」；`cargo --version` → 打印 `rustup 1.29.1`。**修复后**：三条命令 `ok=True`、`exit_code=0`，`cargo --version` → `cargo 1.98.1`，`answered_as_rustup=False`；`shim_probe.pass=true` |
| 失效边界 | ①只覆盖 **rustup 软链接形态**的 shim；若某个安装用硬链接或复制，本声明既不触发也不覆盖（`shim_facts` 会如实记为非软链）。②回归测试需要创建符号链接的权限，无权限时该用例**退化为 no-op**；因此门禁额外要求本机存在 `canonical_loses_name=true` 的 shim，避免「没有 shim 所以通过」的假绿。③只证明**启动名**正确，不证明被代理程序的行为；`cargo check` 那一半用的是 fixture 的 GOLDEN 修复版，所以它同时验证了「cargo 真能编译通过」。④与 C8 一样是**本机/平台**边界：换一台没有 rustup shim 的机器，这条声明只报告未触发。⑤该缺陷此前使条件 D 在 Rust 任务上**无法执行任何 cargo/rustc 命令**，而 A 走 `cmd` 不受影响——因此 C13/C15 在 2026-09-24 之前登记的 D 侧 exec 数字受此污染 |
| 状态 | 已证实（本机，Windows + rustup 软链 shim） |

### C19 · exec 失败分解（失败到底是诊断、试错还是缺陷，TF-0072）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物把条件 D 的失败 `exec.run` 分成三类（规则写在 `tools/exec_failure_breakdown.py` 里）：`first_diagnostic`（该命令在本 run 里第一次失败——对这套任务而言，**看到失败本身就是工作**）、`repeat`（同一条命令在后续再次失败，即试错）、`toolchain_probe`（`--version` / `+toolchain` 之类的探测）。**修复 C18 之前**：with 臂 45 次失败 @101.44 tok = 81.7% 的 exec token，其中 first_diagnostic 89.3%、toolchain_probe 10.7%、**repeat 0**，且集中在 Rust 任务（`rust_fix_compile_error` 14 次、`rust_search_and_edit` 8 次、`rust_add_unit_test` 4 次）。**修复之后**：with 臂失败降到 **21 次 @82.62 tok**，**Rust 任务归零**，剩余失败全在 Python/TS 任务上且 100% 是 first_diagnostic（repeat 与 toolchain_probe 均为 0） |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_failure_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_failure_breakdown.json` |
| 样本量 / 日期 | 修复前 with 臂 76 次 `exec.run`（45 次失败）；修复后 50 次（21 次失败）；2026-09-24 |
| 最近实测 | 修复后 with：`exec.run` 50 次 / 2121 tok（39.9% of D），成功 29 次 @13.31、失败 **21 次 @82.62**（占 42.0% 的调用、81.8% 的 exec token），**100% first_diagnostic，repeat 与 toolchain_probe 均为 0**；失败集中在 `ts_fix_type_error`（9 次）、`python_edit_and_retest`（6）、`python_fix_pytest_fail`（3）、`ts_package_script_fail`（3），**Rust 任务全部归零**。without：`exec.run` 47 次 / 1957 tok，失败 22 次 @74.05（83.2%），同样 100% first_diagnostic。修复前同臂为 76 次 / 5585 tok、失败 45 次 @101.44（89.3% first_diagnostic + 10.7% toolchain_probe） |
| 失效边界 | ①分类是**启发式**：`--version` / `+toolchain` 关键词判为探测，同命令第二次失败判为重复，因此 `repeat=0` 是「没有出现同命令二次失败」而非「模型从不试错」。**本轮 ts 任务的 9 次失败经 C21 分解后是 6 次裸名启动失败 + 3 次工具链缺失，都没有产出可操作诊断**——即 `first_diagnostic` 在这 9 次上只说明「是该命令第一次失败」，不说明「看到了值得看的失败」。②**修复前的数字受 C18 污染**：Rust 任务的失败里有相当部分由启动缺陷造成，不能当作「模型试错成本」的证据；引用时必须同时引用 C18。③`first_diagnostic` **不等于浪费**：这套任务的很多条目就是「跑一次失败、看诊断、再修」，所以它的占比高本身不是缺陷。④只对本模型、本任务集、当前轮次成立；换模型或改任务集必须重跑 |
| 状态 | 已证实（本机单模型、诊断性） |

### C20 · D 与 A 的步骤构成（多出来的步骤从哪来，TF-0078）

| 维度 | 内容 |
|------|------|
| 主张原文 | 分解两条件的步骤构成（不含 `task_complete`，与 live bench 口径一致）：**D 4.533 步/run、170.60 tok/run；A 3.233 步/run、194.43 tok/run**（比值 1.402 / 0.877）。D 按类别：exec 1.667、edit 1.167、read 1.133、meta 0.567；A 全部是 `run_command` 3.233。**A 的 97 条命令里有 34 条（35.0%）一次做多件事**（read+run 11、read+write 10、run+write 10、三合一 3），而 D 的 typed op 不能合并——步骤差主要来自这里。**「可合并的重复调用」只有 12 次（8.8% 的步骤、13.02 tok/run）**，逐条查看后大多不是浪费：4 次是编辑后重跑同一条 pytest（状态已变，属合法复验），约 8 次是 `ts_fix_type_error` 里模型反复换姿势调用 tsc。失败观察的构成以 `error`（560 字符）与 `diagnostics`（325）为主，即**可操作内容**；可裁的 `stats`（103）与 `stdout/stderr_summary`（各 48）合计约 20%，但各自都带信号，评估后不动 |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/step_composition.py --out eval/step_composition.json`，再 `python tools/claim_gate.py` |
| source | `tools/step_composition.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`bench/aci/tasks/*.json`、`eval/step_composition.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行 / 30 次 A 运行；2026-09-24（C18 修复后） |
| 最近实测 | D 4.533 步/run（170.60 tok）vs A 3.233 步/run（194.43 tok），比值 **1.402 / 0.877**；D 的 op 构成（30 次运行合计）`exec.run` 50、`file.replace_exact` 22、`file.view` 21、`repo.summary` 14、`file.read_many` 13、`file.write` 13、`repo.search` 3；A 的多合一命令 34/97（35.0%）；重复调用 D 12 次（8.8%，13.02 tok/run）、A 4 次（4.1%）；失败观察 leave-one-out：`error` 560、`diagnostics` 325、`stats` 103、`ok` 52、`stderr_summary` 48、`stdout_summary` 48、`exit_code` 34 字符 |
| 失效边界 | ①**「重复调用」不等于浪费**：判据是 `(op, args)` 完全相同，看不到状态变化——编辑后重跑同一条验证命令会被计入，而那正是正确行为。因此 8.8% 是**上界**。②多合一的判定是**关键词启发式**（命令串里是否同时出现 read/run/write 提示词），不是语法分析。③`ts_fix_type_error` 的探测链已由 TF-0082 逐类量化（C21）：3 次 D 运行共 **15 次 exec 调用 / 754 tok**，其中 **6 次 / 288 tok 是裸名 `npm` / `npx` 启动失败**（PATH 上无扩展名的 POSIX shim 抢在 `npm.cmd` 前面被选中，属**产品侧解析缺陷**，跟踪在 TF-0083）、**6 次 / 457 tok 是缺 `node_modules` 的失败与安装绕行**（fixture 声明了 `typescript` 但不带 `node_modules`，prompt 却承诺 `tsc --noEmit succeeds`）、**只有 3 次 / 9 tok 是任务真正需要的验证**。也就是说这条链里约 8 次「重复调用」并不全是环境开销，而是产品缺陷与环境边界各占一半；本轮**不改任务集**（判据见 C21 的敏感性分析：剔除后 D/A 步骤比 1.402 → 1.278、token 比 0.876 → 0.753，两条结论都不翻转，而改 fixture 会让 C12 直接把 live 证据判为陈旧、必须整轮重跑）。④失败观察的构成来自**代表性复现**（在 pristine fixture 上重跑失败命令），不是当轮轨迹的原样重放。⑤只对本模型、本任务集、本轮 120 行成立 |
| 状态 | 已证实（本机单模型、诊断性） |

### C21 · ts fixture 的两条边界：工具链获取链与成功谓词（TF-0082）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物 + 本机文件事实做确定性分解（不调用 API）：①`ts_fix_type_error` 在条件 D 下 3 次运行共 **15 次 exec 调用 / 754 tok**，逐类为**裸名启动失败 6 次 / 288 tok**（PATH 上无扩展名的 POSIX `npm` / `npx` 抢在 `npm.cmd` 前面被选中，`exec.run` 拿它启动必然失败）、**缺 typescript 的失败 3 次 / 409 tok + 安装绕行 3 次 / 48 tok**、**任务真正需要的验证 3 次 / 9 tok**；②A 也付这条边界（3 次运行 11 次工具链相关调用 / 990 tok），但 raw shell 把读/跑/写折进一条命令，桶会重叠，只能当上界；③把 D 侧这条链剔除后，该任务由 7.333 步 / 427.0 tok 降到 3.333 步 / 178.7 tok，全量 D/A 步骤比 1.402 → **1.278**、token 比 0.876 → **0.753**，**两条结论都不翻转**；④同一 fixture 的成功谓词是**字面 golden 匹配**（`file_contains "return a + b"`），6 次运行里有 **5 次**把类型错误真的改掉了却判失败（D 0/3、A 1/3），而 prompt 承诺的行为只写在 `optional_verify` 里、live runner **从不执行**它（源码里硬编码 `"optional_verify": None`）；⑤`ts_package_script_fail` 本身不需要任何工具链，却仍 3/3 次先发一条注定失败的 `npm test`（144 tok）——这一半与 fixture 无关，纯产品侧 |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 复现命令 | `python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json`，再 `python tools/claim_gate.py` |
| source | `tools/ts_fixture_audit.py`、`bench/aci/results/latest_live.json`、`bench/aci/tasks/ts_fix_type_error.json`、`bench/aci/tasks/ts_package_script_fail.json`、`bench/aci/fixtures/ts_fix_type_error/**`、`bench/aci/fixtures/ts_package_script_fail/**`、`bench/aci/runners/live_agent_loop.py`、`src/process_command.rs`、`eval/ts_fixture_audit.json` |
| 样本量 / 日期 | 两个 ts 任务各 3 次 D 运行 + 3 次 A 运行（live with 臂，seeds 42/43/44）；2026-09-24 |
| 最近实测 | D `ts_fix_type_error` 7.333 步 / 427.0 tok，其中边界 5.0 次调用 / 251.3 tok（裸名 2.0 次 / 96.0 tok、缺 typescript 1.0 次 / 136.3 tok、安装绕行 1.0 次 / 16.0 tok、真实验证 1.0 次 / 3.0 tok）；剔除边界后 3.333 步 / 178.7 tok。全量 D/A：步骤比 1.402 → 1.278（band [1.278, 1.402]）、token 比 0.876 → 0.753（band [0.753, 0.876]），`conclusion_flips=false`。成功谓词：**5 次「改对了却判失败」**（D 0/3、A 1/3），复算判定与记录成功逐条一致；`live_runner_skips_optional_verify=true`。本机被无扩展名 shim 遮蔽的裸名：`npm`、`npx`、`yarn`、`pnpm`、`corepack` |
| 失效边界 | ①**裸名那一半是机器事实**（性质同 C18）：本机 nvm-for-Windows / nodejs 目录同时有无扩展名 `npm` 与 `npm.cmd`，旧 `resolve_candidate` 先返回无扩展名文件所以必然选错；该缺陷已在本轮修复并由 C22 机检。换一台只有 `.cmd` 的机器这一半不触发，产物会如实记为 `shadowed=false`。②**本工具不执行 tsc**：fixture 无离线 typescript、本机也无全局 `tsc`，所以「`const x: number = a + b` 是合法修复」是**语言事实**而不是实测；要用 `tsc --noEmit` 实测这批补丁，必须先落地离线工具链（TF-0085）。③A 侧分桶是上界：raw shell 把安装、写文件、验证折进一条命令，关键词分类拆不开。④「剔除边界」的反事实只改 D 的 ts 任务（A 也付这条边界，把 A 一起改会把比值推回观测值），所以 band 是**下界→观测值**的区间，不是点估计。⑤成功谓词是字符串级重放（typed ops 直接重放；raw shell 从 `python -c ...write(...)` 一行里解出字面量），不是重跑工作区。⑥只对本模型、本任务集、本轮 120 行成立 |
| 状态 | 已证实（本机单模型、诊断性） |

### C22 · exec 按 PATHEXT 解析裸名（Windows 无扩展名 shim 遮蔽，TF-0083）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在 PATH 上同时存在无扩展名 `npm`（POSIX shim）与 `npm.cmd` 的机器上，`exec.run(["npm", ...])` / `["npx", ...]` 必须按 PATHEXT 解析到可启动的 `.cmd`，而不是把无扩展名脚本交给 Win32。`tools/exec_failure_breakdown.py` 的 `bare_name_probe` 对每个被遮蔽的裸名**通过真实 exec.run** 跑 `<name> --version`，并先用 `<name>.cmd --version` 做对照（对照跑不起来则该名字跳过、不归因于解析） |
| 门槛数字 | `== 1.00`；且本机必须确实存在「无扩展名 shim 遮蔽裸名」的情况、且至少一个名字的 `.cmd` 对照可运行（fail-closed，避免在没有这种 shim 的机器上空过） |
| 复现命令 | `python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json`，再 `python tools/claim_gate.py`；单测：`cargo test --lib process_command` |
| source | `tools/exec_failure_breakdown.py`、`src/process_command.rs`（`resolve_candidate`）、`eval/exec_failure_breakdown.json` |
| 样本量 / 日期 | 本机 5 个被遮蔽的裸名（corepack / npm / npx / pnpm / yarn），每个 1 条裸名命令 + 1 条 `.cmd` 对照；2026-09-24 |
| 最近实测 | **缺陷态**：`npm --version` → `E_EXEC_SPAWN`（resolved 到 `...\nvm\v24.15.0\npm`）、`npx --version` 同样失败；同一时刻 `npm.cmd` / `npx.cmd` / `cmd /c npm` 均 `ok=true exit=0`（11.11.0）。**修复后**：5/5 裸名 `ok=true exit=0`（corepack 0.34.6、npm 11.11.0、npx 11.11.0、pnpm 10.33.2、yarn 1.22.22），`bare_name_probe.pass=true`；同一产物的 C18 rustup shim probe 仍 `pass=true` |
| 失效边界 | ①只覆盖**裸名**（argv[0] 不带路径分隔符、不带扩展名）：显式写 `npm.cmd` 或 `cmd /c npm` 本来就能跑，不在本声明范围内。②这是**本机/平台**事实：换一台 PATH 上没有无扩展名 `npm` 的机器，本声明只报告未触发，门禁按 fail-closed 判失败。③对照判据是 `<name>.cmd --version` 退出码 0，对照不通过的名字会被跳过，所以 `sample_size` 可能小于 PATH 上被遮蔽的名字数。④它只证明**能启动**，不证明被启动程序的业务行为（版本字符串只作为「确实跑起来了」的证据）。⑤与 C18 是同一段代码路径上的两个不同不变量：C18 管「带扩展名的 symlink 不丢调用名」，C22 管「无扩展名的裸名不被不可启动的兄弟文件抢走」。⑥它不覆盖 `exec.run` 之外的启动路径（raw shell 走 `cmd`，本来就有 PATHEXT 语义） |
| 状态 | 已证实（本机，Windows + nvm-for-Windows/nodejs） |

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
- C16 是**客户端渲染**声明：它测的是参考客户端把读取信封渲染给模型时的体积，不是产品契约，也不是模型能力；引用时必须带上「产品信封未变」与「>10 行窗口仍保留 `total_lines`」两条边界。
- C17 是**诊断**声明：它说明 D 的读取用在哪，用来决定该不该动提示词或工作区清单。引用时必须带上「`unreferenced` 不等于无用」与「token 是按路径均摊」两条边界，不得写成「D 有 25% 的读取是浪费」。
- C18 是**平台缺陷**声明：它守住「启动名不被 canonicalize 破坏」这一条不变量，只对本机 rustup 软链 shim 生效。引用它时必须带上「硬链接/复制形态不覆盖」「无 symlink 权限时回归用例退化」两条边界；**更要紧的是**：引用 2026-09-24 之前的 D 侧 exec 数字时，必须同时引用 C18，因为那批数字是在缺陷态下测的。
- C20 是**诊断**声明：它说明 D 多出来的步骤是 typed-op 拆分的结果，不是浪费。引用时必须带上「重复调用是上界」「多合一是启发式」两条边界，不得写成「D 有 8.8% 的步骤是浪费」。
- C21 是**任务集边界**声明：它把 ts fixture 的获取链拆成产品侧（裸名 `npm`/`npx` 解析缺陷）与环境侧（fixture 不带 `node_modules`），并给出剔除后的 D/A 比值区间。引用时必须带上「裸名那一半是机器事实」「本工具不执行 tsc」「band 是下界→观测值」三条边界，不得写成「ts 任务 59% 的 token 是浪费」；它也不替代 C13 的成功率口径——成功谓词的缺口由 TF-0084 跟踪。
- C22 是**平台解析**声明：它守住「裸 `npm`/`npx` 必须解析到可启动的 PATHEXT 候选」这一条不变量，与 C18 是同一段代码路径上的两个不同缺陷。引用时必须带上「只覆盖裸名」「本机事实、无遮蔽的机器判失败」「对照不通过的名字会被跳过」三条边界，不得写成「exec.run 在 Windows 上已经完全等价于 cmd」。
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

## 7. L3 观察质检（不进 C1–C22 门禁）

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

