# 观察体积归因与 P1-P5 吸收方案（2026-10-14）

## 一句话

A1-A5 全部在优化失败路径，但实测 **失败观察只占全部 observation token 的 8.7%**；
**91.3% 花在成功观察上**。这是"结构补齐了、收益没出现"的根因。

## 成功观察（r5，272 个 ok=true）字符构成

| 成分 | chars | 占比 |
|---|---:|---:|
| 实际正文（text/summary） | 205,749 | 57.8% |
| **stream 元数据开销** | **91,120** | **25.6%** |
| meta（effects/capabilities/profile） | 33,026 | 9.3% |
| envelope（schema/id/op/status） | 26,112 | 7.3% |
| 合计 | 356,007 | 100% |

264/272 个成功观察里 stderr 状态是 `empty`，却仍输出完整九字段对象
（status/raw_bytes/returned_bytes/omitted_bytes/raw_complete/encoding/decoding_lossy/summary）。
即近 100% 的成功观察白付了 25.6% 的元数据开销。

## 证据

- 来源：`D:\VerseShellEval\agent-shell-benefit\l4-budget48-r5-20261013\cells`
- 失败观察 26 个占 observation token 8.7%；成功观察 272 个占 91.3%
- E_TIMEOUT 失败的 suggested_next 建议"加倍 timeout"，模型采纳 **0/9**
- 20 条 suggested_next 被照抄执行 **0 条**

## A prime 的对照做法

```json
{"schema":"...raw-observation/v1","exit_code":0,"stdout":"...","stderr":"",
 "stdout_bytes":134,"stderr_bytes":0,"stdout_truncated":false,
 "stderr_truncated":false,"elapsed_ms":69,"timed_out":false,"error":null}
```

即 stdout/stderr 是**平铺字符串**，元数据是**扁平标量**，空流是**空字符串**。

## 吸收清单（按证据强度 × 收益/成本）

| 优先级 | 动作 | 预期 | 证据强度 | 落点 |
|---|---|---|---|---|
| **P1** | 成功路径观察瘦身：flat 投影 | obs −20~25% | 强（25.6%+7.3%+9.3%） | src/operation.rs |
| **P2** | 空流折叠，去掉空对象 | 消除常态浪费 | 强（264/272 empty） | src/operation.rs |
| **P3** | 预算可见（剩余 calls/时间） | 治 cap（5/60 异常） | 中 | src/operation.rs |
| **P4** | workspace 越界软提示 | 救 T405 类 | 中（单案例） | src/operation.rs |
| **P5** | 控制字符折叠计数 | 小幅降本 | 中（字段已存在未用） | src/operation.rs |

## 明确不做（避免过度设计）

- 不补 `policy_rule`（安全模型不同）
- 不扩 substitutions 映射表（当前命中 1/22，先验证价值）
- 不引入 kernel policy / network policy / credential proxy（属 microsandbox/agentsh 职责）
- 不做多后端 runtime 抽象（无当前需求）

## 保持不变的契约

- `verseshell.observation/v1` schema 名不变
- `data.stdout` / `data.stderr` 仍保留 `text` / `summary` 键（`obs_stdout` 依赖）
- `ok` / `status` / `error` / `suggested_next` / `diagnostics` 不变
- 仅在 `ok=true` 且流未截断、未丢失字节时走瘦身路径