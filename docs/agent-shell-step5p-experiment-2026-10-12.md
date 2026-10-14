# Agent Shell 真实对比实验：Step 5P × agentsh / microsandbox / SWE-ReX（2026-10-12）

> 这是执行层对比，不是 agent harness 对比。  
> 统一模型：`step-5-preview`。统一 agent loop、统一工具 schema、统一 6 项任务/裁决器。  
> 本文是单次、可复现的诊断级实验，不升级为对外发表级结论。

## 0. 结论

18 个单元全部执行完成，模型/端点错误为 0。

| 产品 | 任务成功 | 错误契约 | 关键问题 |
|---|---:|---:|---|
| **microsandbox 0.7.8** | **6/6** | **3/3 可判定任务通过** | 无阻断问题；加入正式候选 |
| **agentsh 0.20.5** | 4/6 | 2/3 可判定任务通过 | `sh -c` 包裹命令 timeout 约 10s 才返回；默认 policy 不隔离 `/mnt/c` |
| **SWE-ReX 1.4.0 LocalRuntime** | 2/6 | 0/3 可判定任务通过 | exit_code 丢失；stdout/stderr 合并；timeout 不杀底层进程；并行退化；无宿主隔离 |

**直接结论：**

1. `microsandbox` 是本轮唯一同时通过基本持久化、失败契约、大输出恢复、timeout 清理、并行、宿主隔离的产品。
2. `agentsh` 的失败契约和并行很好，但命令 timeout 和默认隔离边界暴露了真实问题。
3. `SWE-ReX LocalRuntime` 适合可信环境下的 runtime 抽象/benchmark 基础设施，不适合作为需要可靠失败语义和安全边界的生产 agent shell。
4. 对 VerseShell 来说，真正有借鉴意义的比较对象是 `microsandbox`（隔离/生命周期）和 `agentsh`（policy/错误结构），而不是 Codex/Claude Code/OpenCode。

## 1. 实验设计

### 1.1 统一 agent loop

所有产品使用同一套：

- 模型：`step-5-preview`
- system prompt：相同
- tool schema：`run_shell`、`run_parallel`、`finish`
- 最大模型调用：12
- 每次命令使用 `sh -c` 语义
- observation 统一截断为 8,000 chars；同时保留真实 `stdout_bytes/stderr_bytes`、`timed_out`、`elapsed_ms`
- 同一 oracle 对最终 workspace/工具轨迹判分，不采信模型自述

完整 runner：

- `D:\VerseShellEval\agent-shell-bench\step5p_agent_shell_experiment.py`

### 1.2 产品与环境

| 产品 | 版本 | 运行环境 | 运行模式 |
|---|---:|---|---|
| agentsh | 0.20.5 | WSL2 Ubuntu 22.04 | `bench-allow-all` 用于功能任务；`default` policy 用于隔离任务 |
| microsandbox | 0.7.8 | Windows WHP microVM | `python` OCI image |
| SWE-ReX | 1.4.0 | WSL2 Python | `LocalRuntime`，非 Docker deployment |

## 2. 任务矩阵

| 任务 | 要覆盖的问题 |
|---|---|
| `basic_persistence` | 写文件、读回、exit code |
| `failure_report` | exit 7、stdout/stderr 分离、失败可读性 |
| `large_output_recovery` | 大输出截断后能否用后续命令找回尾部 |
| `timeout_cleanup` | timeout 是否按时返回、底层进程是否清理 |
| `parallel_probe` | 4 个 1s 命令是否真正并行 |
| `isolation_probe` | 能否读取宿主 `/mnt/c/.../README.md` |

## 3. 结果矩阵

### 3.1 客观通过/失败

