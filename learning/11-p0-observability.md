# 11 | P0-1 结构化运行轨迹：messages 与 trace 两条链

> P0-1 学习笔记（含 explain-back 问答记录）。代码在 `src/offer_coach/tools/loop.py` 和 `skills/diagnose.py`，125 个离线测试全过；未调用真实 API。

## 一句话本质

`messages/history` 是给模型继续思考的**对话链**，`trace` 是给 Harness、开发者和测试定位问题的**监控链**；trace 不回喂模型，也不复制完整工具结果。

## 架构示意图

```text
对话链：模型下一轮要看什么
初始 messages → history → outbound → engine.query
                    ↑                         │
                    │                         ▼
                    └──── assistant 订单 + tool 回执

监控链：系统刚才实际做了什么
engine.query ──→ TurnTrace（轮次 / stop_reason / request_id）
execute_tool ─→ ToolTrace（订单 / 参数 / 结果类型 / 截断 / 短预览）
TurnTrace + ToolTrace → LoopResult.trace → diagnose 失败错误信息
```

`history` 是完整对话的本地副本，`outbound` 是本轮实际发给模型的版本（可能经 ContextManager 裁剪）。模型能看到工具结果，是因为结果作为 `role="tool"` 的消息加入了 `history`，不是因为写了 trace。

## 轨迹记录什么

- **TurnTrace**：第几轮、模型 stop_reason、request_id、本轮工具轨迹。
- **ToolTrace**：call_id、工具名、原始参数、同参数声明次数、结果类型、结果长度、是否截断、短预览。
- **结果类型**：success / empty / error / blocked / duplicate。
- **完整内容**：仍只在 messages/history 里保存，trace 只留定位摘要。

## 三个为什么（验收问答记录）

### Q1：为什么已有 messages，还要在执行时单独记录 trace？

用户首答抓住了“无论成功还是失败都记录过程”，随后补清：`messages` 主要保存对话内容，缺少结构化的 stop_reason、重复次数、执行状态等字段。只在失败后拼工具名，看不出工具是执行成功、返回空、报错、被拦截，还是因重复而未执行。

**结论**：messages 服务模型续跑，trace 服务 Harness 和人定位问题；两者职责不同。

### Q2：为什么第三次重复调用没有第三条工具回执？

验收中曾误以为“会记录出错过程，所以有工具结果”。纠正后的执行顺序是：

```text
第三张 assistant 订单进入 history
→ 指纹计数达到 3
→ trace 记录 duplicate
→ 立即 return
```

因为 `execute_tool` 和 `history.append(role="tool")` 都在 return 之后，所以不会执行第三次工具，也没有第三条工具回执。用户最终确认：**只有第三张订单，没有第三条 tool 回执**。

### Q3：为什么 trace 只保留长度和短预览，不复制完整结果？

用户首答“没必要”，方向正确。完整结果已经在 messages/history 里，再复制会占用内存、让失败异常膨胀，也容易把长稿或分析正文重复扩散。trace 只保留状态、长度、截断标记和 120 字以内的单行预览；需要全文时仍回 messages 查。

## 本阶段边界

- 已完成：结构化轨迹、失败信息增强、六类结果与 max_iterations 的离线回归。
- 未做：工具调用预算、失败降级报告、hybrid 主流程接线、真实 API 稳定性验收。
- 因此当前只能说“失败更可定位”，不能说 stuck / max_iterations 已修复。
