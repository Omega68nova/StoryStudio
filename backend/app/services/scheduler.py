from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from app.database import Database, utc_now
from app.managers.aiManager import AIGeneratorManager
from app.services.events import EventHub
from app.services.job_handlers import JobExecutionContext, JobHandler
from app.services.runtimes import ProcessSupervisor
from app.services.minigames import MinigameService
from app.services.npc import NpcDirector
from app.services.story_planner import StoryPlanner
from app.services.world import WorldEngine


RUNTIME_STATES = {
    "idle",
    "loading_storyteller",
    "generating_story",
    "preparing_context",
    "thinking_low",
    "thinking_smart",
    "validating_action",
    "repairing_action",
    "finalizing_story",
    "switching_to_image",
    "generating_image",
    "restoring_storyteller",
    "runtime_error",
    "planning_world",
    "awaiting_review",
    "awaiting_minigame",
}


def read_settings(db: Database) -> dict[str, Any]:
    """Compatibility helper retained for existing imports in main.py/services."""
    import json

    row = db.fetch_one("SELECT * FROM runtime_settings WHERE id = 1") or {}
    row["llama_extra_args"] = json.loads(row.pop("llama_extra_args_json", "[]"))
    row["comfy_command"] = json.loads(row.pop("comfy_command_json", "[]"))
    row["data_dir"] = str(db.data_dir)
    return row


