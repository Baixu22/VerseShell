# 公开数据集调研：能否替代或补充 ACI-Bench 的 10 任务手写集

- 调研对象：`bench/aci/`（ACI-Bench v1.3.0，10 任务，seed 42）
- 调研问题：是否存在一个**完整的公开数据集**，可以直接替换或补充本仓库手写的 10 任务基准
- 结论日期：2026-09（本报告只读取仓库文件，未修改任何代码）

---

## 1. 结论先行

**没有任何公开数据集可以「直接」喂给本仓库的 runner。** 本仓库的 runner 有三条硬性结构要求，公开数据集全部不满足：

1. **`workspace_fixture` 必须是一个普通目录树。**
   `live_agent_loop.py::prepare_workspace()` 用 `shutil.copytree` 把 `bench/aci/fixtures/<name>/` 复制到本机临时目录（`tempfile.mkdtemp`），agent 直接在这个目录里跑，`check_success` 也在这个目录里读文件。
   所有主流公开数据集提供的是**容器镜像或环境配置**（Harbor `environment/Dockerfile`、SWE-bench 每实例 Docker 镜像、SWE-rebench 的 `docker_image` + conda yaml），**没有一个提供「已就绪的目录树」**。

2. **成功判定只支持 5 种谓词。**
   `check_success()` 的词汇表是 `file_equals` / `file_contains` / `file_not_contains` / `file_matches` / `command_exit_0` / `all`，全部是**针对本机目录的同步断言**。
   公开数据集的判定是 `tests/test.sh` 写 `/logs/verifier/reward.txt`（Harbor）或 `FAIL_TO_PASS` / `PASS_TO_PASS` 测试节点列表（SWE-bench 系）。前者需要容器内路径 `/tests`、`/logs`，后者需要**逐测试节点**的通过/失败，而谓词层只有整条命令的退出码。两者都需要新增谓词类型，不是字段映射。

3. **执行面是本机 Windows + 本机工具链，不是容器。**
   `raw_shell` 条件走 `subprocess.run(shell=True)`（Windows 上是 `cmd /C`），`verseshell_aci` 条件走 `target/debug/ae.exe --serve`。**`ae` 是宿主可执行文件，无法在容器里被 Harbor 调度。**

另外两个具体的阻塞点：

