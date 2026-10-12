# VerseShell 修复与 live 闭环交接单

日期：2026-09-29。仓库：C:\Users\27933\Desktop\verseshell\verseshell。

当前结论：代码与离线统计已有一批修复，但全部缺陷尚未闭环，尚不具备宣称 ACI 总体优越或全部验收通过的证据。本文件记录当前状态、未完成工作、live 时机及数据解释；不是一次新测量报告。本次编写只核对文件、执行离线复算，没有调用模型端点或跑 live。

## 1. 接手规则与证据入口

按 docs/repair-backlog.json 的 11 个 id 串行处理；原说明见 docs/repair-handoff-2026-09-29.md，最新工作状态见 audit-r12-scratch/repair-progress.md。原交接单及 backlog 仍残留旧诊断和旧数字，不能将其所有文字当作已经复核的事实。以原始文件、具体计算口径和修复回执核对冲突，不覆盖历史测量。

修复方负责代码、配置、离线复现、测试和负对照；测试方负责端点探针、模型生成、任务冻结、live、校准及测量验收。修复方不修改 bench/aci/tasks/*.json、bench/aci/fixtures/**、bench/aci/results/latest_live.json，不提升候选，不执行 freeze_task_set.py --version，不降低 C14=0.15、C16=0.10 或行排除门槛，不删弱检查。观测面、系统提示或工具描述改变，必须明确写“需要重跑 live”。

每项回执继续使用：id；症状及命令输出；已确认根因/假设；文件与关键行；验证及负对照；观测面是否改变；未完成部分；对旧报告的反驳。旧回执集中在 audit-r12-scratch/repair-<id>-2026-09-29/receipt.md；补充项路径见下文。

## 2. 当前可核对基线

最近完成的完整验收记录：eval/evidence.json，generated_at=2026-09-29T11:52:44.040268+00:00；以及 audit-r12-scratch/repair-p2-4-2026-09-29/receipt.md 和验证日志。本次写文档没有重新执行耗时完整测试。

| 项目 | 最近已记录结果 | 含义 |
|---|---|---|
| Python 回归 | 61/61 通过 | 本地代码回归 |
| MSVC cargo | 287 passed / 0 failed / 1 ignored | 不是 live 验收 |
| 完整 claim_gate | exit 1，28/31 PASS | 红项 C12、C14、C16；不能写成原基线29/31 |
| 独立统计复算 | 34/34 | 一致性证据，不证明研究设计有效 |
| C14 | 0.0422，FAIL | 门槛0.15不变 |
| C16 | 0.0768，FAIL | 门槛0.10不变 |
| C34 | 0.5654，PASS | 命名信封开销口径，不能替代前两项通过 |

C12 当前列出六份陈旧产物：bench/aci/results/latest.json、bench/aci/results/latest_live.json、eval/jev_obs_report.json、eval/cross_shell.json、eval/task_design_audit.json、eval/task_admissibility.json。必须逐份确认生成者、依赖和测量权限后真正重建，不能只更新 fingerprint 或时间戳。当前18步 refresh 链并不包含所有这些产物的生产入口，因此“整链 exit 0”本身不保证 C12 PASS；P1-2整链验收仍欠缺。

原交接单把 --skip-tests 的期望也写成29/31不准确：该选项会使 C6/C7/C8 标为 STALE，不能与完整运行 PASS 数直接比较。所有命令都记录 exit code、红项集合及 PASS 数；exit 1是门禁判定，不能不看内容就称崩溃，也不能忽略。

工具链已在 D:\dev_c++ 找到；vcvars64.bat 位于 VC\Auxiliary\Build，MSVC14.50.35717。vswhere 未发现安装不等于工具链不存在。Python3.10；在配置好 MSVC 环境的终端运行 cargo。已有 supervisor 在 audit-r12-scratch/repair-p2-4-2026-09-29/ 下。长进程应落日志和退出状态，观察超时不等于测试失败，不要因此重复启动。

## 3. 11项 backlog 的交接状态

| id | 已完成与确认的问题 | 尚欠缺及下一步 |
|---|---|---|
| P0-1 | 已复算并纠正首轮截断诊断；没有直接缩提示 | 根因不确定；逐轮 reasoning/finish_reason 诊断、预注册因果实验、据实验选择缓解方案及新live均未完成 |
| P0-2 | task_generate_v2/run_task_plan 显式作者模型、家族政策、固定作者、不跨模型fallback、plan SHA及续跑隔离；已有离线验证和文档边界 | 现25任务无法事后获得独立性；需要新异源留出集及同源/异源D/A对照。人工家族声明不能证明供应商隐藏路由 |
| P0-3 | 保留300秒限制；新增budget_sensitivity及刷新/C12接入、负对照 | 未修改/重测端点，超时未消除；若改流式或proxy必须先测再更新约束 |
| P1-1 | merge共享row_class、partial、端点success=null及raw_success保留；C35逐行定位受影响比较，严格/宽松路径及真实负对照已验 | partial只可用于诊断，不是可主张的完整研究；新live下仍须验证链路 |
| P1-2 | 补mock、three-arm、cross-shell并放在token校准之前；当前18步；选项错误和子进程失败传播有回归验证 | 完整刷新与C12 PASS未验；全链包含测量，由测试方执行，链外产物也须补齐 |
| P1-3 | splice支持ACI凭据及明确优先级、逐格原子保存、原预算/seed重放、拒绝缺配置及merged输入；8项离线测试 | 尚无修复后的真实端点运行证据；不要把模型任务失败重试至成功 |
| P2-1 | 删除摘要归因时遗漏顶层hash已修；129匹配/4排除离线重放；C34恢复 | 原C14/C16仍FAIL；采用允许的保留FAIL、限制声明范围分支，不称产品指标达标 |
| P2-2 | task_design_audit区分标签/实测/未知；配额分母与难度余量解释已修，已接入刷新/C12 | 盲设计、新冻结集和预注册A基线区间的实测缺失；本会话看过结果，不能冒充盲设计者 |
| P2-3 | Rust --no-fail-fast；TS node:test；12–18用例和有意义长载荷；二进制UTF-8读取；原五候选副本A8 0/5→5/5、GOLDEN5/5 | 未改或提升原候选；JS还缺variants；并非完整A1–A8准入。新生成和正式live未验 |
| P2-4 | repeated_run_uncertainty实现完整重复网格校验、run×task bootstrap及方差分量；14项测试；ITT和精确阈值修正；旧seed伪重复负对照exit2 | ≥3次同配置完整独立采集缺失；新方法未自动接管C25/C28/C37批准，正式统计接线/独立验收仍待完成 |
| P2-5 | 仅调查，尚未修复；确认token桶混用、错误不变量、过度下界解释及声明标签不全 | 下一条本地修复，详见第5节；不得把已发现写成已修复 |

P0-3派生判定按 artifact/model/condition/task 分组，使用整数条件 truncated_rows×10≥rows，不按成功率筛任务，也不同于比较级“排除率>10%”规则。已复算210组：with为12个敏感任务/13组，without为4个任务/6组；不用于事后删除不利任务。

P2-3同批副本结果为 Rust 277→1961、391→2104、442→1933、590→2325；JS 394→3537 proxy token，18例中7失败。原断言载荷未变，说明旧“只换报告机制一定不够”的概括不成立；本地探针不能替代未来模型生成有效性。

## 4. 补充缺陷与必须纠正的旧叙述

- SUP-HOSTNAME：src/builtins.rs在COMPUTERNAME缺失/空时返回null，已补sysinfo主机名回退和Windows回归。产品可见输出改变，**需要重跑 live**；不能把旧live指纹改成新代码来消除此要求。回执目录 repair-c7-hostname-2026-09-29。
- SUP-C7-EXIT：曾在process-lifecycle测试附近非零退出，记录246项通过但没有断言失败；旧门禁未保存exit/stderr。现已增加诊断，后续独立cargo及完整门禁通过，原退出根因仍不确定，不称已修复。
- SUP-MOCK-UTF8：command_exit_0只需要返回码却用本机文本编码解码，产生GBK线程异常。已复用二进制run_bounded，保留超时/非零/缺程序失败及进程树清理；真实mock解码错误0。与SUP-C7-EXIT不得混为一谈。
- SUP-REFRESH-OPTIONS：未知/空--only、矛盾选项和缺输入可产生假完成；已提前拒绝，allow-missing实际执行且不吞子进程失败，输出明确仅选中步骤完成。
- P2-4额外发现：旧ITT把被排除但最终成功的行当成功；比例及方向先舍入再判门槛。已修为保守ITT及精确计数/Fraction，原始success未动。
- 历史已修列表还记有run_task_plan槽位交集、Rust模块路径/Cargo名称与variant目录、freeze归类、C34新鲜度、policy_blocked与impossible一致性、cross-shell Holm缺scoring triple等。它们是既有记录，不是本次新交付；接手时保留回归，不再次声称首次修复。
- 研究规模应写：with/without各35任务×3条件×3seed=315格，共630格；每条件每配置105格。“格”是任务运行，可能含多次模型请求，不等于630次API调用。
- 工作进度文件中的“目标active”是未完成业务状态；最近工具查询没有active goal对象，不应混为一谈。

P0-1本次离线复算再次得到：D有15/105 completion截断，其中9格首轮零工具、6格后续截断；15格中2格最终成功。9格首轮completion均16384，耗时187760–215622ms。A的completion截断为3格，但统一row_policy的cap_truncated为4格；不同字段不能互换。旧“15格首轮、全部失败、字段签名完全一致”不成立。

当前llm_prompt_tokens是多轮累计输入usage，含重复历史，不是系统提示/schema单次体积；不能从D/A均值比推出“D系统提示大26%”。跨任务规模存在截断也不足以排除任务形态/难度作用。等长实验的单次结果不能直接二分为“长度原因/框架原因”；截断/填充还可能改变信息和语义，需要对照与重复。

## 5. P2-5剩余本地工作：先把计量口径修清楚

| 字段/指标 | 实际计量对象 | 不能替代什么 |
|---|---|---|
| observation_tokens | 交付观察文本的max(1,len(text)//4)代理累计 | 不是模型输入usage，也不是费用 |
| llm_prompt_tokens | 每次请求的端点输入usage累计，含提示、schema、重发历史 | 不是系统提示长度 |
| llm_completion_tokens | 端点返回的输出usage，具体reasoning计费边界须确认 | 不自动等于可见回答字数 |
| usage总量 | 输入+输出usage | 未含价格/缓存规则时不能称金额成本 |
| cl100k_base replay | 同一抽样观察文本的独立BPE计数 | 不是被测模型专属tokenizer，也不是整轮usage |
| cost_per_success/CPST | 必须查实际实现；现有相关字段使用观察代理/成功数 | 名字中的cost不等于货币 |

待改位置包括tools/live_uncertainty.py的real_tokenizer_note、tools/three_arm_report.py的usage_note、tools/acceptance_power.py相关注释及字段标签、docs/acceptance-criteria.md §4.2和docs/claims-and-evidence.md逐条token声明。重点复核C1/C9/C13–C17/C19–C21/C25–C28/C30/C31/C34，不漏各自分母、样本、配对范围和估计量。C9还可能用ceil(len/4)/字节口径，不应机械贴同一标签。

tools/token_proxy_calibration.py的real_tokens_never_exceed_chars不变量错误：Unicode字符可拆为多个BPE token；现有shape_panel已经有CJK 278字符、284 token的反例。应为完整文本记录UTF-8字节量并检查适用的byte-level BPE边界，不能拿截短缓存文本算完整样本字节数。当前说明“proxy是这些shape的下界”也过强，同类样本已有高估和低估；C27 notes的旧约33%/下界文字应同步核对，不改数值门槛。

建议先加Unicode反例、同桶配对、缺失文本/usage和元数据回归，再修解释与结构化计量标签。若涉及门禁逻辑必须有负对照。ratio_bootstrap可按已知kind标注，acceptance_power的泛化acceptance_ratio不能自动猜测口径，应在具体输出字段标注。只重建受影响的离线派生报告；不要执行默认会调用端点的全量校准，更不要将旧缓存usage重新盖章为新测量。

校准当前样本：60份，52低估、7高估、1相等；real/proxy均值1.2442、中位数1.2150。ASCII47份均值1.2505，其他13份1.2213。同一30个抽样观察配对：real A12859/D20269，D/A=1.5763；proxy A11822/D16884，D/A=1.4282。两者聚合方向一致，2/30单元方向不一致。这不是35任务整轮数据，不能拿它与全轮比值做同桶方向判断；也不能将所有比值乘以1.2442。校准ratio_check还保留published_proxy_ratio=0.8855，其来源/对应cohort需核对，不要当当前整轮基线引用。

## 6. 我对现有数据的判断

当前with配置普通全部已评分行的比值，来自eval/live_uncertainty.json arms[0].ratio_bootstrap：

| D/A指标 | 点估计 | 当前task bootstrap CI95 |
|---|---:|---|
| 工具调用数 | 0.8035 | [0.6678,0.9691] |
| 观察文本proxy | 0.6377 | [0.5169,0.7820] |
| 端点usage总量 | 1.3158 | [1.0169,1.7884] |
| 输入usage | 1.2595 | [0.9580,1.7449] |
| 输出usage | 1.5832 | [0.9716,2.9661] |

这些是描述性数值，未纳入完整独立重跑方差，且D排除率超门槛，不能据此批准比较主张。旧交接单0.6347/1.3583/1.894不是当前这些字段的数值，应核对历史版本，不能拼接新旧点估计和区间。

| with配置条件 | 普通评分成功率 | 保守ITT | analysable | cap排除 |
|---|---:|---:|---:|---:|
| A | 95/105=0.9048 | 0.9048 | 95/101=0.9406 | 4/105 |
| A′ | 92/105=0.8762 | 0.8762 | 92/105=0.8762 | 0/105 |
| D | 88/105=0.8381 | 86/105=0.8190 | 86/90=0.9556 | 15/105 |

D在保守ITT较差、条件可分析集稍高可以同时成立：筛选改变了估计对象，不能据此证明预算是唯一原因。端点错误是未知结果，原始success不能直接填失败；保守ITT把排除行计失败是另一个明确的敏感性口径。

我的判断是：接口确实有减少观察文本和命名包装开销的局部机制证据；当前研究不足以证明端到端总token或成功率优势。观察更短与总usage更多并不矛盾，累计历史和completion可能抵消收益，具体贡献仍待逐轮诊断。我们也没有充分依据将当前结果推广为ACI必然更差。

35个小型合成任务、单一模型/端点/配置、25个任务的同源生成标签、任务难度天花板、独立采集重复缺失都限制外推。标签记录25/25作者同被测模型，但历史fallback进一步削弱真实作者可核实性；不是证明任务都偏向某条件，更不能说有利结果在逻辑上无法证伪。

7个任务已确认large、25个覆盖、10个手写未知，不能把7/35称为全量测得的比例。若仅已有7个确认且未知不重分类，追加x个确认large需(7+x)/(35+x)≥1/3，即x≥7；补5个仅12/40。观察量大不等于推理难；A观测成功95/105给正向提升余量0.095238，小于0.15，但不排除更小/负向效应，也不限定未来基线。

不同seed的差异是描述性波动，不识别独立跑间方差，不是数学下界；单轮区间显著与否也受配对方法、聚类、重复和多重比较影响。新run×task方法的合成测试只证明部分实现性质；三次独立重复仍只有2个run自由度，不保证覆盖率充分校准。

## 7. live节奏：按证据阶段推进，不按每天重跑

| 阶段 | 启动条件与负责人 | 必交产物/退出条件 |
|---|---|---|
| L0 本地收尾 | 修复方先完成P2-5、诊断代码、回归与保护面检查 | 精确变更清单、离线正/负对照、缺失项；不调用端点 |
| L1 端点与因果探针 | 测试方确认端点/模型/超时能力，并在看新结果前冻结实验计划 | P0-1控制实验及逐轮记录；P0-3约束复测（若改端点）；实验输出独立存放 |
| L2 据证据修产品 | L1完成后修复方分析因果证据，预注册缓解策略再改 | 模型可见变更声明、本地验收；需要重跑live，不与旧配置混合 |
| L3 数据集独立设计 | 未接触任务级live结果的作者设计；测试方负责生成及准入 | 同源/异源来源、完整A1–A8、variants、large分母和难度目标；冻结清单及哈希 |
| L4 正式候选锁定 | L2/L3及所有本地前置通过，配置和指标方案固定 | code/tree/toolchain/task/prompt/schema/config指纹；正式study manifest |
| L5 完整采集 | 测试方按锁定配置采集A/A′/D及with/without | 每完整重复保留原始格、配置、时间/顺序、usage、finish_reason、失败和checkpoint |
| L6 重复与统计 | 同任务/seed集合/预算等配置至少3次完整独立采集 | 重复研究manifest、run×task区间、两种row-policy、独立统计验证 |
| L7 证据与验收 | 输入固定后由测试方运行完整派生链及链外缺项 | C12真正新鲜、全门禁、主张资格、负对照和最终逐项回执 |

L1先以预注册小规模探针查可行性，再按预定样本/重复数完成诊断；不要每个参数试一次便宣布因果。比较D原版、长度匹配版与必要框架对照，明确字符还是token长度，固定工具权限/schema/任务/预算，对不可保持不变的部分披露。平衡条件执行顺序，避免端点时变与条件混杂。记录首轮及逐轮usage、finish_reason、可获得的reasoning长度/字段；未提供的reasoning不能据token量脑补。实验停止/重试规则须预先确定；实验格不能混入正式验收。

L3可以在严格盲信息边界下独立进行，但正式L5需等待候选产品和新任务集都锁定。如果先用已看过的旧任务验证机制，只作为开发证据。新的难度设计不能按本轮失败任务挑样来制造低A基线；如需pilot，预先分开开发集与封存确认集并固定选择规则，不能在确认集上反复挑到目标区间。

正式节奏建议：先完成1次完整采集做结构/端点健康核验，再继续预注册的另外至少2次完整采集；不得依据第一轮效果好坏决定是否继续。若一个完整重复覆盖当前规模with+without则为630任务运行，3次为1890格（新任务数变化时重算）。不是API调用数或承诺时长；原约13小时只能视作历史参考，测试方按端点容量安排。

原seed42/43/44三个文件只是一次完整seed网格的分片，不是三次完整独立重复。不可复制文件充数；不可用不同预算/提示/任务集合拼成重复。若正式采集中途改模型可见面或关键配置，应保留旧批次但另起研究版本，不能只补D的不利格后与旧A比较。

端点失败按预注册规则补跑并保留全部尝试、原因和被替换记录；逐格checkpoint避免丢进度。splice输入是原始run文件，保持原seed/预算，不能对merged或缺重放配置的数据强行补。真实模型解题失败要如实保留。宽松合并允许保留partial诊断，但partial不进入肯定性验收。

C14/C16若沿用保留FAIL的窄声明路径，最终交付须明确它们仍不成立，不能把所有主张标绿；若选择改产品追求达标，则另行预注册、实现、离线重放及live验证。不要求为了PASS数修改阈值。

## 8. 可执行验证及闭环收尾清单

在仓库根目录、已配置MSVC环境运行以下本地命令；它们不等于live：

~~~powershell
python -m unittest discover -s tests -p test_*.py
python tests/test_repeated_run_uncertainty.py -v
python tools/claim_gate.py
python tools/statistics_crosscheck.py --out audit-r12-scratch/handoff-crosscheck.json
python tools/run_variance.py --out audit-r12-scratch/handoff-run-variance.json
git diff --stat -- bench/aci/tasks bench/aci/fixtures bench/aci/results/latest_live.json
~~~

预期失败负对照（不能改称真实研究）：

~~~powershell
python tools/repeated_run_uncertainty.py --manifest audit-r12-scratch/repair-p2-4-2026-09-29/invalid-seed-study.json --out audit-r12-scratch/handoff-invalid-study.json
~~~

已记录exit2、缺210格；其他负对照见各receipt：P1-1人为API错误应严格merge exit2、宽松partial exit0而C35 FAIL并定位行；P0-3源变更C12应红；P2-4缺格/重复/配置混用必须拒绝。

以下仅由测试方在正确输入就绪后执行，不能作为修复方“离线重刷”误跑：

~~~powershell
python tools/refresh_live_artifacts.py
python tools/repeated_run_uncertainty.py --manifest <真实完整study.json> --out <重复研究报告.json>
python tools/claim_gate.py
~~~

refresh含cross-shell计时和token校准端点调用，且仍需按C12逐项补链外产物；正式live具体参数以tools/live_round.py的当前CLI和锁定study为准，不复制带临时配置的历史命令。本文件不代替预注册实验方案。

每轮收尾检查：全部原始格可追溯；无缺格/重复/配置混用；失败与重试未选择性丢弃；两种row-policy及预算敏感诊断齐全；重复区间与点估计同数据同口径；confirmatory/exploratory及多重比较明确；新方法的独立复算与门禁接线完成；所有受影响证据真正刷新；完整测试无新增非预期红项；C14/C16处置明确；逐项回执列出仍未满足的条件。遇到修复需求返回对应阶段，保留旧数据版本，不移动门槛。

保护面特别说明：本次重新逐字节核对，repair-c7-hostname-2026-09-29/protected-files.json中的160个基线文件均未变、无删除。git diff仍显示入场时已存在的6文件差异，25170插入/2292删除，因此不能声称要求的git diff为空，也不能清除这些用户已有改动。递归磁盘扫描另见两个Git忽略的新增.pyc：

- bench/aci/fixtures/python_edit_and_retest/tests/__pycache__/test_greet.cpython-310-pytest-6.2.5.pyc
- bench/aci/fixtures/python_fix_pytest_fail/tests/__pycache__/test_math.cpython-310-pytest-6.2.5.pyc

本次未删除或修改它们。其具体生成时机未确定；旧“零新增”只适用于当时受保护清单口径，不能外推为整个目录。后续验证在临时副本执行并控制Python字节码及测试缓存写入；测试方核对指纹枚举规则，不能仅凭Git忽略就断言无影响。保护面检查要同时报告基线哈希、Git差异及未跟踪/忽略文件。

交接后的第一步是P2-5本地修复，同时把L1所需诊断与预注册实验准备成可审阅输入；随后交测试方执行L1。只有代码回执、真实测量和独立验收都满足对应条目的要求，才逐项关闭。当前P0-1、P2-5及多项外部实测仍开放；整体验收尚未完成。
