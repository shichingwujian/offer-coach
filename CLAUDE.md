# offer-coach 项目指南

## 项目概述

为自己（28 届求职者）打造的面试诊断 Agent：输入面试问答文字稿，输出结构化诊断与改进建议。
手写 Harness 架构，不依赖 LangChain/LangGraph。

- 架构参考：`../zero2Agent-main/final-project/`（12 篇教程）
- 实现参考：`../OfferPilot-main/`（Go 语言，只读，不照抄）
- 题库来源：`../zero2Agent-main/learn-agent-interview/`（MIT，需在 README 注明）

## 技术栈

- Python ≥ 3.11，src 布局
- LLM：OpenAI 兼容接口（开发期 DeepSeek），`openai` SDK 自封装 retry / 成本日志
- 结构化输出：Pydantic v2
- 存储：SQLite（直接 SQL，不用 ORM；全文检索用 FTS5）
- CLI：typer；测试：pytest
- 单元测试/CI 一律走 FakeProvider，不联网、不烧钱

## 目录结构

```text
src/offer_coach/
  engine/     Query Engine：LLM 客户端、重试、token/成本日志、FakeProvider
  knowledge/  题库解析、SQLite FTS5 检索
  tools/      原子工具：query_knowledge_base / analyze_content / generate_report
  skills/     任务级能力：diagnose_text 等（tools 的有意义组合）
  cli.py      typer 入口
tests/        pytest，与 src 结构对应
learning/     每个阶段的讲解验收笔记（架构图 + 三个为什么）
```

## 开发约定

- 所有公开函数带类型标注；跨模块数据用 Pydantic 模型，不用裸 dict
- 错误分三类：`input_error` / `service_error` / `timeout`，不允许裸 `except Exception` 吞掉
- 每个 LLM 调用必须记录 token 数和成本到日志
- 提交前必走 `pre-commit-check` skill；测试全过才算完成

## 常用命令

```bash
pip install -e ".[dev]"   # 安装（ editable + 测试依赖 ）
pytest                    # 跑全部测试
offer-coach hello         # CLI 冒烟
```

## 禁止项

- 禁止 `git push`（由用户手动执行）
- 禁止写 `.env`、禁止写 `*.db` 文件（由程序运行生成）
- 禁止安装 requirements 之外的新依赖而不先说明理由
- 禁止在代码里硬编码 API key；密钥只从环境变量读

## 环境契约

`.env`（从 `.env.example` 复制）：

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

模型未配置时，涉及真模型的命令必须明确报错，禁止生成机械兜底结果。

## 参考实现地图

| 本仓库模块 | OfferPilot 参考（Go） | 教程 |
|---|---|---|
| engine/ | `OfferPilot-main/backend/internal/llm`、`internal/harness` | final-project/03-query-engine |
| knowledge/ | `OfferPilot-main/backend/internal/knowledge` | final-project/05-knowledge-base |
| tools/ + skills/ | `OfferPilot-main/backend/internal/harness` | final-project/04-tools-skills |

Go 代码只查设计决策，不逐行翻译；教程（中文）优先于代码。

## 协作协议

1. 用户用**业务语言**提需求是预期行为；AI 负责走 `feature-spec` skill 翻译成技术方案
2. 流程：需求澄清 → **前置知识讲解（大白话，锚定用户已懂的代码）** → 技术方案（含影响面）→ 三个为什么考试 → 用户确认 → 实现 → 范读（带着导读读代码）→ 测试 → 更新 progress.md 和 decisions.md
   - 铁律：**没教过的概念不许考**。考试只考讲解过的内容
3. 每完成一个阶段，走 `explain-back` skill 做讲解验收，过了才进下一阶段
4. 测试全过才允许标记完成或建议提交
