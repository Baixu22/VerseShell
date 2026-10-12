# 修复交接单：第 14 轮 live 暴露的产品与管道缺陷

> **读者**：接手修复的 agent / 工程师。
> **写作时间**：2026-09-29。**基线**：`task_set_version = 3.0.0`，完整门禁 **29/31**。
> **本文件自包含**：你不需要本次会话的上下文。所有结论都指向仓库内可复算的产物与命令。
>
> **分工（重要）**：**你只做修复**，不跑 live、不改任务集。改完之后由原测试方重跑测量。
> 判定你改完是否合格的最小自检见 §7。

---

## 0. 一句话背景：这次测试到底测了什么

被测对象是 **VerseShell 的 ACI 接口层**（typed observation ops + 紧凑投影 + 配套系统提示），
问题是：**在同一个真实函数调用模型上解决同一批任务时，它是否比裸 shell 更省步数/token、成功率是否更高。**

第 14 轮的实际配置（全部来自 `bench/aci/results/latest_live.json` 的 `live_config`）：

| 项 | 值 |
|---|---|
| 模型 | `sn-glm-5-3-flash`（本地 OpenAI 兼容端点 `http://127.0.0.1:3065/v1`） |
| 任务集 | v3.0.0，**35 个任务**（10 手写 + 25 生成） |
| 条件（三臂） | `raw_shell`（A，裸 shell）、`raw_shell_coached`（A′，等长提示对照）、`verseshell_aci`（D，被评估的接口） |
| seed | 42 / 43 / 44 |
| 规模 | 每臂 315 格 = 35 任务 × 3 条件 × 3 seed；**两臂共 630 格**，每格都是一次真实模型调用 |
| 预算 | `max_turns=20`、`max_tokens=16384`、`temperature=0.0` |

**但这一轮真正花时间的是第二层**：因为端点随机、且客户端与 harness 有缺陷，
大部分工作是先确定"这些数字到底能不能用"——行分类、预算混淆、跑间方差、统计代码独立复算、证据指纹新鲜度。
**最终 7 个未关闭项里有 3 个属于测量装置本身，不是产品。**

**这一轮没有测的东西**（引用时必须说明）：35 个小型合成任务、单一模型、单一端点、单机、单轮。
它**不能**支持"ACI 在总体上更好/更差"，只能支持"在这套配置的这一轮里，以下具体事实成立"。

---

## 1. 第 14 轮的结论（修之前必须先看这个）

### 1.1 按预注册的 §0.6 行处置规则（`docs/acceptance-criteria.md`）

> 修复核查：下表重新按原§0.6计算当前冻结文件，未改原始行、未重跑live。旧D值0.8381是全部已评分行成功率，不能标作把被排除行计失败的ITT。

| 臂 | n | endpoint_failure | cap_truncated | 排除率 | ITT成功率 | analysable成功率 |
|---|---:|---:|---:|---:|---:|---:|
| A raw_shell | 105 | 0 | 4 | 3.8% | 0.9048 | 0.9406 |
| A′ raw_shell_coached | 105 | 0 | 0 | 0.0% | 0.8762 | 0.8762 |
| D verseshell_aci | 105 | 0 | 15 | 14.3% | 0.8190 | 0.9556 |

**D 的 cap 截断率 14.3% > §0.6.3 的 10% 门槛 → 两条成功率对比与全部 token 比值对比都被判为不可主张。**

### 1.2 数字本身（引用时必须成对给出两个口径）

| 量 | 点估计 | CI95（按任务聚类） |
|---|---|---|
| 全部已评分行成功率 D−A（非保守ITT；配对 McNemar，only_A=10 / only_D=3，p=0.092285） | −0.0667 | [−0.1331, −0.0003] |
| 观察 token 比 D/A（`len//4` 代理） | 0.6347 | [0.5148, 0.7776] |
| **真实 tokenizer 总 token 比 D/A** | **1.3583** | [1.0303, 1.8986] |
| 真实 tokenizer 输出 token 比 D/A | 1.894 | [1.145, 3.2616] |
| CPST D/A | 0.6852 | 成功率非劣下界 **−0.1331 < −0.10 → 非劣不成立** |

