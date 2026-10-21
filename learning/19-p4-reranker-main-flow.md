# 19 | P2-4 精排裁判上岗：从评估链路走进正式诊断

> P2-4 学习笔记。P2-3 的 v2-m3 裁判只在评估脚本里上班（recall@5 92.6%），本阶段把它接进正式诊断主流程。代码改动 = 四层传话 + 一条降级链，174 个离线测试全过。

## 一句话本质

最底下的检索本体（`search_hybrid`）早在 P2-3 就支持裁判了；这个阶段干的是**把裁判从 CLI 一路传到检索本体**的接线活，外加一条"裁判挂了不拖垮诊断"的降级链。招聘比喻：终面官只在模拟招聘里用过，现在让他真上岗。

## 完整数据流（`diagnose 稿子.txt --rerank`）

```text
① CLI（cli.py diagnose_cmd）
   --rerank 开关 → 校验：phrase/terms 下开就报错（没有决赛圈可复评）
   → 懒加载 FastEmbedder + FastReranker
   ↓
② 诊断入口（skills/diagnose.py diagnose_run）
   reranker 原样下传，不加逻辑
   ↓
③ 工具工厂（tools/builtin.py default_registry → make_query_knowledge_base）
   把 reranker 焊进查库工具闭包
   ↓
④ 统一检索入口（knowledge/db.py search_for_diagnosis）
   auto/hybrid + 有向量索引 → search_hybrid(..., reranker=裁判)
   ↓
⑤ 检索本体（search_hybrid，P2-3 已就绪）
   字面/向量各报 30 名 → RRF 合榜 → 裁判复评前 30 → 裁 top-5 交给模型
```

工具回执如实报 `检索模式：hybrid+rerank`——嘴上说的和实际跑的必须一致（D014）。

## 降级链（增强能力缺失不拖垮诊断）

```text
hybrid+rerank（满配）
  ↓ 裁判加载崩（模型文件损坏等）
hybrid（摘掉裁判重试粗排，fallback_reason = "复评通道不可用：..."）
  ↓ 向量通道也崩 / 没 embedder / 没建向量索引
terms（fallback_reason 写明原因）
```

每一级退化都在 `fallback_reason` 留痕。回执是出问题时唯一的现场照片：
照片拍错，排查方向就错——比如裁判静默退化了，回执却写 hybrid，
三个月后诊断质量下降时根本想不到去查裁判。

## 三个为什么（本阶段考试记录）

1. **裁判崩了怎么办？** 退普通 hybrid 继续诊断，降级原因写进回执。
   增强能力是锦上添花，不是命根子（和 embedder 挂了退 terms 同一原则）。✅
2. **auto 模式下没建向量索引但开了 --rerank，裁判上班吗？** 不上。
   裁判是精排，精排对象是粗排圈出的决赛圈；没有 hybrid 粗排就没有决赛圈，
   terms 的 5 个结果没有可复评的东西，裁判一起歇着。✅
3. **为什么回执要区分 hybrid 和 hybrid+rerank？** 回执是审计线索/现场照片。
   统一写 hybrid 会掩盖裁判是否真在上班，出问题排查时漏掉整条复评链路。✅

## 边界

- 裁判只在 hybrid 路径上岗；terms 模式不配裁判是刻意设计，不是遗漏
- 裁判是本地模型（v2-m3，约 570MB），推理零 API 费用、CPU 秒级
- 不传 `--rerank` 一切照旧，旧行为零变化
- 真实长稿验收（带裁判跑真模型）仍待 API 额度恢复
