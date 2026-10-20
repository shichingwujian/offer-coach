# 决策日志

每条决策记录：背景 / 选项 / 决定 / 理由 / 影响。面试时这就是你的弹药库。

## D001 | 2026-10-10 | 用 Python 自实现 Harness

- 背景：参考实现 OfferPilot 是 Go + Next.js，PRD 是 TypeScript。
- 选项：(a) 学 Go 复刻 (b) Python/FastAPI 自实现，Go 代码只当参考书
- 决定：(b)
- 理由：学习目标是 Agent 工程原理而非新语言；Python 是 AI Agent 生态最主流语言；概念翻译比照抄代码学到的更多
- 影响：所有设计需跨语言翻译；用 agent-api-lab（纯 Python）做 loop 骨架的地基

## D004 | 2026-10-10 | Query Engine v1 范围裁剪：非流式、单 Provider、无缓存/限流/路由

- 背景：教程 03-query-engine 是 8 文件全家桶（3 家 Provider + 流式 + 重试 + 限流 + 缓存 + 路由 + 预算），一次全做对新手中断风险高
- 选项：(a) 照教程全做 (b) v1 只做 Provider 接口 + OpenAI 兼容实现 + FakeProvider + 分类重试 + 成本账本
- 决定：(b)
- 理由：MVP 是 CLI 文字诊断，流式等 Web UI 阶段再上（SSE 才需要）；缓存/限流/路由是 Sub-agent 并行阶段的需求；单一 OpenAI 兼容接口已覆盖 DeepSeek/GPT/Qwen
- 影响：上层只有 `QueryEngine.query()` 一个入口；后续加流式时 Provider 接口需加 `stream()` 方法，属于已知扩展点

## D003 | 2026-10-10 | 测试策略：FakeProvider 优先，真模型只做验收

- 背景：LLM 调用不稳定、要花钱、结果不可复现，直接拿真模型写单元测试会导致 CI 随机失败
- 选项：(a) 全部用真模型 (b) HTTP 层录制回放（VCR）(c) 自实现脚本化 FakeProvider
- 决定：(c)，模式来自 zero2Agent `examples/agent-api-lab`
- 理由：确定性（同一测试永远同结果）、零成本、离线可跑；脚本化 provider 还能注入故障（429/超时/5xx）测试重试逻辑
- 影响：engine/ 的 LLM 客户端必须设计成"可替换 provider"（依赖注入），真模型路径只做少量验收测试

## D005 | 2026-10-12 | Context v1 只做滑窗+预算，摘要压缩推迟 v2

- 背景：教程 06-context-memory 给了三种武器（滑窗/摘要/分层预算），全做会引入摘要调用的预算、质量、递归摘要等新问题
- 选项：(a) 三种全做 (b) v1 只做滑窗 + token 预算 + 成对裁剪
- 决定：(b)，摘要列为已知扩展点
- 理由：摘要是唯一"要花钱+会出错"的策略；当前 diagnose 一次仅 4-6 轮（几千 tokens），离 64K 窗口很远；滑窗是"此刻就在保命"的底线
- 影响：ContextManager 只有死保区+滑窗区两层；将来加摘要时作为 fit 的可替换策略接入，主结构不动

## D007 | 2026-10-14 | 记忆写入：死规则触发 + 只坐实不洗白（v1）

- 背景：教程给了"LLM 判断写入"和"显式规则触发"两条路；"弱点改善了怎么办"也需要立场
- 决定：① 写入只用死规则（analyze 低分触发、/profile 手动写画像），不用模型判断"值不值得记"；② preference 记忆类型不做；③ v1 只坐实不洗白
- 理由：教程点名 LLM 判断写入是垃圾桶风险之源；洗白规则（扣多少、何时算洗白）引出一串新问题，v1 简化；画像自动字段（弱项/分数/次数）本来就在诊断结果里，零新入口（user_profile 从"不做"修正为"做"，用户追问依据后复查翻案）
- 影响：记忆插件是旁观型 post 插件；洗白列为已知扩展点（连续 ≥4 分降坐实度 + "已攻克"留档，想法来自用户 Q3 回答）

## D006 | 2026-10-13 | 评估集做两层：召回评估 + 机制消融

