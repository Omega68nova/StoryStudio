from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.database import Database
from app.managers.aiManager import AIGeneratorManager
from app.services.events import EventHub


RuntimeStateSetter = Callable[
    [str, str | None, str | None],
    Awaitable[None],
]
EnqueueJob = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class JobExecutionContext:
    """Everything a generation handler may use from the scheduler."""

    db: Database
    events: EventHub
    ai: AIGeneratorManager
    job: dict[str, Any]
    cancel_event: asyncio.Event
    set_runtime_state: RuntimeStateSetter
    enqueue: EnqueueJob

    @property
    def job_id(self) -> str:
        return str(self.job["id"])

    @property
    def project_id(self) -> str:
        return str(self.job["project_id"])

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self.job.get("payload") or {})

    async def state(
        self,
        state: str,
        detail: str | None = None,
    ) -> None:
        await self.set_runtime_state(
            state,
            self.job_id,
            detail,
        )


class JobHandler(Protocol):
    """One domain handler per generation job kind."""

    async def run(self, context: JobExecutionContext) -> None:
        ...

    async def cancel(self, context: JobExecutionContext) -> None:
        ...

    async def failed(
        self,
        context: JobExecutionContext,
        error: BaseException,
    ) -> None:
        ...


class BaseJobHandler:
    """Convenient defaults while handlers are migrated one at a time."""

    async def cancel(self, context: JobExecutionContext) -> None:
        return None

    async def failed(
        self,
        context: JobExecutionContext,
        error: BaseException,
    ) -> None:
        return None