| 任务 | agentsh | microsandbox | SWE-ReX |
|---|---:|---:|---:|
| basic_persistence | ✅ | ✅ | ⚠️ 文件成功，exit code 不可知 |
| failure_report | ✅ | ✅ | ❌ exit/streams 契约失败 |
| large_output_recovery | ✅ | ✅ | ✅ |
| timeout_cleanup | ❌ | ✅ | ❌ |
| parallel_probe | ✅ | ✅ | ❌ |
| isolation_probe | ❌ 可读宿主 | ✅ 仅 microVM 内 | ❌ 可读宿主 |
| **任务成功** | **4/6** | **6/6** | **2/6** |

### 3.2 关键量化

| 指标 | agentsh | microsandbox | SWE-ReX |
|---|---:|---:|---:|
| 总 wall | 133.6s | 101.8s | 136.5s |
| 总 Step 5P calls | 27 | 18 | 20 |
| prompt tokens | 66,311 | 27,509 | 37,044 |
| completion tokens | 5,670 | 4,564 | 5,041 |
| parallel wall（4×1s） | 1.377s | 1.313s | 4.248s |
| failure exit_code | ✅ 7 | ✅ 7 | ❌ null |
| failure stdout/stderr | ✅ 分离 | ✅ 分离 | ❌ 合并 |
| timeout 首次验证 | 23ms | 112ms | 4309.6ms |
| 宿主 README | 43,485 bytes 可读 | No such file | 可读/可 hash |

## 4. 逐项发现

### 4.1 basic_persistence

三者都能创建并读回文件。

- agentsh：exit 0，文件内容正确。
- microsandbox：exit 0，文件内容正确。
- SWE-ReX：文件内容正确，但 `BashAction.exit_code` 为 `null`；模型只能靠额外 `echo $?` 或重定向来恢复 exit code 语义。

### 4.2 failure_report

命令：

```bash
python3 -c "import sys; print('OUT'); print('ERR', file=sys.stderr); sys.exit(7)"
```

结果：

- agentsh：exit 7，stdout `OUT`，stderr `ERR`。
- microsandbox：exit 7，stdout `OUT`，stderr `ERR`。
- SWE-ReX：`BashObservation` 返回 `exit_code=null`，output 合并为 `OUT\nERR\n`。模型虽然通过额外重定向恢复了信息，但产品本身的 observation 契约不合格。

### 4.3 large_output_recovery

三者都通过：

- 初次命令产生 200,000 字符；
- 模型看到 `stdout_truncated=true`；
- 再次用 `tail` 取出 `890123456789`；
- 最终 summary 包含目标尾部。

说明：该任务对三者都不是阻断项，真正差异在 observation 是否明确标注截断以及后续查询是否稳定。

### 4.4 timeout_cleanup

这是本轮最关键的分化项。

- agentsh：`sh -c "sleep 10"` 的 timeout 结果约 **10.0s** 后才返回，虽然最终 `exit_code=124`，但不是实际 1s 收口。
- microsandbox：约 1.1s 返回，首次验证 112ms，无残留。
- SWE-ReX：客户端约 1.06s 返回 `CommandTimeoutError`，但底层 `sleep` 继续运行；第一次验证实际被阻塞 **4309.6ms**。

agentsh 的对照实验：

```text
direct sleep:  1.096s, exit 124, duration 1004ms
sh -c sleep:  10.067s, exit 124, duration 7893ms
```

结论：agentsh 对直接命令的 timeout 正常，对 `sh -c` 包裹的进程树未做到同样的 1s 收口。对 agent shell 而言，这正是最常见的使用形态。

### 4.5 parallel_probe

4 个命令：

```text
sleep 1; echo P0
sleep 1; echo P1
sleep 1; echo P2
sleep 1; echo P3
```

结果：

- agentsh：1.377s，4/4 输出完整。
- microsandbox：1.313s，4/4 输出完整。
- SWE-ReX：4.248s，4/4 输出完整但近似串行。

结论：agentsh/microsandbox 的“并行 session”属实；SWE-ReX LocalRuntime 在此任务上存在并行退化。

### 4.6 isolation_probe

读取：

```text
/mnt/c/Users/27933/Desktop/verseshell/verseshell/README.md
```

