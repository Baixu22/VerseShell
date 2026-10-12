# C16 新候选采集计划（2026-09-30）

用户已授权完成前置准备后使用指定模型开始采集。本轮目标是新候选的工程验收，
不是因果研究或模型能力优势的确认性试验。C14 保留原 FAIL；C16 门槛仍为 0.10。

## 固定配置

- 模型 `glm-5.3-flash`，用户提供的本机 `/v1/responses` 接口；不切换模型或协议。
- 原 task set 3.0.0 的 35 任务，原任务/fixture 不修改。
- A、A′、D 三条件；with/without read_files 两配置；42/43/44 三分片。
- 总计 **630 个任务运行**；单格可能请求模型多次。
- 每格最多 8 turns，每次 16384 max_output_tokens，temperature=0。
- Responses 不发送 seed；三分片不是三次完整独立重复，不宣传 seed 可复现性。
- 任务内按 task index + shard seed 轮转条件顺序。两配置按固定 with 后 without
  顺序采集，保留时间信息；配置与时间可能混杂，本轮不据此主张消融因果效应。
- HTTP 429 最多 3 次总尝试；记录每次尝试。其他端点错误和真实解题失败不自动
  重跑。端点失败作为未知结果保留，允许输出显式 partial 诊断，不能据此宣告验收通过。

## 开跑前与运行中约束

离线回归、投影契约、Responses 工具往返探针完成后，执行同一接口的 3 个 smoke
任务 × 3 条件（9 格），与正式数据分开。它是协议/运行器检查，失败不得静默重试。
端点或运行器失败阻止正式启动；实际解题失败保留并判断是否为已确认的工程缺陷。

采集配置保存在 `bench/aci/results/c16-glm53-responses-20260930/collection.json`，
包含代码指纹、二进制 SHA-256、调度程序摘要和完整任务配置，不含 API key。
checkpoint 绑定同一身份；缺失、损坏、代码/配置变化均拒绝续跑。
合并验证配置一致、准确格集合、无重复；保留采集指纹及各源文件 SHA-256，不用当前
树给旧数据重盖章。进程运行中源代码/二进制变化则停止并保留 checkpoint。

产物在独立目录，默认不发布或覆盖正式基线。完成后须核对网格、失败分类、两份
合并产物及 C16 重放，再重建受影响证据链。630 格完成本身不等于 C16/C12 PASS。
目前旧证据链仍过期，不在开始采集前将其强制标绿。

## 本次前置修复

1. `live_identity.py` 统一格身份、配置和完整性校验。
2. runner 拒绝不匹配/损坏 checkpoint，记录采集身份，支持无调用 dry-run。
3. merger 拒绝混合配置/重复/缺格，保留原指纹，不把三个 seed 文件写成三次 repeat。
4. `live_round.py` 冻结配置、检查旧输出后复用、非零立即停止、默认独立输出。
5. Responses 适配保留原始 output（含 reasoning 项），按 call_id 回传工具结果；
   input/output usage 映射到原有诊断字段，max_output_tokens 截断单独记录。

协议依据：[OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling)。
该文档说明协议结构；本机代理兼容性由实际探针另行验证。

## 接口兼容修订（正式首格前）

首批 smoke 的前三格均为 HTTP 400，已保留原 checkpoint 并停止该批次，未计为模型
能力失败。原 runner 首轮只发送 system 消息；代理接受 system+user 及 user+真实
工具列表的独立探针。现为所有条件统一增加 `Begin the task.` 用户消息，保留原系统
提示全文。新候选另起 smoke-v2，原失败批次不覆盖、不混入正式采集。此变化纳入新
候选指纹；旧 Chat Completions / 旧模型结果不作为本轮的同配置对照。
