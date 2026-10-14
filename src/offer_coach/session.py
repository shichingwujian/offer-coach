"""Session：会话存档/读档（教程 07-permission-session）。

把完整历史存成 JSON，长诊断中断后读档接着跑，不用从头再来。
存档含面试稿隐私，sessions/ 目录已加入 .gitignore，不进 git。
"""

from __future__ import annotations

import json
from pathlib import Path

from offer_coach.engine.models import Message


def save_session(path: Path, messages: list[Message]) -> None:
    """把历史存成 JSON 存档。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([m.model_dump() for m in messages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_session(path: Path) -> list[Message]:
    """读档。存档不存在 = 明确报错。"""
    if not path.exists():
        raise FileNotFoundError(f"存档不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Message.model_validate(d) for d in data]