**口径不可混用**：全部已评分行D低6.7pp，按§0.6保守ITT约低8.6pp，analysable约高1.5pp。排除规则改变了估计对象；仅凭符号变化不能证明预算是唯一因果解释。

### 1.3 不同 seed 的描述性波动（不等于独立完整跑间方差）（`eval/run_variance.json`）

| 指标 | seed42 | seed43 | seed44 | 跨seed描述性 SE / 已发布半宽 |
|---|---|---|---|---|
| 成功率差 D−A | **+0.0286** | **−0.0857** | **−0.1429** | **0.76×** |
| 观察 token 比 | 0.7182 | 0.6220 | 0.5817 | 0.31× |

**符号在 seed 之间翻转**。已发布区间未包含独立完整重跑的不确定性，**不得**把 `[−0.1331, −0.0003]` 读成"D 显著更差"。

---

## 2. 修复清单（按建议优先级）

> 每条格式相同：**症状 → 证据（可复算）→ 根因（已证实/待证）→ 修复范围 → 验收标准 → 禁止事项**。
> 机器可读版本见 `docs/repair-backlog.json`。

### P0-1 · D 臂专属的 turn-1 completion 截断（对应节点 TF-0121）

**症状**：D 臂 105 格里有 **15 格**在**第一轮**就把 16384 的 completion 预算烧完、**一个工具调用都没发出**，
从而被记为任务失败。A/A′ 基本没有。

**证据**（全部可在 `bench/aci/results/latest_live.json` 里按字段复算）：

- 这 15 行的字段签名完全一致：`completion_truncated_turns == 1`、`llm_completion_tokens ≈ 16453`、
  `tool_calls == 0`、`observation_tokens == 0`、`trajectory == []`、`elapsed_ms ∈ [199476, 213661]`、
  `last_error is None`、`harness_crash == False`。
- 逐臂均值（同一次运行内）：**每行输入提示 token** A 9,015 / A′ 9,924 / **D 11,393**；
  **每行 completion token** A 1,593 / A′ 1,610 / **D 3,017**。
- 被截断的 12 个任务的 pristine 观察量跨度是 **141–1559 token**（含多个 small/medium）——
  **与任务规模无关**，所以这不是"新任务太难"。

**根因**：**已证实的是相关，不是因果**。D 的提示/工具 schema 更大（+26%）且推理输出约 2 倍，
两者与截断同时出现；但"提示更大导致推理更多、进而烧穿预算"这一步**尚未被实验分离**。

**修复范围**：`bench/aci/runners/live_agent_loop.py` 的 D 侧系统提示与工具描述（体积/措辞）、
或端点侧 `max_tokens` 策略（注意 P0-3 的硬上限）。

**验收标准**：
1. 先做**因果分离实验**（见下），再改；不得直接缩提示了事。
2. 改后 D 臂的 `cap_truncated` 比例 **≤ 10%**（§0.6.3 门槛），且 A/A′ 不因此变差。
3. 新增/更新一条**逐行诊断字段**（例如首轮 reasoning 字符数），使"模型真的在思考"与"预算被烧穿"可区分。
4. 缓解方案必须在**下一轮 live 之前**写进 `docs/acceptance-criteria.md`（预注册），不得看到结果后再定。

**建议的因果分离实验（这是我最想让你先做的一件事）**：
把 D 的系统提示**截断/填充到与 A 相同长度**再跑同一批任务，看截断率是否消失。
若消失 → 是提示体积问题，缩提示即可；若不消失 → 是 D 的任务框架让模型倾向长推理，
那是更深的接口设计问题，缩提示解决不了。

**禁止**：不要靠抬高 `max_tokens` 规避（本端点 300 秒上限不可抬，见 P0-3）；
不要放宽 §0.6.3 的 10% 门槛。

---

### P0-2 · 生成任务的模型 = 被测模型（对应节点 TF-0115）

**症状**：**25 个生成任务全部由 `sn-glm-5-3-flash` 生成**，而这个模型同时是**被评测的模型**。
任务因此落在被测模型自己的分布内，任何对它有利的结果都**无法事后证伪**。

