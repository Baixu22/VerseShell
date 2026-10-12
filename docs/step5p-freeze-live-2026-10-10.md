# 2026-10-10 冻结候选真实开发试点

日期：2026-10-10（Asia/Shanghai）。**工程诊断，不是正式研究、产品门禁或默认分支落地。**

## 授权与身份

账户持有人提供与已有 verseshell-step5p.env 相同的 StepFun 密钥，模型 step-5-preview，基址 https://api.stepfun.com/step_plan/v1（用户给出的 host 无 /v1，沿用已验证的 /v1）。未改仓库 .env.local（那是 C13 基线端点）。密钥未写入仓库。

冻结候选：D:/VerseShellLive/node-freeze-20261010-01a120ce ，ready_for_live=true，二进制 SHA256 0192c5cf21787603e4a7392ae1cb35e3965cc9957eec37f39a94dcf641cffebe。未改冻结源码。

## 探针

冻结 prelive_probe.py、2 请求、60s、16384 completion：exit 0，HTTP 200/200，usage 完整。探针用量 prompt 722 + completion 136，与任务格分开。

## 采集

预注册三任务 x 三条件 x 双变体 x seed 42 = 18 格；repeat_call_limit=3 全条件相同；max_turns 24；max_tokens 16384。正式 30/5/3 分析计划未传给 live_round（地板会拒绝 3 任务/1 seed），身份用 verify_readiness 单独核对。

首次用 venv python.exe 启动：完成 6 个 leaderboard 格后，launcher Job Object 在 round 仍 running 时关闭，解析为 unknown_or_conflicting_exit。6 行 checkpoint 保留。

随后用 base interpreter 与 --resume-paused 恢复同一 tag step5p-dev-20261010-r2：跳过 6 行，重试中断格，完成其余 12 格。控制 exit 0，离线报告 baseline/compact_all 完成。

## 18 格原评分

- leaderboard 6/6 success=true, stop=task_complete
- csvlite compact_all raw_shell: success=null, stop=repeat_call_limit
- csvlite baseline raw_shell_coached: success=false, stop=repeat_call_limit
- csvlite baseline verseshell_aci: success=true, stop=task_complete
- csvlite baseline raw_shell: success=true, stop=task_complete
- csvlite compact_all verseshell_aci: success=true, stop=task_complete
- csvlite compact_all raw_shell_coached: success=false, stop=turn_limit
- envconfig 6/6 success=true, stop=task_complete

计数：15 true / 2 false / 1 null。stop：15 task_complete、2 repeat_call_limit、1 turn_limit。合并比较 NOT_CLAIMABLE。不是三次独立重复，不是产品收益。

主产物：D:/VerseShellLive/node-freeze-20261010-01a120ce/workspace/bench/aci/results/step5p-dev-20261010-r2/latest_live.json
