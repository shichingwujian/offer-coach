# 02 | Query Engine：一次模型调用的三道岗

> D3 学习笔记。代码在 `src/offer_coach/engine/`，8 个文件，9 个测试全过。

## 一句话本质

Query Engine 是**所有 LLM 调用的唯一入口**（总闸）。它不管对话循环、不管工具——只管"把一批消息安全、省钱、抗故障地发给模型，把结果拿回来"。agent loop 将来建在它上面。

## `query()` 内部的三道岗（按顺序）

```text
engine.query(messages)
  ① ledger.check_budget()           ← 预算岗：花超直接抛错，provider 一次都不被碰
  ② with_retry(provider.complete)   ← 重试岗：见下方错误分类
  ③ ledger.record(turn.usage)       ← 记账岗：查价格表算钱，累加
  返回 ModelTurn
```

⚠️ 易混点（我考试时栽过的）："记历史→模型选工具→执行工具→再记历史"是 **agent loop**（上层），不是 query()。query() 只是一次调用的保镖，对工具一无所知。

## 错误分类：值不值得重拨

| 错误 | 类比 | retryable |
|---|---|---|
| 429 限流 / 超时 / 5xx | 对方占线，等会儿再拨 | ✅ |
| 400 请求非法 / 401 鉴权失败 | 拨的是空号，再拨一百次也没用 | ❌ |
| 预算超支 | 自己拉闸，根本没拨 | ❌（且不调 API） |

重试节奏：优先听服务器的 `retry_after`，否则指数退避（1s → 2s → 4s…，封顶 30s），最多 3 次。

## 三个为什么（我的答案 + 订正）

**Q1：sleep 为什么做成参数？**
❌ 我原答：因为要等 API 说的时间（那是 retry_after 的事，答偏了）。
✅ 订正：**测试不能真等**。写死 `time.sleep()` 测试要跑半分钟；传假 sleep 进去，重试逻辑照跑、等待归零。规律：**凡是让测试变慢/变贵/不稳定的东西，都做成可替换的**（依赖注入）。

**Q2：FakeProvider 为什么用剧本队列而不是写死一个回复？**
✅ 我答对了：剧本必须可控变化，才能模拟"先 429 后成功"，否则重试路径永远测不到。

**Q3：EngineConfig 把零件收在一起图什么？**
✅ 基本对：它是**装配清单**——造 Engine 时一次性配齐 provider/预算/重试/sleep，之后调用方只喊 `query()`，换 Fake→DeepSeek 只改装配那一行。

## 文件地图（按数据流顺序）

| 文件 | 职责 | 核心 |
|---|---|---|
| models.py | 数据结构 | Message / ToolCall / Usage / ModelTurn，Pydantic 保类型 |
| errors.py | 错误分类法 | QueryEngineError + 六个工厂方法 |
| retry.py | 重试循环 | with_retry，sleep 可注入 |
| provider.py | 插座 + 电池 | Provider(Protocol) + FakeProvider(deque 剧本 + calls 记录) |
| cost.py | 电表 | check_budget 调用前拉闸 / record 记账 |
| engine.py | 总闸 | query() = 三道岗 |
| openai_provider.py | 翻译官 | 消息格式互译、SDK 异常→六类错误 |
| tests/ | 行为说明书 | 每个测试名 = 一条"输入 X 应输出 Y" |

## 对应参考实现

- zero2Agent `examples/agent-api-lab/lab.py`：`_complete_with_retry`（598-607）→ 我们的 retry.py；中央记账 → 我们的 cost.py
- 教程：final-project/03-query-engine（我们按 D004 裁剪：非流式、单 Provider、无缓存/限流/路由）
