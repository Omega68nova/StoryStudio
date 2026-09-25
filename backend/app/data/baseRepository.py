from __future__ import annotations

from typing import Any


class BaseRepository:
    """Shared persistence boundary for typed repositories."""

    def __init__(self, db: Any) -> None:
        self.db = db
