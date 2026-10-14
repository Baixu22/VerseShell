# 与同系产品的差距定位与吸收方案（2026-10-13）

用户诉求：VerseShell 与同系 agent shell 存在明显差距，需要吸收他们好的设计。
本轮不跑模型，直接读竞品源码 + 对照我们自己的实现，给出可落地的吸收清单。

## 0. 一句话结论

差距**不在执行层**（microsandbox 已证明执行层用别人更强），而在**信息层的两个具体缺口**：

1. 失败时我们只给「哪个码 + 一句 hint」，agentsh 给「**下一步做什么**」的可执行子建议；
2. 我们的观察**全档都比 raw 贵 1.8x-2.8x**，而竞品的观察体积是可控的。

## 1. 竞品源码级设计（实际读到的，不是二手描述）

### 1.1 agentsh 的 `ExecGuidance`（pkg/types/exec.go:94）

```go
type ExecGuidance struct {
    Status           string   // ok | failed | blocked（面向 agent 的分类）
    Blocked          bool
    Retryable        bool
    Reason           string
    PolicyRule       string   // 命中哪条策略
    BlockedOperation string   // 被挡的操作
    BlockedTarget    string   // 被挡的目标
    Substitutions    []Suggestion  // 「改用这个」——有序可执行命令
    Suggestions      []Suggestion  // 「下一步做这个」——无替代方案时的补救
}
```

关键设计思想（`internal/api/app.go:1091-1260` 的 guidanceForResponse）：

- **失败分类面向 agent**：ok / failed / blocked 三态，而不是只给 exit code。
- **substitution 优先于 suggestion**：能给出「改用哪条命令」就直接给命令，
  例如 curl 被挡 -> 建议 `wget -qO- <url>`；http 被挡 -> 建议 https 版本。
- **按错误文本做 recourse 启发式**：
  - `timed out` -> retryable=true + `increase_timeout`（附示例命令）
  - `executable file not found` -> `use_absolute_exe`
  - `permission denied` -> `fix_permissions`；若是 pyenv/asdf shim 再给 `/usr/bin/python3` 替代
- **retryable 是有依据推导的**，不是固定值：approve 决策、有 substitution、超时等都会置 true。
- 每条 suggestion 都带 `Action`（机器可读）+ `Reason`（人/模型可读）。

### 1.2 microsandbox / SWE-ReX 的可吸收点（此前已测）

- microsandbox：真正的 OS 级隔离 + 正确的 timeout/并行语义（执行层，不建议自研）。
- SWE-ReX：干净的 runtime interface 抽象，可把 local/Docker/Modal 换后端。

## 2. 我们自己的实际实现（对照）

`src/operation.rs:71` OperationError：

```rust
pub struct OperationError {
    pub code: String,        // E_PROCESS_EXIT / E_TIMEOUT / ...
    pub message: String,
    pub recoverable: bool,   // 语义上等于 agentsh 的 retryable
    pub hint: Option<String>,// 通常只是第一条 diagnostic 的 message
}
```

我们**已有**而 agentsh 没有的：`diagnostics[]`（结构化 expected/found/path/line）、
`suggested_next[]`（可执行 op+args）、`data.exit_code/timed_out/stdout/stderr`。

### 2.1 实测差距（l4-slim-r3 的 25 次 D 失败调用）

| 指标 | 值 |
|---|---|
| D 失败调用总数 | 25 |
| 按码分布 | E_PROCESS_EXIT 12 / E_TIMEOUT 4 / 无码 9 |
| **带 suggested_next 的失败** | **13 / 25（52%）** |

即：**近一半的失败没有给任何下一步动作**，只有 code + message + 一句 hint。
对比 agentsh 的 guidanceForResponse：每个失败分支都至少给 2 条 suggestion。

## 3. 差距清单（可落地）

| # | 差距 | 竞品做法 | 我们的现状 | 优先级 |
|---|---|---|---|---|
| G1 | 失败无「下一步」 | 每个失败分支都产 suggestion/substitution | 52% 的失败带 suggested_next，48% 不带 | 高 |
| G2 | 无「替代命令」概念 | Substitutions 给可直接跑的命令 | 只有 suggested_next（op+args），非命令 | 高 |
| G3 | retryable 无依据 | 由决策/替代/超时推导 | recoverable 基本恒为 true | 中 |
| G4 | 无失败分类 | status: ok/failed/blocked | 只有 ok: bool | 中 |
| G5 | 观察体积偏大 | — | 全档 1.8x-2.8x raw（已做瘦身，仍有差距） | 高 |

## 4. 吸收方案（按优先级，均为最小改动）

