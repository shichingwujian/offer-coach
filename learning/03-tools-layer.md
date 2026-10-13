# 03 | Tools 层：模型没有手，只会下单

> D4 学习笔记。代码在 `src/offer_coach/tools/`，11 个测试全过（全 FakeProvider）。

## 一句话本质

**模型只会写订单（tool_calls），Harness 才是跑腿的。** Tools 层就是"货架 + 收银员 + 车间"：模型看菜单下单，Harness 按单取货执行，结果挂订单号送回。

## 一张订单的旅行（六步）

```text
① 模型回复带 tool_calls：[{id: "call_1", name, arguments: "JSON字符串"}]
② run_loop 先把这条 assistant 消息 append 进历史   ← 先记录后执行
③ 动作指纹 (name, arguments) 第 3 次重复 → stuck  ← 防死循环哨兵（数的是重复下单，不是失败）
④ execute_tool：查注册表 → json.loads → 校验必填 → 调函数
   任何失败 → 错误文本，绝不抛异常                  ← 失败当数据
⑤ 结果包成 role=tool 消息，tool_call_id 挂回 "call_1" ← 订单配对
⑥ 新历史再发模型 → 模型读到结果 → 最终回答 → completed
```

## 三个为什么（订正版）

**Q1：execute_tool 的 except Exception 为什么不算"裸 except 吞错"？**
吞错 = 错误消失了（`except: pass`，垃圾扫到地毯下）。这里错误**换形式继续流动**：异常→错误文本→亲手交给模型→模型自我纠错。全程可见、有处理、有下文，叫"失败当数据"。

**Q2：make_analyze_content 为什么是工厂函数？**
工具参数由模型按说明书填，模型只会填 `transcript`（稿子原文），不知道也不该知道发动机。但 analyze 干活必须调模型 → 外层函数装配时把 **engine 塞进函数身体**（闭包 = 函数出生时被塞进的行李），内层只暴露 transcript。**行李 = engine（QueryEngine）。**

**Q3：D5 换 FTS5 为什么模型和 loop 无感？**
**接口稳定，实现可换**：模型只看说明书（name/参数/返回），loop 只调 execute_tool。函数身体内部换掉，说明书和签名不动 → 无人察觉。和 Provider 插座（Fake↔真模型）是同一招式的第三次使用。

## 我栽过/问过的地方

- 动作指纹数的**不是失败次数**，是"同一（工具名+参数）重复下单"——治的是"结果正确但模型原地打转"这种隐蔽病
- 注册表选字典**不是为了查找快**（5 个工具没区别），是为了"加工具 = 注册一行，循环零改动"（对扩展开放，对修改关闭）
- builtin.py 不是 harness。Harness = engine + loop + registry（通用框架，不管业务）；builtin = 三个业务工具（只是货架上的货）

## 文件地图

| 文件 | 角色 | 核心 |
|---|---|---|
| registry.py | 货架+收银员 | ToolDef（说明书+函数）、ToolRegistry（字典）、execute_tool（四道检查全变文本） |
| loop.py | 循环 | run_loop：先记录后执行、指纹哨兵、三种退出 completed/stuck/max_iterations |
| builtin.py | 车间 | 种子题×5（空货架）、make_analyze_content（闭包塞 engine）、generate_report（纯模板不烧钱）、default_registry（装配处） |

## 埋给 D5 的钩子

`query_knowledge_base(keyword)` 签名不变，内部从"5 条种子子串匹配"换成"SQLite FTS5 全文检索"，题库灌入 zero2Agent 384 题。
