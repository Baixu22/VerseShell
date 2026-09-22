# VerseShell 节点规划独立审计提示词（完整版）

> 用途：将本文件**原样**交给独立审计方（另一 Agent / 人类评审）。  
> 审计对象：`task-forest` 中已落地的开发-验收节点规划（提案 `TFP-aci-deepen-2026-09` + `TFP-forest-plan-v2`）。  
> 你**不是**实现者，只做规划审计：对照「预期 ↔ 节点 ↔ 验收」一比一核对，指出缺漏、越界、不可验收项。  
> 默认工作区：`C:\Users\27933\Desktop\verseshell\verseshell`（或当前 repo 根）。

---

## 0. 审计任务一句话

请以独立第三方身份，**只审计节点规划本身**（完整性、可验收性、依赖正确性、边界是否守住），不要改代码、不要代为开发。输出：通过 / 有条件通过 / 不通过 + 逐节点意见 + 越界风险清单。

---

## 1. 项目真实基本情况（防误解）

### 1.1 这是什么

| 项 | 内容 |
|----|------|
| 名称 | VerseShell |
| 形态 | **Agent-Computer Interface Runtime**（本地 ACI 运行时），不是给人用的 shell |
| 主用户 | Coding Agent（Claude Code / Codex / 其它 MCP/JSON-RPC 客户端） |
| 主合同 | 版本化 **typed op** + 观察信封 `verseshell.observation/v1` |
| 次级面 | VerseShell 类型化 DSL / 旧 `cmd` 路径（兼容，非主推） |
| 实现 | Rust（`ae` / `ae-mcp`） |
| 项目性质 | **单人个人项目的工程化探索**，不是上线商业产品 |
| License | AGPL-3.0-or-later |

### 1.2 产品主张（审计时以此为准，勿另立）

1. 把 coding agent 最贵的失败链（读噪声、改错文件、连锁失败、不可撤）收成**可执行、可恢复、可测量**的观察合同。  
2. 对 LLM 直接有用的才做深：结构化诊断、可执行下一步、一步恢复；**不为「创新」而扩面**。  
3. 每条对外数字声明必须绑定可复现证据；未过线不得写入 README 主张。

### 1.3 已有能力基线（规划应在基线上深化，不是重写）

- Typed ops：`exec` / `file` / `tx` / `repo` / `test` / `ops.*`（含 ledger 查询）
- Observation Budget + 语义 reducer：`cargo` / `pytest` / `git` / `npm_install`
- Artifact + `result.query`（raw 可取回）
- hash 编辑（`expected_hash`）+ trash/`tx.restore`
- 会话 observation ledger
- 自建 ACI-Bench（mock）：A(raw_shell) vs D(verseshell_aci)，指标 success / tool_calls / observation_tokens
- 已有测试：closed-loop、reducer 对抗、token 压缩、operation 协议等

### 1.4 明确边界（出现下列方向即视为越界，审计应扣分并点名）

| 不做 / 不在本规划 | 原因 |
|------------------|------|
| 继续堆人类 shell 模块（db/clip/cron/pkg/ansible…） | 服务人类，不服务 coding agent |
| 完整 LSP `repo.symbols` / `repo.references` | 已 defer，体量大 |
| VSCode 面板 / Web Dashboard / 插件市场 | 面向人 |
| 引擎 COW / 真流式 / PGO | 有升级触发器，当前非瓶颈 |
| bash 兼容体验 / 交互 REPL 打磨 | 次级兼容面 |
| SyntaxKB / AgenticBinary 实验面 | 非主合同 |
| 为上线做多租户/计费/SLA/合规认证 | 个人探索项目 |
| 大规模真人标注 / 外包标注流水线 | 单人开发会累死；只保证**数据有来源** |
| 无证据的营销式声明（如「省 80%」无主语） | 违反声明纪律 |

### 1.5 约束（规划必须尊重）

- **少人标**：验收优先确定性指标 + 复用仓库内 fixture/GOLDEN/已有报告；人工只做小样本抽检而非全量标注。  
- **数据有来源**：每条评测样本 / 声明证据必须能回溯到仓库文件或明确外部来源 URL/命令。  
- **规划即执行骨架**：开发只能按 `task-forest` 的 `todo` 中 ready 节点推进；`done` 必须回写 evidence。  
- **工作区 WIP**：方案 A——已有未提交改动保留作 P1 收尾，不强制 `git checkout` 回退（已记入决策节点）。

