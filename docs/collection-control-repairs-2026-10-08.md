# 采集控制与存储恢复节点开发回执

日期：2026-10-08。范围：TF-0133、TF-0134；承接 TF-0126，保留 TF-0140/0141 的产品门禁与源码落地缺口。

## 实际缺陷与实现

原轮 `storage-watch-final.json` 记录 launcher PID 49908、exit_code=null；同轮 round.status.json 记录 Python PID 13240、completed、exit_code=0。两份原始文件保留不动。旧 D:/VerseShellLive/control/run-live.ps1 把 null 当成不满足成功条件，从而跳过报告；它不是新的控制入口。

- 新入口 `tools/live_control.py` 使用 Python Popen 保留进程句柄并 wait 取得退出码。轮次状态同时保存唯一 control_generation_id；控制回执绑定实际 round generation/PID，兼容 Windows venv 启动器与解释器 PID 不同。非零进程码优先；未知、冲突、旧 generation 或仍存活的所有者均不能完成收尾。已存在的无绑定旧回执不能被补造为新入口的成功证据。
- 两种变体从冻结 collection 读取，分别写入唯一 reports-attempt 目录。每个变体记录终态、工具退出码、日志、源摘要和报告摘要；一个变体失败仍记录另一个变体的结果，整体保持失败。report-only 重试不启动采集、不覆盖旧报告。
- `tools/refresh_live_artifacts.py` 对每一步持久化 running/completed/failed、真实退出码（未知保留 null）；缺报告、源变化和写入异常不能写 complete=true。保留旧 CLI 与选择性 refresh 路径。
- 新入口 Windows 默认储备为 D >=15 GiB、C >=2 GiB。策略通过环境传给 round/runner，并写入 collection/run_identity/live_config；恢复和合并校验该身份，不将新策略混入旧轮。
- 磁盘检查位于启动、恢复、每个未完成格派发前以及报告变体启动前。当前格提交后下一格前暂停；STOP 由 runner 直接读取父目录，不再猜测 shard 文件名。恢复须空间恢复且显式 --resume-paused；标记归档而非自动删除。磁盘读取失败按不可用处理。

## 离线验证边界

控制测试使用真实本机子进程；模型调用和报告内容使用标明的离线 fixture，不是新模型测量。磁盘读数及 ENOSPC 用注入方式覆盖，不填满真实磁盘。验证包括：0/非零/未知退出码、旧 generation、缺报告、源变化、两个变体、独立重试、D/C 阈值及未知读数、STOP 传播、写入失败保留已提交行、同身份恢复不重复格。

本批没有改 Rust 源码，没有运行付费模型、发布、提交或合并，没有重新评分历史原轮。新源码须进入新冻结 checkout 与 readiness 后才能采集；不能复用旧轮 tag 补跑。进程树在控制器/整机被强制终止时的跨进程回收，以及持续写入故障下所有诊断文件都能落盘，不在本批已证明范围；无法写盘时保持失败/不再派发，不声称当前格可无损恢复。

源码与权威森林位于本仓库；测试临时目录、缓存、构建目标、日志及证据均按本批 environment.ps1 放到 D 盘。新生产冻结版本的全部评分副本路径尚须再核验，TF-0134 不关闭。

## 复现


控制入口（只展示用法，本批没有启动新采集）：

```powershell
python tools/live_control.py --workspace D:/NEW_FROZEN_WORKSPACE --tag NEW_TAG -- --model MODEL --env-file PRIVATE_ENV --preflight READINESS --probe-report PROBE --analysis-plan PLAN --prompt-variants baseline,compact_all --seeds 42,43,44,45,46 --arms with
```

失败后仅重做离线报告（新目录，绝不自动重跑采集）：

```powershell
python tools/live_control.py --workspace D:/NEW_FROZEN_WORKSPACE --tag NEW_TAG --finalize D:/NEW_FROZEN_WORKSPACE/bench/aci/results/NEW_TAG/control/GENERATION/collection-exit.json
```

本机回归命令：

```powershell
. 'D:/VerseShellLive/control-repair-20261008/environment.ps1'
python -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
python -X utf8 tools/claim_gate.py --metrics eval/metrics.json --compact-ratio eval/compact_ratio.json --evidence D:/VerseShellLive/control-repair-20261008/evidence/claim-gate.json
```

门禁复用已有 metrics/compact_ratio，不重测、不覆盖历史指标；门禁红项不因工程回归通过而转绿。

## 产物与状态

- 完整 Python 回归：231 tests，73.126 秒，exit 0；包含 11 个控制测试及 19 个恢复测试（不重复计数）。日志：D:/VerseShellLive/control-repair-20261008/logs/python-tests-final.log。
- 产品门禁：25/31，exit 1。C12/C14/C16/C24/C34/C36 仍红；不修改门槛，不用工程测试替代正式研究或评分审计。
- 本批源码范围 git diff --check：exit 0；仓库整体检查 exit 2，已有森林/历史结果/任务 JSON 的格式告警保留，未扩展修复范围。
- 两个 CLI 的 --help 均 exit 0。回归中暴露的本批补丁错误已修复并完整重跑；失败日志仍保留，不能拿早期失败版本的报告代替最终版本。
- TF-0133、TF-0134 与父分支 TF-0126 从 ready 转为 in_progress；不关闭节点。TF-0140/0141 继续承接产品门禁、默认分支落地与新冻结版本核验；TF-0135/0136 等其他分支不标作已完成。

精确补丁、文件摘要和边界核验分别位于同一证据根目录的 implementation.diff、change-manifest.json、evidence/change-boundary.json。补丁基线是会话开始时的脏工作区，不是 HEAD；既有改动和暂存区保留。

证据根目录：D:/VerseShellLive/control-repair-20261008/。
