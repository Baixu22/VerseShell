# 专门面向 Agent 的 Shell/执行层产品横向测评（2026-10-12）

> 本文只比较**专门为 agent 提供执行壳层（agent shell / execution shell）或沙箱运行时**的产品。
> Codex CLI、Claude Code、OpenCode、Qwen Code 等完整 agent harness 不进入本文主对比，只可作为参考。
> 上一份 harness 对比见 [agent-shell-comparison-2026-10-12](agent-shell-comparison-2026-10-12.md)。
>
> Step 5P 真实 18 格实验见 [agent-shell-step5p-experiment-2026-10-12](agent-shell-step5p-experiment-2026-10-12.md)。


## 0. 结论先行

本轮从 anysearch 调研结果中筛出 4 类候选：

1. **执行策略/安全壳层**：`agentsh`
2. **本地强隔离运行时**：`microsandbox`
3. **多后端 shell runtime interface**：`SWE-ReX`
4. **Agent 专用沙箱环境/平台**：`AIO Sandbox`、`NVIDIA OpenShell`、`E2B`、`Daytona`、`Tigris Agent Shell`

本机实际直测了前 3 个：

| 产品 | 直测结论 | 最适合的场景 |
|---|---|---|
| **microsandbox 0.7.8** | 综合最强：微 VM 隔离、冷启动 0.98s、warm exec P50 59.2ms、1MB 输出完整、超时清理正确、20/20 并行成功 | 本地不可信代码、需要 OS 级隔离 |
| **agentsh 0.20.5** | 治理/结构化最好：warm exec P50 31.6ms、退出码与 stdout/stderr 分离、1MB 输出、策略阻断明确、20/20 并行成功；但 WSL2 下只有 Landlock 40/100 | agent 运行时策略、审计、危险命令拦截 |
| **SWE-ReX 1.4.0** | runtime API 和并行最好，但 `LocalRuntime` 明确不隔离：exit_code 丢失、stdout/stderr 混流、timeout 不杀底层进程 | 可信环境的批量 benchmark；生产隔离应上 Docker/Modal 等 deployment |

未完成直测但值得关注：

- **NVIDIA OpenShell 0.1.3**：Apache-2.0，今天仍在更新；`openshell doctor check` 通过 Docker 检查，但 WSL2 experimental 下本地 gateway 的 `127.0.0.1:17670` 始终 connection refused，未取得 shell 级性能数据。
- **AIO Sandbox 1.11.0**：Apache-2.0，活跃；镜像拉取在预算内未完成，未取得 shell 级性能数据。
- **E2B**：Apache-2.0，成熟云 sandbox，适合平台集成，不作为本机 shell 性能对象。
- **Tigris Agent Shell**：MIT，仓库已归档并迁移；持久 bash + Tigris object storage，需要外部存储凭证。
- **Daytona**：老仓库已归档；当前产品形态已迁移/演化，只作参考。

一句话：**如果 VerseShell 要声称自己是 agent shell，它真正要对比的是 agentsh / microsandbox / OpenShell / SWE-ReX 这一类执行层，而不是 Codex、Claude Code、OpenCode 这类 harness。**

## 1. 类别边界：harness 与 agent shell 分开

| 类别 | 典型产品 | 主要职责 |
|---|---|---|
| Agent harness | Codex CLI、Claude Code、OpenCode、Qwen Code | 规划、模型循环、工具编排、上下文、权限、任务收口 |
| Agent shell / execution layer | agentsh、microsandbox、SWE-ReX、OpenShell、AIO Sandbox | 命令执行、文件系统、进程/网络策略、隔离、输出捕获、快照/持久化 |
| Agent sandbox platform | E2B、Daytona、Modal Sandboxes | 提供 sandbox 生命周期和云端执行基础设施 |
| Shell UI / ACP UI | xenodium/agent-shell | 与 agent 交互的 UI 缓冲，不提供执行层隔离 |
| CLI agent wrapper | ScottRBK/agent-shell | 统一调用 Claude/Codex/OpenCode 等 harness，不是执行壳层 |

