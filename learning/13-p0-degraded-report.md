# 13 | P0-3 降级报告：loop 怎么停，不等于诊断算什么样

> P0-3 学习笔记（含 explain-back 问答记录）。代码在 `src/offer_coach/skills/diagnose.py` 和 `src/offer_coach/cli.py`，138 个离线测试全过；未调用真实 API。

## 一句话本质

`LoopStatus` 只说明模型工具循环**怎么停下来**；`DiagnosisStatus` 才说明用户拿到的结果算 **full / degraded / failed**。降级报告只拼已经成功执行过的工具回执，不再调用模型补写。

## 两层状态

```text
run_loop
  ↓
LoopStatus：completed / stuck / max_iterations / tool_budget_exceeded
  ↓
diagnose_run 判断“还剩什么可用材料”
  ├─ completed + 非空最终回答 → full
  ├─ 非 full + 有成功工具材料 → degraded
  └─ 无成功工具材料 / API 异常 → failed
```

例子：第三次重复查库触发 `stuck`，但前两次查库已经成功。

- `LoopStatus = stuck`：循环确实没走完
- `DiagnosisStatus = degraded`：已有题库材料还能保留
- 不是 `failed`：因为 failed 表示没有可用产物

类比：菜没装盘，但炒好的部分还能端出来；必须贴“不完整”标签。

## 报告正文和中断原因分属两个数据源

```text
trace
  ├─ 哪个 tool_call_id 成功了？
  ├─ 哪个调用 duplicate / budget_exceeded？
  └─ 中断现场摘要

history / messages
  └─ role="tool" 的完整回执正文
```

所以 `_successful_tool_materials()` 的做法是：

1. 从 `trace` 找 `outcome == "success"` 且非空的 `call_id`
2. 再用这些 `call_id` 去 `history` 里取 tool 回执正文

一句话：`trace` 判断“哪份材料可信”，`history` 提供“材料正文”。

## 两个入口的分工

### `diagnose_run() -> DiagnosisResult`

新接口，返回结构化状态：

```python
status: full / degraded / failed
report: 报告文本
reason: 降级或失败原因
iterations: 跑了几轮
loop_status: 底层 loop 怎么停的
```

CLI 和未来真实验收都走这里。

### `diagnose() -> str`

旧接口继续严格：

- `full`：返回报告文本
- `degraded / failed`：抛 `RuntimeError`

原因：旧评估链路只看“有没有返回字符串”。如果旧接口直接返回降级报告，下游会误以为完整成功。

## 降级报告为什么不调模型

降级报告由代码模板拼接，不再发起模型调用：

1. 防止模型把缺失步骤编造成完整结论
2. 避免失败路径继续花钱
3. 避免在已经失败的路径上新增一个失败点

## 三个为什么（验收问答记录）

### Q1：`stuck + 两次成功查库` 为什么是 degraded，不是 failed？

用户一开始不清楚。讲解后结论：`stuck` 只说明循环怎么停；前两次成功查库留下真实材料，所以诊断结果是“不完整但可用”，即 `degraded`。`failed` 是没有可用材料或服务调用失败。

### Q2：为什么要同时看 `trace` 和 `history`？

用户答：“trace 是终止原因，history 是工具调用。”补充精确说法：`trace` 不只记录终止原因，还记录每个 `tool_call_id` 的成功/失败/重复/超预算状态；`history` 里的 tool 消息保存真正回执正文。先用 trace 判断材料可信，再从 history 取正文。

### Q3：为什么旧 `diagnose()` 遇到 degraded 仍然报错？

用户答：“不是本来就报错吗？”表面行为相同，但原因变了：以前是没有降级概念，非 completed 一律报错；现在是旧接口只有字符串返回值，无法表达“不完整”，继续报错是为了防止旧调用方把 degraded 误当 full。

## 本阶段边界

- 已完成：`DiagnosisResult`、`diagnose_run()`、确定性降级报告、CLI 状态提示、session 保留、只有 full 写诊断摘要。
- 未做：真实 API 长稿验收、hybrid 主流程接线、消融/裁判模型。
- 当前可以宣称“非完成循环不再丢掉已有工具材料”；不能宣称真实长稿稳定性已验证。