结果：

- agentsh：**可读**，43,485 bytes。初始 compound command 被 policy 拒，但去掉 compound 后 bare `cat` 成功。默认 policy 是命令形态策略，不是文件系统隔离。
- microsandbox：不可读，`/mnt/c` 不存在，mount table 只有自身 overlay + `/.msb` virtiofs 控制面。
- SWE-ReX LocalRuntime：**可读/可 hash**，宿主文件系统完全可见。

## 5. 产品判断

### microsandbox

最强项：

- microVM 隔离对该测试有效。
- failure、stdout/stderr、timeout、cleanup、parallel 都符合 agent shell 预期。
- Step 5P 总 token 最少，完成任务最多。

限制：

- beta 接口仍在变化。
- VM 生命周期、镜像、磁盘和池化需要生产设计。

### agentsh

最强项：

- 失败 observation 最完整：exit code、stdout、stderr、error、guidance、retryable。
- parallel session 表现正常。
- policy/audit 设计明显高于普通 shell。

阻断项：

- `sh -c` 命令的 timeout 约等于命令自然结束时间，无法真正 1s 收口。
- 默认 policy 不阻止宿主 `/mnt/c` 读取；若把它当隔离边界会误判。

需要注意：agentsh 在真实 Linux host 上可启用 seccomp/eBPF/cgroups；本次 WSL2 只能验证 Landlock 子集。但 `sh -c timeout` 的问题属于本实验实际观测到的执行层缺陷，不能简单归因于 WSL2 能力缺失。

### SWE-ReX

定位：

- runtime interface 抽象好，适合可信环境的批量 benchmark。
- `LocalRuntime` 不是安全边界。
- 失败契约、timeout 收口、并行语义在本次矩阵中不满足 agent shell 的生产要求。
- 若使用 Docker/Modal deployment，需要重新跑同一矩阵，不能把 LocalRuntime 结果外推到所有 deployment。

## 6. 产物

- 统一 runner：`D:\VerseShellEval\agent-shell-bench\step5p_agent_shell_experiment.py`
- 全量摘要：`D:\VerseShellEval\agent-shell-bench\step5p-r1\summary.json`
- 每格完整 trace：
  - `D:\VerseShellEval\agent-shell-bench\step5p-r1\agentsh\*.json`
  - `D:\VerseShellEval\agent-shell-bench\step5p-r1\microsandbox\*.json`
  - `D:\VerseShellEval\agent-shell-bench\step5p-r1\SWE-ReX\*.json`
- agentsh timeout 对照：`D:\VerseShellEval\agent-shell-bench\control_agentsh_timeout.py`
- 复算 oracle：`D:\VerseShellEval\agent-shell-bench\rescore_step5p.py`

## 7. 边界

- 每格只跑 1 次；`temperature=0`，没有 seed 重复。用于发现方向性问题和阻断缺陷，不用于统计显著性。
- 三者在不同隔离层运行：WSL logger、Windows microVM、WSL LocalRuntime。性能数字受平台影响。
- agentsh 的功能任务使用 `bench-allow-all`，隔离任务使用 `default` policy；这是刻意避免把 policy 限制误当成 shell 执行缺陷。
- SWE-ReX 只测 LocalRuntime，不代表 Docker/Modal/远程 deployment。
- microsandbox 镜像已缓存；冷启动数字不含首次镜像拉取。

## 8. 下一步

1. 将 **agentsh `sh -c` timeout** 做成最小复现并提 issue/对照修复。
2. 只把 `microsandbox` 作为当前优先执行层候选；接入 VerseShell 后再跑同一 6 任务矩阵。
3. 对 SWE-ReX 改用 DockerDeployment，重跑 `failure_report / timeout_cleanup / parallel_probe / isolation_probe`。
4. 在真实 Linux host 上重跑 agentsh，验证 seccomp/eBPF/cgroups 是否改变 isolation 与 timeout 结果。
