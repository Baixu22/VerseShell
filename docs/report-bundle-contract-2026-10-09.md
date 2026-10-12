# TF-0133：报告清单漂移修复

日期：2026-10-09（Asia/Shanghai）。范围仅为离线报告生成与收尾契约，不是新的模型测量或正式产品验收。

## 根因与最小修复

`refresh_collection` 已生成 5 份 JSON 和 2 份 Markdown，但 `live_control.finalize` 仍只认可旧的 3 份 JSON。原测试 reporter 同样手写旧三项清单，未真正接入生成器：因此既漏掉了完整新报告被拒绝，也漏掉了旧不完整清单仍可被接受。

- 在 `tools/refresh_live_artifacts.py` 定义唯一的 `COLLECTION_REPORT_FILES`，生成器和控制器共同消费。
- 精确核验七项文件及其 SHA-256，包含成本归因、异常审计的 Markdown；不再用 `glob` 将任意附加 JSON 纳入已验证报告。
- `tests/test_live_control.py` 保留独立写明的预期清单；真实本机子进程调用真实生成函数，仅分析步骤的 runner 使用离线文件 fixture。覆盖两个变体、缺文件、缺清单项、旧三项清单、七项逐一篡改、额外声明、重试保留旧报告。

旧清单不会被追认为完整；需要使用修复后的生成器在新的 report-only 尝试目录重做报告，不覆盖历史产物。

## 验证

| 验证 | 结果 | 退出码 |
|---|---|---:|
| 新回归加载本会话修改前的两个生产模块 | 15 项中 7 条失败，证实完整报告拒绝及旧清单误接受 | 1 |
| 修复后完整 Python 回归（含 15 项控制器测试） | 370/370，无跳过，167.224 秒 | 0 |

首轮全量验证将 `CARGO_TARGET_DIR` 指向新空目录，造成 AE 缺失、相关失败与跳过；原日志保留，不能作为源码回归结论。最终验证复制已有候选 AE 到本轮 D 盘测试目录，配置 `ACI_TEST_AE`，使用 `D:/VerseShellLive/.venv/Scripts/python.exe`。解释器、二进制和本次三个源码/测试文件的运行前后摘要一致。此轮没有重建 Rust，不能声称验证了新的 Rust 构建。

复现：

```powershell
. 'D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/environment.ps1'
& 'D:/VerseShellLive/.venv/Scripts/python.exe' -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
```

## 证据与边界

- [修改前失败日志](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/regression-before.log)
- [最终全量日志](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/full.log) · [退出码与摘要稳定性](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/result.json)
- [三个源码/测试文件的精确增量](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/implementation.diff) · [摘要与范围](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/change-manifest.json)
- [测试二进制来源](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/after/preparation.json) · [首次环境故障](D:/VerseShellLive/tf-node-dev-20261009-01a11e89/baseline/full.log)

没有启动模型端点采集、重写 canonical eval、改验收阈值、提交/合并或修改 Task Forest。TF-0133 保持开放；新冻结版本接入、TF-0140 产品门禁和 TF-0141 源码落地仍需各自证据。本批分析报告内容为离线 fixture，不能冒充真实分析结果。