- **Harbor 的 Windows 任务容器只支持 `nop` 和 `oracle` 两个 agent。** 官方 agent 能力表里 `Windows` 一栏只有 `nop`、`oracle`（[Harbor 文档](https://docs.harborframework.com/core-concepts/agents/pre-integrated-agents)）。也就是说，即使把 Terminal-Bench 的 Windows 任务跑起来，也**没有真实 agent 的位置**，更不用说条件 D。Terminal-Bench 的 Windows 任务本身是「Linux 里套 Docker、Docker 里套 QEMU、QEMU 里装 Windows」（[Ivan Bercovich, What Makes a Good Terminal Bench Task](https://www.ivanbercovich.com/2026/writing-a-good-terminal-bench-task)）。
- **SWE-smith 明确不支持 Windows。** 官方 README：`SWE-smith requires Docker to create execution environments. SWE-smith was developed and tested on Ubuntu 22.04.4 LTS. We do *not* plan on supporting Windows or MacOS.`（[SWE-smith README](https://github.com/SWE-bench/SWE-smith)）

**更关键的判断：本仓库要测的东西，公开数据集里没有人在测。**

本仓库的头号指标是 **D/A 观察 token 比（observation-token ratio）**，即在**同一批任务、同一套成功谓词**下，typed ops 的 ACI 面比裸 shell 少看多少字节。公开基准全部以 **pass rate / resolved rate** 为头条指标（Terminal-Bench 用 task resolution rate，SWE-bench 用 resolved rate）。目前没有任何公开基准把「观察 token 效率」当作主要指标。

所以答案是：**测试方案不能靠「换数据集」解决，只能分层——本地 10 任务集继续承担 A/D 对比（这一层不可替代），另外引入一个公开数据集做「外部有效性」第二层（只测通过率），两者用不同的 runner、不同的判据，不能混算。**

---

## 2. 对比表

| 数据集 | 任务数 | 任务/判定格式 | 是否必须 Docker | Windows 支持 | 许可证 | 能否直接喂给本仓库的 runner | URL |
|---|---|---|---|---|---|---|---|
| **Terminal-Bench 1.0**（beta） | **~100**（README 表述为 "currently in beta with ~100 tasks"，非精确计数） | 任务目录：英文 instruction + test script + oracle solution | **是**（harness 依赖 `uv` + `Docker`） | 未核实（README 未声明；历史 harness 为 Linux 容器） | **Apache-2.0** | **否** | [github.com/harbor-framework/terminal-bench-1](https://github.com/harbor-framework/terminal-bench-1) |
| **Terminal-Bench 2.0** | **89** | Harbor 格式：`instruction.md` + `task.toml` + `environment/Dockerfile` + `solution/solve.sh` + `tests/test.sh`（reward 写到 `/logs/verifier/reward.txt` 或 `reward.json`） | **是**（Docker / Modal / Daytona） | **实质不支持**：`[environment].os` 可为 `windows`，但 Windows 容器只有 `nop` / `oracle` agent 可用 | **Apache-2.0**（源码仓库） | **否** | [Harbor Hub 任务列表（"Displaying 89 of 89 tasks"）](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2/latest?tab=tasks) · [HF 镜像](https://huggingface.co/datasets/harborframework/terminal-bench-2.0) · [论文摘要](https://arxiv.org/abs/2601.11868) |
| **Terminal-Bench 2.1** | **89**（2.0 的修复版刷新） | 同 2.0 | **是** | 同上 | 未核实（随主仓库 Apache-2.0） | **否** | [Artificial Analysis TB 2.1](https://artificialanalysis.ai/evaluations/terminalbench-2-1) |
| **Terminal-Bench 3.0** | **74** | 同 2.0（`registry.json` 声明 version `3.0.0`, 74 tasks） | **是** | 同上 | **Apache-2.0**（镜像内 `LICENSE`，与源仓库一致） | **否** | [huggingface.co/datasets/harborframework/terminal-bench-3.0](https://huggingface.co/datasets/harborframework/terminal-bench-3.0) |
| **Terminal-Bench 4.0** | **66**（移除 8 个饱和/易拒答/已公开/有质量问题的任务） | 同 2.0；每个任务有独立测试集，**全部测试通过才算通过** | **是** | 同上 | 未核实 | **否** | [Artificial Analysis TB 4.0](https://artificialanalysis.ai/evaluations/terminalbench-4-0) |
| **Terminal-Bench Challenges** | **3**（单任务基准，无时间/资源限制） | Harbor 格式；按任务特定指标（正确性 + 性能）评分 | **是** | 同上 | 未核实 | **否** | [tbench.ai 公告](https://www.tbench.ai/news/terminal-bench-challenges) |
| **SWE-bench（full）** | **2,294** | HF 实例：`problem_statement` + `base_commit` + `patch` + `test_patch` + `FAIL_TO_PASS` / `PASS_TO_PASS`；判定 = 应用模型 patch 后测试节点状态翻转 | **是**（v5 CLI 从 task repo 构建镜像） | **否**（官方建议 x86_64，arm64 为实验性；Windows 未声明支持） | **MIT** | **否** | [SWE-bench FAQ](https://www.swebench.com/SWE-bench/faq/) · [GitHub](https://github.com/SWE-bench/SWE-bench) |
| **SWE-bench Lite** | **300** | 同上 | **是** | 否 | **MIT** | **否** | [swebench.com/lite.html](https://www.swebench.com/lite.html) |
| **SWE-bench Verified** | **500**（人工确认可解） | 同上 | **是** | 否 | **MIT** | **否** | [OpenAI 公告](https://openai.com/index/introducing-swe-bench-verified/) · [GitHub](https://github.com/SWE-bench/SWE-bench) |
| **SWE-smith** | **数字不一致，需注意**：HF 卡面写 **50,137** instances / 128 repos；HF Dataset Viewer 显示 **59,136** 行；GitHub README 写 **52k**。三者口径未核实 | 实例：`instance_id` / `patch` / `FAIL_TO_PASS` / `PASS_TO_PASS` / `image_name` / `repo` / `problem_statement`；每个 repo 一个 Docker 镜像（250+ 环境） | **是**（明确要求 Docker） | **明确不支持**（"We do *not* plan on supporting Windows or MacOS"） | **MIT** | **否** | [HF 数据集](https://huggingface.co/datasets/SWE-bench/SWE-smith) · [GitHub](https://github.com/SWE-bench/SWE-smith) |
| **SWE-rebench** | **27,878** 行（`test` 21.3k + `filtered` 6.54k；正文表述 "over 21,000 issue–pull request pairs from 3,400+ Python repositories"） | 扩展 SWE-bench schema：`problem_statement` / `patch` / `test_patch` / `base_commit` / `FAIL_TO_PASS` / `PASS_TO_PASS` / `install_config` / `requirements` / `environment`（conda yaml）/ `docker_image` / `license_name` | **是**（提供 7,500 个预构建 Docker 镜像） | **否**（Linux 容器 + conda 环境） | **CC BY 4.0**，但**须逐个实例遵守其源仓库许可证**（每行带 `license_name`） | **否** | [huggingface.co/datasets/nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench) |
| **SWE-rebench-openhands-trajectories** | **67,074** 条轨迹（2.08 GB） | **不是任务集**，是轨迹集：`trajectory_id` / `instance_id` / `repo` / `trajectory`（完整多轮消息列表）/ `tools` / `model_patch` / `exit_status` / `resolved` / `gen_tests_correct` / `pred_passes_gen_tests` | 否（只读数据集；关联的任务侧需要 Docker） | 可读取（纯 parquet） | **CC BY 4.0**（经 HF API `cardData.license` 核实） | **否**（无测试台、无成功谓词） | [HF 数据集](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) · [许可证 API](https://huggingface.co/api/datasets/nebius/SWE-rebench-openhands-trajectories) |
| **Long-Horizon Terminal-Bench (LHTB)** | **46**（跨 9 个领域） | 容器化终端任务 + 隐藏 verifier + 多步 gold solution，dense reward-based grading | **是**（容器化） | 未核实 | 未核实 | **否** | [GitHub](https://github.com/zli12321/LHTB) · [项目页](https://zli12321.github.io/LHTB/) |
| **本仓库 ACI-Bench v1.3.0** | **10** | 单 JSON：`prompt` + `workspace_fixture`（普通目录）+ `success` 谓词字典（`file_equals`/`file_contains`/`file_not_contains`/`file_matches`/`command_exit_0`/`all`）+ 可选 `golden` / `optional_verify` | **否** | **是**（原生 Windows，含 2 个 Windows 专属任务） | 仓库自有 | —（本身就是） | `bench/aci/tasks/manifest.json` |

---

## 3. 逐项可行性分析

按「离可用最近」排序，分析前 3 个候选接入本仓库 harness 的具体成本。

### 3.1 Terminal-Bench 2.0 / 3.0（89 / 74 任务）

**字段映射**

| 本仓库字段 | Terminal-Bench 对应物 | 映射可行性 |
|---|---|---|
| `prompt` | `instruction.md` | **可直接映射**（唯一干净的一对一字段） |
| `workspace_fixture` | `environment/Dockerfile`（或 `task.toml` 的 `[environment].docker_image`） | **无对应物**。Harbor 的环境是容器镜像，不是目录树。`prepare_workspace()` 的 `shutil.copytree` 无从下手 |
| `success` | `tests/test.sh` → `/logs/verifier/reward.txt` | **无对应物**。只能勉强用 `command_exit_0` 包一层脚本去读 reward 文件，但 `test.sh` 必须在容器内跑（依赖 `/tests`、`/solution`、`/logs` 三个特殊路径，见 [Harbor 环境文档](https://docs.harborframework.com/core-concepts/tasks/environment)） |
| `golden` | `solution/solve.sh` | **语义可映射**，但执行位置仍在容器内 |
| `optional_verify` | 无（TB 的验证就是唯一的 `tests/`） | **无对应物** |
| `timeout_sec` / `weight` / `modes` / `lang` / `platform` | 无对应物（Harbor 的资源声明在 `task.toml` 的 `[environment]` 段，语义不同） | **无对应物** |

**具体适配工作量**

要真的把 Terminal-Bench 跑进本仓库，需要新建一条与 `live_agent_loop.py` **平行的** pipeline，而不是给现有 runner 加分支：

1. 把 Harbor 作为外部 harness 跑（`uv tool install harbor`），本仓库侧只提供一个 agent 适配器。Harbor 要求「子类化 `BaseAgent` 或 `BaseInstalledAgent`」（[HF 镜像说明](https://huggingface.co/datasets/harborframework/terminal-bench-2.0)），这意味着要写一个把 `ae --serve` 暴露给 Harbor 的 agent 包，并把它装进容器。
2. **`ae.exe` 是 Windows 宿主可执行文件，必须先在容器内（Linux）构建**，否则条件 D 在容器里根本不存在。
3. 判定从「Harbor reward」翻译成本仓库的结果 schema，需要在 runner 外做一层 join。
4. 环境成本：Docker Desktop + WSL2；Harbor Hub 官方建议 `--env modal` 或 `--env daytona`（"Terminal-Bench includes GPU and multi-container tasks. We recommend running on Modal or Daytona."，[Harbor Hub](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest)），否则 GPU 任务与多容器任务（`torch-tensor-parallelism`、`caffe-cifar-10`、`build-pov-ray` 等）在本地无法完成。

**结论**：Terminal-Bench 能测的是**通过率**，测不到 D/A 观察 token 比。它的价值是「外部有效性」——证明 ACI 没有在自造任务上过拟合。**成本高，收益是间接的。**

---

### 3.2 SWE-rebench（27,878 行，CC BY 4.0）

**字段映射**

| 本仓库字段 | SWE-rebench 对应物 | 映射可行性 |
|---|---|---|
| `prompt` | `problem_statement` | **可直接映射** |
| `workspace_fixture` | `base_commit` + `install_config` + `requirements` + `environment`（conda yaml）+ `docker_image` | **无对应物**。理论上可以 `git clone` + `git checkout <base_commit>` 造出目录树，但**依赖环境装不上就没有可用的工作区**：这些是 3,400+ 个真实 Python 仓库，`install_config` 里含 `apt-get`、conda yaml、多版本 Python（样本里可见 `"python": "3.9"`）。在本机 Windows 上逐仓库成功安装是不可控的 |
| `success` | `FAIL_TO_PASS` / `PASS_TO_PASS`（测试节点列表） | **谓词词汇表不够用**。`command_exit_0` 只给整条命令的退出码；SWE-bench 的判据是**逐测试节点**状态翻转（`FAIL_TO_PASS` 从 fail 变 pass，且 `PASS_TO_PASS` 不回归）。要接入必须新增谓词类型（如 `test_nodes_pass`），并实现一个 pytest 输出解析器 |
| `golden` | `patch`（gold patch） | **语义可映射**（本仓库已有 `GOLDEN/` 目录约定） |
| `optional_verify` | `test_patch`（测试补丁） | 语义接近，但应用顺序（先打 `test_patch` 再判）本仓库没有对应机制 |
| — | `hints_text` / `created_at` / `meta` / `version` / `environment_setup_commit` / `license_name` | **无对应物**（`license_name` 是本仓库完全没有的字段，而它是合规必需的） |

**具体适配工作量**

1. 新增谓词类型 + pytest 节点解析器（**这是唯一一处本仓库谓词层真正的扩展**，对其他数据集也复用）。
2. 工作区构造从「复制目录」改成「clone + checkout + 装依赖」，需要为每个实例做环境隔离（容器或 venv），否则实例间互相污染。本仓库当前的 `prepare_workspace` 是「每次一个临时目录」，**没有环境隔离层**。
3. 规模：27,878 行 × 2 条件 × 3 重复 ≈ 167k 次真实模型调用。按本仓库当前 10 任务 × 2 条件 × 3 重复 = 60 行的量级，**这是一个数量级以上的成本跃升**。必须先做子集抽样。

**结论**：SWE-rebench 是这三个候选里**判定语义最接近 SWE 类能力**的，而且许可证清晰（CC BY 4.0 + 逐实例 `license_name`）。但它的价值同样只在通过率，且成本最高。

---

### 3.3 nebius/SWE-rebench-openhands-trajectories（67,074 条轨迹，CC BY 4.0）

**它不是基准，不能喂 runner。** 理由：

- 没有 `workspace_fixture`：只有 `instance_id`，工作区需要另去 `nebius/SWE-rebench` 取（要 Docker）。
- 没有 `success` 谓词：`resolved` 是**别处算出来的标签**，数据集里不带可复算的判定。
- 没有 `prompt` 之外的输入：`trajectory` 里的 system message 是 OpenHands 自己的脚手架提示，不是本仓库的任务提示。

**但它对第 5 节（数据完整性）有直接价值**，这是它唯一的用途：

- `trajectory` 字段含**每一步观察的完整文本**（`role: 'tool'` 的消息内容），所以**可以用真实 tokenizer 重新计算观察 token**，用来量化本仓库 `len(text)//4` 代理的误差。
- 数据集自带规模统计（Table 1）：OpenHands v0.54.0 + Qwen3-Coder-480B 的平均轮数 **64.3**、最大 **408**。这给出了「真实 ACI 循环的观察量级」，可作为本仓库 4.07 次工具调用的外部参照——**两者差一个数量级，说明本仓库的任务集是「短任务」而非长任务，外推时要注意**。
- 字段 `gen_tests_correct` / `pred_passes_gen_tests` 提供了「agent 自己写的测试是否有效」的度量，本仓库没有这一维度。

**结论**：作为**离线测量方法论语料**使用，不作为基准。

---

## 4. 推荐方案

**推荐 (b)：保留本地 10 任务集作为第一层，另加一个公开数据集作为第二层；不替换。**

### 4.1 为什么不能替换（(c) 被否决）

1. **公开数据集测不到本仓库的主张。** 本仓库头号指标是 D/A 观察 token 比（当前 0.8855），全部候选数据集的头条指标都是通过率。换成公开数据集等于**放弃唯一能支撑 ACI 主张的测量**。
2. **本仓库当前 live 结果还没达到自己冻结的承诺。** `docs/v1.1-freeze.md` 第 32 行写的是「higher success **and/or** ≤0.7 tool calls **and/or** ≤0.6 observation tokens」。当前 live 是工具比 **0.9919**、token 比 **0.8855**——**两条数值门槛都没过**，gate 只靠 `success_rate_D > success_rate_A`（0.80 vs 0.6333）这一支通过。这个分支恰恰是统计上最弱的一支（见 5.1，p≈0.152）。在这种情况下换数据集，是把「未达标的指标」换成「不测的指标」。
3. **Windows 覆盖会归零。** 本仓库 10 个任务里有 2 个是 Windows 专属（`windows_path_normalize_edit`、`windows_batch_capture_diag`），且 C18/C22 两个已登记的缺陷声明（rustup shim 启动名、裸名 `npm`/`npx` 解析）**只在本机 Windows 上成立**。所有候选公开数据集都不支持 Windows（SWE-smith 明确声明，SWE-bench 官方只建议 x86_64，Terminal-Bench 的 Windows 容器没有真实 agent 位）。替换会直接删掉这条证据链。

### 4.2 为什么不能只保留本地集（(a) 不够）

1. **10 任务不足以支撑通过率结论。** n=30/arm 时，观测到的 0.1667 成功率差**不显著**（z=1.43，双侧 p≈0.152，计算见 5.1）。当前「D 成功率首次明显高于 A」的说法在统计上站不住。
2. **没有外部有效性证据。** 10 个任务全部是仓库自造的 30 行以内小 fixture（`rust_search_and_edit` 只要求 `src/lib.rs` 里出现 `return a + b`），无法排除「ACI 只在这 10 个形状上有效」。
3. **任务集自身在动。** v1.2.0 改过 ts 的行为判定，v1.3.0 改过 `python_noisy_install_summary` 的正则（`docs/claims-and-evidence.md` C13/C23/C24）。自造集的谓词与任务同源，**存在「判定跟着实现改」的结构性风险**，外部集能对冲这一点。

### 4.3 推荐的分层方案

| 层 | 数据集 | 测什么 | 用什么跑 | 判据 | 成本 |
|---|---|---|---|---|---|
| **Tier 0（离线，立刻可做）** | `nebius/SWE-rebench-openhands-trajectories`（CC BY 4.0） | 只做**测量校准**：用真实 tokenizer 重算观察 token，量化 `len(text)//4` 的误差；用 64.3 平均轮数作外部量级参照 | 纯离线脚本，不调模型 | 代理误差区间；不产生对外主张 | **低**（一个 2.08 GB parquet + 一个 tokenizer） |
| **Tier 1（保留，必须）** | 本地 ACI-Bench v1.3.0（10 任务） | **D/A 观察 token 比 + 工具比 + 通过率**，同一任务、同一谓词 | `live_agent_loop.py`（不变） | 冻结门槛 ≤0.7 工具比 / ≤0.6 token 比，**分开报告，不再用 OR 合并** | 现有成本；建议把 `--repeat` 从 3 提到 ≥11（见 5.2） |
| **Tier 2（新增，外部有效性）** | Terminal-Bench（固定一个 tag，建议 3.0 的 74 任务或 2.0 的 89 任务） | **只测通过率**，不测 token | **Harbor**（Docker / Modal / Daytona），**不是** `live_agent_loop.py` | 通过率 + oracle 校验；与 Tier 1 数字**不得相加或合并** | **高**：Docker Desktop + WSL2；写一个 Harbor agent 适配器；把 `ae` 在 Linux 容器内构建；GPU/多容器任务需 Modal 或 Daytona |
| **不建议** | SWE-bench / Verified / SWE-smith / SWE-rebench | — | — | — | 在 Windows 上不可行或成本失控：SWE-bench 需 120 GB 存储 + 16 GB RAM + x86_64；SWE-smith 明确不支持 Windows |

### 4.4 成本的明确说明

- **Tier 0 是唯一「今天就能做完」的一步**，而且它直接改善 Tier 1 的可信度（把 token 代理误差写清楚）。
- **Tier 1 提到 `--repeat 11` 的成本**：10 任务 × 2 条件 × 11 = 220 行，是当前 60 行的 3.67 倍。按当前 `avg_elapsed_ms` 与端点延迟估算，这是一次数小时级的重跑；但它是**让成功率结论从「不显著」变成「显著」的最低成本**。
- **Tier 2 的成本主要是工程而非算力**：Harbor agent 适配器 + Linux 容器内构建 `ae` + 判定翻译层，是**新的代码路径**，不是字段映射。如果目标只是「证明 ACI 在外部任务上不掉通过率」，可以先用 Terminal-Bench 的一个固定子集（例如 oracle 校验通过的 20–30 个非 GPU、非多容器任务）来限制成本。
- **不要做的事**：把 Tier 2 的通过率与 Tier 1 的 D/A 比值放进同一张表做「总分」。两者样本、判定、执行面都不同，合并即口径污染（本仓库 `docs/claims-and-evidence.md` 的 C13⑧ 已经为 mock 与 live 立过同类规则）。

---

## 5. 数据完整性的判定方法

问题重述：如何用这样的数据集验证「每条主张都有完整的数据反馈」。

### 5.1 当前样本量的实际统计结论（这是本报告最硬的一条）

当前 artifact：`bench/aci/results/latest_live.json`，`n_rows = 60`（10 任务 × 2 条件 × 3 重复，`repeat=3`，`temperature=0`，`seed=42`），每臂 **30** 行。

**成功率**（A 0.6333 / D 0.80，差 0.1667）：

- 两比例 z 检验（合并比例）：**z = 1.4327，双侧 p ≈ 0.1519** → **不显著**。
- 达到 80% power、α=0.05 所需样本量：**约 111 行/臂**。在 10 任务上即 **约 11 次重复/任务-条件**（当前是 3 次）。
- 也就是说：**「D 成功率明显高于 A」这句话目前没有统计支撑**，而 gate 正是靠这一支通过的。

**观察 token**（A 177.63 / D 157.30，差 20.33）：

- 配对设计（同一任务同一重复）：所需对数取决于**配对差的 SD**，而该 SD **未记录在 artifact 里（未核实）**。
- 若配对差 SD ≈ 25 → 需约 **12 对**（10 任务上约 1.2 次重复）；若 SD ≈ 30 → 约 **17 对**；若 SD ≈ 40 → 约 **30 对**（约 3 次重复）。
- 非配对两样本：SD ≈ 30 时需约 **34 行/臂**（约 3.4 次重复/任务-条件）。
- 关键结论：**token 指标比成功率指标「便宜得多」**——token 效应量相对噪声更大，3 次重复量级就够；成功率不够。

**建议的最小配置**

| 主张类型 | 最小重复数（10 任务上） | 依据 |
|---|---|---|
| 观察 token 比 / 工具比 | **≥ 4**（配对报告，同时记录配对差 SD） | 配对 80% power，SD≤40 的保守假设 |
| 成功率差 | **≥ 11** | 两比例 80% power，基于观测到的 0.1667 |
| 任何跨模型外推 | **≥ 2 个模型**，各自独立报告 | 单模型不可外推（见 5.3） |

**必须修的一处设计问题：`meets_acceptance` 是三条判据的 OR。**

`compare_a_vs_d()` 里 `meets_acceptance = (rd > ra) or (td < ta*0.7) or (od < oa*0.6)`。三条各按 α=0.05 判，族错误率约 1−(0.95)³ ≈ **14%**。再加上 10 个任务各自也有判据，多重比较没有做任何校正。**建议**：三条判据分别报告并各自给置信区间，`meets_acceptance` 只作为「是否需要进一步测」的触发器，不作为对外主张的依据。

### 5.2 用公开数据集做「完整数据反馈」的检验清单

「每条主张都有完整的数据反馈」= 每个数字都能回溯到**逐行原始记录**，且每个结论都带**样本量与不确定性**。可机械检验的清单：

1. **逐行可追溯**：主张里的每个聚合数（`success_rate`、`avg_tool_calls`、`avg_observation_tokens`）必须能由 `rows[]` 重算，且**逐行记录**：`task_id`、`condition`、`model`、`run_index`、`success`（含 `None`）、`tool_calls`、`observation_tokens`、`trajectory`。当前 `latest_live.json` 满足这一条（60 行全在）。
2. **排除项必须显式列出**：`success is None`（UNVERIFIED）的行被排除在成功率之外，必须同时报告 `scored_rows` 与 `unverified_rows`（当前均为 30/0）。**若某轮出现 `unverified_rows > 0`，成功率必须写成区间而非点值。**
3. **样本量与重复数必须写进 artifact**：`live_config.repeat`、`seed`、`temperature`、`tasks`、`conditions` 已在 payload 里——引用主张时必须一并给出。
4. **不确定性必须给出**：当前 artifact **不含任何 CI / SD / 方差**。这是最需要补的一项：至少给出成功率的 Wilson 区间与 token 的均值±SD。
5. **指纹新鲜度**：`evidence.fingerprint` 覆盖 `src/**/*.rs`、`bench/aci/tasks/*.json`、`bench/aci/fixtures/**/*`、`live_agent_loop.py`。**改任何任务或 fixture 都会让数字作废**（`docs/claims-and-evidence.md` C12/C21 已机器化这条）。引入外部数据集时，必须把外部数据集的**固定版本 tag 或 commit hash** 纳入指纹，否则「外部集结果」无法证明是对哪个版本测的。
6. **两条件必须对称插桩**：当前 A 侧的 trajectory **不记录单条命令的成败**（只有 D 侧有 `aci_ok`），所以 `docs/claims-and-evidence.md` C15 明确说 A 侧无法做成功/失败拆分。**任何「D 的失败更多/更少」类主张在 A 侧都没有数据支撑。** 引入公开数据集时要保证两侧插桩对称。

### 5.3 具体陷阱（逐条，且多数在本仓库已有记录）

1. **端点噪声（最大的一条）。**
   `docs/claims-and-evidence.md` C13④ 记录：A 侧代码八轮未动，其 with 臂 obs_tok 却在 **168.6 / 197.4 / 170.5 / 168.9 / 202.4 / 180.9 / 155.9 / 177.6** 之间摆动，约 **±14%**。
   **后果**：D/A 比值的变化被 A 侧漂移主导，**比值本身不能当趋势证据**；能读的是 D 的绝对开销与确定性复算（C14/C16）。
   **对策**：报告 A 与 D 的**绝对均值 + CI**，把比值降级为派生量；配对分析（同任务同 seed）优于独立两样本。

2. **seed 不被端点尊重。**
   `live_config.seed=42` 且 `temperature=0`，但 C13③ 明确写「端点接受 `seed` 但不严格复现，3 次重复给的是经验区间而非确定性复算」。
   **后果**：不能声称「可复现」。3 次重复不是 3 个确定性样本，而是 3 个噪声样本。
   **对策**：把重复数当作**增大 n** 的手段（这正是 5.1 要求 `--repeat ≥ 11` 的原因），而不是当作「复现性证据」。

3. **`len(text)//4` 是 token 代理，不是真实 tokenizer。**
   代码里 `estimate_tokens(text) = max(1, len(text) // 4)`；C13⑤/C14④/C15⑤/C16⑤ 都登记了这条边界。
   **后果**：D/A 比值是**字符数比值**，不是真实 token 比值。对英文 ASCII 约 ±10% 误差，对含 CJK / 非 ASCII 的输出误差更大。
   **对策**：这正是 Tier 0 的用途——用 `SWE-rebench-openhands-trajectories` 里 67k 条真实观察文本，配真实 tokenizer 重算，量化代理误差。**在误差量化之前，不应把 0.8855 写成「观察 token 少 11.5%」。**

4. **单模型外推。**
   C13② 记录：只测 `sn-glm-5-3-flash`，且「该模型曾被端点下架又恢复，复测前必须先核对 `/v1/models`」。
   **后果**：任何「ACI 省 token」的结论只对该模型、该任务集、该轮成立。
   **对策**：**任何跨模型/跨端点的推广都必须先补测**。Tier 2 若用 Harbor，可以通过 `--model` 换模型，但那是另一条 pipeline，不能与本机 live 数字混算。

5. **成功判定中途变更（自造集特有）。**
   v1.2.0 把 `ts_fix_type_error` 从字面匹配改成跑 `tsc --noEmit`；v1.3.0 把 `python_noisy_install_summary` 的正则改成「单行 + 点名 `six`」（C13/C23/C24）。
   **后果**：**跨版本引用 live 数字必须声明版本**（C21④）。v1.2.0 与 v1.3.0 的成功率不可直接比较。
   **对策**：外部数据集的版本 tag 也必须冻结并写进 artifact。

6. **任务腐化（公开数据集特有）。**
   Terminal-Bench 官方公告明确记录 1.0 有任务腐化案例：`download-youtube` 因 YouTube 反爬策略变化而「今天能解、明天不能解」（[tbench.ai 公告](https://www.tbench.ai/news/announcement-2-0)）。2.0 因此做了大量人工 + LM 辅助验证。
   **后果**：外部集不是「一次接入永久有效」，它会随时间腐化。
   **对策**：按官方建议每次跑前先做 oracle 校验——`uv run harbor run -d terminal-bench/terminal-bench@latest -k 5 --agent oracle --n-concurrent 500 --env modal`（[Terminal-Bench README](https://github.com/harbor-framework/terminal-bench)），`-k 5` 即 5 次重复检测 flaky 任务。**oracle 不过的任务必须从分母里剔除，并记录剔除列表。**

7. **并行 tool call 与解析级联（若引入公开集的 ACI 面）。**
   `arXiv:2605.29676` 的实验显示：在多轮 agentic 循环里，一次 tool call 解析失败会**触发额外的推理轮次**，其自身的 thought/action/observation 载荷会**吃掉整个轨迹累积的节省**（TOON 在 Qwen3-32B thinking 下最终 token 变化为 **+8%**，TRON 为 **+11%**，即**反而变多**）；BFCL 的 `parallel` / `parallel_multiple` 类别准确率在多格式下**塌到接近 0**（[Notation Matters](https://arxiv.org/html/2605.29676v1)）。
   **后果**：观察面的压缩收益**不是单调的**，取决于工作负载形状与模型的解析成功率。
   **对策**：任何 ACI 改动都必须报告**解析失败率**与**重试轮次**，否则「省了 token」可能只是「把 token 花在了重试上」。

8. **Tier 2 的统计尺度与 Tier 1 完全不同。**
   Terminal-Bench 2.0（89 任务）在 p=0.85 时的二项标准误约 **3.8%**；TB 3.0（74）约 4.2%；TB 4.0（66）约 4.4%；而本仓库 10 任务在 p=0.85 时约 **11.3%**。
   **后果**：本仓库 10 任务的分辨率**只有 TB 的 1/3**——这是「本地集必须扩样本（靠重复）」的另一个理由，也是「Tier 2 不能与本仓库数字并列比较」的量化依据。
   Artificial Analysis 对 TB 4.0 的口径是 `pass@1 averaged over three repeats per task`（[AA TB 4.0](https://artificialanalysis.ai/evaluations/terminalbench-4-0)）——**外部基准自己也在用 3 次重复**，所以本仓库的 3 次不是异常，但对成功率主张仍不够（见 5.1）。

9. **许可证是合规项，不是可选项。**
   `nebius/SWE-rebench` 是 **CC BY 4.0**，但官方要求「请遵守每个实例所基于的具体仓库的许可证」，并提供逐实例 `license_name` 字段（[SWE-rebench 页面](https://huggingface.co/datasets/nebius/SWE-rebench)）。SWE-smith / SWE-bench 是 **MIT**；Terminal-Bench 源码仓库是 **Apache-2.0**。
   **后果**：把外部实例导入本仓库并重分发时，`license_name` 必须逐行保留；本仓库当前的 task schema **没有这个字段**。
   **对策**：若引入外部任务，task JSON 需要新增 `license` / `source_url` / `source_version` 三个溯源字段。

10. **公开集没有「观察 token」指标——不要把它伪装成有。**
    Artificial Analysis 在 TB 4.0 上确实报告 `Output Tokens per Task` 与 `Cost per Task`（[AA TB 4.0](https://artificialanalysis.ai/evaluations/terminalbench-4-0)），但那是**输出 token 与成本**，不是**观察（输入侧工具返回）token**；而且它不区分 A/D 条件。目前没有发现任何公开基准以 observation-token efficiency 为头条指标（SWE-agent 的 ACI 工作提出了 ACI 概念，但其论文的指标是 resolved rate，见 [SWE-agent ACI 文档](https://swe-agent.com/0.7/background/aci/) 与 [arXiv:2405.15793](https://arxiv.org/html/2405.15793v3)）。
    **后果**：**「用公开数据集替代 A/D 观察 token 比」这条路在现有公开资源下不存在**，这是本报告第 1 节结论的直接依据。

---

## 附：本报告的事实来源清单

所有数据集事实均来自本次实际抓取的页面：

- Terminal-Bench 任务格式与组件：<https://docs.harborframework.com/core-concepts/tasks/overview>
- Terminal-Bench 环境（Docker / Modal / Daytona / Windows os）：<https://docs.harborframework.com/core-concepts/tasks/environment>
- Harbor agent 能力表（Windows 仅 `nop` / `oracle`）：<https://docs.harborframework.com/core-concepts/agents/pre-integrated-agents>
- Terminal-Bench 2.0 = 89 任务（Harbor Hub）：<https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2/latest?tab=tasks>
- Terminal-Bench 2.0 论文摘要（89 tasks，CC BY 4.0 论文）：<https://arxiv.org/abs/2601.11868>
- Terminal-Bench 2.0 发布公告：<https://www.tbench.ai/news/announcement-2-0>
- Terminal-Bench 2.0 HF 镜像（Harbor 用法）：<https://huggingface.co/datasets/harborframework/terminal-bench-2.0>
- Terminal-Bench 3.0 HF 镜像（74 tasks，Apache-2.0）：<https://huggingface.co/datasets/harborframework/terminal-bench-3.0>
- Terminal-Bench 4.0 = 66 任务 + 3 次重复：<https://artificialanalysis.ai/evaluations/terminalbench-4-0>
- Terminal-Bench 1.0（~100 tasks beta，Apache-2.0，Docker+uv）：<https://github.com/harbor-framework/terminal-bench-1>
- Terminal-Bench 主仓库（oracle 5 次校验命令）：<https://github.com/harbor-framework/terminal-bench>
- Terminal-Bench Challenges（长时程、token 密集、单任务）：<https://www.tbench.ai/news/terminal-bench-challenges>
- Terminal-Bench Windows 任务的 QEMU-in-Docker 现状：<https://www.ivanbercovich.com/2026/writing-a-good-terminal-bench-task>
- SWE-bench（MIT、Docker、资源要求、Verified 500）：<https://github.com/SWE-bench/SWE-bench>
- SWE-bench 任务数（2,294 / 300 / 500）：<https://www.swebench.com/SWE-bench/faq/> 与 <https://www.swebench.com/lite.html>
- SWE-bench Verified 公告：<https://openai.com/index/introducing-swe-bench-verified/>
- SWE-smith（MIT、Docker 必需、不支持 Windows/macOS）：<https://github.com/SWE-bench/SWE-smith>
- SWE-smith 数据集（卡面 50,137 / viewer 59,136 行，数字不一致）：<https://huggingface.co/datasets/SWE-bench/SWE-smith>
- SWE-rebench（27,878 行，CC BY 4.0 + 逐实例 `license_name`，7,500 预构建镜像）：<https://huggingface.co/datasets/nebius/SWE-rebench>
- SWE-rebench-openhands-trajectories（67,074 行，字段表，平均 64.3 轮）：<https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories>
- 上述轨迹集许可证 `cc-by-4.0`（HF API `cardData.license`）：<https://huggingface.co/api/datasets/nebius/SWE-rebench-openhands-trajectories>
- LHTB = 46 任务：<https://github.com/zli12321/LHTB>
- ACI 概念（SWE-agent，指标为 resolved rate）：<https://swe-agent.com/0.7/background/aci/> 与 <https://arxiv.org/html/2405.15793v3>
- 多轮 agentic 循环中的 token 压缩与解析级联：<https://arxiv.org/html/2605.29676v1>

**本仓库内部依据**：`bench/aci/tasks/manifest.json`、`bench/aci/tasks/*.json`、`bench/aci/runners/live_agent_loop.py`、`bench/aci/results/latest_live.json`、`docs/claims-and-evidence.md`、`docs/v1.1-freeze.md`。

**明确标注为「未核实」的项**：Terminal-Bench 1.0 的精确任务数与 Windows 支持；Terminal-Bench 4.0 与 Challenges 的许可证；LHTB 的许可证与 Windows 支持；SWE-smith 50,137 / 52k / 59,136 三个数字的口径差异；本仓库 token 指标的配对差 SD（artifact 未记录）。