**证据**（可复算：遍历 `eval/task_set_freeze.json` 的 `promoted`，读每个
`bench/aci/tasks/<id>.json` 的 `provenance`）：

- `generator == "sn-glm-5-3-flash"`：**25/25**
- 独立正确解的作者：`sn-kimi-k3` 25 次、`deepseek-v4.1-flash` 25 次（这是 A3 判据要求的 ≥2 个独立解）
- 被测模型（`latest_live.json` 的 `live_config.model`）：`sn-glm-5-3-flash`
- `provenance.independent_of` 只声明"生成时未提供 VerseShell/ACI 上下文"——它**只保证提示隔离，不保证模型独立性**。

**根因**：数据集构造与被测对象同源。这是**设计问题**，不是代码 bug。

**修复范围**：`docs/task-generation-protocol.md`（独立性协议）、`tools/task_generate_v2.py`（作者模型选择）、
留出集的构造方式。

**验收标准**：
1. 下一批任务里，**留出集的一部分必须由非该端点家族的模型生成**（或引入公开数据集任务）。
2. 在 `docs/claims-and-evidence.md` 的 C13/C29 失效边界里写明该风险与其暴露面。
3. 给出"同源 vs 非同源"两组任务上 D/A 差异的对照结果（这需要一次 live，由测试方跑）。

**禁止**：不要声称已排除该风险；现有 25 个任务**无法**事后修复，只能靠新批次对照。

---

### P0-3 · 端点 300 秒非流式上限锁死 completion 预算（对应节点 TF-0120）

**症状**：抬高 `max_tokens` 不是补救——它把"长度截断"换成"无法合并的产物"。

**证据**（`audit-r12-scratch/cap_probe/`）：把 11 个被截断单元格用 `--max-tokens 32768` 原权重重跑
→ **通过 2、仍长度截断 0、HTTP 502 9**；失败墙钟全部聚在 ~300 秒；
`502` 报文为 `非流式响应超时(300秒)`；而 `bench/aci/runners/merge_live_runs.py` 遇到任何 `api_error` 行即 **exit 2 拒绝合并**。

**修复范围**：端点侧（proxy 配置）或 harness 侧的请求策略（如流式），**不在 `live_agent_loop.py` 里硬扛**。

**验收标准**：
1. 若端点不可改：在 `docs/acceptance-criteria.md` §0.5 保留现状说明（已写入），并把"预算敏感任务"做成
   **派生判定**（见 P1-1）。
2. 若端点可改：把 300 秒上限提高或改成流式，并**重新测量**该约束（不得继承旧结论）。

---

### P1-1 · 单格端点失败会卡死整条证据链（对应节点 TF-0122）

**症状**：一个格反复 502，就让**整轮** live 无法合并、所有派生产物永久陈旧（C12 判红）。

**证据**：
- `bench/aci/runners/merge_live_runs.py` 第 70–75 行：任何 `api_error` 行 → 打印错误并 `return 2`。
- 本轮实测：`python_csvlite_parse_80d158b2 [raw_shell]` 在 seed 42/44 上反复 502（一次连续 6 次失败），
  **但同格在 without 臂与后续重试中都能成功**——所以这是**端点状态相关**，不是该任务结构性不可用。
- 该工具**已有** `--allow-api-errors`，但它只写一个计数（`live_config.api_error_rows`），
  **不产出逐行分类**；而 §0.6 的分类只实现在 `tools/live_uncertainty.py::row_class()`。

**修复范围**：
- `bench/aci/runners/merge_live_runs.py`：`--allow-api-errors` 时调用**同一份** `row_class()`
  产出逐行 `row_class` 字段，并在产物里标 `partial: true`。
- `tools/claim_gate.py`：让门禁能区分"因端点失败而 partial"与"正常完整"，partial 时报出受影响的行与对比。

**验收标准**：
1. 用 `--allow-api-errors` 合并的产物带 `partial: true` 且每行有 `row_class`。
2. 门禁对 partial 产物给出明确且**非静默**的判定。
3. 负对照：人为把一行标成 `api_error`，门禁必须报出它。

