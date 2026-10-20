# progress.md

> **下次从这里开始：P2-1 漏网解剖 ✅（157 项离线测试 + 11 条归因：召回病 2 / 排序病 5 / 融合挤压 4）→ P2-2 按 D015 下药：先做融合池深度与输出 k 解耦（预计零依赖救回 5 条）；真实长稿验收待 API 额度恢复**

## 当前阶段

核心层 D1-D10 收官 ✅ → 深度冲刺：D11 评估集+基线 ✅ → D12 查询预处理 ✅ → D13 混合召回 ✅（122 测试全过，recall@5 37.0%→72.2%→79.6%）→ D14 消融已停止（无有效结论，不写简历）→ P0 诊断稳定性：P0-1 结构化运行轨迹 ✅ → P0-2 工具调用预算 ✅ → P0-3 降级报告 ✅ → P1-1 hybrid 主流程接线 ✅ → P2-1 漏网解剖 ✅（157 测试全过）→ P2-2 融合池深度解耦（下一阶段）

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
- D11：召回评估集落地 `eval/recall_set.jsonl`（54 条手写：keyword 20 / paraphrase 18 / scenario 16）+ `evaluation/recall.py`（run_recall 注入式检索函数，同一把尺子量不同策略）+ CLI `eval` 命令；**基线：recall@5 = 37.0%（keyword 100% / paraphrase 0% / scenario 0%）——漏网全是"无结果"，整句短语匹配是元凶**；6 测试（累计 81）；结果记录在 eval/README.md
- D12：查询预处理落地 `knowledge/preprocess.py`（三刀拆词：标点切段→停词当刀→长段滑窗二字块，纯规则零依赖，D009 不引入 jieba）+ `search_smart`（每词各查合并：标题 2 分/正文 1 分、同分比最佳名次、每词 limit×4 进池；search_questions 基线一行不动）+ CLI `eval --mode phrase|terms`；**recall@5 = 72.2%（+35.2pp）：keyword 100% / paraphrase 33.3% / scenario 81.2%**；中途修了一次 keyword 回退（高频词 LIKE 池截断 → 加权+大池）；11 测试（累计 92）；D008（Transcript IR 预留 ASR 适配器话术）入决策日志
- D13：混合召回落地 `knowledge/embedder.py`（Embedder 协议 + FastEmbedder 懒加载 bge-small-zh 512 维本地模型 + FakeEmbedder 哈希假向量，DI 第 7 次）+ db.py 三件套（build_vectors 坐标入库 BLOB / search_vectors 余弦排序 / search_hybrid **RRF 按名次融合**——两路分数是两种货币没法比，名次可比）+ CLI `--mode hybrid` + `ingest --vectors`；**recall@5 = 79.6%（keyword 100% / paraphrase 55.6% / scenario 81.2%）**；插曲：HF 被墙 → hf-mirror 镜像 16 秒解决（D010 风险备案命中）；剩余 11 条漏网是 bge-small 拉不动的最深语义鸿沟（v2：bge-m3/reranker/同义词）；10 测试（累计 102）
- D14（机器就位，实验待跑）：机制消融落地 `evaluation/ablation.py`（run_fn 注入，DI 第 8 次；别名粗判口径；均值±标准差，翻车如实计数）+ diagnose 双开关（`ablate_kb` 没收检索工具+剧本改两步 / `ablate_script` 裸剧本只留身份；ToolRegistry 加 `unregister`）+ 6 份埋雷稿 12 颗雷（`eval/ablation/`，话题全在题库射程内）+ CLI `ablate` 命令；11 测试（累计 113）；**真机 36 次诊断待用户亲自开炮**

- P0-1：结构化运行轨迹落地——TurnTrace（轮次 / stop_reason / request_id）+ ToolTrace（参数 / 同参次数 / success / empty / error / blocked / duplicate / 截断 / 短预览）+ diagnose 失败信息改读 trace；完整结果仍留 messages，trace 不回喂模型；125 个离线测试全过；explain-back 通过，笔记在 `learning/11-p0-observability.md`，决策见 D011

- P0-2：工具声明预算落地——ToolBudget（总工具 8 次 / 知识库检索 3 次）+ 超预算 budget_exceeded 轨迹 + tool 回执补齐 + 一轮无工具 finalize；正常收尾 completed，收尾仍下单 tool_budget_exceeded；131 个离线测试全过；explain-back 通过，笔记在 `learning/12-p0-tool-budget.md`，决策见 D012

