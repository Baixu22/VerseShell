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
# C12 会在上面三份产物缺少指纹或指纹过期时失败；按提示重跑对应 runner 即可
# C13：live A/D 对比（真实模型，凭据只经环境变量）
python bench/aci/runners/live_agent_loop.py --full --model <model> --base-url <endpoint> --max-turns 8
```

## 3. 声明表（C1–C13）

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
| 样本量 / 日期 | 5 项操作 × 3 shell（Bash 无 Disk 等价命令，故 4 项）× 20 次 + 3 次预热；2026-09-22 |
| 最近实测 | worst 0.2109（CPU info，4.7x）；Disk 0.0313（28.6x）、List 0.0406（24.6x）、Read 0.0817（12.2x）、Pipeline 0.0646（15.5x）；`all_commands_ok=true` |
| 失效边界 | 墙钟测量，含进程启动开销，只代表本机与当前工具链（AMD Ryzen 7 7745HX / Windows PowerShell 5.1 `-NoProfile` / Git Bash）；不测吞吐、内存、并发；门禁读的是**已存产物** `eval/cross_shell.json`，改动热路径后必须重跑 runner 才会更新（C12 会判陈旧）；每次重跑数字都会小幅漂移，README 表格必须与产物逐行一致（由 C10 检查）；README 里旧的 v0.5.1 数字（3.7x / 14.4x / …）已作废并被本声明取代 |
| 状态 | 已证实（本机单次测量） |

### C12 · 证据新鲜度（产物指纹）

| 维度 | 内容 |
|------|------|
| 主张原文 | 门禁依赖的三份已存测量（ACI-Bench mock 结果、L3 观察质检报告、跨 shell 基准）都记录了生成时被测代码面的 sha256 指纹，且该指纹与当前代码重算结果一致——也就是说这些数字描述的仍是当前实现，而不是两个月前的实现 |
| 门槛数字 | 三份产物的记录指纹与重算指纹全部一致（`>= 1.00`） |
| 复现命令 | `python tools/claim_gate.py`；重跑产物用 `python bench/aci/runners/run_suite.py --mode mock`、`python tools/jev_obs_judge.py`、`python tools/cross_shell_bench.py` |
| source | `bench/aci/results/latest.json`、`eval/jev_obs_report.json`、`eval/cross_shell.json`、`tools/claim_gate.py` |
| 样本量 / 日期 | 3 份产物；2026-09-22 |
| 最近实测 | 3/3 fresh（PASS）。引入本声明前的产物（如 2026-07-27 的 bench 结果）没有指纹字段，会被直接判失败 |
| 失效边界 | 只覆盖登记在 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 的三份产物；指纹是**文件内容哈希**，不含运行环境（OS / 工具链 / CPU），所以换机器重跑不会因环境不同被判陈旧——跨机器可比性仍受 C11 的边界限制；产物未记录指纹时判失败（fail-closed） |
| 状态 | 已证实 |

### C13 · live A/D 对比（真实模型，单机单模型）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在一个真实函数调用模型（本地 OpenAI 兼容端点上的 `sn-glm-5-3-flash`）上跑 ACI-Bench 全量 10 任务 × 2 条件：条件 A（raw shell）与条件 D（VerseShell ACI）的成功率相同（0.6），但 D 的工具调用数与观察 token 都约为 A 的 2–2.6 倍。**在该模型与该任务集上，ACI 没有减少步骤或 token** |
| 门槛数字 | 无（负向结论，只登记事实，不设通过门槛） |
| 复现命令 | `python bench/aci/runners/live_agent_loop.py --full --model <model> --base-url <endpoint> --max-turns 8` → `bench/aci/results/latest_live.json`、`live_REPORT.md` |
| source | `bench/aci/runners/live_agent_loop.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_baseline_preharnessfix_2026-09-22.json`、`bench/aci/tasks/*.json` |
| 样本量 / 日期 | 10 任务 × 2 条件 × 1 模型；修复前/后各一次完整运行；2026-09-22 |
| 最近实测 | 修复前：A 0.6 / 2.7 tools / 151.8 tok，D 0.6 / 5.4 / 306.4（比值 2.00 / 2.02）；修复后：A 0.6 / 2.8 / 152.1，D 0.6 / 6.5 / 399.0（2.32 / 2.62）。D 仅在 `windows_path_normalize_edit` 明显更省（0.34x token） |
| 失效边界 | ①**单模型单次**：未固定温度/种子，同一任务两次运行的 token 可差 1.5–3 倍（例：rust_fix_compile_error 187→590），因此两次全量跑的比值差异（2.02 vs 2.62）**不能**归因于 harness 修复；方向（D 更费）在两次运行中一致，量级不可外推。②观察 token 用 `len(text)//4` 估算，不是真实 tokenizer。③成功判定是任务自带的文件谓词，不要求真的跑测试（A 常常不跑测试也满足）。④本机 `tsc` 缺失、裸 `pytest` 在 Windows 上因 console-script 的 `sys.path` 行为失败（规范形式 `python -m pytest`），两条件同样受限。⑤**与 mock 的 C1/C2 不可混用**：mock 的 D 直接套 GOLDEN 补丁，0.106/0.55 是评分管线自检，不是能力测量 |
| 状态 | 已证实（本机单模型，负向结论） |

## 4. 与 README 主张的对应关系

- README 若出现 C1/C2 类数字，必须写成「mock bench，10 任务/条件，seed 42」并指向 `eval/evidence.json`，不得写成真实模型实测。
- C9 是**分层**声明：可以说「小响应信封 ≥40% 节省（实测 42.4%）」，不得把它写成「compact 整体省 50–70%」或「观察载荷省一半」——后者实测为负。
- C5 未证实：README 不得出现「上手成本低」「零学习成本」这类肯定句。
- C10 是**兜底**声明：README 新增任何可执行示例或实现类数字时，先在 `tools/readme_claims_check.py` 的 registry 里加一条，否则它不受门禁保护。它也逐行校验 README 的跨 shell 表格与 `eval/cross_shell.json` 一致——重跑 `tools/cross_shell_bench.py` 后必须同步更新 README 表格。
- C11 是**本机**声明：README 的跨 shell 表格必须与 `eval/cross_shell.json` 的实测一致，不得写成跨机器保证；改动热路径后必须重跑 `tools/cross_shell_bench.py`。
- C12 是**证据新鲜度**声明：改动被测代码后先重跑对应 runner（`run_suite.py` / `jev_obs_judge.py` / `cross_shell_bench.py` / `live_agent_loop.py`）再跑门禁；产物缺少指纹时直接判失败（fail-closed），不允许用旧数字过门禁。
- C13 是 **live** 声明：引用真实模型结果时必须同时给出模型、端点、运行次数与方差边界；不得把 mock 的 C1/C2 数字写成真实模型实测，也不得用 live 的负向结论否定 mock 的管线自检作用（两者口径不同）。
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

## 7. L3 观察质检（不进 C1–C13 门禁）

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