### A1 失败即给可执行下一步（对应 G1/G2）

在 `execute_run` 的失败分支补一个「按错误码产出 recourse」的函数，覆盖已知码：

| 错误码 | 建议动作 |
|---|---|
| E_PROCESS_EXIT | 若 stderr 匹配 `not found` -> 建议装包/换绝对路径；匹配 `permission denied` -> 修权限；否则给 result.query 看完整日志 |
| E_TIMEOUT | 建议提高 timeout_ms 或改跑更窄的命令（附具体参数） |
| E_STALE_HASH | 已有 data.actual_hash + 重试建议（保持） |
| E_AMBIGUOUS | 已有 matches[] + --index 建议（保持） |
| E_OUTSIDE_WORKSPACE | 建议改用 workspace 内路径 |

关键：**每条都带可执行动作**，而不是只描述错误。

### A2 补 `substitutions`（对应 G2）

在 error 结构里加 `substitutions[]`，元素为 `{action, command, reason}`。
首批只做有把握的启发式（学 agentsh 的保守做法）：

- 命令不存在 -> 给出常见替代（如 `python` -> `python3`）
- http 被挡 -> 建议 https
- 工具缺失（如 xxd）-> 建议等价工具（如 od）

### A3 retryable 推导（对应 G3）

把 `recoverable` 从常量改为推导：有 substitution / 是超时 / 是审批类 -> true；策略拒绝 -> false。

### A4 失败分类 status（对应 G4）

在 observation 顶层加 `status: ok|failed|blocked`（blocked 用于策略/能力拒绝）。
这是向后兼容的加法，不改既有字段。

### A5 继续压观察体积（对应 G5）

已做：不回显 argv/cwd、微型省略不发句柄、空输出一行摘要。
待做：流元数据 compact 投影（此前模拟显示单独做最多到 ratio 1.25，
需与 A1-A4 的"少调用"配合才可能整体达标）。

## 5. 诚实边界

- 本轮只做源码对照与方案，**未改任何产品代码**，也未跑模型。
- agentsh 的 guidance 是在 policy/network 语境下的设计，我们吸收的是**结构**（action+reason+可执行），
  不是照搬它的策略语义。
- G5 的观察体积差距，靠裁剪信封无法单独解决（已用离线模拟验证）。
- 未改 Task Forest；未提交、未合并、未推送。


## 7. 已落地：A1 + A3（本轮实际改的产品代码）

吸收了 agentsh guidanceForResponse 的核心思想——失败必须带可执行的下一步，以及 retryable 要有依据。
改动集中在 src/operation.rs：

新增 recourse_for_failure(exit_code, stderr_text, stdout_bytes, timeout_ms, timed_out)，失败时按证据产出可执行动作：

| 失败形态 | 产出的下一步 |
|---|---|
| 超时 | exec.run，timeout_ms 翻倍，note 说明「重试或缩小命令」 |
| 命令/工具缺失 | exec.run，command -v 探测，note 说明「确认工具存在或用绝对路径」 |
| 权限拒绝 | exec.run，ls -l，note 说明「检查权限/可执行位」 |
| 其他失败 | 不编造，返回 None，由真实的 result.query 承载 stderr |

同时把 error.recoverable 从常量改为有依据的推导（超时/非零退出 = true），
并在没有 diagnostic 时给出可读的 hint（指向 suggested_next）。

### 实测效果（用 l4-slim-r3 的 25 次真实 D 失败回放）

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 失败带可执行下一步 | 13/25（52%） | 16/25（64%） |

### 关键设计选择：宁缺毋滥

早期版本对所有失败都塞一条通用 echo inspect-failure-details，实测发现这是空洞的占位动作，
会稀释真正的建议。改为只在有把握时给定制动作，否则返回 None（此时 result.query 已能取到完整 stderr）。
这比「每条都凑一条」更诚实，也避免制造假动作。

### 一个真实的环境坑

Windows 的「命令不存在」是 OEM 码页输出，英文子串匹配（not found）会失败。
改为结构化判断：stdout 字节数为 0 且 stderr 非空且退出非零。这比文本匹配跨平台稳健。

## 8. 尚未落地（下一步）

- A2 substitutions[]（替代命令表）：需要维护一份工具替代映射。
- A4 顶层 status: ok|failed|blocked：纯加法，向后兼容。
- A5 观察体积：需与调用数下降配合，单靠裁剪不够（已验证）。


## 9. 已落地：A2 + A4（本轮第二批产品代码）

继续吸收 agentsh ExecGuidance 的形状——Status / Substitutions / Suggestions 同级。

### A4 顶层 status

