from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository


class RuntimeRepository(BaseRepository):
    """Typed access to runtime settings used outside scheduler/process code."""

    def settings(self) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM runtime_settings WHERE id=1"
        ) or {}
        row = dict(row)
        row["llama_extra_args"] = json.loads(
            row.pop("llama_extra_args_json", "[]")
        )
        row["comfy_command"] = json.loads(
            row.pop("comfy_command_json", "[]")
        )
        row["data_dir"] = str(self.db.data_dir)
        return row
