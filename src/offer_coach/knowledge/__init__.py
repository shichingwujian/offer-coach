"""knowledge 包统一出口：题库解析、灌库、检索。"""

from offer_coach.knowledge.db import (
    RetrievalMode,
    RetrievalResult,
    build_db,
    build_vectors,
    has_vectors,
    search_for_diagnosis,
    search_questions,
)
from offer_coach.knowledge.parser import Question, parse_file, parse_markdown

__all__ = [
    "Question",
    "RetrievalMode",
    "RetrievalResult",
    "build_db",
    "build_vectors",
    "has_vectors",
    "parse_file",
    "parse_markdown",
    "search_for_diagnosis",
    "search_questions",
]
