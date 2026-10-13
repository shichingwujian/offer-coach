"""knowledge 包统一出口：题库解析、灌库、检索。"""

from offer_coach.knowledge.db import build_db, search_questions
from offer_coach.knowledge.parser import Question, parse_file, parse_markdown

__all__ = [
    "Question",
    "build_db",
    "parse_file",
    "parse_markdown",
    "search_questions",
]