class GenerationScheduler:
    """DB-backed FIFO dispatcher.

    The scheduler intentionally owns only:
      * queue ordering
      * restart recovery
      * cancellation signalling
      * generic job status transitions
      * runtime-state publication
      * dispatch to one handler per job kind

    Story generation, planning, image persistence, world mutation, NPC logic,
    minigames and prompt construction do not belong here.
    """

    def __init__(
        self,
        db: Database,
        events: EventHub,
        supervisor: ProcessSupervisor,
        handlers: Mapping[str, JobHandler] | None = None,
    ) -> None:
        self.db = db
        self.events = events
        self.supervisor = supervisor

        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task[None] | None = None
        self.state = "idle"
        self.current_job_id: str | None = None

        self.cancel_events: dict[str, asyncio.Event] = {}
        self._scheduled_job_ids: set[str] = set()

        self.ai = AIGeneratorManager(
            lambda: read_settings(self.db),
            supervisor,
            state_callback=self._runtime_transition,
        )

        # Transitional API facades. main.py still references these services
        # through scheduler.*. They remain here through Phase 2 so the
        # scheduler refactor can land without rewriting every API route in
        # the same commit. Phase 3 should inject these directly into routes.
        self.world = WorldEngine(db)
        self.story_planner = StoryPlanner(self.world)
        self.npc_director = NpcDirector(self.world)
        self.minigames = MinigameService(db, self.world)

        # Handlers can be installed after construction so main.py can keep the
        # existing scheduler = GenerationScheduler(...) shape during migration.
        self.handlers: dict[str, JobHandler] = dict(handlers or {})
        if handlers is None:
            # Lazy imports avoid making the scheduler module the owner of
            # handler implementations while retaining drop-in construction.
            from app.handlers.imageJobHandler import ImageJobHandler
            from app.handlers.storyJobHandler import StoryJobHandler
            from app.handlers.batchGenerationJobHandler import BatchGenerationJobHandler

            self.handlers.update({
                "story": StoryJobHandler(),
                "image": ImageJobHandler(),
                "batch_generation": BatchGenerationJobHandler(),
            })

    async def _runtime_transition(
        self,
        state: str,
        detail: str | None = None,
    ) -> None:
        """Bridge AIGeneratorManager transitions into scheduler runtime events."""
        await self._set_state(
            state,
            self.current_job_id,
            detail,
        )

    # ------------------------------------------------------------------
    # Compatibility properties
    # ------------------------------------------------------------------

    @property
    def llama(self):
        return self.ai.llama

    @llama.setter
    def llama(self, value):
        self.ai.llama = value

    @property
    def comfy(self):
        return self.ai.comfy

    @comfy.setter
    def comfy(self, value):
        self.ai.comfy = value

    @property
    def gpu_owner(self) -> str | None:
        # Old code/UI called the text owner "storyteller".
        return "storyteller" if self.ai.gpu_owner == "text" else self.ai.gpu_owner

    @property
    def transition_reason(self) -> str | None:
        return self.ai.transition_reason

    @property
    def llama_runtime_mode(self) -> str:
        return self.ai.llama_runtime_mode

    @property
    def llama_requested_context_tokens(self) -> int | None:
        return self.ai.llama_requested_context_tokens

    @property
    def load_count(self) -> int:
        return self.ai.load_count

    @property
    def unload_count(self) -> int:
        return self.ai.unload_count

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        if not kind:
            raise ValueError("Job handler kind cannot be empty")
        self.handlers[kind] = handler

    def register_handlers(self, handlers: Mapping[str, JobHandler]) -> None:
        for kind, handler in handlers.items():
            self.register_handler(kind, handler)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self.worker is not None:
            return

        self.worker = asyncio.create_task(
            self._run(),
            name="generation-scheduler",
        )

        # Preserve current StoryStudio behavior: queued jobs survive restart.
        for row in self.db.fetch_all(
            "SELECT id FROM generation_jobs "
            "WHERE status='queued' ORDER BY created_at,id"
        ):
            await self._schedule_existing(str(row["id"]))

    async def stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            finally:
                self.worker = None

        await self.ai.shutdown()

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    async def _schedule_existing(self, job_id: str) -> None:
        if job_id in self._scheduled_job_ids:
            return
        self._scheduled_job_ids.add(job_id)
        self.cancel_events.setdefault(job_id, asyncio.Event())
        await self.queue.put(job_id)

    async def enqueue(self, job_id: str) -> None:
        if job_id in self._scheduled_job_ids:
            return

        job = self.db.get_job(job_id)
        if not job:
            raise ValueError(f"Generation job does not exist: {job_id}")

        self._scheduled_job_ids.add(job_id)
        self.cancel_events[job_id] = asyncio.Event()
        await self.queue.put(job_id)

        await self.events.publish(
            "job",
            {
                "job_id": job_id,
                "status": "queued",
            },
        )

    async def cancel(self, job_id: str) -> None:
        cancel_event = self.cancel_events.setdefault(
            job_id,
            asyncio.Event(),
        )
        cancel_event.set()

        job = self.db.get_job(job_id)
        if not job:
            return

        handler = self.handlers.get(str(job["kind"]))
        if handler is not None:
            context = self._context(job, cancel_event)
            await handler.cancel(context)

        # Handler cancellation is responsible for domain-specific cleanup
        # (pending reviews, planning stage state, minigames, assets, etc.).
        # The scheduler owns the generic terminal job state.
        latest = self.db.get_job(job_id) or job
        status = str(latest.get("status") or "")

        if status == "queued":
            self.db.update_job(job_id, "cancelled")
            await self.events.publish(
                "job",
                {
                    "job_id": job_id,
                    "status": "cancelled",
                },
            )

    # ------------------------------------------------------------------
    # Runtime state
    # ------------------------------------------------------------------

    async def _set_state(
        self,
        state: str,
        job_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        if state not in RUNTIME_STATES:
            raise ValueError(f"Unknown runtime state: {state}")

        self.state = state
        payload: dict[str, Any] = {
            "state": state,
            "job_id": job_id,
        }
        if detail:
            payload["detail"] = detail

        if job_id:
            self.db.update_job_progress(
                job_id,
                state,
                detail or state.replace("_", " "),
            )

        await self.events.publish("runtime", payload)

    def _context(
        self,
        job: dict[str, Any],
        cancel_event: asyncio.Event,
    ) -> JobExecutionContext:
        return JobExecutionContext(
            db=self.db,
            events=self.events,
            ai=self.ai,
            job=job,
            cancel_event=cancel_event,
            set_runtime_state=self._set_state,
            enqueue=self.enqueue,
        )

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            self.current_job_id = job_id

            cancel_event = self.cancel_events.setdefault(
                job_id,
                asyncio.Event(),
            )

            try:
                job = self.db.get_job(job_id)

                if (
                    not job
                    or job.get("status") == "cancelled"
                    or cancel_event.is_set()
                ):
                    continue

                kind = str(job.get("kind") or "")
                handler = self.handlers.get(kind)
                if handler is None:
                    raise RuntimeError(
                        f"No generation handler registered for job kind '{kind}'"
                    )

                self.db.update_job(job_id, "running")
                await self.events.publish(
                    "job",
                    {
                        "job_id": job_id,
                        "status": "running",
                    },
                )

                context = self._context(job, cancel_event)
                await handler.run(context)

            except asyncio.CancelledError:
                # Worker shutdown should still cancel the worker itself.
                if (
                    self.worker
                    and asyncio.current_task() is self.worker
                    and not cancel_event.is_set()
                ):
                    raise

                job = self.db.get_job(job_id)
                if job:
                    handler = self.handlers.get(str(job.get("kind") or ""))
                    if handler is not None:
                        await handler.cancel(
                            self._context(job, cancel_event)
                        )

                    latest = self.db.get_job(job_id) or job
                    if latest.get("status") not in {
                        "completed",
                        "failed",
                        "cancelled",
                        "awaiting_review",
                        "awaiting_minigame",
                    }:
                        self.db.update_job(job_id, "cancelled")

                await self.events.publish(
                    "job",
                    {
                        "job_id": job_id,
                        "status": "cancelled",
                    },
                )

            except Exception as exc:
                message = str(exc) or type(exc).__name__
                job = self.db.get_job(job_id)

                if job:
                    handler = self.handlers.get(str(job.get("kind") or ""))
                    if handler is not None:
                        try:
                            await handler.failed(
                                self._context(job, cancel_event),
                                exc,
                            )
                        except Exception as cleanup_exc:
                            await self.events.publish(
                                "error",
                                {
                                    "job_id": job_id,
                                    "source": "handler_failure_cleanup",
                                    "message": str(cleanup_exc),
                                },
                            )

                    latest = self.db.get_job(job_id) or job
                    if latest.get("status") not in {
                        "completed",
                        "failed",
                        "cancelled",
                        "awaiting_review",
                        "awaiting_minigame",
                    }:
                        self.db.update_job(
                            job_id,
                            "failed",
                            error=message,
                        )

                await self._set_state(
                    "runtime_error",
                    job_id,
                    message,
                )
                await self.events.publish(
                    "error",
                    {
                        "job_id": job_id,
                        "message": message,
                    },
                )

            finally:
                self.cancel_events.pop(job_id, None)
                self._scheduled_job_ids.discard(job_id)
                self.current_job_id = None
                self.queue.task_done()

                if self.state != "runtime_error":
                    await self._set_state("idle")
