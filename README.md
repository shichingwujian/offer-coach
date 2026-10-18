# offer-coach

输入面试问答文字稿，输出结构化诊断与改进建议的个人学习项目。

项目重点不是“再接一个模型 API”，而是两件事：

1. **用 Python 手写 Agent Harness**：不依赖 LangChain / LangGraph，自己实现 Provider、工具循环、上下文、Hook、记忆等机制。
2. **用评估集驱动中文检索优化**：所有召回改进都用同一批查询和 Recall@5 复测，不靠“感觉更好了”。

## 核心成果

- 将 **807 道面试题**灌入 SQLite FTS5 知识库，支持按关键词检索参考回答。
- 中文查询预处理后，Recall@5 从 **37.0% 提升到 72.2%**。
- 本地向量召回 + FTS5 + RRF 融合，在评估链路上进一步提升到 **79.6%**。
- **122 项离线自动化测试**：通过 FakeProvider、依赖注入和故障注入覆盖 Agent 行为，无需调用真实模型。

## 诊断工作流程

```text
面试问答文字稿
      │
      ▼
CLI / diagnose Skill（导演剧本）
      │
      ▼
Agent Loop
      ├── analyze_content          → 四个维度评分并引用证据
      ├── query_knowledge_base     → 查询 SQLite FTS5 面试题库
      └── generate_report          → 确定性 Markdown 模板排版
      │
      ▼
结构化诊断报告
```

Agent Loop 负责“模型声明工具调用 → Harness 执行 → 工具结果回填 → 再调模型”的循环，并提供轮数上限和相同动作指纹检测，防止无限执行。

## 架构分层

| 层 | 当前实现 |
|---|---|
| Engine | OpenAI 兼容 Provider、DeepSeek 接入、分类重试、指数退避、成本账本与预算拉闸 |
| Tools | ToolRegistry、工具 Schema、统一错误回传、最小 Agent Loop |
| Skills | `diagnose` 导演剧本：分析 → 查库 → 报告 |
| Knowledge | Markdown 解析、SQLite FTS5、LIKE 短词兜底、拆词预处理、本地向量与 RRF 融合 |
| Context | 死保区 + 滑窗裁剪；工具调用与工具结果成对裁剪，避免孤儿消息 |
| Hooks / Permission | pre/post 插件管线、只读白名单、高风险操作人工确认 |
| Memory / Session | 弱点坐实度、开局召回、诊断摘要、Session 存档与恢复 |
| Evaluation | 分层召回评估集、Recall@K、注入式检索函数；消融代码保留但未形成有效结论 |

## 检索评估

评估集包含 **54 条人工构造查询**，标准答案为题目标题：

- `keyword`（20 条）：题面原词片段
- `paraphrase`（18 条）：换个说法问同一件事
- `scenario`（16 条）：面试现场式转述

**Recall@5** 表示正确题目是否出现在前 5 个检索结果中。

| 查询类型 | 整句短语基线 | 拆词 OR + 加权合并 | 混合召回 + RRF |
|---|---:|---:|---:|
| keyword | 100% | 100% | 100% |
| paraphrase | 0% | 33.3% | **55.6%** |
| scenario | 0% | 81.2% | 81.2% |
| **总计** | **37.0%** | **72.2%** | **79.6%** |

两次改进分别解决不同问题：

- **拆词预处理**：标点切段 → 停词切分 → 长段二字滑窗；每个词分别检索后按标题/正文命中加权合并，解决整句连续匹配造成的漏召。
- **混合召回**：FTS5 负责字面匹配，本地 `bge-small-zh-v1.5` 负责语义召回；RRF 只按两路名次融合，避免直接相加两种不可比的原始分数。

完整的漏网归因和实验记录见 [eval/README.md](eval/README.md)。

> 口径说明：拆词与混合召回已在**检索评估链路**中验证；正式诊断工具目前仍使用基础 FTS5 检索，尚未把混合召回接入主流程。

## 快速开始

要求 Python 3.11+。

```bash
python -m venv .venv
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
# macOS / Linux：source .venv/bin/activate

pip install -e ".[dev]"
pytest
```

### 1. 准备题库

原始 Markdown 题库按“分类子目录 + `index.md`”组织。题库原文和生成的 `questions.db` 不随仓库发布，可以使用自己的题目灌库：

```bash
offer-coach ingest /path/to/question-bank
```

也可以用 `python -m offer_coach.cli` 代替上述 `offer-coach` 命令。

### 2. 运行本地召回评估（无需 API Key）

```bash
offer-coach eval --mode phrase   # 整句短语基线
offer-coach eval --mode terms    # 中文拆词预处理
```

### 3. 可选：本地向量与混合召回评估

```bash
pip install -e ".[vectors]"
offer-coach ingest /path/to/question-bank --vectors
offer-coach eval --mode hybrid
```

向量模型首次运行需要下载。网络无法访问 Hugging Face 时，可设置镜像环境变量：

```powershell
# Windows PowerShell
$env:HF_ENDPOINT="https://hf-mirror.com"
```

向量计算和召回评估均在本地完成，不调用模型 API。

### 4. 运行真实诊断（需要模型 API）

```bash
cp .env.example .env
# 在 .env 中填入自己的 OPENAI_API_KEY；该文件已被 Git 忽略
offer-coach diagnose demo.txt
```

真实诊断会调用模型并产生费用；召回评估和测试不会。

## 项目结构

```text
src/offer_coach/
├── engine/          # Provider、重试、成本账本、QueryEngine
├── tools/           # 工具注册表、执行器、Agent Loop
├── skills/          # diagnose 技能与导演剧本
├── knowledge/       # 题库解析、FTS5、预处理、向量与混合召回
├── context/         # 上下文裁剪
├── hooks/           # pre/post 插件管线
├── memory/          # 长期记忆与开局召回
├── permission/      # 权限闸
└── evaluation/      # 召回评估与实验代码

eval/                # 评估集、结果记录、实验夹具
tests/               # 离线自动化测试
learning/            # 学习笔记与概念复习卡
decisions.md         # 关键技术取舍记录
```

## 已知边界

- 54 条评估集适合发现明显回退，不足以代表所有真实查询；绝对数字应结合查询类型和漏网归因理解。
- 长稿诊断中观察到过 `stuck` / `max_iterations`，端到端稳定性仍需后续修复与真实稿验收。
- 机制消融已停止，现有数据不用于声称题库或导演剧本的端到端贡献。
- 当前仅提供 CLI；未实现 Web UI、部署和 ASR 语音输入。

## 致谢

- 架构与题库参考 [zero2Agent](https://github.com/ranxi2001/zero2Agent)（MIT）
- 实现设计参考 [OfferPilot](https://github.com/ranxi2001/OfferPilot)（MIT）
- 本项目为用 Python 重新实现的个人学习项目，非 fork