Observation 新增 status 字段（agentsh 的 agent-friendly 分类）：

| 取值 | 条件 |
|---|---|
| ok | 命令成功 |
| failed | 命令失败（非零退出/超时） |
| blocked | 策略/能力拒绝（错误码含 DENY / CAPABILITY / OUTSIDE） |

实测三态：成功 -> ok；xxd 缺失 -> failed；无 shell.exec 能力 -> blocked。

### A2 substitutions[]

新增 Suggestion { action, command, reason }（与 agentsh 的 Suggestion 同形），
并在失败时按 stderr 产出**可直接运行的替代命令**：

| 触发 | 替代命令 |
|---|---|
| xxd 缺失 | od -c <file> |
| curl 缺失 | wget -qO- <url> |
| python 缺失 | python3 <script> |
| 权限拒绝 | chmod +x <file> && ./<file> |

实测（microVM，Linux）：xxd 缺失 -> status=failed + 1 条 substitution（od -c）。

### 设计对齐

| 字段 | agentsh ExecGuidance | VerseShell（现在） |
|---|---|---|
| status | ok/failed/blocked | 已对齐 |
| retryable | 有依据推导 | recoverable（上轮已改） |
| substitutions | {action,command,reason} | 已对齐 |
| suggestions | {action,command,reason} | suggested_next（op+args） |
| diagnostics | events | diagnostics[]（我们更强） |

即：**在失败信封的结构上，我们已补齐 agentsh 的两个主要缺口**，
同时保留了 agentsh 没有的 diagnostics / suggested_next / artifact。

### 二进制

- Linux ae 重新构建：832426fe（含 A1+A2+A3+A4）
- 7/7 契约测试通过；observation_ledger 1/1；process_command 6/6


## 10. 已落地：A5 —— blocked 路径的完整信息（agentsh 最后一块拼图）

agentsh 的 ExecGuidance 还有三个字段说明「被挡了什么」：blocked_operation / blocked_target / policy_rule。
我们此前把 blocked 只做成一个 status 布尔，agent 不知道能否换条路重试。

### 新增字段

Observation 新增 blocked_operation、blocked_target（policy_rule 我们暂不需要：
VerseShell 的拒绝来自 capability/workspace jail，没有可命名的策略规则集）。

### 新增 Observation::blocked 构造器

把「失败」与「被挡」区分开：被挡时必须给出 (a) 被挡的操作与目标，(b) 换什么做法。

| 阻断类型 | blocked_operation | 换路建议 |
|---|---|---|
| 能力缺失 E_CAPABILITY_DENY | sh（缺失的能力）+ 首个 argv | substitution: grant_capability；suggested_next: runtime.handshake 查看已授予能力 |
| 审批 E_NEEDS_APPROVAL | <builtin>.needs_approval | suggested_next: 带上 approval_token 重试 |
| 越狱 E_OUTSIDE_WORKSPACE | <builtin>.outside_workspace | substitution: 把输入移到 workspace 根下 |

### microVM 实测（Linux ae 12b427a9）

| 场景 | status | blocked_operation | substitutions |
|---|---|---|---|
| echo ok | ok | - | 0 |
| xxd 缺失 | failed | - | 1（od -c <file>） |
| cat 不存在的文件 | failed | sh | 0 |
| 无 shell.exec 能力 | blocked | sh | 0（改为 grant_capability 提示） |

### 与 agentsh 的最终对齐表

| 字段 | agentsh | VerseShell |
|---|---|---|
| status ok/failed/blocked | 有 | 已对齐 |
| blocked_operation / blocked_target | 有 | 已对齐 |
| policy_rule | 有 | 无（我们没有可命名的策略规则集，能力模型不同） |
| retryable | 有依据推导 | recoverable（有依据） |
| substitutions {action,command,reason} | 有 | 已对齐 |
| suggestions | 有 | suggested_next（op+args） |
| diagnostics 结构化定位 | events（弱） | diagnostics[]（强：path/line/expected/found） |
| artifact / result handle | 无 | 有（可回查完整输出） |

结论：**失败信封的两个主要缺口已补齐**；我们在 diagnostics 与 artifact 上仍强于 agentsh。
唯一保留差异是 policy_rule——那属于安全模型路线差异，不是信息层缺陷。

## 6. 建议的落地顺序

1. **A1**（失败即给下一步）——直接命中我们实测的 48% 缺口，改动最小，收益最直接。
2. **A3 + A4**（retryable 推导 + status 分类）——同一处改动，顺带完成。
3. **A2**（substitutions）——需要一份替代命令表，单独一步。
4. **A5**（体积）——需要配合调用数下降，最后做。
