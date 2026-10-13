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

## D002 | 2026-10-10 | 题库直接复用 zero2Agent 384 题，不自建内容管线

- 背景：题库内容来自 zero2Agent（MIT License）
- 选项：(a) 自建"AI 生成→筛选→入库"管线 (b) 直接导入 384 题
- 决定：(b)，README 注明来源
- 理由：用户决策，优先把诊断闭环跑起来；内容管线进迭代 backlog
- 影响：面试被问题库来源时需诚实说明；迭代期可补自建管线作为差异化
