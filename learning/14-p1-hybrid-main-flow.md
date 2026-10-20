# 14 | P1-1 hybrid 主流程接线：换内脏，不换菜单

> P1-1 学习笔记（含 explain-back 问答记录）。代码在 `src/offer_coach/knowledge/db.py`、`src/offer_coach/tools/builtin.py`、`src/offer_coach/skills/diagnose.py` 和 `src/offer_coach/cli.py`，144 个离线测试全过；未调用真实 API。

## 一句话本质

正式诊断的 `query_knowledge_base` 不再固定调用旧的整句检索，而是统一走 `search_for_diagnosis()`：能用 hybrid 就用 hybrid，不能明确退回 terms，并把真实检索路径写进工具回执。

## 架构示意图

```text
模型下单
query_knowledge_base(keyword)
  ↓
execute_tool
  ↓
query_knowledge_base 工具函数
  ↓
search_for_diagnosis(mode, embedder)
  ├─ mode=phrase → search_questions
  ├─ mode=terms  → search_smart
  ├─ mode=hybrid → search_hybrid；不可用则 terms + fallback_reason
  └─ mode=auto
       ├─ 有 embedder + 有向量索引 → search_hybrid
       └─ 条件不够 → search_smart + fallback_reason
  ↓
RetrievalResult(hits, mode_used, fallback_reason)
  ↓
工具回执：检索模式 + 题目内容 → history → 下一轮模型
```

模型只负责说“我要查资料”；Harness 负责决定“这次用哪条检索路”。

## 为什么要记录真实路径

`RetrievalResult` 不只有 `hits`，还记录：

- `mode_used`：这次真实走的是 phrase / terms / hybrid
- `fallback_reason`：如果没走成 hybrid，为什么没走成

这是为了防止“嘴上 hybrid，实际 terms”。以后看 session 或工具回执，就能确认这次诊断到底用了什么检索。

## CLI 口径

`offer-coach diagnose` 新增：

```bash
--retrieval auto    # 默认：有向量条件用 hybrid，否则 terms
--retrieval phrase  # 旧基线
--retrieval terms   # D12 拆词
--retrieval hybrid  # 明确请求混合召回，不可用则显式退回 terms
```

`fastembed` 仍是可选依赖；测试继续用 `FakeEmbedder`，不会下载真实向量模型。

## 三个为什么（验收问答记录）

### Q1：为什么不新增 `query_hybrid_knowledge_base`，而是继续用 `query_knowledge_base`？

用户在前置考试已答对：工具菜单不变，只换内部实现。模型不需要学习新工具名，Harness 在工具内部选择检索路径。本阶段 explain-back 不应重复考同一题。

### Q2：为什么 fallback 不能只悄悄退回 terms，还要记录 `mode_used` 和 `fallback_reason`？

用户答：“记录啊，保真保可用。”补充完整：退回 terms 是为了保可用；记录真实路径是为了保真。没有向量索引或向量模型时诊断继续工作，但工具回执必须明确“这次不是 hybrid”。

### Q3：如果向量表建了，但 FastEmbedder 加载失败，系统怎么表现？

用户答：“不是有检索模式的回答吗？”补充完整：`search_for_diagnosis()` 捕获向量通道的加载/运行错误，退回 terms；工具回执显示 `检索模式：terms（向量通道不可用：...）`。用户能看到结果，开发者能从 fallback 原因定位问题。

## 本阶段边界

- 已完成：统一检索入口、真实路径记录、工具回执显示检索模式、诊断入口传递 embedder、CLI `--retrieval`。
- 未做：真实 API 长稿验收、检索质量进一步优化、reranker/同义词。
- 现在可以说“正式诊断路径已具备 auto/hybrid 接线”；不能说“每次真实诊断都一定走 hybrid”，因为 auto 会按向量索引和 embedder 可用性明确退化。
