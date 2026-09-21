from __future__ import annotations

import asyncio

import pytest

from app.services.job_handlers import BaseJobHandler


class RecordingHandler(BaseJobHandler):
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.cancels: list[str] = []

    async def run(self, context) -> None:
        self.runs.append(context.job_id)
        context.db.update_job(
            context.job_id,
            "completed",
            result={"ok": True},
        )

    async def cancel(self, context) -> None:
        self.cancels.append(context.job_id)


def test_base_handler_has_noop_cleanup() -> None:
    handler = BaseJobHandler()
    assert handler is not None
