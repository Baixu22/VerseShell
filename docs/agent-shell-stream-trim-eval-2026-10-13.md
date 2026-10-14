# 流元数据裁剪：可行性评估与决定（2026-10-13）

承接 l4-slim-r3 的 POSITIVE：D 成功率已达标，但效率仍差 raw（3491 vs 1892 obs tokens）。
本页记录“再砍流元数据”这一步的评估与决定。

## 一、先做离线模拟（不烧预算）

用 l4-slim-r3 的 60 格真实 trace，对 D 的观察信封做逐级裁剪后重算 observation token：

| 变体 | 裁剪内容 | D tokens | A-prime tokens | D/Ap ratio |
|---|---|---:|---:|---:|
| base | 无 | 3492 | 1916 | 1.82 |
| slim | 去 schema/id/op、meta 只留 2 字段、流字段保 6 个 | 2650 | 1840 | 1.44 |
| integrated | 再折叠空 stderr、流只留 summary/text/artifact | 2396 | 1840 | 1.30 |
| minimal | 再去掉整个 meta | 2275 | 1817 | 1.25 |

## 二、结论：达不到效率门槛，不做无谓长跑

handoff 效率门槛是 D obs tokens <= A-prime x 0.8。
即使极端裁剪（去掉全部信封噪声），ratio 仍为 1.25，离 0.8 很远。

原因是 token 大头不在信封：

- 内容文本本身约 625 tokens/call
- 调用数 D 215 次 vs A-prime 187 次
- 信封（含流元数据）裁剪到底也只省约 35%

因此不再为效率门槛重跑 L4（会烧 3 小时且注定不达标）。
要真正拿到效率门槛，需要更少的调用与更紧的内容预算，那要动 provider 契约，属单独的一步。

## 三、本次实际完成的事

1. 重新确认 l4-slim-r3 的三处修复在源码中完好：不回显 argv/cwd；微型省略不发产物句柄（MATERIAL_OMISSION_BYTES=64）；空输出用一行 no output。
2. 重建并校验 Linux ae 二进制，可复现、行为一致：heredoc ok；小输出无句柄无 argv 回显；大输出 status=truncated 且保留产物句柄。

## 四、过程中的一次真实事故（必须记录）

- 尝试用脚本改写 src/operation.rs 时，一次 shell 误用把该文件截断为 0 字节。
- 该文件承载 l4-slim-r3 的三处修复且尚未提交。
- 处置：从 git HEAD 恢复，逐条重放三处修复，用 git diff 逐行核对确认与事故前一致。
- 校验：Rust 构建通过、process_command 单测 6/6、Python 契约 5/5、microVM 行为验证通过。
- 教训：改源码用一次性结构化脚本加 assert 锚点，不要用 shell 内联多行改写。

## 五、当前状态

- src/operation.rs：三处修复已恢复且经 diff 核对（+11/-10 行）。
- src/process_command.rs：换行守卫修复保留（+13/-1 行）。
- 无残留 sandbox；未提交、未合并、未推送；未改 Task Forest。
- Linux ae 二进制：f49abeff（可复现自当前源码）。

## 六、下一步选项（需选择）

1. 接受现状：POSITIVE 已达成（成功率门槛），效率劣势记录在案，不再追求 -20%。
2. 改 provider 契约（按 profile 收紧内容预算等）以争取效率门槛，但会改变 arm 契约，必须重跑并另起轮次。
3. 回到 L1-L3，看 D 在简单/中等档的效率表现是否也偏离。
