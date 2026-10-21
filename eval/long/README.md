# 真实长稿验收（待 API 额度恢复后执行）

历史背景：D14 消融中 full 配置在长稿上翻过车（t02-t05，8 次翻车 = 5 stuck + 3 max_iterations）。
P0-1（轨迹）→ P0-2（预算）→ P0-3（降级）三连修完后，**还没用真实长稿验证过**。
这份验收就是还这笔债：只跑正常诊断配置，不接裁判模型，人工看报告质量。

## 稿子

`long-01.md`：约 4000 字、12 轮问答，话题全在题库射程（RAG/向量/RRF/reranker/context/记忆/prompt）。
候选人表现有强有弱，刻意埋了两处明显错误供诊断挖掘：

1. **把 reranker 说成"相当于给向量通道加权"** —— 错误。加权是在被污染的名次上调汇率，
   reranker 是换信息源读原文精读（D017 的核心区别）。
2. **"余弦在向量特别长的时候也会受长度影响"** —— 错误。余弦归一化后只看方向，
   与长度无关；受长度影响的是点积。

另外有一处薄弱但不算错的回答值得观察（bge-small vs bge-m3 的选型理由薄弱、"下载快"不是理由）。

## 执行步骤（充值后按顺序）

PowerShell 先设一次编码（防中文乱码），本窗口内有效：

```powershell
$env:PYTHONIOENCODING="utf-8"
```

```powershell
# 0. 冒烟：确认额度到账（一次调用，约 1 分钱以内）
python scripts/ping_api.py

# 1. 正常诊断配置，带精排裁判（主流程推荐配置）
python -m offer_coach.cli diagnose eval/long/long-01.md --rerank --session long01 --output eval/long/report-01-rerank.md

# 2. 对照：不带裁判（隔离裁判对稳定性的影响）
python -m offer_coach.cli diagnose eval/long/long-01.md --session long01-plain --output eval/long/report-01-plain.md
```

每条命令跑完记录三样东西（填到下表）：

- **状态**：full / degraded / failed（CLI 会打印降级警告；failed 退出码 1）
- **轨迹**：`sessions/<名字>.json` 里的 TurnTrace（几轮、几次工具、有没有 budget_exceeded/stuck）
- **账单**：CLI 末尾打印的本次账单

| 配置 | 状态 | 轮数/工具数 | 是否翻车 | 账单 |
|---|---|---|---|---|
| --rerank |  |  |  |  |
| 不带裁判 |  |  |  |  |

## 报告质量人工判卷（不接裁判模型，肉眼三条）

1. 有没有点出 reranker ≠ 加权 这个错误？
2. 有没有点出"余弦受长度影响"这个错误？
3. 引用的题库题和稿子话题对不对得上（不是瞎引）？

## 口径红线

- 只跑正常诊断配置，不接 LLM 裁判（用户不为消融/裁判再花 token）
- 翻车如实记录，不 rerun 刷数字；翻车了先去 session 轨迹里找第几轮、什么工具、为何停止
- 两份报告原文留在本目录，验收结论写回 progress.md 和 learning/
