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
| --rerank | full | analyze×1 + kb×3 成功 + kb 超额×5 被预算拒 → 正常收尾，终答 6327 字 | 否 | $0.0121 |
| 不带裁判 | full（状态口径内） | analyze×1 + kb×4（第 4 次被 kb 预算拒）→ 无工具 finalize 轮 | **新翻车形态：DSML 泄漏**（见下） | $0.0089 |

## 验收结果（2026-10-21，DeepSeek 真机）

**稳定性（P0 三连修的目标）✅**：两次运行都没有 stuck / max_iterations 死循环；
kb 预算触发后都能补回执收尾——P0-2 机制在真实长稿上工作正常。
`检索模式：hybrid+rerank` 在真实工具回执中如实出现（D014/D018 口径落地）。

**人工判卷三条（rerank 组报告 `report-01-rerank.md`）✅✅✅**：
1. ✅ 挖出"reranker≈加权"错误，且引用题库标准答案给出"融合层 vs 判决层"纠正话术
2. ✅ 挖出"余弦受长度影响"错误，区分了维度灾难/长文本语义平均/点积三个易混现象
3. ✅ 引用题库题与稿子话题对得上（RRF、Embedding 选型、余弦相似度），非瞎引

**🔴 新翻车形态（plain 组）：DSML 泄漏。** kb 预算耗尽 → 无工具 finalize 轮 →
模型想调 generate_report 但手里没工具，把工具调用写成 `DSML` 标记文本当终答
交差（`report-01-plain.md` 原文留档）。系统判 full（终答非空），但交付物是乱码。
讽刺的是 DSML 参数里的分析本身挖出了两颗雷——**分析能力在线，交付通道翻车**。

**药方候选（未实施，见 D019）**：
1. finalize 轮放行 `generate_report`——它是纯模板零 LLM 成本，预算本来防的是烧钱工具，
   把免费排版工具也收走等于逼模型手写报告
2. 终答检测工具调用标记（DSML/XML 样式）→ 判 degraded 而非 full
3. 终答出现工具调用标记时自动补一轮真调用

**口径声明**：两次运行各跑一次，未 rerun 刷数字；翻车如实记录。
两份报告原文在本目录，session 轨迹在本地 `sessions/`（隐私，不入库）。

## P0-4 回归验证（2026-10-21，修复后）

plain 配置（出事故的那个）重跑一次：`report-01-fixed.md`。

- **DSML 泄漏修复生效** ✅：kb 预算（已调 5）第 6 次被拒 → 收尾轮模型调 generate_report
  → **白名单放行、真实执行** → 模型看着排版回执写终答 → full，报告 grep DSML = 0
- 轨迹：analyze×1 → kb×4 → kb×2（第 6 次被预算拒）→ 收尾轮 1：generate_report success
  → 收尾轮 2：无工具交终答——与回归测试 `test_finalize_round_executes_zero_cost_report_tool` 脚本一致
- 判卷：两颗埋雷再次全挖出（reranker≠加权、余弦不受长度影响均标 P0）
- 账单 $0.0246（kb 预算 3→5 后多查了 2 次，成本上升在预期内）

## 报告质量人工判卷（不接裁判模型，肉眼三条）

1. 有没有点出 reranker ≠ 加权 这个错误？
2. 有没有点出"余弦受长度影响"这个错误？
3. 引用的题库题和稿子话题对不对得上（不是瞎引）？

## 口径红线

- 只跑正常诊断配置，不接 LLM 裁判（用户不为消融/裁判再花 token）
- 翻车如实记录，不 rerun 刷数字；翻车了先去 session 轨迹里找第几轮、什么工具、为何停止
- 两份报告原文留在本目录，验收结论写回 progress.md 和 learning/
