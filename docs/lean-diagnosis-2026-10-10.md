# 瘦诊断运行：用低成本定位问题

日期：2026-10-10。全量 `step5p-formal-20261010-r1` 在 170 行后被操作者暂停，原因是三份 1050 格正式采集的成本/周期不适合当前“定位问题”的目标。已完成的 partial checkpoint 全部保留，主库没有继续跑 r1/r2/r3。

## 简化工具

新增 `tools/lean_diagnose.py`，提供两条路径。

### 1. 只分析已有 checkpoint（不调用模型）

```powershell
python -X utf8 tools/lean_diagnose.py `
  --from-jsonl bench/aci/results/step5p-formal-20261010-r1/with_seed42.json.rows.jsonl `
  --max-turns 80 --max-tokens 16384 `
  --out-dir D:/VerseShellLive/freeze-live-20261010-03/lean-partial-r1
```

### 2. 只跑 9 格诊断矩阵

默认任务为三个历史问题样本：

- `node_envconfig_validate_dd681123`
- `js_leaderboard_rank_b1603acf`
- `python_csvlite_parse_80d158b2`

默认矩阵：3 任务 × 2 关键条件（raw_shell、verseshell_aci）× 1 变体 × seed 42 = **6 格**，不做 30/5/3 正式研究门槛。若只查 raw-shell 循环，可再加 `--conditions raw_shell`，只跑 3 格。

```powershell
python -X utf8 tools/lean_diagnose.py `
  --tag step5p-lean-YYYYMMDD-HHMMSS `
  --env-file D:/VerseShellLive/secrets/stepfun-step5p-20261010.env `
  --max-turns 24 --max-tokens 16384
```

工具会自动运行 `live_round.py`，然后再生成 `lean-diagnosis/diagnosis.json` 和 `diagnosis.md`。

## 已暂停的 r1 partial 结果

`D:/VerseShellLive/freeze-live-20261010-03/lean-partial-r1/diagnosis.json`

- 有效行：170；写进程被杀时产生的半行：1（显式记为 `malformed_rows`）
- success：160 true / 10 false
- stop：161 task_complete、3 turn_limit、5 repeat_call_limit、1 completion_limit
- endpoint failure：0
- `completion_truncated_turns`：1
- `result.query`：13 次，13 次通过，全部为 canonical `result://sha256/<64hex>`

失败集中在 raw_shell 一侧：

- `python_batch_splitter_05613a34 / raw_shell`：turn_limit 80
- `py_region_top_seller_7f713e22 / raw_shell_coached`：turn_limit 80
- `node_envconfig_validate_dd681123 / raw_shell`：turn_limit 80
- `python_config_reader_686653a1 / raw_shell`：repeat_call_limit
- `python_parse_orders_708606f4 / raw_shell`：repeat_call_limit
- `ts_package_script_fail / raw_shell_coached`：repeat_call_limit
- `python_exception_mislabel_0816896a / raw_shell_coached`：repeat_call_limit
- `python_exception_mislabel_0816896a / raw_shell`：completion_limit
- `python_csvlite_parse_80d158b2 / raw_shell`：repeat_call_limit

### 零成本根因命中表

| 停止形态 | 任务/条件 | 最长连续相同调用 | 最高频调用 |
|---|---|---:|---|
| repeat_call_limit | `python_config_reader_686653a1 / raw_shell` | 3 | 读取自身文件末尾 repr |
| repeat_call_limit | `python_parse_orders_708606f4 / raw_shell` | 3 | 读取 `orders.py` 前 200 字节 |
| repeat_call_limit | `ts_package_script_fail / raw_shell_coached` | 3 | `npm test` |
| repeat_call_limit | `python_exception_mislabel_0816896a / raw_shell_coached` | 3 | 多行重定向 + `type ml.txt` |
| repeat_call_limit | `python_csvlite_parse_80d158b2 / raw_shell` | 3 | `echo one\necho two` |
| turn_limit 80 | `python_batch_splitter_05613a34 / raw_shell` | 1 | 80 个不同工具调用，持续 thrash |
| turn_limit 80 | `py_region_top_seller_7f713e22 / raw_shell_coached` | 1 | 重复检查 `copy1.py` 的 `LEN/COMMENT` |
| turn_limit 80 | `node_envconfig_validate_dd681123 / raw_shell` | 1 | 反复 `type envConfig.mjs` 并继续动作 |
| completion_limit | `python_exception_mislabel_0816896a / raw_shell` | 1 | 40 回合后一次 completion 截断 |