**禁止**：不要把 502 当成模型失败计入成功率。

---

### P1-2 · 重刷链漏掉三份会随 live 变的产物（**本项是我在实操中被咬了两次才定位的**）

**症状**：`tools/refresh_live_artifacts.py` 跑完并 exit 0，但 C12（新鲜度）、C33、C10 **仍然红**。

**证据**：
- 该脚本的 CHAIN 只有 13 步（`tf45_envelope_replay` … `run_variance`），
  **不含 `eval/three_arm_report.json`、`eval/cross_shell.json`、`bench/aci/results/latest.json`（mock bench）**。
- 这三份都被 `tools/claim_gate.py::EVIDENCE_ARTIFACTS` 覆盖，因此 live 重跑后它们即判陈旧。
- `eval/cross_shell.json` 还读 `latest_live.json` 的 `wall_clock_context`；`eval/three_arm_report.json`
  读同一份 live 数据，C33 会因它 stale 而报 "row_policy disagrees between the two artifacts"。
- **顺序陷阱**：`tools/token_proxy_calibration.py` 的指纹覆盖 `bench/aci/results/*.json`，
  所以 mock bench **必须在校准之前**重跑，否则校准产物立刻陈旧。

**修复范围**：`tools/refresh_live_artifacts.py` 的 CHAIN，在正确位置补三步：
`run_suite.py --mode mock` → `three_arm_report.py` → `cross_shell_bench.py`（**都在 `token_proxy_calibration` 之前**）。

**验收标准**：在**不改动任何 live 数据**的前提下重跑该脚本，`python tools/claim_gate.py` 的 C12 必须为 PASS。

---

### P1-3 · `splice_live_cells.py` 的键与写盘语义（运维缺陷）

**症状 A**：它只认 `DEEPSEEK_API_KEY` 或 `--api-key`，而本仓库其余工具统一从 `.env.local` 读 `ACI_BENCH_API_KEY`
→ 直接运行必然 `ERROR: no API key`。

**症状 B**：它**只在整个 run 文件的所有坏格都成功后才写盘**；只要有一格仍旧失败就 `return 2`，
前面已成功的格子全部作废（本轮实际发生了：同一文件重跑 6 次，每次都重新消耗端点时间）。

**证据**：`bench/aci/runners/splice_live_cells.py` 第 37/41 行（键）、第 65–67 行（`return 2`）、第 77 行（写盘）。

**修复范围**：该文件。

**验收标准**：
1. 与仓库其它工具一致地读取 `.env.local` 的 `ACI_BENCH_API_KEY`（保留 `--api-key` 覆盖）。
2. 逐格写盘（或在全部失败时**保留已成功的补丁**并报告哪些仍失败），不得丢弃已完成的补跑。

---

### P2-1 · C14 / C16 产品缺口（紧凑读投影对"总桶"的节省不足）

**症状**：C14 = **0.0422**（门槛 ≥0.15）、C16 = **0.0768**（门槛 ≥0.10），均判 FAIL。

**证据**（`eval/tf45_envelope_replay.json`、`eval/read_path_breakdown.json`）：
- 本轮读取桶 pre-change 归因（字符占比）：`content 78.2%`、`line_wrapper 10.8%`、`residual 4.3%`、
  `counts 2.7%`、`digest 2.7%`、`path 1.4%`。
- C16 的行文本投影**只动** `line_wrapper` 与 `counts`，合计约 13.5%，所以对总量的影响上限就在这个量级。
- **混合不变口径下它其实做得不错**：命名信封开销 `40702 → 17688` 字符 = **0.5654**，已由 C34 判 PASS。

**修复核查补注（2026-09-29）**：单文件摘要归因器原先没有删除优先使用的短 `hash`，
把摘要成本记入了 residual。上面的归因比例已按修正后的129条匹配调用更新；总 token 与
C14/C16/C34 数字未变。另须区分：C14 是完整摘要对比短摘要，C16 才是行包装和计数对照，
不能将两者的收益合并或把 C34 当作它们通过。详见 `audit-r12-scratch/repair-p2-1-2026-09-29/receipt.md`。

