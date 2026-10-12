# 声明-证据矩阵（claims-and-evidence）

> **2026-10-09 当前入口**：第3节保留历史登记与阈值，不代表当前树全部通过。
> 当前状态以 `claim_gate.py` 输出的 `claim_inventory` / `.claims.md` 为准，逐项列出实际选定文件、摘要、版本、样本量及限定状态。
> `verified_current_check` 只表示该次当前控制检查；`verified_selected_measurement` 只验证所选证据的限定命题，可含历史数据，不授予当前模型效果或整体产品结论。
> 真实完整重复、独立任务/作者来源以及新冻结开发验收仍须各自证据，不能用本表、森林状态、单轮完成或元数据匹配替代。
> 路由与原始结果保留规则见 [TF-0140](claim-routing-2026-10-09.md)。

> **2026-10-06 更正**：下方 eval/ 与 r15 数字为历史基线。c20/c21 为旧评分器和
> D-only compact 描述下的工程采集，不能证明当前代码已通过验收，也不能单独归因于接口。
> 本次修复、离线证据和 Step 5 P 复测边界见 [修复报告](c20-c21-repair-2026-10-06.md)。

> **2026-09-30 候选状态**：C16 新候选改变了模型可见格式与请求协议，旧 r15 数字
> 属于历史基线，不能代表当前树的新鲜验收。指定模型的新采集已启动，C14 原门槛与
> 失败结论保留，C16 待实测。见 [前置准备回执](pre-live-preparation-2026-09-30.md)。

> **Live区间范围说明（P2-4）**：本文件历史live模型结果的区间默认未包含独立完整重跑的不确定性。比值为任务聚类口径，Wilson/配对t各有其假设；不同seed的离散度不是独立跑间方差的可识别估计，也不是其下界。新方法和输入要求见 `docs/repeated-run-protocol.md`，真实重复数据尚未到位，不能把旧区间称为跨运行已校准区间。

> task-forest 节点：TF-0007（步骤6）。上游输入：`eval/manifest.json`（步骤5）、mock bench 结果、README/docs 里的对外主张。
> 机器读取方：`tools/claim_gate.py` → `eval/evidence.json`。**门槛数字以本文件为准**，改门槛必须同时改两处。
> 纪律：任何对外数字（README / docs / 演示）必须能在本文件找到一行声明，且该行带 `门槛 / 复现命令 / source / 失效边界 / 状态`。未过线或未证实的声明**不得**以肯定口吻写进 README。

## 1. 状态定义

| 状态 | 含义 | 允许的措辞 |
|------|------|-----------|
| 已证实 | 确定性指标，仓库内一条命令可复现，样本来源在仓库内 | 可用肯定句，并注明命令 |
| 实验室 | 只在受控/模拟条件下成立（如 mock 轨迹、单机小样本），未在真实模型上复测 | 必须写明「mock/受控条件下」 |
| 未证实 | 无确定性指标或未测量 | 只能写成待验证/未知，不得进 README 主张 |

## 1.5 口径对照表（每个 token / usage / cost 数字到底在数什么）

> **先读这一节再读第 3 节。** 下面这些数字来自几种互不相通的口径；混用（相加、平均、互相换算）会让结论看起来变了方向。

| 口径名 | 定义 | 不是什么 | 出现在哪些 claim |
|------|------|---------|----------------|
| `observation_tokens`（观察 token 代理） | `max(1, len(text)//4)`，对**交付给模型的观察文本**计数 | **不是**模型输入 usage；**不是**花费；**不是**真实 tokenizer 计数 | C1、C13–C17、C19、C20、C21、C25、C28、C30 的「观察 token」与 D/A 比值 |
| `llm_prompt_tokens`（端点输入 usage） | 端点自己报的 input usage，**跨每一次请求累加**（system prompt + tool schema + **重发的历史** + reasoning） | **不是**某一次请求的 system prompt／工具 schema 大小——**不得**用它的均值推出「D 的 system prompt 比 A 大 N%」 | C13、C25、C28 的 `usage/prompt_token_ratio` |
| `llm_completion_tokens`（端点输出 usage） | 端点自己报的 output usage | **不是**可见答案的字符数：reasoning 是否计入账单的边界**未确认**，所以不能用它反推「答案短了 N%」 | C13、C25、C28 的 `completion_token_ratio` |
| usage 合计 | input + output usage | 在没有价格／缓存规则之前**不是**金额；不得写成「省了多少钱」或「便宜 N%」 | C13、C25、C28 |
| `cl100k_base` 重放（C27 校准） | 对**同一份抽样观察文本**的独立 BPE 计数（`tiktoken:cl100k_base`，tier 1） | **不是**被测模型（`sn-glm-5-3-flash`）的 tokenizer；**不是**整轮 usage；**不得**用它去修正端点 `usage`，也不得与端点 `usage` 相加/平均 | C27 |
| `cost_per_success` / CPST | **观察 token 代理** ÷ 成功数（当前实现） | 名字里有 "cost"，但**不是**货币金额 | C13 的历史行、C28、`docs/acceptance-criteria.md` §4.3 |
| C9 的 token 代理 | `ceil(bytes/4)`（`examples/compact_ratio.rs`，**按字节**） | 不是 `len//4`（按字符）；不是真实 tokenizer。C9 的 headline 取 byte 与 token 代理中**更小**的一侧 | C9 |
| C34 的份额 | **字符数**之比（命名信封开销 = `line_wrapper` + `counts` 的字符数） | **不是** token、不是代理、不是 usage | C34 |

两条校准附带说明（都属 C27 的产物 `eval/token_proxy_calibration.json`）：

