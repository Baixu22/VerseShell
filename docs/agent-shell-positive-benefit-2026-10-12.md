# Agent Shell 正收益验收：P1 结果（2026-10-12）

按 [AGENT-SHELL-POSITIVE-BENEFIT-2026-10-12](dev/handoffs/AGENT-SHELL-POSITIVE-BENEFIT-2026-10-12.md) 执行。
本页是轻量记录；权威产物在仓库外。

## 裁决

`NO_EVIDENCE`

- 30/30 格完整，缺失 0。
- 异常率 0：endpoint_error 0、adapter_error 0、task_timeout 0、turn_cap 0。
- safety_violation 0。
- A′ 与 D 的 prompt token 代理差异 3.9%（≤20% 上限），等量提示成立。

## 配对结果（D vs A′）

| 指标 | A′ | D |
|---|---:|---:|
| 成功率 | 10/10 | 10/10 |
| 首错后恢复率 | 1.0（n=4） | 1.0（n=3） |
| 平均 observation tokens | 580.1 | 1001.8 |
| 平均 tool calls | 2.7 | 2.4 |
| 平均 model calls | 3.7 | 3.3 |

未达到 handoff 5.2 任一门槛：成功率不提升（10/10 对 10/10）、恢复率不提升（均 1.0）、
observation tokens 反而更高、tool/model calls 降幅未达 15%。

唯一失败是 T03/A（model_error）：模型把 echo "EXIT_CODE=$?" 追加到命令后，
shell 进程退出码被改写为 0，真实 exit 7 只出现在 stdout 文本里。

## 与上一轮的差异（诚实记录，不拼接）

- p1-20261012 与 p1-20261012-r2 保留，不删除、不改写。
- 修掉两个 harness 缺陷后另起 p1-20261012-r3：
  1. raw 臂此前把 timeout_seconds+15s 传给 msb exec，导致 sleep 10 不超时；已改为按调用方超时。
  2. T08 oracle 的 kill 判定过严，已按实际 kill 命令形态修正。
- 修复改变了 provider/harness 源码，因此换新轮次标识，不与旧轮拼接。

## 产物

- 轮次目录：D:\VerseShellEval\agent-shell-benefit\p1-20261012-r3\
  - manifest.json（含 ae 二进制、harness 源码、prompt、tool schema 的 SHA256）
  - preregistration.md
  - cells/<task>__<arm>__<seed>.json（30 格完整原始 trace）
  - rows.jsonl、summary.json、report.md
- 执行层：microsandbox 0.7.8；模型：step-5-preview。
- Provider D 调用的是 microVM 内真实 ae 二进制产出的 verseshell.observation/v1。

## 边界

- 单次采集（1 seed），诊断级，不升级为正式/发表级结论。
- 本页不关闭任何功能宣称，不修改 Task Forest 状态。
- 结论只对 microsandbox 0.7.8 + step-5-preview + 本 10 任务矩阵成立。