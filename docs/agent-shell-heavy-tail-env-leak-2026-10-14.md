# L4 heavy-tail 归因：运行时控制面泄漏给 agent 命令（2026-10-14）

承接 r7 的纵向对比：D 的工具调用集中在两格，这两格又大部分花在侦察 VerseShell 自己。

## 1. Heavy-tail 规模（r7）

| cell | D 调用 | A prime 调用 | D obs tokens | 结果 |
|---|---:|---:|---:|---|
| T413/D | 40 | 9 | 16,416 | 成功 |
| T420/D | 72 | 37 | 41,829 | turn_cap 失败 |

这两格占 D 全部 288 次调用的 **39%**。

## 2. 归因：因果链可直接读出

T413/D 的前几次调用：

```
#2  env | sort; ...                          -> 输出含 AETHER_STATE_DIR=/var/ae-state
#5  cat /var/ae-state/audit.log; ls ...      -> 读了我们的审计日志
... 后续 26/40 次调用用于侦察运行时
```

T420/D 同样在 `#1 env` 里拿到控制面变量，并在 `#3 ls /usr/local/bin` 发现 `ae`，
接着 `#4 ae --help`、`#6 ae -c ...`、`#7 strings /usr/local/bin/ae`。

**根因**：`exec.run` 以 `env=None` 派生任务命令，子进程完整继承 ae 自己的环境，
其中包含运行时控制面变量；`/usr/local/bin/ae` 也在 PATH 上。

实测暴露面（D 臂观察体里出现这些字符串的条数）：

| 轮次 | 暴露 AETHER_* 的观察 | 涉及 cell | 暴露 ae 二进制 |
|---|---:|---:|---:|
| r6 | 4 | 4 | 1 |
| r7 | 9 | 2 | 1 |

## 3. 本轮修复：任务命令不再继承运行时控制面

`src/process_command.rs::configure_command_environment` 在未显式传入 env 时，
先按前缀剔除 `AETHER_*` 与 `AE_*` 再派生。产品里这两个前缀下的变量共 28 个，
全部是运行时配置（caps / policy / approvals / workspace / state dir / timeouts / rbac）。
显式传入 env 的调用方行为不变；`PATH`、`HOME` 等任务环境原样保留。

新增两个不依赖环境变量竞态的纯函数测试：
`runtime_control_plane_vars_are_recognised`、`inherited_environment_drops_the_runtime_control_plane`。

## 4. 直接 A/B 证据（同一 microVM、跑 `env | sort`）

| 二进制 | 泄漏的运行时变量 |
|---|---|
| r7（改前，sha 6a826ac4…） | AETHER_APPROVE_ALL, AETHER_CAPS, AETHER_MODE, AETHER_STATE_DIR, AETHER_WORKSPACE, AE_MAX_CONCURRENCY |
| **r8（改后，sha 250337a6…）** | **（空）**，且 PATH/HOME 完好 |

`cargo test --lib`：165 -> **167 passed / 0 failed**。

## 5. 尚未处理（候选，未实现）

- `/usr/local/bin/ae` 仍在 PATH 上：`ls /usr/local/bin` 就能发现它（T420/D 的 #3 -> #4 触发点）。
  可改到非 PATH 目录（如 /opt/verseshell/ae）并按绝对路径调用；代价是 adapter 需先建目录，属执行层约定变更。
- **未跑 L4 r8**：单轮 60 格、预计约 3 小时，超出 AGENTS.md 的约 2 小时默认上限，需用户逐次授权。

## 6. 诚实边界

- 归因来自 r6/r7 已存产物（离线），本文件不新增模型调用。
- 环境泄漏修复的直接证据是 microVM 内的 A/B 探针，不是 L4 疗效证据；对成功率/成本的影响尚未测。
- 改动未提交（AGENTS.md：不擅自提交）。