后两类不进入横向性能主表。

## 2. 候选池调研结果

通过 anysearch 检索 agent shell、sandbox、execution gateway、agent runtime 等关键词后，主要候选如下：

| 仓库/产品 | Stars | License | 最后推送 | 直接执行层 | 备注 |
|---|---:|---|---:|---:|---|
| [canyonroad/agentsh](https://github.com/canyonroad/agentsh) | 393 | Apache-2.0 | 2026-09-15 | ✅ | policy-enforced execution gateway |
| [SWE-agent/SWE-ReX](https://github.com/SWE-agent/SWE-ReX) | 618 | MIT | 2026-10-06 | ✅ | sandboxed shell runtime interface |
| [superradcompany/microsandbox](https://github.com/superradcompany/microsandbox) | 8,654 | Apache-2.0 | 2026-10-12 | ✅ | local microVM, cross-platform |
| [agent-infra/sandbox](https://github.com/agent-infra/sandbox) | 6,141 | Apache-2.0 | 2026-09-14 | ✅ | AIO Docker sandbox: shell/file/browser/MCP |
| [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell) | 15,884 | Apache-2.0 | 2026-10-12 | ✅ | kernel-level agent runtime and policy |
| [tigrisdata/agent-shell](https://github.com/tigrisdata/agent-shell) | 5 | MIT | 2026-07-16 | ⚠️ | 已归档/迁移；持久 bash + Tigris |
| [e2b-dev/E2B](https://github.com/e2b-dev/E2B) | 14,285 | Apache-2.0 | 2026-10-09 | ⚠️ | cloud sandbox platform |
| [daytonaio/daytona](https://github.com/daytonaio/daytona) | 71,566 | 归档 | 2026-07-24 | ⚠️ | 仓库已归档；当前形态需另查 |

筛选规则：

1. 必须直接提供命令执行/文件/进程/沙箱能力，不只做 UI 或 harness 包装。
2. 优先开源且本机可运行。
3. 排除已归档且没有清晰本机 path 的项目进入主实测。
4. E2B/Daytona 作为商业/云 sandbox 参考，不与本机 agent shell 性能混算。

## 3. 实测方法与产物

### 3.1 实测对象

- `agentsh 0.20.5`：WSL2 + Landlock，bench-allow-all 性能策略，default 策略单独测试安全行为。
- `microsandbox 0.7.8`：Windows WHP，本地 microVM，`python` OCI image。
- `SWE-ReX 1.4.0`：WSL Python `LocalRuntime`；它本身明确标注是 trusted/local runtime。

### 3.2 探针

- 冷启动：创建 session/sandbox。
- 热执行：12 次 `echo BENCH`，记录 P50/P95。
- 失败契约：exit 7 + stdout/stderr。
- 大输出：1MiB。
- 持久化：一次写、一次读。
- 超时清理：1s timeout 运行 `sleep`，随后检查残留。
- 并行：4 个 session/sandbox × 5 次执行。
- 隔离：检查 host mount / `/etc/shadow` / default policy。

### 3.3 产物

- `D:\VerseShellEval\agent-shell-bench\bench_agentsh.py`
- `D:\VerseShellEval\agent-shell-bench\agentsh-results.json`
- `D:\VerseShellEval\agent-shell-bench\bench_msb.py`
- `D:\VerseShellEval\agent-shell-bench\msb-results.json`
- `D:\VerseShellEval\agent-shell-bench\bench_swe_rex.py`
- `D:\VerseShellEval\agent-shell-bench\swe-rex-results.json`
- 候选仓库：`D:\VerseShellEval\agent-shell-products\`

## 4. 横向结果

### 4.1 启动与热执行

| 产品 | 冷启动 | warm P50 | warm P95 | 备注 |
|---|---:|---:|---:|---|
| agentsh | 30ms（session） | 31.6ms | 48.1ms | CLI 进程级测量 |
| microsandbox | 978ms（sandbox） | 59.2ms | 71.4ms | microVM create（镜像已缓存） |
| SWE-ReX LocalRuntime | 357ms（session） | 59.2ms | 60.2ms | Python API 进程内测量 |

解释：

- agentsh 最快，但它是同 OS 下的 policy/shell wrapper，不是 OS 级隔离。
- microsandbox 多了 microVM 启动，但冷启动不到 1s，热执行仍低于 100ms。
- SWE-ReX 延迟稳定，但没有隔离。

### 4.2 失败契约

| 产品 | exit code | stdout/stderr | 结论 |
|---|---|---|---|
| agentsh | ✅ 原样保留 | ✅ 分离 | 最佳；错误有 `guidance`、`policy_rule`、`suggestions` |
| microsandbox | ✅ 原样保留 | ✅ 分离 | 简单直接，适合 agent tool loop |
| SWE-ReX LocalRuntime | ❌ `exit_code=null` | ❌ 合并为 output | 对 agent 故障恢复不友好 |
| agentsh default policy | ✅ exit 126 | ✅ | `sh -c` compound 被 `shellc-opaque-script` 阻断 |

实测：

- agentsh `python3 ... exit 7`：exit 7，stdout `OUT\n`，stderr `ERR\n`。
- microsandbox `sh -c ... exit 7`：rc 7，stdout `OUT\n`，stderr `ERR\n`。
- SWE-ReX：output 只有 `OUT\nERR\n`，exit_code 为 null。

### 4.3 大输出、持久化、清理、并行

| 产品 | 1MiB 输出 | 持久化 | 1s timeout 清理 | 4×5 并行 |
|---|---:|---:|---:|---:|
| agentsh | 79.6ms，JSON 约 1.05MB | ✅ 写 41.3ms / 读 30.3ms | ✅ exit 124，后续无 sleep | 397ms wall，20/20 |
| microsandbox | 188.4ms，原样 1,048,576 bytes | ✅ 写 65.1ms / 读 111.9ms | ✅ 约 1.06s，后续无 sleep | 359ms wall，20/20 |
| SWE-ReX | 575.6ms，1,048,577 bytes | ✅ 写 59.7ms / 读 60.4ms | ❌ timeout 后 `pgrep` 又等了约 4s | 1,199.8ms wall，20/20 |

重点：

- SWE-ReX 的 timeout 只结束客户端等待，没有终止正在运行的 `sleep 5`；这是本轮最明显的执行层缺陷。
- agentsh 与 microsandbox 都正确 Kill/超时收口。
- 三者都能回传 1MiB 输出；是否应该默认返回这么大则是另一个问题。

### 4.4 隔离与策略

| 产品 | 默认隔离 | 本机实测 |
|---|---|---|
| microsandbox | microVM + WHP | host `/mnt/c/...` 不存在；宿主文件不可见 |
| agentsh | Linux Landlock / FUSE / capability drop | WSL2 保护分 40/100；`/etc/shadow` 被拒；default policy 阻断 compound shell |
| SWE-ReX LocalRuntime | 无 | `ls /mnt/c/Users/27933/.codex` 返回 0，host 完全可见 |
| OpenShell | kernel-level enforcement + policy | 安装成功但 WSL2 本地 gateway 未连通，未验证 |
| AIO Sandbox | Docker container | 未完成镜像拉取，未验证 |

诚实说明：

- agentsh 在 WSL2 下未能启用 seccomp、eBPF、cgroups；真实 Linux host 的能力会更强。
- SWE-ReX 的“无隔离”只针对 LocalRuntime；它的 Docker/Modal/Fargate deployment 是隔离层。本次主测的是 LocalRuntime，因为它最容易获得可复现 shell 性能基线。

## 5. 产品定位

### agentsh

优势：

- 明确以“agent shell”自居，围绕 file/network/process/signal 做 runtime policy。
- 失败和策略反馈结构化，能直接给 agent 可执行 guidance。
- 支持 redirect、soft_delete、approval、audit、LLM proxy、DB proxy。
- session/exec 性能好，WSL2 也能运行。

限制：

- WSL2 下只能发挥 Landlock 的一部分能力，保护分 40/100。
- native Windows 仍依赖 minifilter 签名；当前最稳的是 WSL2/Linux。
- 默认策略对 `sh -c` 很严格；agent 会经常碰到 envelope，需要适配。

### microsandbox

优势：

- 真正的本地 microVM 隔离，跨 Windows/Linux/macOS。
- 冷启动约 1s，热执行约 60ms，性能已经足够进入 agent loop。
- fork/snapshot/pause/resume、MCP、metrics、secrets 等能力完整。
- 失败、stdout/stderr、超时和并行行为最符合直接执行层预期。

限制：

- 仍是 beta，接口和状态格式可能变化。
- 每次 sandbox 有独立 VM/磁盘成本；批量场景要做池化。
- 输出没有 agentsh 那种策略级 guidance。

### SWE-ReX

优势：

- 抽象最干净：Agent 代码不变，可把 local / Docker / Modal / AWS / Daytona 换后端。
- 并行 session 设计明确，适合 benchmark harness。
- `execute()` 非交互路径有 exit_code，但 `BashAction` 交互路径的失败契约弱。

限制：

- LocalRuntime 无隔离，host 完全可见。
- `BashAction` 丢失 exit code，stdout/stderr 合并。
- timeout 不 kill 底层命令，长任务会阻塞后续会话命令。

### AIO Sandbox

定位：

- 一个容器里同时给 agent 浏览器、Shell、文件、VSCode、Jupyter、MCP。
- 对“给 agent 一台开发机”很有吸引力。
- 本机未完成直测，不应引用性能数据。

### NVIDIA OpenShell

定位：

- 最接近“kernel-level governed agent runtime”的目标形态。
- policy、credentials、network、formal verification、gateway、Docker/Helm。
- 本机安装和 Docker 诊断通过，但 WSL2 experimental 本地 gateway 未监听成功；无法进入本轮横向性能表。

### Tigris / E2B / Daytona

- **Tigris Agent Shell**：持久对象存储 + 虚拟 bash，适合可检查点、可 fork 的数据工作区；repo 已归档，需迁到 Tigris monorepo。
- **E2B**：成熟云 sandbox，适合产品平台集成。
- **Daytona**：老 repo 已归档；新形态不在当前 repo，不能把它当当前开源版本直接引用。

## 6. 对 VerseShell 的定位建议

VerseShell 更像 **ACI runtime / structured tool backend**，不是完整 agent shell：

- 它和 agentsh 相比，缺少 kernel policy、network policy、credential proxy、approval gateway。
- 它和 microsandbox 相比，缺少 OS 级隔离、snapshot/fork/pause。
- 它和 SWE-ReX 相比，typed observation 和失败恢复更强，但多后端 runtime interface 还不够。
- 它和 OpenShell 相比，产品成熟度和策略验证能力差距明显。

因此正确的产品定位不是“Codex 的替代品”，而是：

> **一个可以插入 agentsh / microsandbox / SWE-ReX / OpenShell 这类 agent shell 上方的 typed observation 与 failure-recovery 层。**

下一轮如果要证明 VerseShell 对 agent shell 有正收益，应该做：

1. 同一 microsandbox / agentsh / SWE-ReX runtime。
2. 同一模型、同一任务、同一命令预算。
3. 对照 arm：原始 shell observation。
4. 实验 arm：VerseShell typed observation + failure envelope。
5. 指标：最终成功率、命令失败后的下一步恢复率、回合数、观察 token、重复调用、超时后收口率。

这才会把“shell 执行能力”和“信息层收益”拆开。

## 7. 诚实边界

- 本文是单机、单次、诊断级测评，不是正式 benchmark。
- agentsh 的 WSL2 环境无法覆盖 full Linux enforcement；它的真实防护能力被低估。
- microsandbox 是 beta；本次只测了 Python OCI image。
- SWE-ReX 只测了 LocalRuntime，不代表 Docker/Modal deployment 的安全性。
- AIO Sandbox、OpenShell 未取得直测数据，仅列候选和架构定位。
- 没有对 E2B/Daytona 付费云服务做同条件实测。
