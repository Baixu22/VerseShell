# u2-flash 接入检查

2026-10-01，按用户提供的 `https://maas-api.unisound.com/v1` 和 `u2-flash` 检查。
凭据仅保存于 Git 忽略的本地 `.env.local`，不写入本文或测试日志。

| 检查 | 结果 |
|---|---|
| GET /v1/models | HTTP 200，模型目录包含 u2-flash |
| POST /v1/chat/completions，最小英文请求 | model_not_found，未获得回复 |
| POST /v1/chat/completions，原示例“你好”，无额外参数、无重试 | HTTP 404，model_not_found：模型不存在或无调用权限 |
| 当前已安装 OpenAI SDK | 默认初始化存在 httpx proxies 参数兼容错误；显式 httpx client 的尝试为连接错误，不作为模型权限结论 |
| 现有 runner 的工具往返、九格 smoke | 未执行，基础聊天请求尚未通过 |

结论：服务可连通，但目录列出模型不等于该凭据当前能调用模型。尚不能确定是账号权限、
服务端路由或实际模型 ID 配置问题。不能宣告 R5 通过，也没有切换默认模型或启动新采集。
用户提供的配置已单独保存为待启用；原实验配置、旧数据和代码未修改。

下一步需要服务端确认该凭据对 u2-flash 聊天接口的可用性，或提供对应的正确可调用 ID。
确认后继续原计划的工具往返、usage 检查和小规模集成验证，不自动更换模型。

证据：`audit-r12-scratch/u2-integration-2026-10-01/` 下的 `probe.json`、
`model-discovery.json`、`reference-probe-sdk.json` 和 `reference-probe-urllib.json`。