- `ratio_check.published_proxy_ratio_D_over_A = 0.8855` 的**来源不可考**：产物只记录了这个数，没有记录它取自哪一轮／哪份产物（历史条目里出现过同值的第 9 轮 D/A）。它**不得**当作当前整轮 D/A 基线；当前整轮 D/A 必须用 live 产物的按任务聚类区间。
- 校准样本是**重放子集**：`sample_source = replayed_live_trajectories`、`max_units = 30`，每个单元取两条件各一格 → **60 个观察文本（raw_shell 30 + verseshell_aci 30）**，来自**已存 live 轮次**（r15 的 `bench/aci/results/latest_live.json`，315 行）的重放，**不是整轮**；样本偏短观察，长观察只由合成 fallback 语料代表。
- **r15 的校准是离线重建**（`--no-endpoint`）：`endpoint_cross_check.enabled = false`、`conclusion = "endpoint cross-check disabled"`，所以**端点交叉核对本轮未重测**（端点逐请求延迟使完整探针不可行），须由测试方在下一次校准中重跑；r15 的头条（mean **1.2872** / median **1.2485**）只来自 `cl100k_base` 重放，不含端点读数。字节不变量是 `real_tokens <= utf8_bytes`（**0/71 违反**）；旧的 `real_tokens <= chars` 上界**已撤回**（cl100k_base 是字节级 BPE），反例仍是 CJK 278 字符 / 284 real token。

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
# C23：ts 任务的成功判定必须是行为判定（pristine 失败、GOLDEN 通过）
python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json
# C24：每个带 GOLDEN 的任务都必须 pristine 失败、GOLDEN 通过（等价变体也必须通过）
python tools/task_set_audit.py --out eval/task_set_audit.json
# C20：D 与 A 的步骤构成分解（确定性，无 API 调用）
python tools/step_composition.py --out eval/step_composition.json
# C21：ts fixture 的工具链获取链与成功谓词边界（确定性，无 API 调用）
python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json
# C5：只读 quickstart 的学习成本（真实模型调用，每次 op 都经真实 ae --serve --agent）
python tools/aci_learning_probe.py --repeat 3 --out eval/aci_learning_probe.json
# C25：live 数字的不确定性（Wilson / McNemar / bootstrap，无 API 调用）
python tools/live_uncertainty.py --out eval/live_uncertainty.json
# C26：参考客户端的投影契约（真实 op，逐条检查工具描述承诺的字段是否真的到达模型）
python tools/projection_contract.py --out eval/projection_contract.json
# C27：观察 token 代理对真实 tokenizer 的校准（cl100k_base，离线可跑）
python tools/token_proxy_calibration.py --out eval/token_proxy_calibration.json
# C28：样本量／精度验收——「现在有没有资格下这个结论」
python tools/acceptance_power.py --out eval/acceptance_power.json
# C29：任务准入判据——生成的候选能不能进能力集
python tools/task_admissibility.py --out eval/task_admissibility.json
# 一次重刷全部 live 派生产物（按依赖顺序，末位是上面两条）
python tools/refresh_live_artifacts.py
```

## 3. 声明表（C1–C24）

> **r15-2026-09-29 基线刷新（当前）**：全链已按 r15 刷新（task set 3.0.0；with / without 各 315 行、各 105 对；两臂 `api_error_rows=0`）。**已经换成本轮数字的条目**：C9、C11、C12、C13、C14、C16、C25、C27、C28、C34。**仍是各自轮次标号的诊断条目**（C15、C17、C19、C20、C21，标为「第 10 轮」/「第 9 轮」）是**历史读数**，尚未重新引用 r15 数字——引用它们时必须写明轮次，不得当成当前基线。r15 是**基线刷新**（结构/端点健康核验），**不是预注册的确认性采集**，其刷新数字不得当作新的已确证效应。**每个 token/usage/cost 数字的口径见 §1.5。**

### C1 · 观察 token 比（mock bench）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在 ACI-Bench mock 任务集上，条件 D（verseshell_aci）的单任务平均 observation tokens 不高于条件 A（raw_shell）的一半 |
| 门槛数字 | `token_ratio_D_over_A <= 0.50` |
| 口径 | `observation_tokens` = `max(1, len(text)//4)` **代理**，累加的是 mock 轨迹里交付给模型的观察文本；**不是**端点输入 usage、**不是**花费、**不是**真实 tokenizer 计数。分母是 10 任务/条件、seed 42 的**单任务均值**；mock 的 A 臂固定发全量日志，所以这个比值由脚本内置轨迹决定，不是模型行为（见失效边界） |
| 复现命令 | `python tools/claim_gate.py`（数据来源 `bench/aci/results/latest.json`，由 `python bench/aci/runners/run_suite.py --mode mock` 生成） |
| source | `bench/aci/results/latest.json`、`bench/aci/runners/run_suite.py`、`bench/aci/tasks/*.json` |
| 样本量 / 日期 | mock，10 任务/条件，seed 42，task_set_version 1.3.0，数据生成于 2026-09-24 |
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
| 样本量 / 日期 | mock，10 任务/条件，seed 42，task_set_version 1.3.0，2026-09-24 |
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

### C5 · 学习成本可被 coding agent 吸收（只读 quickstart）

| 维度 | 内容 |
|------|------|
| 主张原文 | 一个 coding agent **只读 quickstart** 就能正确使用主合同（typed op + 观察信封），无需额外人工辅导。可复现指标定义为：把 `docs/quickstart/aci-mcp.md` **单独**作为 system prompt（不给 tool schema、不给文档以外的示例），要求模型一次性输出 JSON-RPC op 行，**每一行都经真实 `ae --serve --agent` 执行**，统计「服务端接受率」 |
| 门槛数字 | `op_acceptance_given_ops_emitted >= 0.70`。该口径的分母**排除「一个 op 都没输出」的格**：那种格是模型的**格式**失败，不是合同被拒；把它算进分母等于用「模型这次答了散文」去指控文档。同口径的 `first_attempt_op_acceptance`（不排除）与 `task_success` 一并报告但不设门槛（后者还取决于模型能力） |
| 复现命令 | `python tools/aci_learning_probe.py --repeat 3 --out eval/aci_learning_probe.json`，再 `python tools/claim_gate.py` |
| source | `tools/aci_learning_probe.py`、`docs/quickstart/aci-mcp.md`、`eval/aci_learning_probe.json` |
| 样本量 / 日期 | 5 个探针任务（write_file / read_window / exact_edit / search_then_report / exec_and_report）× 3 次重复 = 15 格真实模型调用 |
| 最近实测（定版，`--repeat 3`，15 格） | **门槛值 `op_acceptance_given_ops_emitted = 10/14 = 0.7143`（PASS，仅高出 0.014）**；同口径 `first_attempt_op_acceptance = 10/15 = 0.6667`、`task_success = 4/15 = 0.267`、`hash_handoff_rate = 1/3 = 0.333`、`rows_with_no_ops_emitted = 1`、`api_error = 0`。**修复前的缺陷态证据**：单轮探针 `op_acceptance_given_ops_emitted = 2/5 = 0.40`（不达标），失败原因是模型逐字照抄 quickstart 里的字面占位符 `"expected_hash":"<from file.view>"` → `E_STALE_HASH`（当轮 `hash_handoff_rate = 1.0`，但那是抄文本，不是交回摘要），以及 `repo.search` 投影丢匹配（C26）导致 `search_then_report` 必败。**注意定版值明显低于修复后单轮观测的 4/4 = 1.00**：探针样本只有 15 格、且要求一次性输出 JSON 行，波动大；0.7143 这个通过是**边际**的，不得引用成「quickstart 已被证明好用」 |
| 失效边界 | ①这是**文档充分性**测量，不是产品能力测量：探针任务是 5 个自造小场景，且要求模型一次性输出 JSON 行（真实 agent 走 tool-calling 通道，形状不同）。②它只覆盖 quickstart 文档里写到的 op；文档没写的 op 不受保护。③「没输出 op」与「op 被拒」被刻意分开，所以 0.70 这个门槛**不**覆盖格式失败率——后者见 `first_attempt_op_acceptance`。④端点不严格复现 seed，3 次重复给的是经验区间而非确定性复算。⑤与 C10 的分工：C10 校验 README 里**登记过**的示例，quickstart 的示例此前不在任何门禁内——C5 的探针是它第一次被真实调用检验 |
| 状态 | 已证实（真实模型调用；修复前的 0.40 是缺陷态证据） |

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
| 口径 | 「节省」有两把尺子，headline 取**更小**的一侧：`byte_savings`（真实字节，`json_text.len()` vs `compact_text.len()`）与 `token_savings`。这里的「token」是 `examples/compact_ratio.rs::rough_token_count` = **`ceil(bytes/4)`（按字节）**，与 C13–C27 的观察 token 代理 `len(text)//4`（按字符）**不是同一个量**，更不是真实 tokenizer；**不是**端点 usage、**不是**花费。round-trip 检查的是无损性，与 token 数无关；分母是 2 个响应信封 + 5 个观察载荷（确定性复算） |
| 复现命令 | `cargo run --example compact_ratio -- --out eval/compact_ratio.json`，再 `python tools/claim_gate.py` |
| source | `examples/compact_ratio.rs`、`src/compact.rs`、`src/server.rs`、`eval/compact_ratio.json` |
| 样本量 / 日期 | 5 个观察载荷（1 个真实 `ops.list` 观察 + 4 个对抗 fixture 的 reducer 观察）+ 2 个响应信封，确定性复算 |
| 最近实测（r15-2026-09-29，产物 `eval/compact_ratio.json`） | 小响应信封 `response_small_hash`：byte 节省 **42.39%**、token 代理（`ceil(bytes/4)`）节省 **0.4203** → 门禁 C9 = **0.4203**（≥0.40 **PASS**）；观察载荷族合计 **−3.1%**（compact 略大，最差 **−4.5%**）、嵌套大响应 `response_ops_list` **−2.5%**；观察载荷 5/5 round-trip 通过（响应行没有解码器，未做 round-trip）。**历史**：2026-09-22 记的 42.4% / −3.1% / −2.4% 是同一形态的旧一轮读数 |
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
| 最近实测（r15-2026-09-29 全链刷新后 PASS） | 12/12 PASS（检查集仍为 7 示例 + 5 数字；原记 2026-09-22）。修复前 9/12：`reduce`、`reverse` 两个文档示例跑不通；README 的「4 Criterion 套件 / 50 integration tests」与源码真值（5 / 52）不一致。**注意**：r15 重跑 `cross_shell_bench.py` 后 README 跨 shell 表一度使 C10 变红，按回执 F5 用 `sync_readme_cross_shell.py` 同步 5 行后恢复 PASS——这是设计行为（重跑基准必须更新 README 表），不是放宽检查 |
| 失效边界 | 只覆盖脚本内**显式登记**的条目，不覆盖自由散文；README 中未登记的实现类数字（例如「28-arm match」「~50 builtins」「26 modules」）需先加进 registry 才会被检查 |
| 状态 | 已证实 |

### C11 · 跨 shell 墙钟对比（本机）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在同一台机器上，用各 shell 的**语义等价**命令各跑 20 次（**交错执行**、丢弃 3 次预热、计时阶段丢弃 stdout/stderr）后，VerseShell 五项常用操作的中位耗时都不高于 **PowerShell** 的 0.5 倍。**「等价」必须先被证明**：每项操作把每个 shell 的 stdout 归一化成一个语义键（CPU 型号 / 盘符集合 / 目录项集合 / 文件内容 sha256 / 流水线结果），**所有被测 shell 必须给出同一个键**——退出码相同不算数 |
| 门槛数字 | `worst_ratio_ae_over_pwsh <= 0.50` **且**所有命令退出码为 0 **且** `all_outputs_equivalent=true` **且**执行是交错的（§2 的三条要求一起构成 pass 条件） |
| 复现命令 | `python tools/cross_shell_bench.py --iterations 20 --warmup 3`（写 `eval/cross_shell.json`），再 `python tools/claim_gate.py` |
| source | `tools/cross_shell_bench.py`、`eval/cross_shell.json`、`README.md` |
| 样本量 / 日期 | 5 项操作 × 4 shell（Bash 无 Disk 等价命令、cmd 无流水线等价命令）× 20 次**交错**迭代 + 3 次预热 + 1 次冷启动；2026-09-26（v2 协议） |
| 最近实测（r15-2026-09-29，产物 `eval/cross_shell.json`） | **输出等价 5/5 全部证明通过**。**vs PowerShell**：worst **0.1834**（CPU info），Disk 0.0302、List dir 0.0413、Read file 0.0708、Pipeline 1K 0.0622 —— 5/5 严格更快且 ≥2 倍（区间按迭代配对），`all_commands_ok=true`。**vs cmd.exe（裸 shell 基线臂实际使用的 shell）：worst 3.3868 —— ae 在 CPU info 上比 cmd.exe 慢 3.4 倍**，List dir 1.20 倍、Read file 0.93 倍（略快）、Disk info 0.63 倍。**端到端语境（r15）**：工具时间只占一轮墙钟中位数的 **A 1.08% / A′ 1.62% / D 4.50%**，其余是端点推理延迟 |
| 历史实测（v2 协议，2026-09-26；已被 r15 取代，保留作对照） | **输出等价 5/5 全部证明通过**。**vs PowerShell**：worst **0.2682**（CPU info），Disk 0.0358、List dir 0.0447、Read file 0.0799、Pipeline 1K 0.0663 —— 5/5 严格更快且 ≥2 倍，`all_commands_ok=true`。**vs cmd.exe（裸 shell 基线臂实际使用的 shell）：worst 3.3859 —— ae 在 CPU info 上比 cmd.exe 慢 3.4 倍**，List dir 1.27 倍、Read file 0.95 倍也都不快，只有 Disk info 快（0.71）。**端到端语境**：工具时间只占一轮墙钟中位数的 **A 2.85% / A′ 1.76% / D 7.36%** |
| v2 协议修掉的三个不公平（全部由等价检查发现，不是猜的） | ①PowerShell 的 List dir 用了 `Get-ChildItem -File`，**只列文件**，而 `file.ls` / `dir /b` / `ls -la` 都列目录 → 旧对比等于让 PowerShell 做更少的事；②PowerShell 的 Read file 用 `Get-Content -Raw` 未指定编码，**按 ANSI 代码页解码 UTF-8 文件**，读到的字节与 `type` / `cat` 不同（等价检查用内容 sha256 直接抓到）；③旧实现在两个 shell 上**独立重抽**区间，而 v2 是交错执行，必须**按迭代配对** |
| 失效边界 | ①墙钟测量，含进程启动开销，只代表本机与当前工具链（AMD Ryzen 7 7745HX / Windows PowerShell 5.1 `-NoProfile` / cmd.exe / Git Bash）；不测吞吐、内存、并发。②门禁读的是**已存产物**，改热路径或改 live 基线后必须重跑 runner（C12 会判陈旧）。③**「≥2 倍」只对 PowerShell 成立，而 PowerShell 不是基线臂使用的 shell**——引用时必须同时说明，否则读者会以为 ACI 比裸 shell 快 2 倍。④CPU info 这一项两边都在跑 WMI（ae 的 `sys.cpu_info()` 与 PowerShell 的 `Get-CimInstance`），测的其实是 WMI 而非 shell；`ae` 在这项上慢 3.4 倍主要来自 WMI 的固定成本。⑤等价键是**语义投影**，不是逐字节相等：格式不同（JSON vs 文本）是设计使然，键相同只说明「算的是同一件事」；某个 shell 的输出若无法归一化，记为**未验证**而不是通过。⑥每次重跑数字都会漂移，README 表格必须与产物逐行一致（由 C10 检查） |
| 状态 | 已证实（本机单次测量；v2 协议：等价已证明、交错执行、按迭代配对） |

### C12 · 证据新鲜度（产物指纹）

| 维度 | 内容 |
|------|------|
| 主张原文 | 门禁依赖的**登记产物**（最初 12 份，r15-2026-09-29 时已扩到 **25 份**；以 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 为准：ACI-Bench mock 结果、live A/D 结果、L3 观察质检报告、跨 shell 基准、批量读取信封复算、exec token 分解、读取桶紧凑投影、读取用途审计、exec 失败分解、步骤构成分解、ts fixture 边界审计、任务集自洽性审计，以及后续登记的产物）都记录了生成时被测代码面的 sha256 指纹，且该指纹与当前代码重算结果一致——也就是说这些数字描述的仍是当前实现，而不是两个月前的实现 |
| 门槛数字 | 登记产物的记录指纹与重算指纹**全部一致**（`>= 1.00`；r15 为 **25/25**） |
| 复现命令 | `python tools/claim_gate.py`；重跑产物用 `python bench/aci/runners/run_suite.py --mode mock`、`python tools/jev_obs_judge.py`、`python tools/cross_shell_bench.py`、`python bench/aci/runners/live_agent_loop.py`（再 `merge_live_runs.py`）、`python tools/tf45_envelope_replay.py`、`python tools/exec_token_breakdown.py`、`python tools/read_path_breakdown.py`、`python tools/read_usage_audit.py`、`python tools/exec_failure_breakdown.py`、`python tools/step_composition.py`、`python tools/ts_fixture_audit.py`、`python tools/task_set_audit.py` |
| source | `bench/aci/results/latest.json`、`bench/aci/results/latest_live.json`、`eval/jev_obs_report.json`、`eval/cross_shell.json`、`eval/tf45_envelope_replay.json`、`eval/exec_token_breakdown.json`、`eval/read_path_breakdown.json`、`eval/read_usage_audit.json`、`eval/exec_failure_breakdown.json`、`eval/step_composition.json`、`eval/ts_fixture_audit.json`、`eval/task_set_audit.json`、`tools/claim_gate.py` |
| 样本量 / 日期 | 登记产物（最初 12 份，r15 为 **25** 份）；r15-2026-09-29（全链刷新后） |
| 最近实测（r15-2026-09-29） | **25/25 fresh（PASS，首次）**——全链刷新后登记的全部 25 份门禁产物指纹都与重算一致（`c12-staleness-r15.json`）。引入本声明前的产物（如 2026-07-27 的 bench 结果）没有指纹字段，会被直接判失败 |
| 失效边界 | 只覆盖登记在 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 的产物（以代码清单为准）；`live_ab_without_read_files.json` 是配对对照臂，按设计不进 C12（重跑时机由 C13 记录），但它是 `eval/exec_token_breakdown.json`、`eval/read_usage_audit.json`、`eval/exec_failure_breakdown.json` 与 `eval/step_composition.json` 的输入，所以那四份产物会随它一起更新。`eval/ts_fixture_audit.json` 的指纹额外覆盖 `src/process_command.rs`、`bench/aci/tasks/ts_*.json` 与两个 ts fixture；`eval/task_set_audit.json` 覆盖**全部** `bench/aci/tasks/*.json` 与 `bench/aci/fixtures/**`——**改动任何任务或 fixture 都会让 live 证据与本产物一起被判陈旧**（C21/C23/C24 的边界因此是机检的，不靠约定）。指纹是**文件内容哈希**，不含运行环境（OS / 工具链 / CPU），所以换机器重跑不会因环境不同被判陈旧——跨机器可比性仍受 C11 的边界限制；产物未记录指纹时判失败（fail-closed） |
| 状态 | 已证实 |

### C13 · live A/D 对比与 read_files A/B（真实模型）

| 维度 | 内容 |
|------|------|
| 主张原文 | 在真实函数调用模型 `sn-glm-5-3-flash`（本地 OpenAI 兼容端点）上跑 ACI-Bench，**v2.0.0 起为三臂设计**：`raw_shell`（A，中性裸 shell）、**`raw_shell_coached`（A'，与 D 同等详细的 shell 提示，C1 提示词等量对照）**、`verseshell_aci`（D）。**只有 D vs A' 这一支能把效应归因于接口本身**；D vs A 仍含「提示词写得好」的混杂。**当前基线是 r15-2026-09-29**（task set **3.0.0**，35 任务 × 3 条件 × 3 seeds = **630 格**；with / without 各 **315 行**、各自 **105 对**；两臂 `api_error_rows=0`）——但它是一次**基线刷新（结构/端点健康核验）**，**不是预注册的确认性采集**（L1/L2/L3 未完成），所以刷新的数字**不得**当作新的已确证效应引用。以下按轮次排列，历史行保留作逐轮对照。 |
| 最近实测（**r15-2026-09-29 基线刷新（当前）**，task set 3.0.0，产物 `bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/live_uncertainty.json`、`eval/acceptance_power.json`） | **630 格全部完成，两臂 `api_error_rows=0`**；with 臂 **315 行 / 105 对**，三臂（各 105 格）：**A 0.9048（95/105）/ 4.73 工具 / 1266.8 观察 token；A′ 0.8952（94/105）/ 4.66 / 1084.5；D 0.9333（98/105）/ 4.02 / 769.6**。**任务聚类 bootstrap（D/A）**：观察 token **0.6075 [0.5007, 0.7589]**；工具数 **0.8491 [0.6877, 1.0576]**（跨 1.0）；真实 tokenizer 口径（端点 `usage`）总量 **0.9461 [0.6462, 1.5202]**、输入 **1.0255 [0.6960, 1.6803]**、输出 **0.4259 [0.2706, 0.6583]**。**D/A′（提示词等量）**：观察 token **0.7096 [0.5761, 0.8788]**；usage 总量 **1.0817 [0.7558, 1.5772]**、输入 **1.1876 [0.7923, 1.7834]**、输出 **0.4492 [0.3716, 0.6425]**；工具数 **0.8630 [0.7381, 1.0181]**。**成功率**：D−A **+0.0286**，配对 CI95 [−0.0034, 0.0606]，精确 McNemar 仅 D 独赢 **3** vs 仅 A 独赢 **0**（p=**0.25**，不显著）；D−A′ **+0.0381**。**CPST**：D/A **0.5889**、D/A′ **0.6806**，成功率非劣下界 −0.0034 / +0.0013 ≥ −0.10 → 两条 CPST 声明保持可主张。**预算 / 行策**：没有任何一臂构成 cap 约束（cap 撞上限 A 1/105、A′ 3/105、D 0/105；turn-cap A 1 / A′ 1 / D 0，token-cap A 0 / A′ 2 / D 0），行策排除率 A **0.9%** / A′ **2.9%** / D **0.0%**（第 14 轮 D 为 14.3%）。**without 臂**：A 0.8762 / 4.50 / 1320.5；A′ 0.8952 / 4.60 / 1072.1；D 0.9238 / 4.88 / 730.3；观察 token 比 **0.553 [0.4314, 0.7266]**、usage **0.8984 [0.6691, 1.2288]**。**引用纪律**：r15 是**基线刷新**，不是预注册确认性采集；L1/L2/L3 未完成——上述刷新数字**不得**当成新的已确证效应，第 13/12 轮行保留作历史对照 |
| 最近实测（**2026-10-03 · 预算混淆三点曲线（辅助诊断，非定版）**，模型 hy3，task set 3.1.0，产物 `bench/aci/results/c16-hy3-mt8-20261002/`、`c16-hy3-mt20-20261002/`、`c16-hy3-mt40-20261003/latest_live.json`，报告 `audit-r12-scratch/relay-hy3-2026-10-02/three_arm_report_mt{20,40}.json`） | **目的**：分离「预算效应」与「模型效应」。此前 glm@mt=8 与 dsv41@mt=20 两轮**同时**换了模型与预算，谁也不能归因。做法是**固定模型（hy3）只移动 `max_turns`**。三点：**mt=8** → 撞上限 A/A′/D = **27.7% / 34.0% / 2.1%**，成功率 0.6809 / 0.7447 / 0.9787；**mt=20** → **21.0% / 16.2% / 0.0%**，0.7619 / 0.8000 / 1.0000（315 行、`api_error_rows=0`）；**mt=40** → **8.6% / 10.5% / 0.0%**，0.8952 / 0.8762 / 1.0000（315 行、`api_error_rows=0`）。**三档都没有通过 §0.5**（mt=40 时 A′ 仍 10.5%、两臂排除率 11.4%）。**四条发现**：①**混淆的偏袒方向是模型依赖的**——本模型上被截断的是 A/A′，而 §0.5 记录的是「mt=8 时 D 被截断 64%」，即「typed op 更细 ⇒ D 更费预算」不是普遍规律（详见 `acceptance-criteria.md` §0.5.4）；②D−A 成功率差（ITT 口径）随预算 **+29.8pp → +23.8pp → +10.5pp**，而**可分析口径稳定在 +3.7pp / +3.2pp** → mt=8 那个量级的优势主要是**排除率**产物，不是能力差异；③mt=40 时 **A′(0.8762) 反低于 A(0.8952)**，提示词等量对照的增益在预算充足时消失；④真实 `usage` 的**总账口径随预算 1.227 → 0.456 → 0.335（方向翻转、漂 4 倍）**，而**逐任务口径稳定在 1.82 → 1.66 → 1.58**（D 在 63–72% 的任务上更贵）→ 「D 省 token」只在总账 + 特定预算下成立。**引用纪律**：本条是**辅助诊断**，不是预注册的定版采集，**不得**当作 C13 的刷新数字；hy3 的 mt=8 轮被外部终止（只有 seeds 42/43），按 §0.6.7 记 partial，仅作方向证据 |
| 最近实测（**第 13 轮，2026-09-26，tag `tf0100`：第一次两个预算都不构成约束**） | **修完 A 臂 cp936 崩溃后重跑**（tag `tf0100`，`--arms with --seeds 42,43,44 --max-turns 20`）：**225 行、`api_error` 0**。三臂：**A 0.8400 / 4.35 工具 / 1032.4 观察 token**；**A′ 0.8400 / 4.40 / 723.8**；**D 0.8800 / 3.89 / 578.3**。**§3.3 两个预算都不构成约束**：步数上限 0%/0%/0%、**completion 上限 3%/7%/4%（全部 ≤10%）**、**`harness_crash` 三臂全 0**——这是**第一次**真正通过 §3.3（第 12 轮虽然步数上限 0%，但 completion 上限在 A/A′ 上是 11%/15%，见本文 C11 之后的「预算纪律只量了一半」条与 `docs/audit-r12-verification.md` §5.3）。**与第 12 轮同口径对比**：D−A 成功率 **+0.12 → +0.04**、D−A′ **+0.16 → +0.04**；D/A 观察 token **0.6853 → 0.5601 [0.4654, 0.6832]**；**D/A′ 观察 token 1.0567 → 0.7990 [0.6503, 0.9788]，上界首次低于 1.0**；D/A 工具数 **1.0074 → 0.8943**。**真实 tokenizer 口径仍相反**：总 token D/A = **1.0761 [0.7667, 1.6552]**、D/A′ = **1.2654 [1.0372, 1.613]**（**整段在 1.0 之上**） |
| 第 13 轮 · 三条实质变化 | ①**成功率优势缩到 1/3**：第 12 轮的 +0.12/+0.16 里有一部分是预算造成的——A/A′ 各有 11%/15% 的轮次被 completion 上限截断，被截断的轮次不发工具调用、直接记失败，**压低的是 A/A′**，于是放大了 D 的优势；预算修好后优势掉到 +0.04。②**「提示词拉平后 token 优势消失」这条被推翻**：D/A′ 由 1.0567（跨 1.0）变成 **0.7990（上界 0.9788 < 1.0）**，即相对提示词等量对照也有观察 token 优势（余量 0.021，属薄边通过）。③**D 的工具数由「持平」变「更少」**（1.0074 → 0.8943）。**但**：真实 tokenizer 口径下 D 的总开销仍然更高，且对 A′ 那一支的整个区间在 1.0 之上——「观察 token 更省」与「总开销更贵」在本轮同时成立 |
| 第 12 轮实测（**定版；已被第 13 轮取代，保留作对照**） | task set v2.0.0（25 任务）× 3 条件 × 3 seeds = **225 行**，`api_error` 0，`max_turns=20`，三臂撞上限全 0%。三臂：**A `raw_shell` 0.7067 / 3.60 工具 / 888.1 观察 token**；**A′ `raw_shell_coached` 0.6667 / 3.72 / 576.0**；**D `verseshell_aci` 0.8267 / 3.63 / 608.6**。**所有区间均为按任务聚类的 bootstrap**（同任务三个 seed 相关，ICC 0.28–0.56；行级区间保留在 `bootstrap_ci95_row` 作对照）。**结论必须按口径分开写**：①**成功率**：D−A = +0.12（仅 D 赢 16 格 vs 仅 A 赢 7 格，精确 McNemar p=0.0931）、D−A′ = +0.16（17 vs 5，p=0.0169）；但**按任务聚类后 D−A′ 也不显著**（任务级符号翻转 p=0.0643），且 n=75 < 预注册 105 对 → **只能写「未检出」**。②**观察 token（`len//4` 代理口径）**：D/A = **0.6853 [0.5509, 0.9061]** —— L1（上界 <1.0）可主张，**L2「省 ≥15%」的上界 0.9061 > 0.90，不可主张**；D/A′ = **1.0567 [0.7645, 1.5675]** 跨 1.0 → **不可归因于接口**。③**真实 tokenizer 口径（端点 `usage`，§4.2 硬要求）与代理口径方向相反**：总 token D/A = **1.1932 [0.9117, 1.7419]**、输入 **1.545 [1.1103, 2.4214]**、输出 **0.1709 [0.1172, 0.3496]** —— D 把输出/reasoning 压到约 **1/6**，但每轮输入多约 **55%**，**总账贵约 19%**。④**工具数三臂几乎相等**（3.60 / 3.72 / 3.63；D/A = 1.0074 [0.7667, 1.3527] 跨 1.0 → **无证据**）。**最诚实的表述**：D 的成功率方向有利但样本不足；「省 token」**只在 `len//4` 代理口径下、且只对未加提示的裸 shell 成立**，连 L2 都正压在门槛上；按预注册要求的真实 tokenizer 口径，**D 的总开销更高**。**⚠️ 这一轮同时受 §3.3 污染（A/A′ completion 上限 11%/15%）且不可复现（第 13 轮同条件重跑得到 +0.04/+0.04），不得再单独引用** |
| 第 12 轮 · harness 缺陷修正（2026-09-26） | 裸 shell 的 `execute_shell_cmd` 此前没有指定 `encoding`，cp936 下遇到非 ASCII 输出会让读取线程抛错、`stdout` 变 `None`、`out += ...` 抛 TypeError 并**丢弃整条轨迹**。实测 `raw_shell` **3/75**、`raw_shell_coached` **2/75**、`verseshell_aci` **0/75** 行受影响（26/28 次崩溃落在同一个 UTF-8 fixture 任务上）。**剔除这 5 行后 D−A 从 0.120 降到 0.083、D−A′ 从 0.160 降到 0.137**，即原数字**高估了 D 的优势约 0.04**。修复后登记为门禁项 **C31**，`tools/harness_encoding_contract.py` 会在本机复现机制并锁住回归。**注意**：`bench/aci/results/latest_live.json` 记录的指纹覆盖 runner，所以修复使该基线**合法地变为 stale（C12 转红）**，必须重跑 live 才能刷新 |
| 第 12 轮 · 为什么与第 11 轮相反 | 第 11 轮的 D 是**被参考客户端饿死的 agent**：`file.view` 默认窗口 80 行，而客户端对 >10 行的窗口一律不返回内容，于是 D 只拿到哈希 → 45% 的 `file.view` 在重复查看同一路径 → 绕道 `repo.search`（301 次 / 65.7k token）与 shell 读文件。修掉之后 D 的工具数从 **13.05 → 3.63**、观察 token 从 **1316 → 608.6**，同时成功率从 0.7733 **升到 0.8267**。**这不是「调参调出好结果」**：修的是「工具描述承诺了窗口、客户端却把它丢掉」这个契约违反（C30），修法由 `projection_contract` 的两条新检查 + 负对照锁住，任何人都能复现 |
| 第 11 轮实测（**已被 C30 缺陷污染，仅作缺陷证据保留**） | 225 行、`max_turns=20`：A 0.8267 / 4.40 / 1012.1；A' 0.8133 / 5.07 / 761.9；**D 0.7733 / 13.05 / 1316.0**（D 撞上限 **20%**）。当时结论为「D 更贵、成功率略低」——**该结论是 C30 造成的假象，不得再引用** |
| 第 11 轮 · 为什么 D 更贵（归因） | ①**调用粒度**：D 用 typed op（`file.view`/`file.read_many`/`file.replace_exact`/`exec.run` 各算一次），A 用一条复合 shell 命令完成读+改+跑，所以 D 的步数天然更多；②**检索退化**：D 发出 **97 次 `repo.search`**，其中 `x17` 的查询是 `.`（匹配一切）、`x4` 是 `^`，还有 `\S`/`[a-z]`/`e`——模型把 `search_content` 当裸 grep-regex 用，工具描述（「Text or regex to search for」）没有任何引导或约束。**这是产品改进项，但本轮不改**（改了会作废本轮 run），只登记 |
| 第 11 轮 · 上限敏感性（C25/§0.5） | `max_turns=20` 下 A/A' 撞上限 **0%/1%**，**D 撞 20%**。排除撞上限的 16 行后复算：D/A **1.2086** CI95 [0.9183, 1.633]、D/A' **1.5960** CI95 [1.152, 2.2058]——**D/A' 的区间仍不含 1.0**，所以「D 比 A' 贵」这条结论对上限不敏感；D/A 的区间跨 1，故**只说 A' 那支**。提高上限到 40 会让模型扩张到把预算用光（A 的调用数从 5.24 涨到 9.96，出现 546 秒的单格），所以上限不是中立参数，见 §0.5.1 |
| 第 10 轮实测（task set v1.3.0，已被本轮取代） | 修完 C26（投影）与「completion 上限截断」两个测量缺陷后重跑：with 臂 **A 成功率 0.60 / 3.33 工具 / 154.90 观察 token；D 0.5333 / 3.17 / 120.73**（D/A 工具 **0.95**、token **0.7794**）；without 臂 A 0.60 / 3.30 / 152.97、D 0.5667 / 2.80 / 94.80（D/A **0.8485 / 0.6197**）。**统计（C25）**：成功率差 A−D = +0.0667，**不显著**（合并 z=−0.5211，p=0.602；配对 McNemar 仅 A 独赢 3 格 vs D 独赢 1 格，p=0.625）；token 比 bootstrap **0.7794**，CI95 **[0.601, 1.022]**，`P(比 < 0.60)` = **0.0244**；工具比 **0.95**，CI95 [0.7248, 1.2278]，`P(< 0.70)` = 0.0144。**结论（与上一轮相反，必须照实写）**：修复让 D 的 token 比从 0.8855 改善到 0.7794，但**本轮 D 的成功率不再高于 A**（−0.0667，不显著），且冻结承诺的两条数值门槛仍未以可信度达成。逐轮数字波动很大（端点噪声，见失效边界④⑩），单轮不得当作趋势 |
| 上一轮实测（第 9 轮，已被本轮取代） | with：A 0.6333 / 4.10 / 177.63；D 0.80 / 4.07 / 157.30（D/A 0.9919 / 0.8855） |
| 门槛数字 | 无（中性/负向结论，只登记事实，不设通过门槛） |
| 口径 | 两套数字并列、**不得互换**：①三臂的「观察 token」是 `max(1, len(text)//4)` **代理**，只数交付的观察文本；②「真实 tokenizer 口径」是**端点自己报的 `usage`**，**跨每一次请求累加**（system prompt + tool schema + **重发的历史** + reasoning），所以它是**每次运行的累计输入/输出**——**不是**单次 system prompt／schema 的大小，**不是**可见答案字符数，**不是**花费；③它与 C27 的 `cl100k_base` 重放不是同一口径（端点与 `cl100k_base` 在 CJK/hex 形状上不可互换），**不得互相换算、相加或平均**。比值由按 `(task, seed)` 配对的**任务聚类** bootstrap 给出；`usage` 是每行（每次运行）的累计 usage，不是单个工具调用的量 |
| 复现命令 | with：`python bench/aci/runners/live_agent_loop.py --full --model sn-glm-5-3-flash --base-url <endpoint> --max-turns 8 --temperature 0 --seed <s>`；without：同命令再加 `--exclude-tools read_files`；各跑 seeds 42/43/44 后合并：`python bench/aci/runners/merge_live_runs.py --out <artifact> <per-seed runs...>`（任一行带 `api_error` 即 exit 2，拒绝合并） |
| source | `bench/aci/runners/live_agent_loop.py`、`bench/aci/runners/fixture_deps.py`、`bench/aci/runners/merge_live_runs.py`、`bench/aci/runners/splice_live_cells.py`、`bench/aci/tasks/manifest.json`、`src/process_command.rs`（C18 + C22 修复）、`bench/aci/results/latest_live.json`（with，3 次合并）、`bench/aci/results/live_ab_without_read_files.json`（同期对照，3 次合并）、`bench/aci/results/tf85/with_seed*.json`、`bench/aci/results/tf85/without_seed*.json`（逐 seed 原始行）、`bench/aci/tasks/*.json` |
| 样本量 / 日期（历史：第 10 次复测） | 10 任务 × 2 条件 × 3 seeds × 2 臂 = 120 行，`api_error` 0、`success is None`（未验证）0；task_set_version **1.3.0**；`max_turns=8`、`max_tokens=16384`、`temperature=0`；2026-09-25（**第 10 次复测**，含 C26 投影修复与 completion 上限修正）。注意本轮有 **3 行**（全在 D 侧）记录到 `completion_truncated_turns>0`，即仍有推理把 16384 预算烧穿——引用成功率时应说明这 3 行的存在（见 C25 的敏感性） |
| 第 9 轮明细（已被本轮取代，保留作逐轮对照） | **本轮（v1.3.0）** with：A 0.6333 / 4.10 / 177.63；D **0.80** / 4.07 / **157.30**（D/A **0.9919 / 0.8855**）。without：A 0.6333 / 4.23 / 176.90；D 0.5333 / 3.07 / 95.03（D/A 0.7244 / 0.5372）。`read_files` 净效应（相对 without）：工具 **+33%**、观察 token **+66%**。**逐轮 with 臂 D 绝对开销**：411.1 → 333.4 → 296.5 → 303.5 → 177.3 → 144.8 → 152.1 → **157.3**；A：168.6 → 197.4 → 170.5 → 168.9 → 202.4 → 180.9 → 155.9 → **177.6**。**本轮 exec 结构**：`exec.run` **37 次 / 1212 tok**（25.7% of D，32.76 tok/次），成功 29 次 @12.10、失败 **8 次 @107.62**（71.0% 的 exec token）；失败全是 `pytest -q`（4 次）与 `pytest -q tests/test_greet.py`（3 次）这类真实试错，外加 1 次 `powershell Format-Hex`。**差距分桶（总 −14.20 tok/run，D 更省）**：exec **−77.77**、edit +29.87、read +19.70、meta +7.87。**上一轮（v1.2.0）**：with D 0.70 / 4.00 / 152.07（D/A 1.1538 / 0.9752）；without D 0.60 / 3.13 / 93.20 |
| 失效边界 | ①**修复前的 D 侧数字受 C18 污染，不可与修复后比较**：2026-09-24 之前条件 D 在本机无法执行任何 cargo/rustc 命令（`cargo check` → exit 100 且报「0 error(s)」、`cargo build` 被读成 `+build` 工具链、`cargo --version` 打印 rustup 版本），而 A 走 `cmd` 不受影响。引用任何 2026-09-24 之前的 D 侧 exec 数字时必须同时引用 C18 与 C19。②**单模型**（`sn-glm-5-3-flash`），不可外推；该模型曾被端点下架又恢复，复测前必须先核对 `/v1/models`。③**名义确定性**：端点接受 `seed` 但不严格复现，3 次重复给的是经验区间而非确定性复算。④**D/A 比值受 A 侧漂移主导**：A 的代码八轮未动，其 with 臂 obs_tok 却在 168.6 / 197.4 / 170.5 / 168.9 / 202.4 / 180.9 / 155.9 / 177.6 之间摆动（约 ±14%），比值变化不宜单独作为趋势证据；可读的是 D 的绝对开销与确定性复算（C14 / C16）。⑤观察 token 用 `len(text)//4` 估算，不是真实 tokenizer。⑥**成功判定已部分行为化**：`ts_fix_type_error` 跑 `tsc --noEmit`（v1.2.0，C23），`python_noisy_install_summary` 用「单行 + 点名 `six`」的正则（v1.3.0），其余任务仍是各自的文件谓词；C24 守住「pristine 失败 / GOLDEN 通过」这条底线。⑦裸 `pytest` 在 Windows 上因 console-script 的 `sys.path` 行为失败（规范形式 `python -m pytest`），两条件同样受限；ts 侧的环境边界已由 v1.2.0 关闭，产品侧的「裸名 `npm`/`npx` 无法启动」已由 C22 修复。⑧**与 mock 的 C1/C2 不可混用**：mock 的 D 直接套 GOLDEN 补丁，0.106/0.55 是评分管线自检，不是能力测量。⑨上游会间歇性 500（`parse response failed`）：本轮 6 次运行全部干净（0 格受影响），但仍保留 `splice_live_cells.py` 这条补跑路径；合并脚本遇到 `api_error` 即 exit 2。⑩**成功率的逐轮波动主要是端点噪声**：v1.2.0 轮 `python_edit_and_retest` 的 A 是 3/3，本轮变 0/3，而该任务代码未动；本轮 D 的提升里，确定属于修复的是 `python_noisy_install_summary` 的 0/3 → 3/3（两臂），其余是噪声。⑪**without 臂只用于配对对照**（本轮 D 3.07 步 / 95.03 tok），不要单独引用其比值。⑫**历轮数字的替代关系**：D 4.53 / 177.27（v1.1.0 前）、3.77 / 144.80（v1.1.0）、4.00 / 152.07（v1.2.0）都已被本轮的 4.07 / 157.30 取代；跨轮引用必须同时说明 task_set_version 与当时的缺陷状态。⑬**without 臂的名称必须写准**：它的 `exclude_tools` 是 `["read_files"]`，而 `read_files` 是 AE 的 **`file.read_many`（批量读）**；单文件读 `read_file` = **`file.view` 仍然可用**（第 12 轮那次消融里 D 实际用了 24 次）。所以它是「**去掉批量读**」的实验，**不是「拿掉读工具」**——把两者混为一谈会得出「D 高度依赖读工具」这种超出证据的结论（见 `docs/audit-brief.md` P7 的修订注）。另外 §3.3 同样适用于它：without 臂若任一预算 >10% 被截断，测到的就是预算而不是工具效应。⑭**端点的 300 秒非流式上限锁死了可达的 completion 预算，抬上限这条补救在本端点不可执行**：2026-09-27 把那 11 个被截断单元格用 `--max-tokens 32768` 原权重重跑 → **通过 2、仍长度截断 0、HTTP 502 9**（失败墙钟全部聚在 ~300 秒，`502` 报文为「非流式响应超时(300秒)」），而 `bench/aci/runners/merge_live_runs.py` 遇到任何 `api_error` 行即 exit 2 拒绝合并——**抬高上限只是把「长度截断」换成「无法合并的产物」**。因此 §0.5 的第 1 条不能当作总能执行的补救，正确做法是**事先**写死行处置规则（§0.6），并按 §0.6.2 把 `analysable` 与 `intention_to_treat` **两个口径并排**报告。⑮**截断率本身是跑间变量**：同一配置三次独立运行为 **15% → 7% → 13.3%**，所以单轮的「预算不构成约束」很可能是运气，而不是配置的性质——引用时必须同时给出该轮的三臂截断率。**双预算（turn / completion）× 双口径的行处置规则见 `docs/acceptance-criteria.md` §0.6.8（TF-0121，2026-10-10 预注册）：并集 `cap_truncated` 仍是唯一门禁，逐轴分解只作诊断，不得据逐轴或子类改判。** |
| 失效边界补充（P0-2） | 第 14 轮 25/25 个生成任务记录的作者与被测模型同为 `sn-glm-5-3-flash`；提示隔离和独立正确解不能排除任务作者同源风险。旧生成器回退时未记录实际替代模型，故历史来源标签本身也不能独立证明实际作者。当前结果不得外推为异源任务上的效果，也不能宣称已排除同源偏倚；下一批须按 `docs/task-generation-protocol.md` §2.1 预注册同源/异源留出组，由测试方冻结并运行 live 对照。现有 25 个任务不能事后修复。 |
| 状态 | 已证实（本机单模型、3 次重复 × 2 臂；**task set v1.3.0 的口径**） |

### C14 · 批量读取信封（紧凑摘要 + 批量预算，固定轨迹复算）
| 状态（**r15-2026-09-29 全链刷新**，门槛未达成） | **FAIL：0.045 < 0.15**（冻结读取调用 **144** 条，可复现 **141** 条、coverage **0.9792**；代理 token **74280 → 70940**）。本条只比较同一投影器的完整摘要与 16 位摘要，不是 C16 的行包装压缩。**阈值与判定规则未动**；C34 的命名信封收益不能当成 C14 通过。产物 `eval/tf45_envelope_replay.json`（2026-09-30 09:06） |
| 状态（历史：第 14 轮固定轨迹离线复算） | **FAIL：0.0422 < 0.15**（代理 token 72792 → 69718）。129 条可复现调用保持逐字内容且摘要差值不变时，按字符计数和取整得到的 `len//4` 代理节省率保守上界约 5.31%；这不是其他任务集、内容编码或模型行为的上界。推导见 `audit-r12-scratch/repair-p2-1-2026-09-29/scope_analysis.py` |

| 维度 | 内容 |
|------|------|
| 主张原文 | 把 live 运行里模型**真实发出**的读取调用固定下来、用当前二进制重跑，并对**同一份**观察信封做两次投影（旧口径：逐文件完整 `sha256:<64 hex>`；新口径：16 位十六进制紧凑摘要，可直接当 `expected_hash` 前缀回传），模型可见的 observation tokens 下降；同时 `file.read_many` 新增的 `max_total_lines` 预算把最坏情况（8 个 300 行文件）限制在预算之内且仍可分页续读 |
| 门槛数字 | `token_savings >= 0.15`；且 `legacy_comparison_exact == true`、`budget.bounded == true`、`budget.pagination_roundtrip == true`、`coverage > 0` 必须同时成立 |
| 口径 | 两端 token 都是 `len(text)//4` **代理**，对**同一份冻结调用集**的两次投影文本计数（`tf45_envelope_replay.py` 记录 `tokens = len(projected_text) // 4`，与 live bench 同一个估计量）；比较单位是「冻结的读取调用」，分母是**可复现**调用数（第 12 轮 88/93、第 14 轮 129 条、**r15 141/144**），**不是整轮观察量**。第 14 轮 `scope_analysis.py` 的「保守上界约 5.31%」同为**字符计数+取整**的代理口径，不是真实 tokenizer 读数。**不是**端点 usage、**不是**花费；本条与 C16 是两种不同的投影比较，**不得相加或互相替代** |
| 复现命令 | `python tools/tf45_envelope_replay.py --out eval/tf45_envelope_replay.json`，再 `python tools/claim_gate.py` |
| source | `tools/tf45_envelope_replay.py`、`bench/aci/runners/live_agent_loop.py`、`src/ops/file.rs`、`src/ops/common.rs`、`eval/tf45_envelope_replay.json` |
| 样本量 / 日期 | 33 次冻结读取调用（18 次 `file.read_many` + 15 次 `file.view`），其中 29 次可忠实复现；2026-09-24（task set v1.3.0） |
| 第 12 轮实测（**修完 C30 后的定版，门槛未达成**） | 93 次冻结读取调用中 **88 次可复现（coverage 0.9462）**：合计 **40337 → 38262 tok（−5.1%）**，**低于 0.15 门槛**；排除 11 次被批预算截断的调用后，干净子集 77 次为 **−6.4%**，同样低于门槛。分桶：`file.view` 36 次 8760 → 8268（−5.6%）、`file.read_many` 52 次 31577 → 29994（−5.0%）。`legacy_comparison_exact=true`、`bounded=true`、`pagination_roundtrip=true`、`coverage>0` 都成立，**唯一没达标的是节省比例**。**原因是同一个混合效应**：紧凑摘要省的是**每文件固定的摘要字段**，与内容大小无关；C30 修复后 D 的读法变成内容主导（单次读回 600–1300 token 的真实文件内容），固定开销被摊薄，所以比例从 26.2% 掉到 5.1%。**门槛按登记口径判 FAIL，不换度量** |
| 最近实测（第 10 轮） | 35 次冻结读取调用中 **32 次可复现（coverage 0.9143）**，3 次排除（都是 `windows_path_normalize_edit` 读 `out/result.txt` 这类「运行期自产、pristine fixture 无法重建」的调用，报告里逐条给出复算值与 live 记录值）。合计 **2566 → 1895 tokens（−26.2%）**：`file.view` 21 次 1065 → 775（**−27.2%**）、`file.read_many` 11 次 1501 → 1120（**−25.4%**）。预算：默认 8×300 行 → 返回 240 行（上限 240，5 个 deferred，可分页）；`max_total_lines=40` → 返回 40 行（7 个 deferred，可分页）；250 行文件按 window=100 分 3 页逐行复原（250/250）。`bounded=true`、`pagination_roundtrip=true` |
| 失效边界 | ①这是**客户端信封效应**，不是模型行为测量：调用集合被冻结，所以它说不出「模型会不会因此换别的调用」。②只有「stored live 那次运行所用的投影能复现其记录的 token 数」的调用才计入（本轮 `matched={'current': 29}`，`coverage=29/33`）；这条判据同时保证基线确实是模型当时看到的东西，并让工具在「改了客户端却没重跑 live」时直接判失败而不是悄悄给出跨口径比较。③`file.read_many` 18/18 全部精确匹配，且「新口径」合计与 live 实测合计相同，是最强的保真度交叉验证。④token 用 `len(text)//4` 估算，不是真实 tokenizer。⑤预算与分页那一半是结构性事实（返回行数 ≤ `max_total_lines`、分页可逐行复原），与模型无关，但**只在 `file.read_many` 上成立**；`file.view` / `file.read_range` 仍是单文件窗口。⑥本声明的数字**不能**与 C13 的 live D/A 比值相加或相减来解释：C13 的 D 侧同时含 `exec.run` 等非读取开销。⑦**样本随 live 基线换代**：调用集合来自 `bench/aci/results/latest_live.json`，而本产物的指纹 globs **不覆盖**该文件，所以 live 重跑后必须手动重跑本工具才能让数字跟上（TF-0086 记录的正是这类漂移） |
| 状态 | 已证实 |

### C15 · D 的额外 token 从哪来（exec token 分解，TF-0058）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物做逐 op 分解（不调用 API）：①`exec.run` 占条件 D 的 observation token **25.7%**（1212/4719，40.40 tok/run，32.76 tok/次）——**C18 修复前是 61.3%**、**C22 修复前是 39.9%**；②其中 **71.0% 的 exec token 来自失败的命令**（8 次失败 @107.62 tok，占 21.6% 的调用；成功 29 次 @12.10）——失败全是 `pytest -q` / `pytest -q tests/test_greet.py` 这类真实试错；③with/without `read_files` 的 exec 增量 **+8.57 tok/run** 拆成次数效应 +15.28（178%）/ 单次效应 −6.71 / 交互 −2.18；④**差距构成**：总 **−14.20 tok/run（D 更省）**，分桶为 exec **−77.77**、edit +29.87、read +19.70、meta +7.87——exec 仍是最大负贡献；⑤D 每个文件引用 38.65 tok（33 次读取 / 2126 tok / 55 个引用 / 每次 1.67 个引用），A 的读取型命令 36 次 / 1535 tok（42.64 tok/次） |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 口径 | 所有 token 都是 `len(text)//4` **代理**，按每个 op / 每次运行的观察文本累加（`exec_token_breakdown.py` 记录的 `tokens = len(projected_text) // 4`）；分母是 D 臂的运行数与调用数（with 30 次运行 / 37 次 `exec.run`，对照臂 30 次 / 25 次），**不是整轮观察量**；**不是**端点 usage、**不是**花费，也不拆分 reasoning（reasoning 只在端点 `usage` 里，见 C13/C25）。诊断量，不设门槛 |
| 复现命令 | `python tools/exec_token_breakdown.py --out eval/exec_token_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_token_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_token_breakdown.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行（10 任务 × 3 seeds）/ 37 次 `exec.run`；对照臂 30 次 / 25 次；2026-09-24（第八次复测，task set v1.3.0） |
| 最近实测（第 10 轮） | with：D **120.73 tok/run**（总 3622 tok），`exec.run` **23 次 / 467 tok**；with−without 的 exec 增量 **−13.33 tok/run**（次数效应 −3.33、单次效应 −10.00、交互 +1.30）。**差距分桶总计 −28.83 tok/run（D 更省）**：exec **−64.37**、read +6.33、edit +10.80、meta +13.07 |
| 第 9 轮明细（已被取代） | with：D 157.30 tok/run，`exec.run` 37 次 / 1212 tok（25.7%，40.40/run，32.76/次），成功 29 次 @12.10、失败 8 次 @107.62（**失败占 71.0% 的 exec token，只占 21.6% 的调用**）。without：D 95.03 tok/run，`exec.run` 25 次 / 955 tok（33.5%，31.83/run，38.20/次），成功 18 次 @14.39、失败 7 次 @99.43。**exec 增量（with − without）：+8.57 tok/run** = 次数效应 +15.28 + 单次效应 −6.71 + 交互 −2.18。差距分桶（总 **−14.20** tok/run）：exec **−77.77**、edit +29.87、read +19.70、meta +7.87。读取形状：D 33 次读取 / 2126 tok / 每次 1.67 个文件引用 / **每引用 38.65**；A 读取型命令 36 次 / 1535 tok / 42.64 每次。**上一轮同臂（已被取代）**：`exec.run` 36 次 / 1267 tok（27.8%），失败 7 次 @127.71；差距分桶 read +32.23、exec −66.30、edit +25.53、meta +4.67、总 +3.60。**C18 修复前（更早，受 C18 污染）**：`exec.run` 76 次 / 5585 tok（61.3%，73.49/次），失败 45 次 @101.44 |
| 失效边界 | ①**纯诊断**，不是对外主张，也不能反过来当作「ACI 省 token」的证据。②A 侧分桶是**启发式**：按命令字符串关键词分成 build_or_test / read_file / write_or_mkdir / other，优先级 build > read > write；一条命令可能同时读和构建，残差进 other，所以 A 的桶是近似值。③A 的 trajectory 不记录单次命令成败（只有 D 记 `aci_ok`），因此无法对 A 做成功/失败拆分。④「每个文件引用」在 D 侧由 `file.read_many.paths` 精确计数、在 A 侧由 `type`/`cat` 出现次数近似，两者不是同一种计数单位。⑤token 仍是 `len(text)//4` 估算。⑥**exec 增量与差距总和的符号都会随轮次翻转**：v1.2.0 是 +16.50 / +3.60，本轮是 +8.57 / −14.20，差别主要来自 A 侧与端点噪声，不要读成趋势。⑦结论只对**本模型、本任务集（v1.3.0）、本轮 120 行**成立；换模型或换任务集必须重跑 |
| 状态 | 已证实（本机单模型、诊断性） |

### C16 · 读取桶的紧凑投影（客户端渲染，固定轨迹实测）
| 状态（**r15-2026-09-29 全链刷新**，门槛未达成） | **FAIL：0.0789 < 0.10**（**141** 条可复现读取调用、0 条排除；代理 token **77017 → 70940**；字符 308325 → 283972 = −7.9%）。本条比较 `compact=False` 的行数组与 `compact=True` 的换行文本及可推导计数，**不能与 C14 的摘要对照混用**。**阈值与判定规则未动**；C34 以新鲜产物独立通过 **0.5736**，但不替代本条失败。产物 `eval/read_path_breakdown.json`（2026-09-30 09:06） |
| 状态（历史：第 14 轮固定轨迹离线复算） | **FAIL：0.0768 < 0.10**（代理 token 75517 → 69718）。单文件摘要归因漏删短 hash 的缺陷已修复：摘要字符数由低估的 6264 修正为 8064，残余开销从 14756 修正为 12956；总量、内容和命名信封数字不变。C34 当时以新鲜产物独立通过 0.5654，但不替代本条失败 |

| 维度 | 内容 |
|------|------|
| 主张原文 | 把 live 运行里模型**真实发出**的读取调用固定下来，对**同一份**观察信封用真实投影器做两次投影（`format_aci_result(compact=False)` 是改动前的渲染，`compact=True` 是当前），模型可见的读取桶 observation token 下降（**门禁按登记口径**：r15 为 **141** 条可复现调用、**77017 → 70940 = −7.9%**，仍低于 0.10 门槛；早期 v1.3.0 基线曾为 **−20.4%**，2576 → 2051、29 次可复现调用）。紧凑投影做三件事：完整窗口的 `lines` 数组改为单个换行连接的 `text`；窗口从第 1 行开始且覆盖整文件时丢掉 `start_line`；窗口覆盖整文件时丢掉 `total_lines`（此时它等于 `text` 的行数） |
| 门槛数字 | `token_savings >= 0.10`（v1.3.0 实测 0.2038）；且 `calls > 0`、至少一次调用的投影与 stored live 记录一致。**注意门禁用的始终是「全部可复现调用」的口径**：r15 为 **0.0789**（141/141 条调用都带内容，所以「全量」与「只算渲染内容」在 r15 合并成同一个数）；历史上 v2.0.0 基线上这个数字掉到 0.0739，而当时「只算渲染内容的调用」是 0.1791。**两者都如实报，但门禁不换成后者**——看到数字之后再挪动已注册的度量，正是本仓库要防的那类错误。 |
| 口径 | 两端 token 都是 `len(text)//4` **代理**，对**同一份冻结读取信封**的两种**客户端投影文本**计数（`read_path_breakdown.py` 与 C14 用同一个估计量）；分母是**可复现**读取调用（第 12 轮 89 次；v1.3.0 基线 29 次；**r15 141 次**），**不是整轮观察量**。`eval/read_path_breakdown.json` 同时给出 `legacy_chars` / `current_chars`（r15：308325 → 283972）与 `legacy_tokens` / `current_tokens`（r15：77017 → 70940，代理口径），以及分项**字符份额**（`content` / `line_wrapper` / `counts` 等）；C34 只取其中 `line_wrapper` + `counts` 两项。**不是**端点 usage、**不是**花费 |
| 第 12 轮实测（**修完 C30 后的定版，门槛未达成**） | 89 次可复现调用（4 次排除）：**41905 → 38407 tok（−8.3%）**，**低于 0.10 门槛**。修完 C30 后**不再有「无渲染窗口」的调用**（89/89 都带内容），所以「全量」与「只算渲染内容」两个口径**合并成同一个数**——第 11 轮那个 216/263 的元数据混合本身就是 C30 造成的。**为什么从 20.4% 掉到 8.3%**：紧凑投影只动**信封开销**（`line_wrapper` 与可推导的 `counts`），不动 `content`；当前读法里 **content 占 76.4%**，命名开销 30440 → 16583 字符，即**投影去掉了 45.5% 的信封开销**，但开销只占总量约 18%，折算到总量就是 8.3%。**这是混合比例问题，不是代码回退**（v1.3.0 的读法偏小、开销占比高，所以当时是 20.4%）。**门槛按登记口径判 FAIL，不换度量** |
| 复现命令 | `python tools/read_path_breakdown.py --out eval/read_path_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/read_path_breakdown.py`、`bench/aci/runners/live_agent_loop.py`、`tools/tf45_envelope_replay.py`、`eval/read_path_breakdown.json` |
| 样本量 / 日期 | 29 次可复现读取调用（18 次 `file.read_many` + 11 次 `file.view`），另有 4 次读运行期自产状态的调用被排除；2026-09-24（task set v1.3.0） |
| 最近实测（第 10 轮） | 合计 9632 → 7618 字符（**−20.9%**）、**2394 → 1895 tokens（−20.8%）**；`file.view` 21 次 1002 → 775（−22.7%）、`file.read_many` 11 次 1392 → 1120（−19.5%）。改动前归因：content 40.5%、counts 17.8%、residual 15.7%、digest 10.5%、line_wrapper 8.8%、path 6.8%；改动后：content 51.2%、residual 20.1%、digest 13.2%、path 8.5%、line_wrapper 5.6%、counts 1.4% |
| 失效边界 | ①这是**客户端渲染**改动，不是产品契约改动：`compact=False` 与改动前的投影**逐字节一致**（用 git 上一版的投影器对同一批冻结调用逐条比对，全部 identical），所以没有任何消费者需要迁移——兼容策略就是「不动契约」。②丢 `total_lines` **只在客户端展示内容时才成立**：>10 行的窗口不展示内容，此时 `total_lines` 是唯一信息、必须保留（改动后 counts 仍占 1.3% 正是这部分）。这也是该优化不能放进产品信封的原因。③作用域是 `file.view` / `file.read_many`；`file.read_range` 在本轮 live 调用集中未被使用，未纳入测量。④只测读取桶，不代表 D 的总 token 变化——总变化由 live 复测给出（C13）。⑤token 仍是 `len(text)//4` 估算。⑥两项更激进的改动被**评估后否决**：摘要从 16 位降到 8 位（约再省 4%，但碰撞界从 2^-64 降到 2^-32），以及让 `start_line > 1` 的完整窗口也丢 `total_lines`（空文件/尾换行边界下推导不可靠）。⑦样本随 live 基线换代：调用集合来自 `bench/aci/results/latest_live.json`，该文件在指纹 globs 内，所以 live 重跑后本产物会被 C12 判陈旧、必须重跑 |
| 状态 | 已证实（确定性复算） |

### C17 · 读取用途审计（D 的读取到底用在哪，TF-0067）

| 维度 | 内容 |
|------|------|
| 主张原文 | 对已存 live 产物做读取用途审计（不调用 API），按**代码里定义**的规则给每条读取路径分类：`referenced_in_run`（同一 run 里被编辑、或在 exec 命令里被点名）、`task_subject`（任务 prompt 或成功谓词里点名）、`task_file`（fixture 自带的 `TASK.md`，其内容系统提示已以更详细的版本携带）、`unreferenced`（以上都不是）。**with 臂 D：55 条路径中 referenced 29（52.7%）、task_subject 5（9.1%）、TASK.md 3（5.5%）、unreferenced 18（32.7%）**（按 token：1067.83 / 202.5 / 134.5 / 721.17，份额 50.2% / 9.5% / 6.3% / 33.9%）；同期 A：68 条文件引用中 referenced 31（45.6%）、task_subject 18（26.5%）、TASK.md 7（10.3%）、unreferenced 12（17.6%）。逐条比对 10 个 fixture 的 `TASK.md` 与注入提示：**提示词每条都更详细，`TASK.md` 没有独有信息**，所以「读 `TASK.md`」是可证明的冗余——而且它在两个臂里都存在。据此加了提示规则 8（「`TASK.md` 只是重复上面的任务，不要为它花一次工具调用」），并用 live 复测验证：**改动后 D 的 `TASK.md` 读取从 27 条 / 1064.5 tok 降到 3 条 / 134.5 tok（−87%）** |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 口径 | token 都是 `len(text)//4` **代理**，且**批量调用的 token 按路径数均摊**（不是逐文件实测）——一次多文件 `read_many` 的信封开销也会摊到每条路径上，所以份额里含信封开销；分母是 with 臂 D 的 33 次读取 / 55 条路径（A 侧 68 条文件引用），**不是整轮观察量**；**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/read_usage_audit.py --out eval/read_usage_audit.json`，再 `python tools/claim_gate.py` |
| source | `tools/read_usage_audit.py`、`bench/aci/tasks/*.json`、`bench/aci/runners/live_agent_loop.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/read_usage_audit.json` |
| 样本量 / 日期 | 改动前（TF-0067 轮产物）：with 臂 38 次 D 读取调用 / 85 条路径；**本轮（v1.3.0）**：33 次 / 55 条、68 条 A 文件引用；2026-09-23 → 2026-09-24 |
| 最近实测（第 10 轮） | with：D **35 次读取 / 52 条路径 / 1941 tok**，按 token 份额：`referenced_in_run` **38.6%**、`unreferenced` **32.7%**、`task_subject` 15.7%、`task_file`（TASK.md）**13.0%**；without 臂 D 30 次 / 30 条 / 950 tok，`referenced_in_run` 57.0%、`unreferenced` 38.3%、`task_subject` 4.7%。**`TASK.md` 份额已从改动前的 33.4% 降到 13.0%** |
| 改动前（发现问题的依据） | with：D 85 条路径中 `TASK.md` **27 条 / 1064.5 tok（33.4%）**；A 78 条中 16 条（17.6%）。**本轮** with：D 55 条路径中 `TASK.md` **3 条 / 134.5 tok（6.3%）**；A 的 `TASK.md` 占 10.3%（7 条 / 234 tok）。D 的 `unreferenced` 占 32.7%（721.17 tok），主要是 `Cargo.toml` 与 fixture 工程上下文——不是浪费 |
| 失效边界 | ①**`unreferenced` ≠ 无用**：它只表示「本 run 里没有留下可观察的下游使用」。`Cargo.toml` 与 `tests/test_math.py` 都落在这个桶里，但它们分别是工程上下文与失败测试的所在文件——读它们是合理的。能证明冗余的只有 `TASK.md`，因为提示词是它的严格超集。②分类规则是**代码里的启发式**：`referenced_in_run` 靠命令字符串里的路径 token 匹配，路径写法不一致（相对/绝对、反斜杠）会漏判，所以 `unreferenced` 是上界而非精确值。③**批量调用的 token 按路径数均摊**，不是逐文件实测；一次多文件 `read_many` 的信封开销也会摊到 `TASK.md` 头上，所以 6.3% 这个份额里含信封开销。④A 侧必须排除「读取命令自身」的自指（A 用 `type` 读文件，命令里自然出现该路径），否则 A 会 100% 落在 `referenced_in_run`；本工具对此有专门处理。⑤结论只对本模型、本任务集（v1.3.0）、本轮 120 行成立 |
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
| 口径 | token 都是 `len(text)//4` **代理**，按失败 `exec.run` 的观察文本累加；分母是 D 臂 `exec.run` 的调用数（v1.3.0 本轮 37 次 / 8 次失败；第 10 轮 23 次 / 1 次失败），**只统计 D 侧**（A 的轨迹不记单次命令成败，所以 A 无法做成功/失败拆分）；**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/exec_failure_breakdown.py --out eval/exec_failure_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/exec_failure_breakdown.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/exec_failure_breakdown.json` |
| 样本量 / 日期 | 修复前 with 臂 76 次 `exec.run`（45 次失败）；C18 修复后 50 次（21 次失败）；C22 修复后 33 次（5 次失败）；v1.2.0 36 次（7 次失败）；**v1.3.0 本轮 37 次（8 次失败）**；2026-09-24 |
| 最近实测（第 10 轮） | with：`exec.run` **23 次**，成功 22 次 / 415 tok（@18.86）、失败 **1 次 / 52 tok（占 exec token 11.1%）**，100% `first_diagnostic`（失败命令是 `find . -type`）。without：`exec.run` 26 次，成功 20 次 / 270 tok、失败 6 次 / 597 tok（占 68.9%），失败全是 `pytest -q`（`python_fix_pytest_fail` 3 次、`python_edit_and_retest` 3 次），同样 100% `first_diagnostic`。**Rust 编译类失败已归零** |
| 第 9 轮明细（已被取代） | **本轮（v1.3.0）** with：`exec.run` 37 次 / 1212 tok（25.7% of D），成功 29 次 @12.10、失败 **8 次 @107.62**（占 21.6% 的调用、71.0% 的 exec token），**100% first_diagnostic，repeat 与 toolchain_probe 均为 0**；失败全是真实试错——`pytest -q`（4 次）、`pytest -q tests/test_greet.py`（3 次）、`powershell Format-Hex`（1 次），按任务：`python_edit_and_retest` 4 次 / 396 tok、`python_fix_pytest_fail` 3 次 / 300 tok、`rust_add_unit_test` 1 次 / 165 tok，**ts 任务与 Rust 编译任务归零**。without：`exec.run` 25 次 / 955 tok，失败 7 次 @99.43（72.9%），同样 100% first_diagnostic。**v1.2.0 同臂**：36 次 / 1267 tok、失败 7 次 @127.71。**C22 修复后同臂**：33 次 / 917 tok、失败 5 次 @99.0。**C22 修复前同臂**：50 次 / 2121 tok、失败 21 次 @82.62（81.8%）。**C18 修复前**：76 次 / 5585 tok、失败 45 次 @101.44（89.3% first_diagnostic + 10.7% toolchain_probe） |
| 失效边界 | ①分类是**启发式**：`--version` / `+toolchain` 关键词判为探测，同命令第二次失败判为重复，因此 `repeat=0` 是「没有出现同命令二次失败」而非「模型从不试错」。**ts 任务的失败逐轮消失**：C22 修复前 9 次（6 次裸名启动失败 + 3 次缺 typescript）→ C22 修复后 3 次（缺 typescript）→ v1.2.0 起 0 次；即 `first_diagnostic` 只说明「是该命令第一次失败」，不说明「看到了值得看的失败」。②**C18 修复前的数字受 C18 污染**：Rust 任务的失败里有相当部分由启动缺陷造成，不能当作「模型试错成本」的证据；引用时必须同时引用 C18。③`first_diagnostic` **不等于浪费**：这套任务的很多条目就是「跑一次失败、看诊断、再修」，所以它的占比高本身不是缺陷。④只对本模型、本任务集（v1.3.0）、当前轮次成立；换模型或改任务集必须重跑。⑤**失败 exec 的构成随修复逐轮下移，而次数在 5–8 之间波动不等于回归**：C18 前 45 次 → C22 前 21 次 → C22 后 5 次 → v1.2.0 的 7 次 → v1.3.0 的 8 次。最近两轮的失败全部是 `pytest -q` 这类**真实试错**（ts 与 Rust 编译已归零），而同一轮的成功率反而最高（D 0.80）——模型做完了更多任务，自然也就跑了更多验证 |
| 状态 | 已证实（本机单模型、诊断性） |

### C20 · D 与 A 的步骤构成（多出来的步骤从哪来，TF-0078）

| 维度 | 内容 |
|------|------|
| 主张原文 | 分解两条件的步骤构成（不含 `task_complete`，与 live bench 口径一致）：**D 4.067 步/run、149.83 tok/run；A 4.100 步/run、171.50 tok/run**（比值 0.992 / 0.874）。D 按类别：edit 1.267、exec 1.233、read 1.100、meta 0.467；A 全部是 `run_command` 4.100。**A 的 123 条命令里有 36 条（29.3%）一次做多件事**（other 35、read 26、write 19、run+write 15、read+run 11、read+write 9、run 7、三合一 1），而 D 的 typed op 不能合并——**这是 D 仍然多花步骤的主要来源**。**「可合并的重复调用」D 6 次（4.9% 的步骤、3.25 tok/run）、A 32 次（26.0%、18.90 tok/run）**：本轮 A 的重复是 D 的五倍（`python_edit_and_retest` 14 次、`rust_search_and_edit` 13 次），重复调用早已不是 D 的特征。失败观察的构成以 `diagnostics`（620 字符）与 `error`（398）为主，即可操作内容；可裁的 `stats`（103）与 `stdout/stderr_summary`（各 48）、`exit_code`（66）、`ok`（52）合计约 18%，但各自都带信号，评估后不动 |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 口径 | `tok/run` 是 `len(text)//4` **代理** ÷ 运行数（`step_composition.py` 的 `tokens_per_run`）；分母是 with 臂 30 次 D 运行与 30 次 A 运行（不含 `task_complete`）。「可合并的重复调用」的 token 按 `(n−1)/n` 折算该步的代理量（工具按 `(op,args)` 完全相同的重复次数折算），4.9% 是**上界**；**不是**真实 tokenizer、**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/step_composition.py --out eval/step_composition.json`，再 `python tools/claim_gate.py` |
| source | `tools/step_composition.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`bench/aci/tasks/*.json`、`eval/step_composition.json` |
| 样本量 / 日期 | with 臂 30 次 D 运行 / 30 次 A 运行；2026-09-24（task set v1.3.0） |
| 最近实测（第 10 轮） | with：**D 3.167 步/run（114.87 tok）vs A 3.300 步/run（147.10 tok）**，比值 **0.95 / 0.781**。D 的 op 构成（30 次运行合计）`file.view` 24、`exec.run` 23、`file.replace_exact` 16、`file.read_many` 11、`file.write` 10、`repo.summary` 8、`repo.search` 2。A 的多合一命令 **24/99（24.2%）**（read+run 11、run+write 12、read+write 8、三合一 3 等）；可合并的重复调用 D **4 次（4.2% 的步骤，1.75 tok/run）**、A **13 次（13.0%）** |
| 第 9 轮明细（已被取代） | D 4.067 步/run（149.83 tok）vs A 4.100 步/run（171.50 tok），比值 **0.992 / 0.874**；D 的 op 构成（30 次运行合计）`exec.run` 37、`file.replace_exact` 23、`file.read_many` 18、`file.view` 15、`file.write` 15、`repo.summary` 14；A 的多合一命令 36/123（29.3%）；重复调用 D 6 次（4.9%，3.25 tok/run）、A 32 次（26.0%，18.90 tok/run）；失败观察 leave-one-out：`diagnostics` 620、`error` 398、`stdout_text` 263、`stderr_summary` 144、`stats` 103、`exit_code` 66、`ok` 52、`stdout_summary` 48 字符 |
| 失效边界 | ①**「重复调用」不等于浪费**：判据是 `(op, args)` 完全相同，看不到状态变化——编辑后重跑同一条验证命令会被计入，而那正是正确行为。因此 4.9% 是**上界**；本轮 A 的重复（32 次 / 26.0%）是 D 的五倍。②多合一的判定是**关键词启发式**（命令串里是否同时出现 read/run/write 提示词），不是语法分析；本轮 `other`（35 条）占比高，说明相当多命令没被关键词命中。③`ts_fix_type_error` 的环境边界已由 v1.2.0 关闭（C21）：C22 修复前 3 次 D 运行共 15 次 exec / 754 tok，C22 修复后 5.333 步 / 292.3 tok，**v1.2.0 起链上唯一的 exec 就是那次验证**（1 次 / 3 tok），C21 的反事实与观测值已经重合。④失败观察的构成来自**代表性复现**（在 pristine fixture 上重跑失败命令），不是当轮轨迹的原样重放。⑤只对本模型、本任务集（v1.3.0）、本轮 120 行成立 |
| 状态 | 已证实（本机单模型、诊断性） |

### C21 · ts fixture 的两条边界：工具链获取链与成功谓词（TF-0082）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用已存 live 产物 + 本机文件事实做确定性分解（不调用 API）：①**C22 修复前** `ts_fix_type_error` 在条件 D 下 3 次运行共 **15 次 exec 调用 / 754 tok**（6 次 / 288 tok 裸名 `npm`/`npx` 启动失败 + 6 次 / 457 tok 缺 `node_modules` + 3 次 / 9 tok 真实验证）；②C22 修复后降到 5.333 步 / 292.3 tok（只剩缺 typescript 的探测与安装）；③**v1.2.0 起该任务为 3.000 步，边界调用 1.0 次 / 3.0 tok——那一次就是任务需要的验证**（本轮 v1.3.0 为 183.33 tok）：fixture 自带 pinned `typescript`（`deps/typescript-5.4.5.tgz`，由 `bench/aci/runners/fixture_deps.py` 在工作区准备阶段**离线**解包成 `node_modules/typescript` 并写好 `.bin` shim），两个臂从同一份自洽工作区出发，反事实与观测值重合；④同一 fixture 的成功谓词已从 **GOLDEN 字面匹配**（v1.1.0）改为**行为判定**（v1.2.0，跑 `tsc --noEmit`）：对同一批 6 条已存轨迹重算，旧谓词 D 0/3、A 0/3，而 `tsc` **D 3/3、A 3/3**——**旧谓词把 6 次真实修复全判成了失败**；⑤pristine fixture 在 `tsc` 下退出码 2、GOLDEN 退出码 0（任务既不是预先解决、也不是不可解）；live runner 不再静默把 `optional_verify` 置 `None`，而是逐行记录它没有单独执行（`"ran": False` + 声明内容） |
| 门槛数字 | 无（诊断性测量，只登记事实，不设通过门槛） |
| 口径 | token 都是 `len(text)//4` **代理**，按 `ts_fix_type_error` 单任务的 D 侧运行累加；分母只有 3 次 D 运行 + 3 次 A 运行（seeds 42/43/44），**不是整轮**。谓词对照（旧 GOLDEN D 0/3、A 0/3 vs `tsc` D 3/3、A 3/3）是**条数**、不是 token；**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json`，再 `python tools/claim_gate.py` |
| source | `tools/ts_fixture_audit.py`、`bench/aci/runners/fixture_deps.py`、`bench/aci/results/latest_live.json`、`bench/aci/tasks/ts_fix_type_error.json`、`bench/aci/tasks/ts_package_script_fail.json`、`bench/aci/fixtures/ts_fix_type_error/**`、`bench/aci/fixtures/ts_package_script_fail/**`、`bench/aci/runners/live_agent_loop.py`、`src/process_command.rs`、`eval/ts_fixture_audit.json` |
| 样本量 / 日期 | 两个 ts 任务各 3 次 D 运行 + 3 次 A 运行（live with 臂，seeds 42/43/44）；2026-09-24（task set v1.3.0） |
| 最近实测（第 10 轮） | D `ts_fix_type_error` **3.000 步 / 183.33 tok**，边界调用 **0.0 次 / 0.0 tok**——该任务在本轮**没有任何环境边界调用**（`boundary_calls_per_run=0`），反事实与观测值完全重合（`step_ratio_band=[0.95, 0.95]`、`token_ratio_band=[0.7794, 0.7794]`），`conclusion_flips=false`。三个 seed 的成功原因都是 `command_exit_0 ['node','node_modules/typescript/bin/tsc','--noEmit'] -> 0`，即行为判定。**谓词对照（同一批 6 条轨迹）**：旧 GOLDEN 字面匹配 `legacy_pass=1`、声明谓词 `declared_pass=6`；`legacy_predicate_pass_by_condition` D 1/3、A 0/3，`tsc` D 3/3、A 3/3。baseline：pristine `tsc` exit 2（fail）、GOLDEN exit 0（pass）。本机被无扩展名 shim 遮蔽的裸名：`npm`、`npx`、`yarn`、`pnpm`、`corepack` |
| 失效边界 | ①**分类不再给失败归因**：工具按命令**是什么**分桶（npm 安装 / 提到 `tsc` 或 `node_modules` / 裸名），失败一律记为 `toolchain_probe_failed`——启动是否可用由 C22 的探针负责证明，两者不要混用。②**裸名那一半是机器事实**（性质同 C18）：本机 nvm-for-Windows / nodejs 目录同时有无扩展名 `npm` 与 `npm.cmd`；该缺陷已由 C22 修复并机检，换一台只有 `.cmd` 的机器这一半不触发（产物如实记为 `shadowed=false`）。③**本工具现在真的跑 tsc**：fixture 自带 pinned typescript，`tsc_verdict` 在临时工作区里执行 `node node_modules/typescript/bin/tsc --noEmit`；这是本地 node 执行、不访问网络，但因此要求机器上有 `node`（缺失时记为 `ran=false`，不当作通过）。④A 侧分桶是上界：raw shell 把安装、写文件、验证折进一条命令，关键词分类拆不开。⑤**反事实的语义已改变**：v1.2.0 下该任务的边界调用为零，所以 band 退化成一个点——它不再是区间估计，而是「环境边界已消失」的证据。⑥成功谓词的对照是字符串级重放（typed ops 直接重放；raw shell 从 `python -c ...write(...)` 一行里解出字面量），不是重跑工作区。⑦只对本模型、本任务集（v1.2.0）、本轮 120 行成立。⑧样本随 live 基线换代：调用集合来自 `bench/aci/results/latest_live.json`，所以 live 重跑后本产物会被 C12 判陈旧、必须重跑 |
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

### C23 · ts 任务的成功判定必须是行为判定（TF-0084）

| 维度 | 内容 |
|------|------|
| 主张原文 | `ts_fix_type_error` 的成功判定必须测 prompt 承诺的行为，而不是比对 GOLDEN 补丁的字面文本。四项同时成立：①声明的谓词是命令（`command_exit_0`，argv 跑 fixture 自带的 `typescript`），不是 `file_contains`；②**pristine** fixture 在该谓词下失败（任务没有被预先解决）；③**GOLDEN** 补丁通过（任务可解）；④**一个写法不同但等价的修复**（保留绑定并改名 `const total: number = a + b`）也必须通过——这正是 v1.1.0 字面匹配会误杀的形态。用同一批 6 条已存轨迹重算：旧谓词 D 0/3、A 0/3，而真实 `tsc --noEmit` **D 3/3、A 3/3**，即 **6 次真实修复全被旧谓词判错** |
| 门槛数字 | `== 1.00`（四项检查全部成立；`pristine`/`GOLDEN`/等价修复都必须真的跑过 `tsc`，`ran=false` 不算通过） |
| 复现命令 | `python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json`，再 `python tools/claim_gate.py`；单测/复现入口：`python bench/aci/runners/live_agent_loop.py --tasks ts_fix_type_error --conditions verseshell_aci --seed 42 ...` |
| source | `tools/ts_fixture_audit.py`、`bench/aci/tasks/ts_fix_type_error.json`、`bench/aci/tasks/manifest.json`、`bench/aci/fixtures/ts_fix_type_error/**`（含 `deps/typescript-5.4.5.tgz`）、`bench/aci/runners/fixture_deps.py`、`eval/ts_fixture_audit.json` |
| 样本量 / 日期 | pristine + GOLDEN 各一次真实 `tsc --noEmit`（离线、用 fixture 自带的 pinned TypeScript）；2026-09-24 |
| 最近实测 | 检查全过：`predicate_is_behavioural=true`、`pristine_fails=true`（`tsc` exit **2**，报 `TS2322: Type 'number' is not assignable to type 'string'`）、`golden_passes=true`（exit **0**）、`equivalent_fix_passes=true`（改名为 `total` 的等价修复同样 exit 0）。同一产物的历史对照：`legacy_predicate_pass_by_condition` = D 0/3、A 0/3；`tsc_pass_by_condition` = D 3/3、A 3/3；`runs_where_legacy_rejected_a_passing_fix = 6` |
| 失效边界 | ①**它只守这一个任务**：其余任务仍是各自的文件谓词；更基本的那条不变量（pristine 失败 / GOLDEN 通过 / 等价变体通过）由 C24 覆盖全部 10 个带 GOLDEN 的任务。`python_noisy_install_summary` 的同类字面谓词已由 TF-0087 修掉（旧谓词 0/6 → 新谓词 6/6）。②**判据依赖本机有 `node`**：`tsc` 通过 `node node_modules/typescript/bin/tsc` 执行；没有 node 时 `ran=false`，门禁判失败（fail-closed），不会静默通过。③**fixture 自带工具链是前提**：`deps/typescript-5.4.5.tgz` 由 `fixture_deps.materialize_deps` 在工作区准备阶段离线解包；`prepare_workspace` 对它 fail-closed（解包失败即抛错，不把无法自检的工作区交给 agent）。④**版本门槛**：`task_set_version` 已由 1.1.0 升到 1.2.0、再到 1.3.0，跨版本引用 live 数字必须说明。⑤它不替代 C13：谓词正确只保证「成功率的分子分母是同一件事」，不保证模型真的更强 |
| 状态 | 已证实（确定性复算 + 本机真实 tsc 执行） |

### C24 · 任务集自洽性：每个带 GOLDEN 的任务都必须 pristine 失败、GOLDEN 通过（TF-0087）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用**与 live runner 同一个求值器**（`live_agent_loop.check_success`）对全部 10 个带 GOLDEN 补丁的任务做一次夹具级检查：①**pristine** fixture 在声明谓词下必须**失败**（任务没有被预先解决）；②**GOLDEN** 补丁必须**通过**（任务可解）；③为两个谓词出过问题的任务注册的**等价变体**（写法不同但同样正确）也必须通过。这条不变量正是字面文本谓词会破坏、而只对着 GOLDEN 检查时看不出来的东西：`file_contains "return a + b"`（ts）与 `file_contains "packages"`（python）都通过了各自的 GOLDEN，却拒绝了其它所有正确答案 |
| 门槛数字 | `== 1.00`（10/10 任务三项全过；`ran=false`（未验证）不算通过，fail-closed） |
| 复现命令 | `python tools/task_set_audit.py --out eval/task_set_audit.json`，再 `python tools/claim_gate.py` |
| source | `tools/task_set_audit.py`、`tools/trajectory_replay.py`、`bench/aci/tasks/manifest.json`、`bench/aci/tasks/*.json`、`bench/aci/fixtures/**`、`bench/aci/runners/live_agent_loop.py`、`eval/task_set_audit.json` |
| 样本量 / 日期 | 10 个带 GOLDEN 的任务 × 3 种形态（pristine / GOLDEN / 等价变体，其中 2 个任务注册了变体）；2026-09-24（task set v1.3.0） |
| 最近实测 | **10/10 PASS**：全部任务 pristine 失败、GOLDEN 通过；两个注册了变体的任务（`ts_fix_type_error`、`python_noisy_install_summary`）变体也通过。同一产物的历史对照（`predicate_changes`，逐条重放 6 条已存轨迹）：`ts_fix_type_error` 旧谓词 **0/6** → 声明谓词 **6/6**；`python_noisy_install_summary` 旧谓词 **1/6** → 声明谓词 **6/6**（旧谓词只放过了那一行恰好写了复数 `packages` 的摘要）。在上一轮（v1.2.0）的基线上，python 这一项是 0/6 → 6/6 |
| 失效边界 | ①**它只检查夹具级自洽**：pristine / GOLDEN / 变体三种形态，不等于模型在真实运行里的行为——真实数字仍看 C13。②**求值器与 live runner 共用**：`check_success` 是同一份实现，所以它测的是「live 会怎么判」，不是另一套规则。③**变体是人工注册的**：只有出过问题的两个任务注册了变体，其余 8 个只做 pristine/GOLDEN 两项，不能据此说它们的谓词一定不依赖措辞。④`ts_fix_type_error` 的 GOLDEN 形态需要本机有 `node`（要跑 `tsc`），没有 node 时该项 `ran=false` → 门禁判失败。⑤**它不覆盖「任务是否真的做完」**：例如 `python_noisy_install_summary` 的谓词只检查摘要文件，不检查依赖是否真的装上（pip 装进共享环境，装过之后就再也无法从工作区区分）——这条边界与 C13 的口径一致 |
| 状态 | 已证实（确定性复算，10/10） |

### C26 · 参考客户端的投影必须携带工具描述承诺的负载

| 维度 | 内容 |
|------|------|
| 主张原文 | `bench/aci/runners/live_agent_loop.py::format_aci_result` 是参考客户端把 `verseshell.observation/v1` 信封渲染给模型的那一层。**每个暴露给 agent 的工具，其描述里承诺的负载必须真的到达模型**：`search_content`（`repo.search`）承诺「matching files and lines」、`list_files`（`repo.summary`）承诺「branch, dirty files, top-level directory listing」、`replace_in_file`（`file.replace_exact`）要返回可链式的摘要、`read_file`（`file.view`）要返回内容；失败路径上 `E_AMBIGUOUS` 必须保留结构化 `data.matches[]`（line/offset/snippet）；且投影**不得**泄露宿主 `workspace` 绝对路径 |
| 门槛数字 | `== 1.00`（6 项检查全过） |
| 口径 | 本条不发布 token 数字：门槛是 6 项**检查计数**（6/6），不是 token 量。它引用的次数（with 臂 `repo.search` 0 次调用、raw_shell 侧 `grep` 类 11 次）是**调用计数**；相邻条目若把同一缺陷写成 token（例如 C30 的 `65742 tok`），那些 token 均为 `len(text)//4` **代理**，**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/projection_contract.py --out eval/projection_contract.json`，再 `python tools/claim_gate.py` |
| source | `tools/projection_contract.py`、`bench/aci/runners/live_agent_loop.py`、`eval/projection_contract.json` |
| 样本量 / 日期 | 6 项检查，每项都经真实 `ae --serve --agent` 跑一次真实 op 并检查投影 |
| 最近实测 | 6/6 PASS。**修复前**三处缺陷（都是本次由真实调用发现的）：①`repo.search` 成功时投影成 `{"ok": true}`——匹配全部丢失，`search_content` 的描述承诺「返回匹配的文件与行」，而 agent 调用后什么都学不到，于是退回 `exec.run` 里的裸 `grep`；实测影响：with 臂 `repo.search` 0 次调用、raw_shell 侧 `grep` 类命令 11 次。②`repo.summary` 丢掉 `top_level`，即该工具自己承诺的「top-level directory listing」那一半。③`E_AMBIGUOUS` 的服务端信封带 `data.matches[]`，但失败分支在拷贝该字段前就 `return` 了，于是 C4 所依赖的「一步恢复」候选点从未到达模型。修复后 `repo.search` 投影 `{match_count, matches:[{path,line,text}], truncated}`、`repo.summary` 投影 `top_level`（且不含 `workspace`）、`E_AMBIGUOUS` 投影 3 个候选点的 `line/offset/snippet` |
| 失效边界 | ①它只覆盖**投影层**（参考客户端渲染），不覆盖产品信封本身——`verseshell.observation/v1` 一直是对的，丢字段的是客户端。②检查集是**显式登记**的 6 项，不覆盖全部 32 个 op；新增工具时必须在 `tools/projection_contract.py` 里加一条。③`repo.search` 的匹配上限是 50 条、`E_AMBIGUOUS` 候选上限 10 条，超出部分被截断（`truncated` 会如实标记搜索被截断）。④它只证明「负载到达模型」，不证明模型会用它——后者是 C13/C20 的事。⑤修复会改变 D 侧观察量，所以修复后必须重跑 live（C13 及 C14–C21 全部随 live 基线换代） |
| 状态 | 已证实（真实 op + 确定性检查） |

### C25 · live 数字必须带不确定性，且门禁必须说明样本能支撑什么

| 维度 | 内容 |
|------|------|
| 主张原文 | 每份 live 产物的每个头条数字都必须带**区间**，而不只是点估计：成功率给 Wilson 区间（小样本、接近 0/1 时比正态近似正确），两条件差异给合并比例 z 检验与**配对 McNemar**（配对单位是 `(task_id, seed, run_index)`），连续指标（工具数、观察 token）给配对差的均值±t 区间，头条比值（D/A）给 **bootstrap 区间**并给出「比值低于冻结目标」的后验概率。同时，产物里的聚合数必须能由 `rows[]` 逐行重算，两者不一致即判失败 |
| 门槛数字 | `== 1.00`（两臂 × **6** 项检查：区间存在、配对视图存在、比值 bootstrap 存在、**发布的比值区间必须是按任务聚类的**（`bootstrap_unit == "task"`）、**真实 tokenizer 口径必须并列发布**（`usage/prompt/completion_token_ratio` 三项都要有区间）、聚合与逐行一致） |
| 口径 | 两种 token 口径**并列发布、不得混用**：①`observation_tokens` = `max(1, len(text)//4)` **代理**；②端点 `usage` 的 `usage/prompt/completion_token_ratio` 三项——这是**跨每一次请求累加的输入/输出 usage**（system prompt + tool schema + **重发的历史** + reasoning），**不是**单次 system prompt／schema 的大小，**不是**可见答案字符数（reasoning 是否计入账单未确认），**不是**花费（无价格／缓存规则），且**不能**与 C27 的 `cl100k_base` 数字混用（两者在 CJK/hex 形状上不可互换）。比值区间按**任务聚类** bootstrap（`bootstrap_unit == "task"`），配对单位是 `(task_id, seed, run_index)`；成功率用 Wilson，差异用合并 z + 精确 McNemar |
| 复现命令 | `python tools/live_uncertainty.py --out eval/live_uncertainty.json`，再 `python tools/claim_gate.py` |
| source | `tools/live_uncertainty.py`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/live_uncertainty.json` |
| 样本量 / 日期 | 两臂共 **630 行**（with **315** + without **315**；各 **105 对**），无 API 调用；**r15-2026-09-29**：区间按任务聚类、真实 tokenizer 口径与两项退化检查都在跑（**2026-09-26 修订**：区间改为按任务聚类，并新增真实 tokenizer 口径与两项退化检查） |
| 最近实测（r15-2026-09-29，产物 `eval/live_uncertainty.json`） | **with 臂**：A 成功率 0.9048（95/105）Wilson95 [0.8335, 0.9474]、D 0.9333（98/105）[0.8687, 0.9673]；合并 z=0.759（p=0.4479）、配对 McNemar 仅 A 独赢 0 vs D 独赢 **3**（**p=0.25，不显著**）。**任务聚类** bootstrap（105 对、20000 次）：工具比 **0.8491 [0.6877, 1.0576]**（行级 [0.7270, 0.9951]）；观察 token 比 **0.6075 [0.5007, 0.7589]**（行级 [0.5224, 0.7089]）；真实 tokenizer 口径：总 token **0.9461 [0.6462, 1.5202]**、输入 **1.0255 [0.6960, 1.6803]**、输出 **0.4259 [0.2706, 0.6583]**。**D/A′**：观察 token **0.7096 [0.5761, 0.8788]**、usage 总 **1.0817 [0.7558, 1.5772]**、输出 **0.4492 [0.3716, 0.6425]**。**without 臂**：A 0.8762（92/105）[0.7996, 0.9262]、D 0.9238（97/105）[0.8568, 0.9609]；观察 token 比 **0.553 [0.4314, 0.7266]**、usage **0.8984 [0.6691, 1.2288]**。**注**：r15 是**基线刷新**（非预注册确认性采集），上面的可主张/不可主张是登记口径的机械判定，引用时必须说明这一轮的性质 |
| 历史实测（第 12 轮，2026-09-26；已被 r15 取代，保留作对照） | **with 臂**：A 成功率 0.7067（53/75）Wilson95 [0.5956, 0.7976]、D 0.8267（62/75）[0.7257, 0.8958]；合并 z=1.7374（p=0.0823）、配对 McNemar 仅 A 独赢 7 vs D 独赢 16（**p=0.0931，不显著**）。**任务聚类** bootstrap：工具比 **1.0074 [0.7667, 1.3527]**（行级 [0.8191, 1.2521]）；观察 token 比 **0.6853 [0.5509, 0.9061]**（行级 [0.5601, 0.8551]）——**两者上界相差 0.05，正是 L2 门槛 0.90 两侧**；真实 tokenizer 口径：总 token **1.1932 [0.9117, 1.7419]**、输入 **1.545 [1.1103, 2.4214]**、输出 **0.1709 [0.1172, 0.3496]**。**关键结论**：①把区间换成聚类后，**L2「省 ≥15%」的上界越过 0.90，从「可主张」变为「不可主张」**——行级重抽给出的 0.8551 是偏窄的；②**真实 tokenizer 口径与代理口径方向相反**，且按 §4.2 以真实口径为准 |
| 失效边界 | ①它门禁的是**不确定性是否存在**，不是数字好不好看：一个让结论变成「不显著」的宽区间是**正确结果**，门禁照样通过——不许用「过门禁」暗示「差异显著」。②Wilson 区间假设行之间独立，但同一 `(task, seed)` 的 A/D 是配对的，所以配对检验（McNemar / 配对 t）才是主口径，z 检验只作参照。③**bootstrap 必须按任务聚类**：同一任务的三个 seed 相关（实测 ICC 0.28–0.56，有效样本 ≈35–42 而不是 75），按行重抽会系统性偏窄；行级区间保留为 `bootstrap_ci95_row` 只作对照。④`n_for_80pct_power` 是**事后**按观测效应量算的，只能用来回答「还要多少样本」，不能用来回溯宣称本轮已达标。⑤`len(text)//4` 仍是 token 代理，见 C13⑤；**真实 tokenizer 口径由本声明的 `usage_*` 三项并列发布**，两者方向冲突时以真实口径为准。⑥端点不严格复现 seed（C13③），所以「重复」是在增大 n，不是复现性证据。⑦`usage_*` 是端点自己报的 `usage`，**跨轮可比但不可与 C27 的 `cl100k_base` 数字混用**（两者在 CJK 与 hex 形状上不可互换） |
| 状态 | 已证实（确定性统计审计，无 API 调用） |

### C27 · `len(text)//4` 观察 token 代理必须被真实 tokenizer 校准

| 维度 | 内容 |
|------|------|
| 主张原文 | 本仓库**所有**观察 token 数字（C13–C17、C19、C20 的 headline，以及 D/A 比值）都来自 `estimate_tokens(text) = max(1, len(text)//4)`。这条代理此前从未被真实 tokenizer 校验过，而 C13⑤/C14④/C15⑤/C16⑤ 只是把「不是真实 tokenizer」当作边界登记。本声明要求把它**测出来**：代理的误差方向、量级，以及它是否构成真实 token 数的**上界**——结论是**既不是上界也不是下界**（见下） |
| 门槛数字 | `== 1.00`（8 项检查：用了真实 tokenizer、tokenizer 可解析、锚点落在预期区间、四个问题都被显式回答、有样本）。门禁的是「校准存在且诚实」，**不是**「代理准确」 |
| 口径 | 被校准的量是**配对**的：同一份观察文本同时算 `proxy = max(1, len(text)//4)` 与 `real = tiktoken:cl100k_base`，比值 `real/proxy` 以**文本**为单位配对（n=60，来自 30 个重放单元 × 2 条件），均值/中位就是本条的估计量。`real` **不是**端点 usage、**不是**被测模型 `sn-glm-5-3-flash` 的 tokenizer；锚点文本与形状面板是**固定合成文本**，不进 n=60 的统计。端点探测（每次请求唯一 nonce、K=4 取最小）是**次级交叉核对**，与 `cl100k_base` 并列报出、**不平均**（口径总表见 §1.5） |
| 复现命令 | `python tools/token_proxy_calibration.py --out eval/token_proxy_calibration.json`（`--no-endpoint` 可完全离线），再 `python tools/claim_gate.py` |
| source | `tools/token_proxy_calibration.py`、`bench/aci/runners/live_agent_loop.py`、`bench/aci/results/latest_live.json`、`eval/token_proxy_calibration.json` |
| 样本量 / 日期 | 从已存 live 轨迹重放的 60 个观察文本（两条件各 30），用 `tiktoken:cl100k_base`（tier 1，真实 BPE，非近似）逐个测量 |
| 最近实测（**r15-2026-09-29（当前）**，产物 `eval/token_proxy_calibration.json`，`generated_at` 2026-09-30T09:48:49+08:00，`method_revision=2`；**离线重建 `--no-endpoint`**） | **本轮数字（当前）**：`real/proxy` 均值 **1.2872**、中位 **1.2485**（sd 0.2370，min 0.8882、max 1.8824）；相对误差 `(proxy-real)/real` 均值 **−0.1969**、中位 −0.1990。**52/60** 样本代理**低估**（`real > proxy`，86.7%）、**7/60** 代理**高估**、**1** 相等——**所以 `len//4` 既不是上界也不是下界**。按字符类别：`ascii_only` n=**50** 均值 **1.2632**、`non_ascii_other` n=**9** 均值 **1.407**、`cjk` n=**1** 均值 **1.409**。锚点通过：400 字符英文段落 = 100 proxy vs 89 real（预期 [80,120]）。`measurement_integrity.all_measured_on_full_text = true`（60/60 在全文上测量）；字节不变量 `real_tokens <= utf8_bytes` **0/71 违反**；旧的 `real_tokens <= chars` 上界**已撤回**（cl100k_base 是字节级 BPE）。**端点交叉核对本节未重测**（本轮 `--no-endpoint`，`endpoint_cross_check.enabled=false`）——下面那组 20/20、1.0135、0.5986 / 1.2222 是 **P2-5 修复前产物**的读数、**不是本轮值**，须由测试方在下一次校准中重跑。**历史读数（逐轮，不得当常数）**：P2-5 修复前产物 `real/proxy` 均值 **1.2442**、中位 **1.2150**（sd 0.2268，min 0.7361、max 1.7451）；相对误差 `(proxy-real)/real` 均值 **−0.1686**、中位 −0.1770。**52/60** 样本代理**低估**（`real > proxy`，86.7%）、**7/60** 代理**高估**、**1** 相等——**所以 `len//4` 既不是上界也不是下界**。按字符类别：ASCII-only n=**47** 均值 **1.2505**、非 ASCII（`non_ascii_other`）n=**13** 均值 **1.2213**。锚点校验通过：400 字符英文段落 = 100 proxy vs 89 real（预期 [80,120]）；`length_ladder` 单调。形状依赖显著（历史：P2-5 修复前产物的形状面板实测）：英文散文 400 字符 0.89、800 字符 0.722（代理**高估**）、python 源码 0.9423、pytest 失败输出 0.9326、cargo 诊断 1.2548、JSON 信封 1.6238、hex 摘要行 1.8、base64 2.5581、**CJK 段落 278 字符 / 284 real token = 4.1159**（代理**低估**，且**不被字符数上界住**）——**不存在单一修正系数**。**历史对照（保留作逐轮证据，不得当常数）**：上一轮同口径重放为均值 **1.5613** / 中位 1.4914 / 60-60 `real > proxy` / CJK 2.50；2026-09-26 那次为均值 **1.2498** / 中位 1.2146 / 49-60（当时写作「约 16.5%」）；P2-5 修复前产物 1.2442 / 52-60（「约 16.9%」）。**方向（代理低估、形状依赖、既非上界也非下界）稳定，但头条量级跨轮不可复现且新的重放不是逐位确定的**（重放样本与端点探测都随机）。**引用时必须写「本轮实测」并给本轮 n 与区间，不得把「约 33%」或「约 16.5%」当成常数。** 端点交叉核对（**不同口径，不得平均**）：20/20 文本稳定、与 `cl100k_base` 在重放样本上均值 1.0135、中位绝对差 3.0 token；但在 2/11 形状面板上不可互换（CJK 端点/主口径 **0.5986**、hex 摘要行 **1.2222**，本轮实测；上一轮同两项为 0.6021 / 1.2667），两个数字并列报出、不做平均。**该端点交叉核对测自 P2-5 修复前的产物；r15 的离线重建不覆盖它（`endpoint_cross_check.enabled=false`），须由测试方在下一次校准中重测。** |
| 失效边界 | ①**校准用的 tokenizer 不是被测模型的 tokenizer**：`cl100k_base` 是真实、公开的 BPE 词表（GPT-4/3.5 系），被当作「现代 BPE tokenizer」的替身；它不代表 `sn-glm-5-3-flash` 的真实分词，所以**不能用它去修正 C13 的数字**，只能用来说明代理误差的量级与方向。②端点自己的 `usage.prompt_tokens` **不能当基准**：它按内容缓存（同一文本重复返回同一个值，哪怕那个值是错的），且相当比例的请求会被恒定抬高约 +170；工具用「每次请求唯一 nonce + K=4 次取最小值」中和这两点。**任何单次测量都是无效的。**③样本是**从已存 live 轨迹重放的 30 个单元 × 2 条件 = 60 个观察文本**（`sample_source = replayed_live_trajectories`、`max_units = 30`），**不是第 14 轮的 35 任务整轮**，也不代表全轮或全语料；`by_size_bucket` 显示权重偏短观察，长观察只由合成 fallback 语料代表。④`real/proxy` 的分布是**形状依赖**的，不是一个常数——所以不存在「把 D/A 乘以某个系数」这种修正；引用 C13 的 token 数字时必须说明「该数字是 `len//4` 口径」。⑤本条不改变 C13 的结论方向，只改变它的**量级解释**。⑥**代理既不是上界也不是下界**：两个方向都有反例（r15 52/60 低估、7/60 高估；CJK 段落 278 字符 / 284 real token 是「不被字符数上界住」的具体反例），**头条量级不可跨轮复现且本轮重建不是逐位确定的**（1.5613 / 1.2498 / 1.2442 / 1.2872），方向稳定而**具体百分比不稳定**——任何「代理低估约 N%」的表述都必须带本轮样本量与区间，并注明它换一轮就会变。⑦`ratio_check.published_proxy_ratio_D_over_A = 0.8855` 的**来源不可考**（产物只记录了这个数，未记录它取自哪一轮／哪份产物），**不得当作当前整轮 D/A 基线**（见 §1.5）。⑧端点 `usage` 与 `cl100k_base` 是**两种口径**，本条只用后者做校准；不得用本条的 `real` 去修正或平均 C13/C25 的端点 `usage` 数字。⑨**本条的 1.2442 / 1.2150 / 52-60 是 P2-5 全文测量修复之前产物的读数**：修复前 60 个样本里有 **6 个**的 `real_tokens` 在产物内的截断副本上测量，而 `chars` 描述全文；修复后的离线重算为 1.2627 / 1.2288 / 53-60 / 6-60（n=60），且**重放不是逐位确定的**（第二次重跑 1.2623）——所以这些数字只能作为「某一轮、某一份产物」的读数引用，**必须带 n 与产物名**；**r15-2026-09-29 的离线重建（全文测量、`measurement_integrity.all_measured_on_full_text=true`）为 1.2872 / 1.2485 / 52-60 / 7-60（n=60），同样不是逐位确定**。定性结论（非上界/非下界、形状依赖、无单一修正系数、量级跨轮不可复现）不受影响。⑩**端点交叉核对**（20/20 稳定、均值 1.0135、CJK 0.5986 / hex 1.2222）出自 P2-5 修复前的产物；**r15 的离线重建没有重测它**（`endpoint_cross_check.enabled=false`），**属于测试方下一次校准的重测范围**，不得当作修复后的现行值 |
| 状态 | 已证实（真实 tokenizer 校准 + 确定性复算） |

### C28 · 肯定式声明必须达到预注册的样本量／精度门槛

| 维度 | 内容 |
|------|------|
| 主张原文 | **每一条以肯定口吻写出的声明，其区间必须越过自己的门槛**；而**整个 CI95 都落在门槛错误一侧**的声明必须被标成**产品缺口**，而不是「还需要更多数据」。反过来，点估计越界但区间仍跨到可达成一侧的，只能写成**无证据**——点估计会随样本移动，把它说成产品缺口会让人停止收集本该继续的数据。判据、预注册 MDE、精度目标全部写在 `docs/acceptance-criteria.md`，参数表在 `tools/acceptance_power.py::PREREG`，两处必须逐字一致。本声明是**元声明**：它不测产品，它测「我们有没有资格下那些结论」 |
| 门槛数字 | `== 1.00`（**7** 项检查：预注册参数已记录、**11** 个验收项齐全（含 D vs A′ 的成功率与 CPST 两行）、**每一项都有显式布尔 `claimable`**（不许出现 `null`——「未知」不得被读成「没问题」）、`impossible_by_sample_size` / `gap_type` 与**区间**自洽、**比值判定必须由按任务聚类的区间做出**（`unit == "task"`）、**真实 tokenizer 口径必须并列发布**、以及本仓库**确实主张**的验收项（跨 shell 两条）必须 `claimable=true`） |
| 口径 | 它引用的 token 比值（L1/L2/L3、D/A′、CPST 的分子）都是 `len//4` **代理**口径的观察 token（与 C13/C25 同一个量）；同一产物必须**并列发布**端点 `usage` 的 `usage/prompt/completion_token_ratio`——那是**跨每一次请求累加的输入/输出 usage**、**不是**花费、**不能**与 C27 的 `cl100k_base` 互换或平均。样本分母：当前 live **30 对**（比值判定按任务聚类），跨 shell 为 5 操作 × 20 次迭代；「所需 n」是**精度外推**（按 1/√n 缩放），不是功效计算 |
| 复现命令 | `python tools/acceptance_power.py --out eval/acceptance_power.json`，再 `python tools/claim_gate.py` |
| source | `tools/acceptance_power.py`、`docs/acceptance-criteria.md`、`bench/aci/results/latest_live.json`、`bench/aci/results/live_ab_without_read_files.json`、`eval/cross_shell.json`、`eval/live_uncertainty.json`、`eval/acceptance_power.json` |
| 样本量 / 日期 | 当前 live 30 对 + 跨 shell 5 操作 × 20 次迭代 |
| 最近实测（r15-2026-09-29；**计数随轮次移动，引用必须带运行日期与模式**） | **完整门禁 `python tools/claim_gate.py` = 29/31 PASS**——门禁当前登记 **31** 个 gated claims（以 `tools/claim_gate.py` 的登记表为准），红项只剩 **C14 = 0.045** 与 **C16 = 0.0789**（见各自条目），**C12 首次 PASS（25/25 门禁产物新鲜）**，C10 PASS；**完整跑没有 STALE 项**（`--skip-tests` 模式会把 C6/C7/C8 记为 STALE）。**这个计数每轮都会变**，所以只能写成「某日、某种模式的一次运行」，不得把任何一轮门禁结果当成当前状态。**（旧文此处写「22/25 gated claims pass」，那是门禁只登记 25 项时的更早一轮计数，已被取代。）** **所有区间按任务聚类**。**它如实登记了「现在不能主张什么」（r15 登记口径）**：①成功率 **D vs A**：观测 Δ=+0.0286、配对 CI95 [−0.0034, 0.0606]，当前 n=105 只能检出 `|Δ|≥0.0462` → **未检出**；**D vs A′** Δ=+0.0381，同样未检出。②token 比 L1「D 更省」（点 0.6075、CI95 **[0.5007, 0.7589]**）与 L2「省 ≥15%」（上界 0.7589 ≤ 0.90）在登记口径下**可主张**（Holm 校正后仍成立）；**L3「≤0.60」= `gap_type=data_gap`（无证据）**——点估计 0.6075 在 0.60 之上，但 CI95 下界 0.5007 仍低于 0.60，更多数据可能改变估计，**不是**产品缺口。③工具比「调用更少」= `data_gap`（点 0.8491、CI95 [0.6877, 1.0576] 跨 1.0）。④D/A′ 观察 token 比 = 可主张（点 0.7096、CI95 [0.5761, 0.8788]，上界 <1.0）。⑤CPST：D/A = **0.5889**、D/A′ = **0.6806**，非劣下界 **−0.0034 / +0.0013** ≥ −0.10 → **两条都可主张**。⑥**真实 tokenizer 口径**（端点 `usage`）总量 D/A 0.9461 [0.6462, 1.5202] 跨 1.0、输入 1.0255、输出 0.4259；D/A′ 总量 1.0817 [0.7558, 1.5772] 跨 1.0 —— 按 §4.2 以真实口径为准。⑦**跨 shell 两条**：5/5 操作通过（最差 CPU info **0.1834** [0.1817, 0.1845]）。**引用纪律**：以上是 r15 **基线刷新**（非预注册确认性采集；L1/L2/L3 未完成）的登记结果，**不得**当成新的已确证效应 |
| 失效边界 | ①它门禁的是**资格**，不是结论：一项 `claimable=false` 不代表产品不好，只代表**当前样本不许下这个结论**——门禁**故意不因此判红**（否则会逼人删掉诚实的数字）。只有「本仓库确实主张的项失去 claimable」「某项没有显式布尔」「`gap_type` / product-gap 标记与**区间**矛盾」才判红。②预注册 MDE（成功率 0.15）是**选择**，不是自然常数：MDE 越大所需样本越小，所以 MDE 必须写在看数据之前；改 MDE 等于改门槛，必须同时改文档与 `PREREG`。③比值类的「所需 n」是**精度外推**（区间宽度按 1/√n 缩放），不是严格功效计算；它回答的是「还要多少样本」，不能用来回溯宣称已达标。点估计已越过门槛时**不给**这个外推（`n_required=null`），因为此时约束是估计值本身而非区间宽度。④它建立在 C13/C25/C27 的产物之上，所以 live 基线换代后必须经 `tools/refresh_live_artifacts.py` 重跑（该脚本已把本项排在最后）。⑤它不检查自由散文：**文档里写没写肯定句，机器判不了**——这条边界只能靠评审，见 §4 的对应规则 |
| 状态 | 已证实（确定性功效／精度审计，无 API 调用） |

### C30 · 参考客户端的投影必须真的把内容交给模型（默认 `file.view` 的负载）

| 维度 | 内容 |
|------|------|
| 主张原文 | 工具描述承诺 `file.view` = 「View a window of lines around a cursor with total_lines and content hash」，即**窗口里的行**。参考客户端 `format_aci_result` 必须把这份负载交给模型。**实测（第 11 轮）发现它没有**：投影里有一段 `if len(lines) <= 10` 的分支，**只要窗口超过 10 行，就既不输出 `text` 也不输出 `lines`**，只留下 `content_hash` 与 `total_lines`。而 `file.view` 的默认窗口是 **80 行**，所以**用默认参数调用 `file.view` 读任何超过 10 行的文件，模型拿到的只有一串哈希**。 |
| 门槛数字 | `== 1.00`（契约检查：对**超过 10 行**的文件用**默认窗口**调用 `file.view`，投影必须携带内容）。原检查只用 3 行的 `src/lib.rs`，**恰好落在 ≤10 的例外分支里，因此一直是绿的**——检查本身太弱，这是本条最直接的教训 |
| 口径 | 所有 token（`>60 tok`、`repo.search` 301 次 / `65742 tok`、`exec.run` 303 次 / `20621 tok`）均为 `len(text)//4` **代理**，对参考客户端的投影文本计数；分母是第 11 轮 D 侧 live 的**调用计数**（`file.view` 204 次、`repo.search` 301 次、`exec.run` 303 次），**不是整轮观察量**；**不是**端点 usage、**不是**花费。其余数字（45%、`window=<default>` 105 次、`cat`/`type`/`head` 61 次）是比例与调用计数 |
| 复现命令 | `python tools/projection_contract.py --out eval/projection_contract.json`，再 `python tools/claim_gate.py` |
| source | `bench/aci/runners/live_agent_loop.py`（`format_aci_result`）、`tools/projection_contract.py`、`eval/projection_contract.json` |
| 实测证据（第 11 轮） | ①产品信封**是好的**：`ae` 返回的 `data.lines` 有 **45** 行、`window=80`；②参考客户端投影只剩 `{ok, content_hash, total_lines}`，**不含内容**；③D 侧 live：**204 次 `file.view` 中只有 2 次**带回内容（>60 tok），**180 次是纯元数据**；④**45%（91/204）的 `file.view` 是在重复查看同一路径**——第一次拿不到内容，所以再查一次；⑤请求的窗口里 `window=<default>` 有 **105 次**，其余是 20/24/30/40/45/50/60/80/100——**全部 >10，全部被吞**；⑥D 于是转向 `repo.search`（**301 次 / 65742 tok**）与 `exec.run`（303 次 / 20621 tok），其中 **61 次 `exec.run` 是 `cat`/`type`/`head` 这类读文件命令** |
| 对 C13 的影响（必须写进结论） | **C13 第 11 轮的「D 更贵」至少部分是参考客户端造成的，不是 ACI 的固有代价。** 模型被剥夺了读文件内容的能力，只能靠搜索与 shell 绕路，这直接抬高了 D 的步数与 token。因此第 11 轮的否定结论**不能原样归因于接口**，必须与 C30 一起引用 |
| 失效边界 | ①这是**参考客户端**的缺陷，不是产品信封的缺陷：`ae` 返回的 `data` 里 `lines` 完整存在（45 行），被丢掉的只有客户端投影。②修复它会让 D 的观察 token **上升**（终于拿到内容），同时**可能让步数下降**（不必重复查看与绕路）——两个方向都必须重新测量，不能只挑有利的那个。③修好后 C16 的「rendered vs metadata-only」划分会大幅改变（默认视图不再是元数据-only），所以 C16 必须随 live 一起重跑。④`file.view` 的 `window` 上限由产品决定（默认 80），客户端不应再额外设一个更严的隐藏阈值 |
| 状态 | **已修复（2026-09-25）**：`format_aci_result` 的 `len(lines) <= 10` 门槛已删除（`file.view` 与 `file.read_many` 两处），改为携带工具实际返回的窗口；`tools/projection_contract.py` 新增两条用 **60 行文件 + 默认参数**的检查（`default window view returns content`、`read_many returns content`），**并做过负对照**：把旧规则重新套回去，新检查即判 FAIL。C30 单独设为门禁项，避免 C26 那种「fixture 太小所以看不见缺陷」的漏洞重现。**修复后 live 必须重跑**，重跑前 C13/C16 的第 11 轮数字仍受此缺陷影响 |

### C31 · 裸 shell 的观察通路必须无损解码非 ASCII 输出（TF-0100）

| 维度 | 内容 |
|------|------|
| 主张原文 | A／A′ 臂的观察来自 `execute_shell_cmd`。它此前调用 `subprocess.run(..., text=True)` 而**没有指定 `encoding`**，于是 CPython 按 **locale 编解码器**（本机 cp936）解码 shell 输出。输出里只要有一个在该编解码器下非法的字节，读取线程就抛 `UnicodeDecodeError`，`stdout` 变成 `None`，紧接着 `out += ...` 抛 `TypeError`，**整个 agent loop 中断、`trajectory` 为空**，而这一行被当作**普通任务失败**记进产物。这条通路此前**没有任何门禁**（所有已登记检查都只看 ACI 侧），所以它静默存在了三轮头条改写。 |
| 门槛数字 | `== 1.00`（三条检查全过：`utf8_observation_roundtrip` 用真实 `type` 读一个含 U+2014 的 UTF-8 文件、要求观察里该字符原样到达且带退出码标记；`empty_and_failing_commands` 要求空命令／不存在命令都返回 `str` 且不抛异常；`mechanism_control` 与主机无关地证明该 fixture 字节在 **cp936** 下确实不可解码） |
| 口径 | 本条不发布 token 数字：受影响量是**行数／文件数**（`raw_shell` 3/75、`raw_shell_coached` 2/75、`verseshell_aci` 0/75；全仓库 28 行崩溃），方向性影响的 0.120→0.083 / 0.160→0.137 是**成功率**、不是 token。它不测量 token 口径；引用受污染轮次的 token 数时，那些数仍均为 `len(text)//4` **代理**，**不是**端点 usage、**不是**花费 |
| 复现命令 | `python tools/harness_encoding_contract.py --out eval/harness_encoding_contract.json`，再 `python tools/claim_gate.py` |
| source | `bench/aci/runners/live_agent_loop.py`（`execute_shell_cmd`）、`tools/harness_encoding_contract.py`、`eval/harness_encoding_contract.json` |
| 实测证据（第 12 轮冻结 live） | ①受影响行：`raw_shell` **3/75**、`raw_shell_coached` **2/75**、`verseshell_aci` **0/75**；②触发点是**唯一带非 ASCII 的文本 fixture**（`bench/aci/fixtures/typescript_reduce_shared_accumulator_d80f462d/` 的三个文件各含一个 U+2014），该任务上 A 0/3、A′ 0/3、D 3/3；③全仓库 80 个结果文件共 28 行崩溃，26/28 落在同一个任务；④**方向性影响**：把这 5 行排除后 D−A 从 **0.120 降到 0.083**，D−A′ 从 **0.160 降到 0.137**；⑤契约检查在本机复现了机制：pre-fix 调用形态下 `stdout_is_none = true`，读取线程报 `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94` |
| 修复 | `execute_shell_cmd` 显式指定 `encoding="utf-8", errors="replace"`，并把 `out = r.stdout` 改成 `out = r.stdout or ""`；新增 `harness_fault` / `harness_crash` 两个逐行字段，`tools/three_arm_report.py` 与 `tools/live_uncertainty.py` 会单列并给出排除后的成功率（历史行按「有 `last_error` 且 `trajectory` 为空」识别） |
| 失效边界 | ①**强制 UTF-8 会改变非 UTF-8 输出的可读性**：GBK 编码的程序输出会变成替换字符。这是刻意的取舍——被测 fixture 与 `ae` 侧都是 UTF-8（Rust 侧用 `from_utf8_lossy`），两臂必须看到同样的字节，否则比较不公平。②`mechanism_control` 与主机无关，但 `utf8_observation_roundtrip` 只在 Windows＋cmd 下有意义（其它平台会走 `/bin/sh`，`type` 不存在）；在非 Windows 上该检查的失败应视为环境不适用，而不是回归。③它只覆盖**裸 shell 的观察解码**，不覆盖 `ae` 侧（后者已由 `errors="replace"` 与 `from_utf8_lossy` 处理）。④它**不**证明 A 臂没有其它 harness 缺陷，只证明这一类不再静默。 |
| 状态 | **已修复（2026-09-26）**，并登记为独立门禁项 C31 |

### C29 · 进入能力集的任务必须通过准入判据（用 LLM 生成数据集的前提）

| 维度 | 内容 |
|------|------|
| 主张原文 | 用 LLM 生成任务来扩样本量是**允许**的，但只有通过 `tools/task_admissibility.py` 准入判据的任务才能进入能力集。判据全部机械可检、且用**与 live runner 同一个求值器**（`live_agent_loop.check_success`）：**A1** pristine 必须失败、**A2** GOLDEN 必须通过、**A3** ≥2 个**看不到 golden** 的独立正确解必须通过（不同模型家族）、**A4a** 把 fixture 里每个测试/验证文件替换成「必过桩」后谓词**仍须失败**、**A5** 判定在重复执行下不翻转、**A6** prompt 不得逐字引用 golden diff、**A7** provenance（生成器 + 独立性声明）必须存在、**A8** `tier=large` 的任务在 pristine 上跑谓词自己的命令（不缩减 stdout+stderr）**实测观察量必须 ≥1000 token** |
| 门槛数字 | `== 1.00`（5 项检查：协议已记录、计数自洽、**被拒候选不得出现在 `bench/aci/tasks/`**、已发布且声明 `kind=capability` 的任务必须是已准入的、已准入的能力任务必须带反作弊证据）。门禁的是**晋升路径**，不是当前数量 |
| 复现命令 | `python tools/run_task_plan.py --plan bench/aci/candidates/FULL_PLAN.json --rounds N`（生成→准入→重生成缺的，收敛循环）然后 `python tools/task_admissibility.py --out eval/task_admissibility.json`、`python tools/freeze_task_set.py --version <v>`、`python tools/claim_gate.py` |
| source | `tools/task_admissibility.py`、`tools/task_generate.py`、`tools/task_generate_v2.py`、`tools/run_task_plan.py`、`tools/freeze_task_set.py`、`docs/task-generation-protocol.md`、`bench/aci/candidates/**/*`、`eval/task_admissibility.json`、`eval/task_set_freeze.json` |
| 样本量 / 日期 | 首轮 1 个候选；**第 11 轮：32 个候选 → 准入 15 个能力任务，全部晋升进 v2.0.0（25 任务）**；2026-09-25 |
| 第 11 轮实测（v2.0.0 定版） | **32 候选 / 准入 15 / 拒绝 17**，晋升 15 个进任务集（`eval/task_set_freeze.json` 记录清单与指纹）。**A8 是本轮新增的门禁且当场证明必要**：plan#1 的 large 候选实测失败转储 **2627 token**（达标），plan#4 只写 `pytest test_textutil.py` 于是只有 **231 token**（被拒）——「large」必须是门禁不能是愿望。**准入判据抓到的真实缺陷（逐项通过率）**：A1 pristine 失败 **31/31**、A4a 反作弊 **31/31**、A5 确定性 **31/31**、A6 无泄漏 **31/31**、A7 provenance **31/31**、**A2 GOLDEN 通过 16/31**、**A3 独立解通过 15/31**、A8 **2/7**。A2/A3 的低通过率根因是**生成器顺序错**（测试写在 buggy 模块之后 → 测试照着错误行为写，没有任何正确实现能满足），改成 TDD 顺序（正确实现 → 通过它的测试 → 使其失败的 buggy 版）并在写入前本地自检后修复。**预注册 30 个，实际准入 15 个**，原因是端点不可靠（空回复率随请求规模与时刻波动、单步常需跨 4 个模型轮换），这是**测量前的可行性修订**，组合规则（≥3 语言、独立解 ≥2、观察量分层、规模上限）一条没放松，**只有数量未达标**；后果「大观察占比 16% 而非 1/3」已照实登记（见 `docs/task-generation-protocol.md` §4.5） |
| 最近实测 | 23/23 PASS。**试点最有价值的结论是「我的第一版判据是错的」**：最初用 LLM 生成的「作弊补丁」当门槛，被要求「用最懒的方式骗过检查」的模型**没作弊、写了正确实现**，于是「shortcut 通过了」被误读成「谓词可被钻空子」；实际上两者无法区分。改成**机械**的 A4a 之后立刻定位到真缺陷：该任务的 prompt 明写「不要改 `test_batches.py`」而谓词**没有任何东西强制它**——把测试换成 `assert True` 就能过，任务测不到任何东西。**修法不需要改产品**：加一条 `file_contains` 守卫引用测试文件里一行有区分度的原文即可，任务随即 ADMIT（A1–A7 全过，且两个不同模型家族独立写的解都通过 → 谓词判行为而非写法）。`tools/task_generate.py` 的系统提示已强制要求这条守卫 |
| 失效边界 | ①**A4a 只能防「阉割验证器」这一种作弊**；硬编码答案、桩函数、改配置等其他形态靠 `file_missing_verifier` 场景下的 shortcut 与人工评审兜底。②`kind=mechanics` 的任务谓词天然等于交付物（如「创建内容为 X 的文件」），**允许存在但不得进入能力声明**——门禁不判它，靠组合规则排除。③判据只保证「任务是干净可判的」，**不保证任务有代表性**：代表性靠 `docs/task-generation-protocol.md` §4 的预注册组合（≥30 任务、≥3 语言、≥4 类别）。④它**不改 runner**：因为改 `live_agent_loop.py` 会让整条 live 证据链作废，而现有谓词词表已够用——这是刻意的取舍。⑤LLM 生成的 `shortcuts/` 只作参考信息并置 `needs_review`，**不得**当门槛（原因见「最近实测」）。⑥它不检查自由散文：prompt 是否泄漏答案只查「与 golden diff 逐字重合的长度 ≥12 行」，改写式泄漏要靠评审 |
| 失效边界补充（P0-2） | A3 验证独立正确解，A7 要求来源字段存在，均不证明任务作者独立于被测模型；C29 PASS 不能消除当前 25/25 个生成任务的同源风险。v2 新增的生成前家族/分组校验只验证显式声明的一致性，不验证服务商身份、训练数据或隐藏路由；家族来源须人工核实。旧候选不得靠补写声明变成新留出组，现有任务不重写；风险是否减轻仍须新的同源/异源 live 对照。本次不新增门禁阈值，也不重判既有任务。 |
| 状态 | 已证实（真实生成 + 机械准入判定） |

### C34 · 紧凑读投影必须去掉预注册份额的**命名信封开销**（混合不变口径，TF-0117，由 TF-0116 决策）

| 维度 | 内容 |
|------|------|
| 主张原文 | 参考客户端对读取操作的投影在 `compact=True` 下，相对 `compact=False`，必须去掉**命名信封开销**（`line_wrapper` + 可推导的 `counts` 两个分项）的 **≥40%**。这是 C14/C16 的**混合不变重述**：C14/C16 把节省定义成**占整个读取桶的比例**，而该比例随读法混合漂移（修完 C30 后 D 的读法变成内容主导，同一个投影只显示 8.3% 的总量节省），所以它**不是投影的性质** |
| 口径（逐字固定） | ①命名信封开销 = `line_wrapper` + `counts` **两个分项**的字符数（`content` / `digest` / `path` / `residual` **不计入**）；②被比较的是 `format_aci_result(compact=False)` 与 `compact=True`，**都用真实投影器**，不重新实现；③比值 = `(legacy − current) / legacy`；④读取位置 = `eval/read_path_breakdown.json` 的 `totals.legacy_parts` 与 `totals.current_parts` |
| 门槛数字 | `>= 0.40`，**且**必须在**比 `2.0.0` 更新的任务集**上测量，**且**产物自身指纹新鲜 |
| 口径 | 本条的量是**字符数之比**（命名信封开销 = `line_wrapper` + `counts` 的字符数），**不是 token、不是 `len//4` 代理、也不是端点 usage**。三个数字分属两种口径：`0.594` 与 `45.5%` 是**字符份额**，`8.3%` 是 C16 的 `len//4` **代理**总量口径——回答不同问题，不得相加或互相替代。它是**确定性重投影**，没有抽样区间（`p` 值／区间口径不适用） |
| 数据集要求（是声明的一部分，不是附注） | 45.5% 那个数字是在 **task set 2.0.0** 上测到的（`legacy_parts` 30440 → 16583 字符），所以**在 2.0.0 上判 FAIL**——用发现问题的同一批数据证明修复就是分叉花园。门禁按 `eval/task_set_freeze.json` 的 `task_set_version` 与 `DISCOVERY_VERSION = "2.0.0"` 比较，并要求 `eval/read_path_breakdown.json` 记录的指纹与自身 globs 现在仍然一致（否则只要升一次任务集版本就能让旧数字「通过」） |
| 复现命令 | `python tools/read_path_breakdown.py --out eval/read_path_breakdown.json`，再 `python tools/claim_gate.py` |
| source | `tools/read_path_breakdown.py`、`eval/read_path_breakdown.json`、`eval/task_set_freeze.json`、`docs/acceptance-criteria.md` §4.5 |
| 实测证据（r15-2026-09-29 全链刷新，**达标证据**） | **task set 3.0.0** 上：命名信封开销 42033 → 17923 字符 = **0.5736**（≥0.40 **PASS**，`eval/read_path_breakdown.json` 指纹新鲜）→ 它是 **C14/C16 的可主张替代**。**历史对照（不作为达标证据）**：2.0.0 上 23905 → 9706 字符 = **0.594**（达标却因「未在新数据上验证」判 FAIL，这是设计行为）；2026-09-29 之前的 0.5654；同一次优化按 C16 的总量口径只有 **8.3%** |
| 失效边界 | ①这是**冻结调用集上的客户端渲染效应**，**不是模型行为测量**，也不说明 ACI 是否省**总** token；②对总量而言同一优化在 2.0.0 上只有 8.3%——两个数字都对，回答的是不同问题；③它**不能替代 C14/C16**：那两条按原口径**保持 FAIL，门槛不动**；④`≥0.40` 是**产品决策**（TF-0116），不是从数据里挑出来的，改动必须先改文档与 `THRESHOLDS` 再验证；⑤`p` 值/区间口径不适用——这是确定性重投影，不是抽样估计 |
| 状态 | **已登记（预注册于第 14 轮 live 之前）；r15-2026-09-29 在 task set 3.0.0 上 PASS（0.5736）**；门禁项 **C34**。C14/C16 保持 FAIL 不变 |

### C32 · raw-shell 执行的墙钟、进程树与 checkpoint 契约

| 维度 | 内容 |
|------|------|
| 主张 | 超时执行能结束并清理持有输出管道的后代进程；正常命令的退出码、stdout/stderr 保留；已完成的行逐格写入 checkpoint |
| 门槛 | `== 1.00`：`eval/harness_exec_contract.json` 的非空检查集全部通过；C12 另验代码指纹新鲜度 |
| 复现 | `python tools/harness_exec_contract.py --out eval/harness_exec_contract.json`，再运行完整 `tools/claim_gate.py` |
| 来源 | `tools/harness_exec_contract.py`、`bench/aci/runners/live_agent_loop.py`、`eval/harness_exec_contract.json` |
| 负对照 | 旧 `subprocess.run(timeout=...)` 仅杀直接子进程的形态必须仍失败；探针自身有外层时间界限 |
| 边界 | 本机执行契约，不证明模型 API 的 300s 限制已解除，也不证明所有任意进程拓扑或崩溃恢复场景均已覆盖；checkpoint 存在不等于重复研究独立 |
| 当前状态 | 以当前 `eval/evidence.json` 的 C32 和 C12 为准，不从历史交接继承 PASS |

### C37 · 发布统计量的第二实现复算

| 维度 | 内容 |
|------|------|
| 主张 | 用另一代码路径从原始行重算已发布量，比较闭式量与独立随机种子的 bootstrap 结果 |
| 门槛 | `== 1.00`；门禁要求比较集非空、声明比较数至少 20、`n_failed=0`，同时覆盖 `closed_form` 与 `resampled` |
| 比较规则 | 工具对闭式量使用 `5e-4` 舍入容差，对重采样量使用 `0.02` 容差并检查位于 1.0 的同侧；不移动这些既有容差 |
| 复现 | 先刷新 `live_uncertainty` 和 `acceptance_power`，再 `python tools/statistics_crosscheck.py --out eval/statistics_crosscheck.json`，最后完整门禁 |
| 来源 | `tools/statistics_crosscheck.py`、`eval/statistics_crosscheck.json`、`eval/live_uncertainty.json`、`eval/acceptance_power.json`、`bench/aci/results/latest_live.json` |
| 边界 | 第二实现一致能发现算术/重采样实现错误，不证明统计假设、覆盖率、数据独立性或正式验收资格；C12 另验新鲜度 |
| 当前状态 | 以当前 `eval/evidence.json` 的 C37 和 C12 为准；历史比较数量不作新测量 |

## 4. 与 README 主张的对应关系

- README 若出现 C1/C2 类数字，必须写成「mock bench，10 任务/条件，seed 42」并指向 `eval/evidence.json`，不得写成真实模型实测。
- C9 是**分层**声明：可以说「小响应信封 ≥40% 节省（r15 实测 **0.4203**，byte 侧 42.39%）」，不得把它写成「compact 整体省 50–70%」或「观察载荷省一半」——后者实测为负。
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
- C21 是**任务集边界**声明：它把 ts fixture 的获取链拆成产品侧（裸名 `npm`/`npx` 解析缺陷）与环境侧（fixture 不带 `node_modules`），并记录两侧如何被逐轮关闭。引用时要写明「v1.2.0 起该任务已不再有环境边界，反事实 band 退化成一个点」，并带上「本工具现在真的跑 tsc（因此需要 node）」「失败归因看 C22 的探针」两条边界；不得把历史数字写成「ts 任务 40% 的 token 是浪费」。
- C23 是**ts 任务判定**声明：它要求该任务的成功判定是行为判定（跑自己的 `tsc`），且 pristine 失败、GOLDEN 通过、等价修复也通过。引用时必须带上「只守这一个任务」「依赖本机 node」「fixture 自带工具链是前提」三条边界，不得写成「所有任务的成功判定都已行为化」。
- C24 是**任务集自洽性**声明：它用 live runner 的同一个求值器检查全部 10 个带 GOLDEN 的任务（pristine 必须失败、GOLDEN 必须通过，注册过的等价变体也必须通过）。引用时必须带上「只是夹具级自洽，不是模型行为」「变体只注册了两个任务」「不覆盖任务是否真的做完」三条边界，不得写成「所有任务的判定都已经行为化」。
- C5 是**文档充分性**声明：它用真实模型调用测「只读 quickstart 能不能用对合同」，门槛是 `op_acceptance_given_ops_emitted >= 0.70`。引用时必须带上「分母排除『一个 op 都没输出』的格」「探针只有 5 个自造小场景、且要求一次性输出 JSON 行（真实 agent 走 tool-calling 通道）」「端点不严格复现 seed」三条边界；不得写成「quickstart 已被证明好用」这类无边界肯定句。
- C25 是**统计审计**声明：它门禁的是「不确定性是否存在」，不是「差异是否显著」。引用 live 数字时必须同时给出区间（Wilson / bootstrap）与配对检验结果；**不得**用「门禁通过」暗示「D 优于 A 显著」。当前样本下成功率的 A/D 差异不显著，两条冻结数值门槛也未达成——这是本声明的结论，不是它的失效。
- C26 是**投影契约**声明：它守「工具描述承诺的负载必须真的到达模型」。引用时必须带上「只覆盖投影层，不覆盖产品信封」「检查集是显式登记的 6 项，不覆盖全部 32 个 op」两条边界；不得写成「所有 op 的投影都已验证」。
- C27 是**代理校准**声明：它把 `len(text)//4` 的误差测出来（**r15-2026-09-29** 均值 **1.2872**、中位 1.2485、52/60 低估、7/60 高估——**既不是上界也不是下界**；形状依赖、无单一修正系数；头条量级跨轮不可复现且本轮重建不是逐位确定的，引用必须写轮次与产物名并带本轮 n 与区间，早期读数 1.2442 / 1.2627 只作历史。**端点交叉核对 r15 未重测（`--no-endpoint`），须由测试方在下一次校准中重跑**），但**校准用的 tokenizer 不是被测模型的 tokenizer**。引用任何观察 token 数字时必须说明「该数字是 `len//4` 口径」，并带上「形状依赖、不能用单一系数修正」「端点 `usage.prompt_tokens` 不可作基准」两条边界；不得用 C27 去直接修正 C13 的数字，也不得把 C27 的 `cl100k_base` 与 C13/C25 的端点 `usage` 互换或平均。
- **C28 是元声明，优先级最高**：它规定「什么条件下才允许下结论」。任何以肯定口吻写出的新数字，先在 `docs/acceptance-criteria.md` 的对应验收区里查它是否 `claimable=true`；`claimable=false` 的项**只能**写成「未检出／样本不足／产品缺口」，**不得**用「接近」「趋势」「即将达标」这类软化措辞包装。特别地：`impossible_by_sample_size=true` 的项（当前是冻结目标 ≤0.60）**禁止**写成「还需要更多数据」——它是产品缺口。引用时不要只给点估计：每个数字必须带区间与**当前 n 的检出限**。
- **C29 是数据来源声明**：用 LLM 生成任务是允许的（当前 10 任务集外部有效性为零、功效不足），但任何进入能力声明的任务必须先过 `tools/task_admissibility.py`。引用生成的数据集时必须带上「组合规则已预注册（≥30 任务/≥3 语言/≥4 类别）」与「任务集在测量前已冻结」两条，且**不得**按 token 结果增删任务（那是挑选数据）。`kind=mechanics` 的任务**不得**计入能力声明的样本量。
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



### TF-0137 消费者修正（2026-10-08）

旧单 collection 的三项 OR 仅保留为描述性改善，不再生成正式 PASS。JSON、Markdown、score CLI、三条件报告、研究数据资格及 C35 已接入明确的资格/推断边界；数值阈值、原始历史评分和旧产物不变。
本批 Python 276 项中 273 通过、3 tokenizer 依赖跳过；Rust 289 通过、1 忽略。旧轮 1050 行的四个比较全部不可主张，原文件 SHA-256 未变。产品门禁 24/31：C12/C14/C16/C24/C34/C35/C36 未通过；新增 C35 是检出旧 canonical comparison 的肯定标签，不是将当前代码认定为已正式验收。
命令、逐入口清单、原始证据及失效边界见 [TF-0137 修复回执](strict-acceptance-repairs-2026-10-08.md)。单项工程回归、描述性改善和报告 exit 0 均不替代冻结的重复研究；本轮不产生新的模型实验、成本收益或产品达标主张。


### TF-0138 双估计量与评分环境修正（2026-10-09）

新增只读成本归因报告，在同一有效配对集上并列总量比值、cell 等权和任务等权敏感性。四组 174/175/174/172 个有效配对与前序记录一致：总量比值 0.165479–0.265806，而 cell 等权均值 1.247022–1.547065。两种口径方向相反必须同时披露，不能推广为普遍节省。
新请求 profile 只记录准备的 JSON 字节构成和摘要，不改变请求体；旧轮没有此记录，组件 token、reasoning、缓存计费和金额仍未知。正式计划继续保留两个估计量，不更新旧摘要。
真实隔离收尾链曾因共享 Cargo target 污染而在当前 fixture 审计失败。独立评分目录修复后，当前 35/35 pristine/GOLDEN 对照及四阶段报告链通过；这不是历史 live 重新评分。模型工具环境及旧轮是否受影响仍需 TF-0139 核验。完整测试、反例和边界见 [TF-0138 回执](cost-attribution-repairs-2026-10-09.md)。


### TF-0139 全量证据覆盖与环境边界（2026-10-09）

对 step5p-d-r1-20261007 全部1050行完成只读观测审计：143格基础异常并集、907格成功对照；覆盖全部270格Rust行和其中244格原始成功。19,350条观测的摘要、cell与操作名均核验；其中908条旧完成确认缺参数、31条脱敏记录未完整核验参数绑定。这些限制与底层因果 unknown 均保留，不能称为全量独立复评分或全部根因已确认。
模型工具的工作区构建目录隔离已补齐，三条件真实子进程与六个pristine/GOLDEN工具命令对照通过；未来完成确认补存args，默认构建配置有回执。旧轮是否继承过共享Cargo目录仍缺证据。Python321项中318通过/3跳过，进程树受控探针7/7；不以工程通过替代正式重复实验和产品门禁。
逐格清单、反例、成功对照、分域规则及未测边界见 [TF-0139回执](anomaly-audit-repairs-2026-10-09.md)。


### TF-0140 选定输入、版本与当前状态（2026-10-09）

门禁新增claim_inventory，覆盖31个门禁与6个无阈值诊断。实际文件、SHA-256、源/二进制版本、记录样本量及状态分开输出；门禁前后源文件或已消费输入变化，以及通过项仍缺当前绑定，均使C12保持失败。数值谓词通过不再被解释为该输入已适用于当前源码。
可用版本化artifact-map选择独立证据目录。已有显式CLI与map冲突时拒绝；不复制或覆盖canonical旧文件。C12及README检查读取同一选择，C3/C4补记实际metrics输入，C24补记实际审计和任务集。未指定metrics/compact时，原生生成结果写在本次evidence输出旁并保存实际命令。
当前受控重放：C14的计数匹配集合仅6/144，节省约4.9%（仍低于15%）；C16仅3/144，约8.1%（仍低于10%）。这些匹配不证明旧内容相同；不匹配也不能一律归因于live生成状态。C34另外要求实际源摘要、任务清单、实际版本与冻结一致且严格新于2.0.0，再检查原40%命名开销门槛，不能只换版本标签。
README compact百分比改用C9实际门禁采用的较保守侧42.0%，而非单独字节侧约42.4%；两种原始值均保留。旧计时和live数字仍限定为历史，不作为当前版本或当前端点效果主张。
完整重复、独立任务与作者来源尚须TF-0112/0114/0115等节点的实际证据，并通过既有冻结研究评估路径。此矩阵不授予科学效果结论；当前受控验证不能替代这些前置条件。复现与对照见 [TF-0140回执](claim-routing-2026-10-09.md)。


### 新冻结 readiness 与端点前置边界（2026-10-09）

本次独立D盘验证副本与当前370个运行时源码/测试文件逐字节一致，另固定一份历史单元测试fixture。最终Python345项全部执行并通过，无跳过；Rust289通过/1忽略，当前fixture35/35，三配置校准及3150格合成采集/恢复/合并链通过。合成结果没有获得实证主张资格，也不构成三次真实重复。
真实StepFun端点探针在首个请求收到403账户认证前置要求，第二请求及真实基准未启动。没有返回usage，不能写成零成本；失败回执保留已知尝试和缺口。当前访问资格不能从历史成功推断；需要账户持有人处理后重新核验。此处没有更改历史预算上限或声明原阈值。
完整来源、环境修复、历史完成状态纠正及未完成项见 [落地与readiness回执](landing-readiness-2026-10-09.md)。