**根因**：投影削的是"信封"，而总量由 `content`（78%）主导。**这是产品设计问题，不是回归。**

**修复范围**：压缩投影效果的产品侧改动（例如窗口/分页/摘要策略），或**在下一轮预注册里重新定义声明口径**。

**验收标准**：
1. **不得调低 C14/C16 的阈值**——这是 TF-0116 的明确决策（看到数据后挪门槛＝事后挑选）。
2. 若改产品：给出新的 `eval/read_path_breakdown.json`/`tf45_envelope_replay.json`，使 C14 ≥0.15 或 C16 ≥0.10。
3. 若不改产品：保持 FAIL，并让 C34（混合不变口径）继续作为可主张的替代声明。

---

### P2-2 · 难度天花板：任务更"长"但没有更"难"（对应节点 TF-0114）

**症状**：预注册目标是让基线成功率落到 **0.40–0.70**；第 14 轮 A 臂成功率是 **0.9048**（上一轮 0.8400，**不降反升**）。
可用余量 = 0.0952 < 预注册 MDE 0.15 → **固定本轮观测基线时，不可能出现+0.15的正向提升**；这不排除更小效应或负向差异，也不是未来基线的确定上界。

**证据**（`eval/live_uncertainty.json` + `eval/acceptance_power.json`）：
- A 成功率 0.9048（105 对），所需 41 对 → 样本量**达标**，检出限 |Δ| ≥ 0.0962。
- 已确认 pristine 观察 ≥1000 token 的任务为 **7/35 = 20%**；A8产物仅覆盖25个生成任务，另10个手写任务未覆盖，不能将20%当作全量实测比例。目标仍为 ≥1/3。

**根因（我的判断，需要你的实验确认）**："large tier" 的机制是把**失败转储变长**，
这增加了**观察量**，但并没有增加**解题难度**——所以基线成功率反而上升。**"更长"≠"更难"**。
建议先做一个廉价实验：把任务按"模型在 A 臂上的失败率"分层，看失败是否集中在某类任务形态上，再据此设计难度。

**修复范围**：任务生成/难度设计（`docs/task-generation-protocol.md`、候选生成提示），
**必须在看不到 live 结果的前提下做**。

**验收标准**：
1. 新任务集的 A 臂基线成功率落在**事先写死**的区间内（例如 0.40–0.70）。
2. large 占比达到新的、**由算式给出**的目标——注意：**补齐现有剩余 5 个槽位只能到 30.0%，
   达不到 1/3；在不重新确认10个未覆盖任务的前提下，保证达到 1/3 需要7个额外且通过A8的任务**（条件算式见 `docs/task-generation-protocol.md` §4.8）。

---

### P2-3 · 观察机制让 rust/ts 的 large 档不可达（对应节点 TF-0123）

**症状**：A8 要求 `tier=large` 候选的 pristine 失败转储 **≥1000 token**；
rust/ts 的 large 候选实测只有 **277–590**，全部被拒（5 个预注册槽位因此未补齐）。

**证据**：
- 被拒候选实测：`rust_primesieve` 277、`rust_chunker` 390、`rust_sliding_sums` 443、`rust_spiral_order` 590、
  `js_csvlite_parsecsv` 376。
- 同批 python large 轻松达标：`python_nested_flatten` 3496、`python_csvlite_parse` 1559。
- **机制探针（已跑，在被拒候选上做，未触碰任务集）**：把 `js_csvlite_parsecsv_98f2c63f` 的
  `check.mjs` 的 `import assert from 'node:assert/strict'` 换成收集式包装（逐断言 try/catch、失败不抛出、末尾汇总）后：

  | 机制 | 失败数 | 输出 | proxy token |
  |---|---|---|---|
  | 现状（裸 node，首断言抛出即终止） | 1 | 1,529 字符 | **382** |
  | 收集全部失败 | **7** | 2,663 字符 | **665** |

  **665 < 1000 → 只改报告机制不够。** 原因是那 7 个断言比的是 3×4 短数组，`deepStrictEqual` 的 diff 本身就短——
  **字节数取决于断言的载荷，不取决于失败个数。**

