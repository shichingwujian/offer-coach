# progress.md

> **下次从这里开始：D1-D6 用户手动 commit 后 → D7 Context 层（历史管理/压缩）**

## 当前阶段

D6 Skills 层 ✅（含真机验收：DeepSeek 跑通 demo.txt → 报告.md）。**MVP 闭环已通**。

## 进行中

（无）

## 已完成

- 仓库骨架：src 布局、pytest、typer CLI、`.claude/` 工作流四件套（CLAUDE.md / settings / 3 skills）、progress.md / decisions.md / learning/
- D2：吃透 agent-api-lab 的 agent loop，explain-back #1 通过，笔记落在 `learning/01-agent-loop.md`
- D3：Query Engine 落地 `src/offer_coach/engine/`——Provider 接口（Protocol）、FakeProvider（脚本化+故障注入）、OpenAIProvider（openai 3.x，异常翻译、消息翻译）、with_retry（分类重试+指数退避+sleep 可注入）、CostLedger（预算拉闸+记账）、QueryEngine 主类；9 个测试全 FakeProvider/桩，零联网。explain-back #2 通过，笔记在 `learning/02-query-engine.md`
- D4：Tools 层落地 `src/offer_coach/tools/`——ToolDef（说明书+函数）、ToolRegistry（字典注册表）、execute_tool（失败全变错误文本）、run_loop（最小 agent loop：先记录后执行 + tool_call_id 配对 + 动作指纹防死循环）、三个内置工具（题库种子×5 / analyze 走 LLM / report 纯模板）；11 个测试全过
- D5：题库层落地 `src/offer_coach/knowledge/`——parser（正则切块，兼容 ## Q/### Q 两种格式，实灌 807 题）、db.py（FTS5 trigram 建表 + 灌库幂等 + 检索，<3 字关键词走 LIKE 兜底）、CLI `ingest` 命令；query_knowledge_base 换真库内脏（工厂函数焊 db_path），种子题删除；30 测试全过
- D6：Skills 层落地 `src/offer_coach/skills/diagnose.py`——导演剧本驱动三步流程（分析→查库→报告），CLI `diagnose` 命令（from_env 装配 + 账单打印）；加 python-dotenv 搭 .env 桥；34 测试全过；**真机验收：DeepSeek 跑通 demo.txt，报告正确点出三个薄弱点并引用题库**

## 阻塞 / 问题

（无）

## 临时上下文

- 开发期 LLM 用 DeepSeek（OpenAI 兼容），`.env` 从 `.env.example` 复制
- 范围红线：不做语音；其余 10 层按 final-project 官方顺序迭代
