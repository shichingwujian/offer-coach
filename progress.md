# progress.md

> **下次从这里开始：核心层 D1-D10 收官 ✅（75 测试全过，笔记 learning/01-08）→ 深度冲刺 D11：先造尺子（召回评估集 + 纯 FTS5 基线 recall@5）再升级（混合召回），最后消融实验（D006）**

## 当前阶段

核心层 D1-D10 收官 ✅（75 测试全过）→ 深度冲刺：① 召回评估集 + FTS5 基线 ② 混合召回（FTS5+向量）③ 机制消融

## 进行中

（无）

## 已完成

- 仓库骨架：src 布局、pytest、typer CLI、`.claude/` 工作流四件套（CLAUDE.md / settings / 3 skills）、progress.md / decisions.md / learning/
- D2：吃透 agent-api-lab 的 agent loop，explain-back #1 通过，笔记落在 `learning/01-agent-loop.md`
- D3：Query Engine 落地 `src/offer_coach/engine/`——Provider 接口（Protocol）、FakeProvider（脚本化+故障注入）、OpenAIProvider（openai 3.x，异常翻译、消息翻译）、with_retry（分类重试+指数退避+sleep 可注入）、CostLedger（预算拉闸+记账）、QueryEngine 主类；9 个测试全 FakeProvider/桩，零联网。explain-back #2 通过，笔记在 `learning/02-query-engine.md`
- D4：Tools 层落地 `src/offer_coach/tools/`——ToolDef（说明书+函数）、ToolRegistry（字典注册表）、execute_tool（失败全变错误文本）、run_loop（最小 agent loop：先记录后执行 + tool_call_id 配对 + 动作指纹防死循环）、三个内置工具（题库种子×5 / analyze 走 LLM / report 纯模板）；11 个测试全过
- D5：题库层落地 `src/offer_coach/knowledge/`——parser（正则切块，兼容 ## Q/### Q 两种格式，实灌 807 题）、db.py（FTS5 trigram 建表 + 灌库幂等 + 检索，<3 字关键词走 LIKE 兜底）、CLI `ingest` 命令；query_knowledge_base 换真库内脏（工厂函数焊 db_path），种子题删除；30 测试全过
- D6：Skills 层落地 `src/offer_coach/skills/diagnose.py`——导演剧本驱动三步流程（分析→查库→报告），CLI `diagnose` 命令（from_env 装配 + 账单打印）；加 python-dotenv 搭 .env 桥；34 测试全过；**真机验收：DeepSeek 跑通 demo.txt，报告正确点出三个薄弱点并引用题库**
- D7：Context 层落地 `src/offer_coach/context/manager.py`——token 估算（CJK 一字≈1 token）、死保区（system+首条 user）+ 滑窗区、`_blocks` 成对裁剪（订单+回执整包扔留，孤儿结构免疫）、outbound 裁剪副本 vs 内部完整历史；6 测试；D005 摘要压缩推迟 v2；笔记 learning/06
- D8：权限闸 `permission/gate.py`——默认拒绝白名单、confirm 人在环中、remembered 集合（首次问后续记住）、审计留痕；Session 存档/读档（Pydantic dump/validate）；8 测试
- D9：Hook+Command 落地 `hooks/pipeline.py`——pre/post 两排插孔（短路/逐级改写）、truncate_hook 实战插件、权限闸 as_hook() 改造为插件（适配器）、loop 内联闸门删除换管线、CLI chat REPL + 斜杠命令直达电梯；9 测试（累计 57）；笔记 learning/07（讲解版）
- D10：Memory 层落地 `src/offer_coach/memory/`——MemoryStore（SQLite，confidence 坐实度 +0.1 封顶、access_count 召回计数、画像 patch 合并）、make_memory_hook（旁观型 post 插件：只看 analyze、只记 <3 分、解析不到宁可不记、同维度坐实不新增）、recall_block（开局召回：画像非空字段 + ≥0.6 弱点 + 最近 2 次摘要）、analyze 工具升级 v2（JSON 评分 + 确定性渲染 + 原文兜底）、diagnose 接线（剧本注入历史档案、跑成才记档）、CLI --memory + /profile /memory 命令；18 测试（累计 75）；笔记 learning/08（D007：死规则写入 + 只坐实不洗白）

## 阻塞 / 问题

（无）

## 临时上下文

- 开发期 LLM 用 DeepSeek（OpenAI 兼容），`.env` 从 `.env.example` 复制
- 范围红线：不做语音；其余 10 层按 final-project 官方顺序迭代
- **路线（2026-10-13 用户拍板）**：D9/D10 收尾 offer-coach 核心层 → 补两块深度短板：① 混合召回（FTS5+向量）② 评估集 → 之后 Sub-agent/部署/Web 壳推迟。目标：面试深度故事，不追功能广度
- **评估集升级为两层（2026-10-13，读 Mini-dsh 简历后拍板，见 D006）**：① 召回评估（50+ 查询算 recall@5）② 机制消融（10-15 份埋雷面试稿，对照有无题库/导演剧本，算薄弱点命中率，每配置跑 2-3 次看方差）；灵感库存档：AbortController 式取消、JSONL 追加存档、80% 阈值自动摘要、Prompt Optimizer 插件（均 v2，现在不做）
- **D10 v1 范围（2026-10-14 修正版）**：三种记忆全做——user_profile（弱项/分数/次数自动更新，岗位/技术栈可选自报）、weak_point（key 去重 + confidence 坐实）、diagnosis_summary；写入 = post 插件盯 analyze_content 低分维度；开局召回注入导演剧本（画像非空字段 + confidence≥0.6 弱点 + 最近 2 次摘要）。不做：expiresAt 过期（无短期记忆场景）、向量检索（归混合召回冲刺）、preference 类型（需模型判断写不写，垃圾桶风险，v1 只用死规则触发）
- **简历话术锚点**：参照写"DeepSeek Harness '一切皆插'设计思想"，不写 Mini-dsh（同学项目，没分量易穿帮）；被追问"依赖校验/生命周期怎么没做" → 答"全总线对单人项目过重，两排插孔拿八成收益，有意识的取舍"