**修复核查补注（2026-09-29）**：四个Rust候选在默认cargo test下只跑了失败的库测试，integration tests被跳过；`--no-fail-fast` 后原断言输出达到1933–2325 token。TS用node:test注册原18个用例后报告7个失败、3537 token。五个副本的GOLDEN均通过，原候选未改。早期665 token结论只针对手工包装，不是所有报告器的上界；详见生成协议§4.9。

**修复范围**：`tools/task_generate_v2.py` 的 TESTS/large 档提示 + 生成出的 check 运行方式。

**验收标准**：
1. ts 侧**同时**做到：(a) 失败不终止进程、全部打印；(b) 断言比较**长载荷**（`FULL_PLAN.json` 的
   `large_tier_requirement` 本就写了 "assertions print long values"，此前被当成对**条数**的要求）。
2. rust 侧让每条失败用例打印长 payload（而非依赖 `cargo test` 的短摘要）。
3. 用同一批被拒候选复测 A8：报告有几个能越过 1000 token（**不预设是 5 个**）。

---

### P2-4 · 跑间方差没有进入区间（对应节点 TF-0112）

**症状**：已发布区间按**任务**重采样，只建模"抽到了哪些任务"；而端点接受 seed 但不复现。
本轮同配置三 seed 的**成功率差符号翻转**（+0.029 / −0.086 / −0.143）。

**证据**：`eval/run_variance.json`（本轮新增，`tools/run_variance.py`）。
跑间 SE / 已发布半宽：success_delta **0.76×**、observation_token_ratio **0.31×**。

**限制**：3个不同seed只有2个自由度，且seed效应与采集噪声混杂；这是描述性波动，**不是方差下界**，也不能单独证明已发布区间覆盖不足。

**修复范围**：统计工具（`tools/live_uncertainty.py` / `tools/acceptance_power.py`）+ 重跑协议。

**验收标准**：
1. 每配置 **≥3 次完整重跑**（同任务集、同 seed、同预算），逐次保留原始产物。
2. 用方差成分模型或分层 bootstrap 把"跑间"方差并入头条区间，并在产物里给出两个成分的量级。
3. 在任何引用里，只要区间未含跑间方差，必须显式标注。

---

### P2-5 · `len//4` 代理不是上界（C27 已登记，但影响面需重估）

**证据**（`eval/token_proxy_calibration.json`，本轮）：`real/proxy` 均值 **1.2442**、中位数 1.2148；
**52/60 样本违反"代理是上界"**；`ascii_only` 1.2505（n=47）、`non_ascii_other` 1.2218（n=13）；
真实 tokenizer 与端点 tokenizer 在 2/11 形状上不可互换。

**影响**：所有以"观察 token"为口径的结论都偏乐观；而真实 tokenizer 口径下 D/A = **1.3583**（方向相反）。

**修复范围**：产品侧无从修——这是**口径**问题。修复动作是：把真实 tokenizer 口径提升为**主口径**，
或在文档里对每条 token 结论强制标注代理口径。

**验收标准**：`docs/claims-and-evidence.md` 中所有 token 类声明显式标注口径，
且方向冲突时以真实口径为准（§4.2 已有要求，需逐条落实）。

---

## 3. 本会话内已经修掉的缺陷（**无需再修，仅供你了解历史**）

