# TF-0093：R12审计入口的固定输入与克隆复验

日期：2026-10-09（Asia/Shanghai）。本批未发起模型请求，未重试StepFun认证门禁；整体目标仍未完成。

## 改动

- 四个原入口改用共享audit_inputs加载器，移除固定C盘工作区及可变latest读取。统计函数、随机种子和20k/100k等原迭代规模保留。
- 默认清单固定本批自包含输入目录中的with三个tf95分片（42/43/44，225行）和without的seed42（75行）。校验摘要、版本、模型/预算配置、唯一完整网格、数值字段和原审计聚合锚点。
- 合并头部配置从原verify_core参照中恢复并与分片核对；legacy repeat=3是三个seed分片合并，不是三次完整独立重复。
- 只给五个必需Python文件增加gitignore例外，没有整体放开脚本。gitattributes固定脚本LF，并禁止Git转换摘要固定的数据和参照JSON。
- 输出使用新临时目录或显式out-dir；已有结果拒绝覆盖。每份结果附源清单、脚本/helper摘要和结果字节摘要，运行中源变化则拒绝发布。Windows换行导致的输出摘要差异已由回归发现并修正。

## 证据

| 入口 | 退出码 | 比对的数值叶项 | 结果 |
|---|---:|---:|---|
| verify_core | 0 | 262 | 一致 |
| verify_part2 | 0 | 236 | 一致 |
| verify_part3 | 0 | 211 | 一致 |
| verify_part4 | 0 | 30 | 一致 |

总计739个数值叶项匹配；这些包括输入配置/迭代参数，不能全称为独立新计算。比对只预先豁免source路径与part4的_note文字（将“billed input”纠正为收到的usage、非对账账单）。没有调整数值容差来迎合旧结果。
19个数学函数的AST与修改前一致。克隆包在core.autocrlf=true下，摘要固定的数据和计算脚本仍字节一致。
历史来源与版本、三个with分片合计成功数53/50/62、观察/输入/输出总量及全部重算数值互相吻合；但没有原合并文件摘要，所以不宣称恢复了原合并文件的逐字节身份。当前latest没有被当成历史数据。

## 回归结果

- 11项固定输入/输出安全控制通过。全量Python **356/356，无跳过**，exit0。
- Rust **289通过、1忽略**；当前选定输入产品门禁仍 **26/31，exit1**。历史复算通过不使剩余产品/研究门禁自动通过。

## 尚未完成

该独立Git包用于验证可分发性；**主仓库索引和分支未提交/合并**，不能当作默认分支已落地。TF-0093继续保持开放，历史非数值/来源断言仍按原文限定范围读取。
StepFun真实采集仍受前一轮403 real_name_required阻断，本轮不更换账号或端点。未生成新的真实重复数据，不以此历史复验替代TF-0112/0114/0115。

## 复现

```powershell
python audit-r12-scratch/verify_core.py --out-dir 'D:/新的结果目录'
python audit-r12-scratch/verify_part2.py --out-dir 'D:/新的结果目录'
python audit-r12-scratch/verify_part3.py --out-dir 'D:/新的结果目录'
python audit-r12-scratch/verify_part4.py --out-dir 'D:/新的结果目录'
```

[克隆包原件](D:/VerseShellLive/r12-portability-20261009-01a11c1d/evidence/package-clone-current.json) · [逐字段比对](D:/VerseShellLive/r12-portability-20261009-01a11c1d/evidence/clone-replay-current.json) · [数学函数AST核查](D:/VerseShellLive/r12-portability-20261009-01a11c1d/evidence/calculation-ast-check.json)
[全量测试](D:/VerseShellLive/r12-portability-20261009-01a11c1d/logs/python-tests-verified.log) · [最终摘要](D:/VerseShellLive/r12-portability-20261009-01a11c1d/evidence/final-summary.json) · [精确改动](D:/VerseShellLive/r12-portability-20261009-01a11c1d/change-manifest.json)