- P0-3：诊断状态口径落地——`DiagnosisResult(status=full/degraded/failed)` + 新入口 `diagnose_run()`；非 full 但有成功工具回执时确定性拼降级报告（不再调模型补写），无成功材料/API 异常为 failed；CLI 显示降级警告、failed 退出码 1；旧 `diagnose()` 保持严格，防止降级被旧评估链路误算成功；session 降级也保存，只有 full 写 `diagnosis_summary`；138 个离线测试全过；概念补讲记录在 `learning/13-p0-degraded-report.md`，决策见 D013

- P1-1：hybrid 主流程接线落地——`search_for_diagnosis()` 统一检索入口 + `RetrievalResult(hits, mode_used, fallback_reason)`；`query_knowledge_base` 换内脏不换菜单，支持 `auto / phrase / terms / hybrid`，auto 有 embedder+向量索引用 hybrid，否则明确退 terms；工具回执显示真实检索模式；诊断入口和 CLI `--retrieval` 已接线，fastembed 仍为可选依赖；144 个离线测试全过；explain-back 通过，笔记在 `learning/14-p1-hybrid-main-flow.md`，决策见 D014

- P2-1：漏网解剖落地——`evaluation/miss_analysis.py`（find_rank 榜单找名次 / classify 三类病因 / dissect_misses 三通道解剖 / format_dissection）+ CLI `eval --mode hybrid --dissect`；全程字符串比对零模型调用；11 条漏网归因：**召回病 2 / 排序病 5 / 融合挤压 4**；关键发现：融合池深度是隐藏变量（深池融合下 5 条排序病全部进前 5，零依赖可救）、融合挤压是计分规则冤枉向量通道、真召回病只有 2 条；归因表入 `eval/README.md`，P2-2 药方按性价比排序入 D015；157 个离线测试全过；explain-back 通过，笔记在 `learning/16-p2-miss-analysis.md`

## 阻塞 / 问题

- 用户不再为消融投入 API token：P0 不做消融；真实长稿验收待额度恢复后只跑正常诊断配置，不接裁判模型
- full 配置在长稿消融中出现过工具循环翻车（stuck / max_iterations）；P0-1 已补轨迹、P0-2 已补预算与无工具收尾、P0-3 已补降级报告，但真实长稿验收仍未做，不得宣称端到端稳定性已验证
- D13 混合召回已接入正式诊断 auto 路径，但真实使用取决于向量索引和 embedder 可用性；工具回执会写明 hybrid 或 terms fallback，简历不得宣称“每次诊断都走 hybrid”

## 临时上下文

- 开发期 LLM 用 DeepSeek（OpenAI 兼容），`.env` 从 `.env.example` 复制
- 范围红线：不做语音；其余 10 层按 final-project 官方顺序迭代
- **路线（2026-10-13 用户拍板）**：D9/D10 收尾 offer-coach 核心层 → 补两块深度短板：① 混合召回（FTS5+向量）② 评估集 → 之后 Sub-agent/部署/Web 壳推迟。目标：面试深度故事，不追功能广度
- **评估集升级为两层（2026-10-13，读 Mini-dsh 简历后拍板，见 D006）**：① 召回评估（50+ 查询算 recall@5）② 机制消融（10-15 份埋雷面试稿，对照有无题库/导演剧本，算薄弱点命中率，每配置跑 2-3 次看方差）；灵感库存档：AbortController 式取消、JSONL 追加存档、80% 阈值自动摘要、Prompt Optimizer 插件（均 v2，现在不做）
- **D10 v1 范围（2026-10-14 修正版）**：三种记忆全做——user_profile（弱项/分数/次数自动更新，岗位/技术栈可选自报）、weak_point（key 去重 + confidence 坐实）、diagnosis_summary；写入 = post 插件盯 analyze_content 低分维度；开局召回注入导演剧本（画像非空字段 + confidence≥0.6 弱点 + 最近 2 次摘要）。不做：expiresAt 过期（无短期记忆场景）、向量检索（归混合召回冲刺）、preference 类型（需模型判断写不写，垃圾桶风险，v1 只用死规则触发）
- **简历话术锚点**：参照写"DeepSeek Harness '一切皆插'设计思想"，不写 Mini-dsh（同学项目，没分量易穿帮）；被追问"依赖校验/生命周期怎么没做" → 答"全总线对单人项目过重，两排插孔拿八成收益，有意识的取舍"
- **灵感库新增（2026-10-14，朋友建议评审 + D12 讨论，均 v2 现在不做）**：jieba 专业分词（D12 升级点，见 D009）、统一 Transcript IR + ASR 适配器预留（见 D008，话术：不是"不做语音"是"预留适配器"）、口语文本分轮清洗、题库结构化 v2（评分点/追问链/标签/版本）、回放/A/B harness（做完才许上简历）、评分点召回率（D14 指标提法）