| 文件 | 缺陷 | 状态 |
|---|---|---|
| `tools/run_task_plan.py` | 槽位计数统计**所有**候选的 `plan_index`、从不与当前计划求交 → 15 槽计划里混进 FULL_PLAN 的 5 个槽，`absent` 一度 **−19**，并在只剩 **10/15** 时打印 "all 15 plan slots have an admitted candidate" 且 **exit 0**（假收敛） | 已修：按槽位统计并与计划求交 |
| `tools/task_generate_v2.py` | ①spec 返回路径当模块名（`src/lib.rs`）被写进 `Cargo.toml` 的 `name=`，整槽编译失败后跳过；②`correct` 模块没有独立编译闸门（悬空 doc comment 时连烧 3 次**测试**尝试）；③variants 写到 `<tid>/variants/` 而 `task.json` 落到 `<tid>_<seed>/` → A3 看到 **0 个 variant** 而误拒；④rust variant 的 `src/lib.rs` 未建父目录 → **生成器进程崩溃、整轮白跑** | 全部已修 |
| `tools/freeze_task_set.py` | `promoted` 写的是"本次运行提升了什么"、`kept_existing` 写提升前的 manifest → 无法区分手写/生成；`per_tier` 把 10 个"生成了但没写 tier"的任务并进 `existing` 桶 | 已修：按每个任务自身元数据分类 |
| `tools/claim_gate.py` | C34 原先只看任务集版本 → 升一次版本就能让**旧数字**"通过" | 已修：追加"产物自身指纹新鲜"条件 |
| `tools/claim_gate.py` | `_impossible_flag_consistent` 把 §0.6 的 `gap_type="policy_blocked"` 误判为不一致（policy block 与区间无关） | 已修 |
| `tools/acceptance_power.py` | cross-shell 两项缺评分三元组，会让 Holm 显示 `corrected: true` 而实际未校正 | 已修 |

---

## 4. 我加的自动化（你修完之后，这些会替你验收）

| 门禁 | 管什么 |
|---|---|
| **C34** | 紧凑读投影必须去掉 ≥40% 的**命名信封开销**，且必须**在比 2.0.0 更新的任务集上**测量、产物**自身新鲜**。当前 **PASS 0.5654** |
| **C35** | 配对控制臂必须与 with 臂在 seed 集合/任务集合/行数/`git_rev`/`task_set_version` 上一致，且两臂 `api_error` 为 0。含负对照。当前 **PASS** |
| **C36** | 每个判定必须声明假设族；确认性族做 Holm；`exploratory` 不得 claimable。含负对照。当前 **PASS** |
| **C37** | 头条统计必须在**独立代码路径**上复现（`tools/statistics_crosscheck.py`，34/34 项吻合，含负对照）。闭式量须精确、重采样量在容差内且同侧 |
| `eval/run_variance.json` | 跑间方差的直接测量（`tools/run_variance.py`） |

---

## 5. 我的看法（明确区分事实与判断）

**1. 最大的问题不是任何一个 bug，而是"现在问不出答案"。**
按项目自己预注册的 §0.6，第 14 轮的**每一条**成功率与 token 对比都不可主张。
一个诚实的"不可主张"比一个错误的结论好，但代价是：**这套东西目前无法回答它自己提出的问题**。
在修完 P0-1/P0-3 之前，再跑多少轮 live 都只是重复这个状态。

**2. 我会把 P0-2（生成器 = 被测模型）排在比 backlog 更高的位置。**
它是唯一一个**无法事后修复**的问题：现有 25 个任务已经在这条链里，任何"ACI 省 token"的正面结果
都可以被解释成"任务出自它自己的分布"。而且它**不会触发任何门禁**——只有人读到 provenance 才会发现。
如果只修一个"看不见的问题"，我会修这个。

**3. 三个未关闭项属于测量装置，不是产品——这本身是个信号。**
TF-0112（跑间方差）、TF-0122（partial 合并）、P1-2（重刷链漏产物）都与 VerseShell 的功能无关。
在一个"结论完全由几十行统计代码决定"的项目里，**装置是当前的瓶颈，不是功能**。
这也是为什么我把 C37（统计独立复算）做成本轮第一优先级。

**4. "更长 ≠ 更难"是这轮最反直觉的发现。**
large tier 的机制是把失败转储变长，结果基线成功率**从 0.84 升到 0.90**。
我怀疑"加大观察量"这个机制本身与"加难度"是正交的，但**我没有证据证明这一点**——
建议先做一个廉价的分层实验再动任务集。

**5. 我明确不确定的地方（请你也别当成结论）**：
- D 的截断到底是"提示体积"还是"任务框架诱导长推理"，我只测到**相关**（11,393 vs 9,015 提示 token、
  3,017 vs 1,593 输出 token），**没有做因果分离**。P0-1 里的那个截断实验请务必先做。
