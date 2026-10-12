# 前置准备完成与开跑回执

2026-09-30 **18:41（Asia/Shanghai）**，已启动指定模型 `glm-5.3-flash` 的
630 格完整工程采集，接口为用户提供的本机 `/v1/responses`。

## 已完成

- 续跑绑定代码、二进制、任务集、模型、协议、权限、预算、集合与条件；旧身份、
  损坏 checkpoint、重复格、越界格被拒绝，原文件保留。
- 合并校验完整格集合和同一采集配置，拒绝混合来源；保留采集指纹、源文件哈希和
  原 repeat 数，不再使用合并时的当前树给旧数据重盖章。
- Responses 工具往返、call_id、原始 output/reasoning 项、usage、截断状态适配。
  新增统一用户启动消息，解决代理拒绝首轮纯 system 消息的问题。
- 采集 dry-run 已冻结配置；输出留在独立目录。所有端点失败和任务失败保留，
  不按结果补跑；HTTP 429 的有限请求重试保留每次尝试。
- 结束后自动校验 630 格并运行新集合上的 C14/C16 离线重放，生成集合回执。

## 真实验证

| 项目 | 结果 |
|---|---|
| 最终 Python 全回归 | **140 通过**，exit 0，23.160s |
| 实际服务投影契约 | **11/11 通过**，exit 0 |
| Responses 工具往返探针 | **2 次请求通过**，usage 和 finish 状态正常 |
| 最终 smoke-v2 | **9/9 成功**，三任务 × A/A′/D；无 API 错误 |
| 保护面 | **322 文件未变**；任务、fixtures、Task Forest、两份旧正式 JSON、claim_gate.py 保留 |
| 候选清单 | 227 个源文件 SHA-256；另存执行代码副本 |

首批 smoke 有三个 HTTP 400，已停止并保留 checkpoint；第四格停止时尚未完成。
修复后的 smoke-v2 独立保存，没有覆盖失败批次。最终成功不用于抹去这些失败记录。

Responses 没有发送 seed：42/43/44 是采集分片与调度标识，不是服务端随机种子
生效的证明，也不是三次完整独立重复。本轮工程验证不产生因果/模型能力确认性结论。

## 当前执行与证据

- 配置：`bench/aci/results/c16-glm53-responses-20260930/collection.json`。
- 后台 supervisor PID：**40996**；启动时状态为 `running`。
- 状态与日志：`audit-r12-scratch/prelive-2026-09-30/full-run-status.json`、
  `full-run.log`、`full-run.stderr.log`；状态文件在结束/失败时写入退出结果。
- 本地前置回执：同目录 `preflight-verified.json`、`source-manifest.json`、
  `python-verified.log`、`responses-probe.json`、`smoke-nine-v2.json`。
- 采集后结果：集合目录的 `collection-result.json`、`tf45_envelope_replay.json`、
  `read_path_breakdown.json`；未完成前这些文件可能不存在。

**开跑不等于验收通过。** C14 原门槛保留，C16 待新数据判定；未覆盖旧正式基线，
未刷新整个 C12 证据链，未运行本轮 Rust 全套或完整 claim_gate。后续公开声明仍须
完成全链刷新和完整门禁，不能引用历史 29/31 为当前候选的验收结果。

协议说明与范围见 `docs/c16-live-collection-2026-09-30.md`。
