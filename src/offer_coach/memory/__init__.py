"""memory 包统一出口：跨会话记忆（档案柜）。"""

from offer_coach.memory.hooks import make_memory_hook
from offer_coach.memory.retriever import recall_block
from offer_coach.memory.store import MemoryEntry, MemoryStore

__all__ = [
    "MemoryEntry",
    "MemoryStore",
    "make_memory_hook",
    "recall_block",
]