- 跑间方差只有 2 个自由度，`0.76×` 这个比值本身很粗糙；它不能独立证明区间偏窄，也不能给出正确的跑间方差或替代区间。

**6. 一条流程上的建议**：本轮我自己在实现新门禁时引入了两处缺陷（C34 只看版本号、`_impossible_flag_consistent`
误判 `policy_blocked`），**都是靠事后复算发现的，不是靠测试**。
这说明"新加一条门禁"本身需要一条负对照才算完成——建议把"每条新门禁必须附负对照"写成硬规矩。

---

## 6. 你**不要**做的事（会破坏证据链）

1. **不要改 `bench/aci/tasks/*.json` 或 `bench/aci/fixtures/**`**。它们在被测量的指纹面内，
   一改第 14 轮全部证据作废（C12 转红），需要重跑约 13 小时 live。
2. **不要调低 C14/C16 的阈值**（0.15 / 0.10）——TF-0116 的明确决策。
3. **不要把候选任务提升进任务集**（`tools/freeze_task_set.py --version`）——那是下一轮预注册的事。
4. **不要重跑 live**。测量由原测试方负责，否则修复与测量会互相污染。
5. **不要改 `bench/aci/runners/live_agent_loop.py` 的观测面而不声明**——任何改变模型可见内容的改动
   都会让已有 live 数字不可比，必须一起重跑。

---

## 7. 你改完之后的最小自检（**不跑 live**）

```bash
# 1) 契约与单元层面：cargo 测试必须在
python tools/claim_gate.py --skip-tests      # 期望仍是 29/31（C14/C16 红），其余必须 PASS
# 2) 你改的东西若涉及这些层，单独跑它们
python tools/statistics_crosscheck.py --out /tmp/xc.json   # 应 34/34
python tools/run_variance.py --out /tmp/rv.json            # 应能产出
# 3) 证明你没有碰被测量的面（必须为空）
git diff --stat bench/aci/tasks bench/aci/fixtures bench/aci/results/latest_live.json
```

**判定**：第 3 条为空 + 第 1 条与基线一致，即视为"未破坏证据链"。
若你**故意**改了观测面（例如 P0-1 的提示体积），第 3 条不为空是预期的——
此时请在 PR 描述里明确写"需要重跑 live"，由原测试方接手。

---

## 8. 相关产物索引

| 产物 | 内容 |
|---|---|
| `eval/evidence.json` | 31 条门禁判定的最新结果（29 PASS） |
| `eval/acceptance_power.json` | 判定表 + `row_policy`（§0.6）+ `multiplicity`（§0.7） |
| `eval/live_uncertainty.json` | 逐臂成功率/Wilson/McNemar/比值 bootstrap |
| `eval/three_arm_report.py` 产物 `eval/three_arm_report.json` | 两预算的撞上限判定 + 逐对比 `claimable` |
| `eval/run_variance.json` | 跑间方差（本轮新增） |
| `eval/statistics_crosscheck.json` | 独立重实现比对（本轮新增） |
| `eval/read_path_breakdown.json` / `eval/tf45_envelope_replay.json` | C16 / C14 的口径与归因 |
| `eval/token_proxy_calibration.json` | `len//4` 代理校准 |
| `bench/aci/results/latest_live.json` | with 臂原始 315 行（`api_error_rows=0`） |
| `bench/aci/results/live_ab_without_read_files.json` | without 臂原始 315 行 |
| `docs/tf0114-round-notes.md` | 第 14 轮完整记录（含跑间方差 §5.5） |
| `docs/acceptance-criteria.md` | §0.5 预算纪律、§0.5.2 预算敏感清单、§0.6 行处置、§0.7 假设族、§4.5 C34 预注册 |
| `docs/task-generation-protocol.md` | §4.6 难度目标、§4.7 实际结果与生成器缺陷 |
| `docs/claims-and-evidence.md` | C1–C37 声明表与失效边界 |
| `.agent-workbench/task-forest/exports/task-forest.html` | 123 节点森林可视化（含 7 个未关闭节点） |

**未关闭节点**（森林里的权威列表）：TF-0112、TF-0114、TF-0115、TF-0120、TF-0121、TF-0122、TF-0123。