- 背景：读 Mini-dsh 简历（TS 版 coding agent Harness，同赛道深度项目），其最值钱的一条是 Benchmark + 消融实验（Baseline 75% vs Full 90%，回答"怎么证明每层机制有用"）
- 选项：(a) 按原计划只做召回评估 recall@5 (b) 评估集升级为两层
- 决定：(b)
- 理由：recall@5 只回答"检索质量怎么样"，消融才回答"你加的每一层有什么用"——后者是面试官对 Harness 项目的标准追问；消融 = 新药临床试验，停掉一味药看疗效差
- 方案：① 召回评估：50+ 条带标准答案的查询算 recall@5；② 机制消融：10-15 份埋雷面试稿（每份埋 2-3 个已知薄弱点当标准答案），对照组摘题库工具/摘导演剧本，算薄弱点命中率，每配置跑 2-3 次看方差
- 教训吸收：Mini-dsh n=20 仅差 3 个任务，统计意义弱，会被追问；我们把检索评估量做足、消融跑多次
- 不抄的：全插件总线（两孔插线板是规模合适的取舍，面试讲 trade-off）；coding agent 方向（不追广度）
- 灵感库存档（v2 候选，现在不做）：AbortController 式取消、JSONL 追加式存档、80% 阈值自动摘要（D005 推迟项，Mini-dsh 给了参考设计）、Prompt Optimizer 插件

## D010 | 2026-10-15 | 向量后端：本地 fastembed 为默认，API 为可插备选

- 背景：D13 混合召回需要 embedding；用户手里只有 DeepSeek 和 Kimi 的 key，**两家都没有 embedding 接口**；走 API 需另注册（硅基流动有免费 embedding）
- 选项：(a) 注册新 API（硅基流动）(b) 本地小模型 fastembed + bge-small-zh（约 100MB，首次下载）
- 决定：(b) 本地为默认；`Embedder` 接口（Protocol）留好，API 实现随时可插
- 理由：离线、免费、永远可复现——评估集是想跑就跑的尺子，不该依赖网络和外部账号；架构上接口抽象不变，故事反而是"向量后端可替换"（DI 第 7 次：FakeEmbedder 哈希向量跑测试，零联网）
- 影响：`knowledge/embedder.py` 三件套（Embedder 协议 / FastEmbedder 懒加载真模型 / FakeEmbedder 测试）；向量存 SQLite BLOB（question_vecs 表）；`ingest --vectors` 建坐标，`eval --mode hybrid` 复测
- 风险记录：首次下载走 HuggingFace，国内可能被墙 → 备案 `HF_ENDPOINT=https://hf-mirror.com`

## D008 | 2026-10-14 | 输入层预留统一 Transcript 结构 + ASR 适配器（录音不做，但架构留门）

- 背景：外部建议（朋友评审）：录音转文字只是输入适配器，复盘质量才是核心；统一中间表示 `Transcript{turns:[{speaker,text}]}` 可让 ASR 后续零改动接入
- 决定：采纳为话术与 v2 方向——v1 只做文字稿（红线不变），但简历/面试口径统一为"预留 ASR 适配器"而非"不做语音"；口语文本分轮清洗（面试官/我 分轮）列为 v2 输入层任务
- 理由：ASR 是标准能力不是护城河；先隔离 ASR 错误才能公平评估复盘质量；"有取舍"比"缺功能"听起来高级
- 影响：diagnose 入口仍是纯文本文件；v2 若做分轮解析，输出 Transcript 结构喂给 analyze，下游不变
- 同批灵感库新增（来自该建议）：题库结构化 v2（评分点/追问链/标签/版本）、回放/A/B harness（v2，做完才许上简历）、评分点召回率（D14 消融指标的参考提法）

## D009 | 2026-10-14 | 拆词用规则土办法（停词+滑窗），v1 不引入 jieba

- 背景：D12 查询预处理需要中文分词；jieba（词典+统计模型）是成熟方案但引入 ~30MB 依赖
- 决定：v1 用三刀土办法（标点切段 → 停词当刀 → 长段滑窗二字块），jieba 列为已知升级点
- 理由：目标只是让 paraphrase/scenario 破零；真·语义鸿沟归 D13 向量管；有评估集兜底——数字不好再升级，不凭感觉上依赖。面试话术："先用最简实现拿基线，让评估集决定要不要加依赖"
- 影响：preprocess.py 纯规则零依赖；切错的二字块是噪音词，查不到即无害（OR 合并的特性：多切无害，漏切才有事）

## D002 | 2026-10-10 | 题库直接复用 zero2Agent 384 题，不自建内容管线

- 背景：题库内容来自 zero2Agent（MIT License）
- 选项：(a) 自建"AI 生成→筛选→入库"管线 (b) 直接导入 384 题
- 决定：(b)，README 注明来源
- 理由：用户决策，优先把诊断闭环跑起来；内容管线进迭代 backlog
- 影响：面试被问题库来源时需诚实说明；迭代期可补自建管线作为差异化

## D011 | 2026-10-19 | P0 先做结构化轨迹，再加预算和降级

