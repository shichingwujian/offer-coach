# offer-coach

为自己打造的面试诊断 Agent：输入面试问答文字稿，输出结构化诊断与改进建议。

手写 Harness 架构（Tools / Skills / Query Engine / Context / Memory / …），不依赖 LangChain / LangGraph。

## 致谢与血缘

- 架构与题库参考 [zero2Agent](https://github.com/ranxi2001/zero2Agent)（MIT）
- 实现设计参考 [OfferPilot](https://github.com/ranxi2001/OfferPilot)（MIT）
- 本项目为用 Python 重新实现的个人学习项目，非 fork

## 快速开始

```bash
pip install -e ".[dev]"
cp .env.example .env   # 填入你的 key
pytest
offer-coach hello
```

## 目录

```
offer-coach/
├── CLAUDE.md                  ← 优化后的 agent.md（含参考实现地图 + 协作协议）
├── .claude/
│   ├── settings.json          ← 权限：允许 pytest/git commit，禁止 push/写.env/写.db
│   └── skills/                ← feature-spec（带三个为什么考试）、pre-commit-check、explain-back
├── progress.md                ← 首行永远是"下次从这里开始"
├── decisions.md               ← 已记 D001（选 Python）、D002（题库复用）两条决策
├── learning/                  ← 讲解验收笔记的家
├── src/offer_coach/           ← engine / knowledge / tools / skills 四层骨架
└── tests/                     ← pytest 已跑通
```

（开发中，后续阶段见 progress.md）