---

## 2. 已落地的节点规划（请对照仓库内数据一比一审核）

数据位置：

```text
.agent-workbench/task-forest/graph/nodes.json
.agent-workbench/task-forest/graph/edges.json
.agent-workbench/task-forest/proposals/TFP-*.json
.agent-workbench/task-forest/exports/task-forest.html
.mimocode/skills/task-forest/          # skill 本体（规则源）
```

### 2.1 目标树（goal → phase → module/task）

```text
TF-0001 深化 VerseShell 观察合同并建立可复现验收     [global_task, in_progress]
├─ TF-0013 规划门：提案确认并写入任务森林            [milestone, in_progress]  (步骤0)
├─ TF-0002 补齐语义诊断字段并生成修复剧本           [milestone, in_progress]
│   ├─ TF-0003 步骤2：pytest 诊断补 expected/found  [task, in_progress]
│   ├─ TF-0004 步骤3：失败观察生成修复剧本          [task, in_progress]
│   └─ TF-0005 步骤4：E_STALE_HASH/E_AMBIGUOUS 一步恢复 [task, in_progress]
├─ TF-0009 数据集与来源元数据（少人标）             [milestone, ready]
│   └─ TF-0010 步骤5：生成带 source 的评测清单 manifest [task, ready]
├─ TF-0006 声明-证据矩阵与自动验收门禁              [milestone, ready]
│   ├─ TF-0007 步骤6：写声明-证据文档               [task, ready]
│   └─ TF-0008 步骤7：实现 claim_gate 自动指标脚本  [task, ready]
├─ TF-0011 Jev 观察质检接入                         [milestone, ready]
│   └─ TF-0012 步骤8：实现 jev_obs_judge 脚本       [task, ready]
├─ TF-0014 执行纪律：按节点推进并回写 evidence      [requirement, ready]
└─ TF-0015 决策：P1 WIP 保留收尾不回退              [decision, done]
```

### 2.2 依赖边（开发-验收全流程）

```text
TF-0013 规划门
  → TF-0003 步骤2 (pytest 诊断)
  → TF-0004 步骤3 (剧本)          [depends_on TF-0003]
  ∥ TF-0005 步骤4 (一步恢复)       [depends_on TF-0013]

TF-0002 P1 完成语义稳定
  → TF-0010 步骤5 (manifest)
  → TF-0007 步骤6 (claims 文档)    [depends_on TF-0010]
  → TF-0008 步骤7 (claim_gate)     [depends_on TF-0010 及 P1]
  → TF-0012 步骤8 (jev_obs_judge)  [depends_on TF-0008]
```

**预期总序（一比一执行序）：**  
**0 规划门 → 2 pytest 诊断 → 3 剧本 → 4 一步恢复（∥可并行收尾）→ 5 manifest → 6 声明文档 → 7 claim_gate → 8 Jev**  
（步骤1=规划本身；全序与 `display_order` 10/20/30/40/50 一致。）

---

## 3. 开发-验收全流程与「预期」清单（逐条一比一审核）

> 审计方法：对每个步骤，核对 **输入 → 产出物 → 验收标准 → 证据来源** 四列是否在节点里写全且可执行。缺一列 = 有条件通过；缺两列及以上或不可测 = 不通过。

### 步骤0 · 规划门（TF-0013）

| 维度 | 预期 |
|------|------|
| 输入 | 用户确认的规划序；task-forest skill 规则 |
| 产出 | proposal 已 `proposal-save` + `proposal-apply`；`validate` 通过；`export` HTML |
| 验收标准 | 根目录可见 `.agent-workbench/task-forest/exports/task-forest.html`；todo 含上述节点与 depends_on |
| 证据来源 | proposal JSON、events.jsonl、export 时间戳 |
| 通过定义 | 规划可被第三方读懂且无需口头补充 |

### 步骤2 · pytest 诊断字段（TF-0003）

| 维度 | 预期 |
|------|------|
| 输入 | `src/reducers/pytest.rs`；对抗 fixture `tests/fixtures/reducers/adversarial/pytest_*` 及 `tests/semantic_reducer*_tests.rs` |
| 产出 | Diagnostic 含 `expected` / `found`（及必要时 `code`）；assert/E 行可解析 |
| 验收标准 | 失败样本能抽出 expected/found；`cargo test` 相关用例通过；不破坏成功静默 |
| 证据来源 | fixture 路径 + 测试名；禁止无来源「示例日志」 |
| 通过定义 | 字段完备率在对抗集上可机检（给后续 claim_gate 用） |