- 背景：长稿历史运行出现 stuck / max_iterations，但旧日志只有状态，缺少轮次、工具结果和截断信息，无法证明“检索次数过多”就是根因
- 选项：(a) 直接调大 max_iterations (b) 先加调用预算和降级 (c) 先在现有 loop 里记录结构化运行轨迹
- 决定：(c)；P0-1 只增加 TurnTrace / ToolTrace 和失败信息，不改变循环终止规则、不加预算、不做降级、不跑消融
- 理由：没有轨迹就加限制，可能只是换一种失败状态；先让每次失败能回答“第几轮、调用什么、结果如何、为何停止”，后续修复才有证据
- 影响：messages/history 继续保存完整对话并回喂模型；trace 只保存结构化摘要，不回喂模型。第三次重复记 duplicate 且未执行，不新增第三条 tool 回执
- 边界：125 项离线测试通过只证明轨迹与既有控制流未回退，不代表真实模型稳定性已验证；P0-2 工具预算和后续真实长稿验收另行推进

## D012 | 2026-10-19 | 工具预算按声明计数，超预算先补回执再无工具收尾

- 背景：P0-1 已能看清工具轨迹，但 loop 仍只限制外层模型轮数；一轮可含多个工具调用，错误/空结果/权限拦截也可能诱导模型继续下单
- 选项：(a) 只调大 max_iterations (b) 超预算立即返回失败 (c) 总工具预算 + 单项工具预算，超预算补 tool 回执后追加一轮无工具 finalize
- 决定：(c)；预算按“模型声明次数”而非工具成功次数计数；重复检测仍优先报 stuck；diagnose 默认总工具 8 次、知识库检索 3 次，暂不暴露 CLI 参数
- 理由：只调轮数挡不住单轮多调用；立即失败会丢掉已有分析材料；补回执保证 tool_call_id 成对，finalize 让模型基于已有材料正常结束
- 影响：`ToolOutcome` 增加 budget_exceeded，`TurnTrace` 增加 normal/finalize，`LoopStatus` 增加 tool_budget_exceeded；finalize 是正常轮数之外的一次无工具收尾
- 边界：131 项离线测试通过，仍未做降级报告和真实 API 长稿验收，不得宣称端到端稳定性已验证

## D013 | 2026-10-19 | 诊断结果显式区分 full / degraded / failed，降级报告不调模型

- 背景：P0-2 后非 completed 仍统一抛错；模型可能已经留下成功的分析或检索材料，直接报错会丢掉可用产物，也可能让旧评估链路把“返回文本”误当完整成功
- 选项：(a) 继续全部报错 (b) 让旧 `diagnose()` 返回降级文本 (c) 新增结构化 `diagnose_run()`，旧 `diagnose()` 保持只接受 full
- 决定：(c)；`completed + 非空终答` 为 full，非 full 但有成功工具回执为 degraded，无成功材料或 QueryEngineError 为 failed；降级报告用模板拼 history 里的成功 tool 回执，不再调模型
- 理由：LoopStatus 只说明循环怎么停，DiagnosisStatus 才说明结果可用性；结构化状态能防止 degraded 被误算成成功；确定性拼接避免编造、省钱且不增加失败点
- 影响：CLI 改用 `diagnose_run()`；旧 `diagnose()` 对 degraded/failed 继续抛错以保护旧评估入口；session 在降级时也保存；只有 full 才写 `diagnosis_summary`
- 边界：138 项离线测试通过；仍未做真实 API 长稿验收，不得宣称真实模型端到端稳定性已验证

## D014 | 2026-10-20 | 正式诊断检索统一走 search_for_diagnosis，auto 可显式退回 terms

- 背景：D13 的 hybrid 只在评估链路验证，正式 `query_knowledge_base` 仍调用旧 `search_questions`；直接默认强依赖 fastembed 又会让没建向量索引的环境无法诊断
- 选项：(a) 新增 `query_hybrid_knowledge_base` 工具 (b) 默认硬切 hybrid，缺向量就报错 (c) 原工具内部接入统一检索选择器，auto 按条件选 hybrid/terms
- 决定：(c)；新增 `RetrievalResult(hits, mode_used, fallback_reason)` 和 `search_for_diagnosis()`；`query_knowledge_base` 名字不变，内部按 `auto / phrase / terms / hybrid` 选择路径；CLI 增加 `--retrieval`
- 理由：模型菜单保持稳定；缺向量索引是增强能力缺失，不该拖垮诊断；记录真实路径和 fallback 原因，防止“嘴上 hybrid、实际 terms”
- 影响：诊断入口新增 `retrieval_mode` 和 `embedder` 参数；测试用 FakeEmbedder 验证主流程可走 hybrid；CLI 在 auto/hybrid 下懒加载 FastEmbedder；fastembed 仍是可选依赖
- 边界：144 项离线测试通过；真实 API 长稿验收仍未做，不能宣称每次真实诊断都走 hybrid，只能说主流程已具备 auto/hybrid 接线和显式退化
