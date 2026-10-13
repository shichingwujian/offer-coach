"""题库解析器：把 markdown 题库文件切成一道道题（教程 05-knowledge-base）。

题库格式（zero2Agent learn-agent-interview）：
- 文件头是 frontmatter（--- 包着的元信息），跳过
- 每道题以 "## Q：题目" 或 "### Q：题目" 开头（两种层级混用，都算题）
- 正文（新手答/高手答/追问）延续到下一个标题行为止
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

# 题目开头：## 或 ### 后跟 Q：/ Q:（全半角冒号都兼容）
_Q_HEADING = re.compile(r"^#{2,3}\s*Q[：:]\s*")
# 任意 markdown 标题：非题目的标题是当前题的边界
_ANY_HEADING = re.compile(r"^#{1,6}\s")


class Question(BaseModel):
    """一道面试题。category 来自所在目录名（如 01-architecture-design）。"""

    category: str
    title: str
    body: str


def parse_markdown(text: str, category: str) -> list[Question]:
    """把一个 markdown 文件的文本切成题目列表。"""
    lines = text.splitlines()

    # 1. 剥掉 frontmatter：文件开头 --- 到下一个 --- 之间的内容
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1 :]
                break

    questions: list[Question] = []
    title: str | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal title, body_lines
        if title is not None:
            questions.append(
                Question(category=category, title=title, body="\n".join(body_lines).strip())
            )
        title = None
        body_lines = []

    for line in lines:
        if _Q_HEADING.match(line):
            flush()  # 上一道题收工
            title = _Q_HEADING.sub("", line).strip()
        elif _ANY_HEADING.match(line):
            flush()  # 别的标题（大节/小节）：当前题到此为止
        elif title is not None:
            body_lines.append(line)
    flush()
    return questions


def parse_file(path: Path, category: str) -> list[Question]:
    return parse_markdown(path.read_text(encoding="utf-8"), category)