### 步骤3 · 修复剧本 suggested_next（TF-0004）

| 维度 | 预期 |
|------|------|
| 输入 | `src/reducers/mod.rs`（及各 profile 诊断） |
| 产出 | 失败观察带短剧本：典型为 `file.view` → `file.replace_exact`（带 old/new 草图）→ `test.run_target`/`exec.run` |
| 验收标准 | 剧本 op 合法、参数键名与 1.0 ACI 一致、可去重；不塞无关步骤 |
| 证据来源 | 单测；closed-loop 或 protocol 测试中的 suggested_next 断言 |
| 通过定义 | agent 可「照抄参数改一改就能发」，无需查第二份文档 |

### 步骤4 · 一步恢复（TF-0005）

| 维度 | 预期 |
|------|------|
| 输入 | `src/ops/common.rs` HashMismatch；`src/ops/file.rs` replace_exact/apply_patch/edit_range |
| 产出 | `E_STALE_HASH` → `data.actual_hash`（+expected）；`E_AMBIGUOUS` → `data.matches[]`（line/offset/snippet）；附带重试 suggested_next |
| 验收标准 | 失败后**一次**带上 `actual_hash`/加宽 old 即可重试成功；不要求再 `file.view` |
| 证据来源 | `tests/aci_1_0_*` / operation_protocol 相关用例 |
| 通过定义 | 结构化字段稳定出现，而非只写在 message 字符串里 |

### 步骤5 · 数据集 manifest（TF-0010）

| 维度 | 预期 |
|------|------|
| 输入 | `tests/fixtures/**`、`bench/aci/tasks`、`bench/aci/fixtures`、`bench/aci/results/*`、`tests/fixtures/reducers/adversarial` |
| 产出 | `eval/manifest.json`（或同等路径），条目含 `id` / `source` / `expect`（期望字段或谓词）/ `kind` |
| 验收标准 | 每条 `source` 是仓库内真实路径或明确外部 URL；脚本可校验路径存在；**不要求真人标注列** |
| 证据来源 | manifest 自身 + 校验脚本输出 |
| 通过定义 | 第三方能从 source 点开原始样本；无「内部口述样本」 |

### 步骤6 · 声明-证据文档（TF-0007）

| 维度 | 预期 |
|------|------|
| 输入 | 步骤5 manifest；既有 mock bench 结果；本提示第 1.2 节主张 |
| 产出 | `docs/claims-and-evidence.md`：每条声明 Cx = {主张原文, 门槛数字, 复现命令, source, 失效边界, 状态=已证实/实验室/未证实} |
| 验收标准 | 至少覆盖：C1 token 比、C2 tool_calls 比、C3 诊断字段完备、C4 一步恢复、C5 学习成本可吸收、C6 可撤恢复、C7 不回归门禁 |
| 证据来源 | 命令可复制；数字旁写清 mock/live、样本量、日期 |
| 通过定义 | 未过线声明**不得**以肯定口吻进 README；文档内状态字段必须存在 |

### 步骤7 · claim_gate（TF-0008）

| 维度 | 预期 |
|------|------|
| 输入 | manifest + 仓库测试/bench 产物 |
| 产出 | `tools/claim_gate.py` + `eval/evidence.json`（机器可读） |
| 验收标准 | 可计算：字段完备率、`E_STALE_HASH`/`E_AMBIGUOUS` 结构化字段存在率、mock bench 比值；不过线 exit code ≠ 0 |
| 证据来源 | evidence.json 内嵌 source 引用 |
| 通过定义 | CI/本地一条命令可跑；结果与文档门槛一一对应 |

### 步骤8 · Jev 质检（TF-0012）

| 维度 | 预期 |
|------|------|
| 输入 | manifest；观察样本；（可选）TypeSafe/Jev API |
| 产出 | `tools/jev_obs_judge.py` + 质检报告（含 provenance） |
| 验收标准 | **无 API key 时**可降级为确定性启发式并仍出报告；有 key 时用 Choice/Score/Noul 窄问题；**禁止**用 Jev 生成修复代码或替代正则 reducer |
| 证据来源 | 报告逐条 source；若用 Jev 注明模型/模式/是否启发式 |
| 通过定义 | 报告能回答「诊断是否足够修 / 剧本是否可执行」且可复现 |

