# 05 | Skills 层：菜谱——散装零件组装成整机

> D6 学习笔记。代码在 `src/offer_coach/skills/`，34 个测试全过，**MVP 闭环真机验收通过**（DeepSeek 真跑，demo.txt → 报告.md）。

## 一句话本质

Skill = **菜谱**：把工具（厨房设备）按流程串成一道菜。菜谱不替模型做决定——流程写在**导演剧本**（system prompt）里，模型在 loop 里自主下单。

## 一次诊断的旅行（面试标准答案，背这段）

```text
① CLI 把稿子交给 diagnose
② 导演剧本发给模型：分析 → 查库 → 出报告
③ 模型下单 analyze_content → 工具内部调发动机，四维打分
④ 模型看着分析结论，自主下单 query_knowledge_base（薄弱点各查一次）
⑤ 模型下单 generate_report → 纯模板排版，零 token
⑥ 终答 → loop completed → 报告落盘
⑦ 总闸账本记下每笔花销，打印账单
```

三个记忆锚点：**剧本驱动**（改流程=改提示词，不动代码）、**模型下单 Harness 跑腿**、**总闸记账**。

## 为什么（本阶段考点）

**Q1：为什么不写死 analyze→query→report 的固定流水线？**
写死的流水线是傻瓜流水线；模型自主下单才能"看菜下料"——分析发现 Redis 弱就多查两单 Redis。agent 和脚本的区别就在这。改流程只需改剧本文字。

**Q2：账单为什么一定算得清？**
所有 LLM 流量必经 engine.query 三道岗，记账岗在必经之路上，想逃票都逃不掉（总闸设计的回报）。

**Q3：附录的题库内容为什么不靠模型背？**
**准确题库防幻觉**——模型的记忆会编造，题库的检索是事实。这是 RAG 的灵魂。

## 真机验收发现（demo.txt 反面教材实战）

- 报告正确点出三个薄弱点，附录引用的"ReAct vs CoT 开环闭环"直接来自题库——工具链真的在协作
- 报错路径也验收过：第一次用错 base_url（/anthropic 方言窗口）→ 超时 → 分类重试 → 明确报错，不是静默卡死

## 环境契约踩坑记录（以后配环境的 checklist）

1. `.env` 不会自动生效，需要 `load_dotenv()` 搭桥（python-dotenv）
2. 变量名一个字母都不能错：`OPENAI_BASE_URL`（不是 BASE_UR）
3. DeepSeek 有两个窗口：`/v1`（OpenAI 方言，咱们用这个）vs `/anthropic`（Anthropic 方言）
4. 模型名：`deepseek-chat`，别串到别的平台的型号