初步定位：**当前异常主要是 raw-shell 侧命令构造/推理循环，不是端点失败，也不是“测试通过后不停止”**。零成本轨迹扫描显示：170 个有效 cell 中 59 个成功 cell 出现过本地通过标记且后续继续调用，但 9 个失败 cell **全部没有出现过本地通过标记**。因此失败发生在到达可验证通过状态之前，stop-after-success 护栏不能修复它们。

这不是完整覆盖：checkpoint 只到 seed 42 的一部分，尚未合并成 `latest_live.json`，不能用于正式成功率、成本或跨臂结论。

## 3 格 raw-shell 低成本复现（2026-10-10 21:08）

运行：`step5p-lean-raw-20261010-r1`，3 任务 × raw_shell × baseline × seed 42，`max_turns=24`。

- `js_leaderboard_rank_b1603acf`：task_complete，10 tools / 10 turns，通过。
- `node_envconfig_validate_dd681123`：repeat_call_limit，15 turns / 17 tools；同一长诊断命令最高重复 4 次，且从未出现本地通过标记。
- `python_csvlite_parse_80d158b2`：turn_limit，24 turns / 39 tools；从未出现本地通过标记。
- endpoint failure 0、completion truncation 0。

这确认了低成本复现路径：3 格足以复现 2/3 的失败形态。当前最有价值的修复方向不是继续扩展样本，而是针对 raw-shell 的命令构造和编辑闭环，尤其是“反复检查某段源码”和“命令字符串/引号构造失败后继续调用”。

## 本地命令回放器（无模型呼叫）

新增 `tools/replay_failure_commands.py`：从已存 trajectory 重建 pristine workspace，按序重放 raw-shell 命令，最后执行真实 `check_success`。默认 dry-run，只有 `--execute` 才运行。

对两个失败 cell 的本地回放结果：

- `node_envconfig_validate_dd681123 / raw_shell`：最终 `check_success=False`（`node check.mjs` exit 1）。模型在测试失败后反复读取/检查 `envConfig.mjs`，没有形成有效修改闭环。
- `python_csvlite_parse_80d158b2 / raw_shell`：最终 `check_success=False`（`python -m pytest` exit 1）。多次 `python -c ...` 命令因 cmd 引号/重定向出错（`此时不应有 >`、找不到文件），之后进入大量字符串/换行实验，未完成 CSV 解析器修复。
- 两次回放都复现了原失败，且 endpoint failure=0、completion truncation=0。

结论进一步收紧：当前问题是 **raw-shell 的命令构造/编辑闭环失败**，不是端点故障，也不是“测试通过后不停止”。

## 下一步的定位策略

- 不再重跑全量 3×1050，先针对上表中的重复/预算问题做定向复现。
- 若需要新数据，用 9 格 lean 矩阵；如果只是分析已有异常，优先用 `--from-jsonl`，不产生 API 成本。
- 正式三次完整重复留到问题定位收敛、且发布方确认时间/费用后再开跑。

## 3 格 shell_guided 低成本复验（2026-10-10 23:11）

运行：`step5p-lean-guided-dryrun`，3 任务 × raw_shell × `shell_guided` × seed 42，`max_turns=24`、`repeat_call_limit=3`。

- `node_envconfig_validate_dd681123`：task_complete，13 tools / 13 turns，通过（baseline 同任务曾 repeat_call_limit）。
- `js_leaderboard_rank_b1603acf`：task_complete，6 tools / 6 turns，通过（对照）。
- `python_csvlite_parse_80d158b2`：task_complete，16 tools / 12 turns，通过（baseline 同任务曾 repeat_call_limit）。
- endpoint failure 0、completion truncation 0、turn_capped 0、repeat_capped 0。

同一批 3 任务在 baseline raw-shell lean 运行（`step5p-lean-raw-20261010-r1`）里只有 `js_leaderboard` 通过；加入 `shell_guided` 提示后 3/3 通过，且两格都落回 `task_complete`。这与"失败主因是 cmd 命令构造/编辑闭环"的定位一致，是**诊断性对照**，不是正式重复成功率或跨臂结论。

证据：

- `bench/aci/results/step5p-lean-guided-dryrun/latest_live.json`
- `bench/aci/results/step5p-lean-guided-dryrun/with_seed42.json.rows.jsonl`
- `D:/VerseShellLive/freeze-live-20261010-03/lean-guided-r1/diagnosis.json`
- `D:/VerseShellLive/freeze-live-20261010-03/lean-guided-r1/diagnosis.md`
- `D:/VerseShellLive/freeze-live-20261010-03/step5p-lean-guided-r1.stdout.log`