### 全流程集成预期（端到端）

1. 功能（步骤2–4）与验收（步骤5–8）**同一目标树**交付，不是两套叙事。  
2. 任何对外数字 = `docs/claims-and-evidence.md` 一行 + `eval/evidence.json` 一条。  
3. HTML 导出仅含 done/in_progress 及必要祖先，**不得**泄内部证据队列/绝对路径（符合 skill HTML 契约）。  
4. 真人工作量上限：抽检 ≤ 少量样本对齐 Jev/启发式，不建标注平台。

---

## 4. 请审计方输出的固定格式

### 4.1 总判

- [ ] **通过**　[ ] **有条件通过**　[ ] **不通过**  
- 一句话理由：

### 4.2 逐节点一比一表（请复制填写）

| 节点 | 输入完整? | 产出明确? | 验收可测? | 证据有来源? | 依赖正确? | 边界未越? | 判定 | 意见 |
|------|-----------|-----------|-----------|-------------|-----------|-----------|------|------|
| TF-0013 步骤0 规划门 | | | | | | | | |
| TF-0003 步骤2 pytest | | | | | | | | |
| TF-0004 步骤3 剧本 | | | | | | | | |
| TF-0005 步骤4 一步恢复 | | | | | | | | |
| TF-0010 步骤5 manifest | | | | | | | | |
| TF-0007 步骤6 claims | | | | | | | | |
| TF-0008 步骤7 claim_gate | | | | | | | | |
| TF-0012 步骤8 Jev | | | | | | | | |
| TF-0014 执行纪律 | | | | | | | | |
| TF-0015 WIP 决策 | | | | | | | | |

### 4.3 必答清单（防跑偏）

1. 是否存在**无法机检/无法复现**的验收项？列出节点 ID。  
2. 是否存在**越界**方向（对照 §1.4）被写进节点？列出并建议删除或降级。  
3. 依赖序是否与「先功能后数据集再门禁再 Jev」一致？若有环或跳步，指出。  
4. 声明（C1–C7）是否都能落到具体数字门槛与命令？缺哪条？  
5. 少人标约束是否被破坏（是否隐含大量人工标注）？  
6. 每条样本/证据是否都有 `source`？抽 3 条验证路径真实存在。  
7. 是否有节点标题/摘要**外行读不懂**或依赖内部代号（如只写 P04）？  
8. WIP 决策（方案 A）是否与执行纪律冲突？  
9. Jev 范围是否被限制在「窄判定/质检」而非生成式补全？  
10. 给出**最小修改集**（若不通过）：只改规划字段，不扩产品范围。

### 4.4 建议修改（若有）

按优先级列出 ≤ 5 条，格式：`节点ID: 问题 → 建议改法（仍须落在 §1.4 边界内）`。

---

## 5. 审计时的证据抽查命令（只读）

```powershell
# 节点与边
python .mimocode/skills/task-forest/scripts/task_forest.py list --json
python .mimocode/skills/task-forest/scripts/task_forest.py todo --json
python .mimocode/skills/task-forest/scripts/task_forest.py validate

# 提案与导出
Get-ChildItem .agent-workbench/task-forest/proposals
Get-ChildItem .agent-workbench/task-forest/exports

# 样本来源抽查（路径应真实存在）
Get-ChildItem tests/fixtures/reducers/adversarial -ErrorAction SilentlyContinue
Get-ChildItem bench/aci/tasks
Get-ChildItem bench/aci/fixtures
Get-ChildItem bench/aci/results
```

只读即可；**不要** `proposal-apply`、不要改 `nodes.json`、不要跑破坏性命令。

---

## 6. 审计范围外（明确不要求你做）

- 不要求给出新功能创意或产品扩张  
- 不要求补全 LSP/UI/多语言 reducer 全家桶  
- 不要求搭建在线多人标注  
- 不要求代替实现者写生产代码（最多给「规划字段怎么改」）

---

## 7. 签署栏

- 审计方：  
- 日期：  
- 版本（对照 proposal id / git commit）：  
- 总判：通过 / 有条件通过 / 不通过  

---

*本提示与 task-forest skill 规则、VerseShell README/docs/1.0-aci.md 一致处以外，以本提示 §1 边界为审计准绳。*
