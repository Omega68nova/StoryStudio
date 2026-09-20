from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.database import Database, decode_json_fields, new_id, utc_now
from app.schemas import WorkflowMappings
from app.services.context import (
    messages_tokens,
    suggestion_prompt,
    summary_prompt,
)
from app.services.events import EventHub
from app.services.planning import PlanningService, random_direction_messages, stage_prompt
from app.services.planning_v2 import generated_stage_has_content, merge_generated_batch, normalize_generated_defaults
from app.services.memory import provider_for
from app.services.minigames import MinigameService
from app.services.npc import NpcDirector
from app.services.runtimes import ComfyClient, LlamaClient, ProcessSupervisor, RuntimeFailure
from app.services.inline_tools import InlineToolError, InlineToolParser
from app.services.story_planner import StoryPlanner, cancelable, narrative_messages, parse_json_object
from app.services.workflow import inject_workflow, validate_workflow
from app.services.world import NormalizedMutation, WorldEngine, WorldValidationError


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


def _planning_json_error(raw: str) -> json.JSONDecodeError | None:
    text = raw.strip()
    if text.startswith("```"):
        first_break = text.find("\n")
        text = text[first_break + 1:] if first_break >= 0 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return exc
    return None


def _looks_like_token_truncation(raw: str, error: json.JSONDecodeError) -> bool:
    text = raw.rstrip()
    near_end = error.pos >= max(0, len(text) - 48)
    stack, in_string = _open_json_containers(text)
    return "Unterminated string" in error.msg or (near_end and (in_string or bool(stack)))


def _open_json_containers(text: str) -> tuple[list[tuple[str, int]], bool]:
    stack: list[tuple[str, int]] = []
    in_string, escaped = False, False
    for position, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            stack.append((character, position))
        elif character in "]}":
            if stack:
                stack.pop()
    return stack, in_string


def read_settings(db: Database) -> dict[str, Any]:
    row = db.fetch_one("SELECT * FROM runtime_settings WHERE id = 1") or {}
    row["llama_extra_args"] = json.loads(row.pop("llama_extra_args_json", "[]"))
    row["comfy_command"] = json.loads(row.pop("comfy_command_json", "[]"))
    row["data_dir"] = str(db.data_dir)
    return row


class GenerationScheduler:
    def __init__(self, db: Database, events: EventHub, supervisor: ProcessSupervisor) -> None:
        self.db = db
        self.events = events
        self.supervisor = supervisor
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task[None] | None = None
        self.state = "idle"
        self.current_job_id: str | None = None
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.llama: LlamaClient | None = None
        self.comfy: ComfyClient | None = None
        self.gpu_owner: str | None = None
        self.transition_reason: str | None = None
        self.llama_runtime_mode: str = "normal"
        self.llama_requested_context_tokens: int | None = None
        self.load_count = 0
        self.unload_count = 0
        self._job_metrics: dict[str, dict[str, Any]] = {}
        self._runtime_lock = asyncio.Lock()
        self._scheduled_job_ids: set[str] = set()
        self.world = WorldEngine(db)
        self.planning = PlanningService(db, self.world)
        self.story_planner = StoryPlanner(self.world)
        self.npc_director = NpcDirector(self.world)
        self.minigames = MinigameService(db, self.world)

    async def start(self) -> None:
        if self.worker is None:
            self.worker = asyncio.create_task(self._run(), name="generation-scheduler")
            for row in self.db.fetch_all("SELECT id FROM generation_jobs WHERE status='queued' ORDER BY created_at,id"):
                self.cancel_events[row["id"]] = asyncio.Event()
                self._scheduled_job_ids.add(row["id"])
                await self.queue.put(row["id"])

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        await self.supervisor.shutdown()

    async def enqueue(self, job_id: str) -> None:
        if job_id in self._scheduled_job_ids:
            return
        self._scheduled_job_ids.add(job_id)
        self.cancel_events[job_id] = asyncio.Event()
        await self.queue.put(job_id)
        await self.events.publish("job", {"job_id": job_id, "status": "queued"})

    async def cancel(self, job_id: str) -> None:
        event = self.cancel_events.setdefault(job_id, asyncio.Event())
        event.set()
        job = self.db.get_job(job_id)
        if job and job["status"] == "queued":
            if job.get("payload", {}).get("minigame_session_id"):
                self.db.execute(
                    "UPDATE minigame_sessions SET status='cancelled',updated_at=? WHERE job_id=? AND status='resolved'",
                    (utc_now(), job_id),
                )
            self.db.update_job(job_id, "cancelled")
            self._finish_image_suggestion(job, "cancelled")
            self._finish_planning_stage(job, "cancelled")
            await self.events.publish("job", {"job_id": job_id, "status": "cancelled"})
            if job["kind"] == "image":
                await self.events.publish("image", {"job_id": job_id, "status": "cancelled"})
        elif job and job["status"] == "awaiting_review":
            self.db.execute("UPDATE pending_reviews SET status='rejected',updated_at=? WHERE job_id=? AND status='pending'", (utc_now(), job_id))
            self.db.update_job(job_id, "cancelled", error="Review cancelled by user")
            await self.events.publish("job", {"job_id": job_id, "status": "cancelled"})
        elif job and job["status"] == "awaiting_minigame":
            self.db.execute(
                "UPDATE minigame_sessions SET status='cancelled',updated_at=? WHERE job_id=? AND status IN ('awaiting_input','resolved')",
                (utc_now(), job_id),
            )
            self.db.update_job(job_id, "cancelled", error="Minigame checkpoint cancelled by user")
            await self.events.publish("minigame", {"job_id": job_id, "status": "cancelled"})
            await self.events.publish("job", {"job_id": job_id, "status": "cancelled"})
        elif job and job["status"] in {"running", "switching"} and job["kind"] == "image" and self.comfy:
            await self.comfy.interrupt()

    async def _set_state(self, state: str, job_id: str | None = None, detail: str | None = None) -> None:
        if state not in RUNTIME_STATES:
            raise ValueError(f"Unknown runtime state: {state}")
        self.state = state
        payload = {"state": state, "job_id": job_id}
        if detail:
            payload["detail"] = detail
        if job_id:
            self.db.update_job_progress(job_id, state, detail or state.replace("_", " "))
        await self.events.publish("runtime", payload)

    async def _job_phase(self, job_id: str, phase: str, message: str) -> None:
        metrics = self._job_metrics.setdefault(job_id, {"model_request_count": 0, "phase_durations_ms": {}})
        now = time.monotonic()
        previous = metrics.pop("_phase", None)
        started = metrics.pop("_phase_started", None)
        if previous and started is not None:
            metrics["phase_durations_ms"][previous] = round((now - started) * 1000)
        metrics["_phase"] = phase
        metrics["_phase_started"] = now
        self._save_metrics(job_id)
        self.db.update_job_progress(job_id, phase, message)
        await self.events.publish("job", {"job_id": job_id, "status": "running", "stage": phase, "message": message})

    def _save_metrics(self, job_id: str) -> None:
        metrics = {key: value for key, value in self._job_metrics.get(job_id, {}).items() if not key.startswith("_")}
        self.db.update_job_metrics(job_id, metrics)

    def _model_request(self, job_id: str) -> None:
        metrics = self._job_metrics.setdefault(job_id, {"model_request_count": 0, "phase_durations_ms": {}})
        metrics["model_request_count"] = int(metrics.get("model_request_count", 0)) + 1
        self._save_metrics(job_id)

    def _finalize_metrics(self, job_id: str) -> None:
        metrics = self._job_metrics.get(job_id)
        if not metrics:
            return
        now = time.monotonic()
        previous, started = metrics.pop("_phase", None), metrics.pop("_phase_started", None)
        if previous and started is not None:
            metrics["phase_durations_ms"][previous] = round((now - started) * 1000)
        metrics["load_count"] = self.load_count - int(metrics.pop("load_count_at_start", self.load_count))
        metrics["unload_count"] = self.unload_count - int(metrics.pop("unload_count_at_start", self.unload_count))
        self._save_metrics(job_id)

    async def _ensure_runtimes(self) -> tuple[LlamaClient, ComfyClient]:
        # Runtime health is independent: a broken ComfyUI connection must not
        # erase knowledge that llama.cpp still owns the GPU.
        llama = await self._ensure_llama_runtime("normal")
        comfy = await self._ensure_comfy_runtime()
        return llama, comfy

    async def _ensure_llama_runtime(self, runtime_mode: str = "normal") -> LlamaClient:
        async with self._runtime_lock:
            settings = read_settings(self.db)
            requested_context = int(
                settings.get("planning_context_tokens", settings.get("context_tokens", 8192))
                if runtime_mode == "planning" else settings.get("context_tokens", 8192)
            )
            if hasattr(self.supervisor, "ensure_llama"):
                self.llama = await self.supervisor.ensure_llama(settings, requested_context)
            elif self.llama and await self.llama.health():
                pass
            else:  # compatibility with integrations using the original supervisor contract
                self.llama, discovered_comfy = await self.supervisor.ensure_started(settings)
                self.comfy = self.comfy or discovered_comfy
            properties = await self.llama.runtime_properties(autoload=True) if hasattr(self.llama, "runtime_properties") else None
            effective_context = (properties or {}).get("effective_context_tokens")
            if effective_context is not None and int(effective_context) < requested_context:
                ownership = "StoryStudio-managed" if getattr(self.supervisor, "manages_llama", False) else "external"
                raise RuntimeFailure(
                    f"The {ownership} llama.cpp server provides {int(effective_context):,} context tokens, "
                    f"but {runtime_mode} generation requests {requested_context:,}. "
                    "Increase the server context or lower the corresponding Runtime Settings value."
                )
            ownership_known = hasattr(self.supervisor, "manages_llama")
            if runtime_mode == "planning" and ownership_known and not self.supervisor.manages_llama and effective_context is None:
                raise RuntimeFailure(
                    "The external llama.cpp server did not report its effective context through /props. "
                    "Update llama.cpp before using raw planning autocomplete."
                )
            self.llama_runtime_mode = runtime_mode
            self.llama_requested_context_tokens = requested_context
            return self.llama

    async def _ensure_comfy_runtime(self) -> ComfyClient:
        async with self._runtime_lock:
            if self.comfy and await self.comfy.health():
                return self.comfy
            settings = read_settings(self.db)
            if hasattr(self.supervisor, "ensure_comfy"):
                self.comfy = await self.supervisor.ensure_comfy(settings)
            else:
                discovered_llama, self.comfy = await self.supervisor.ensure_started(settings)
                self.llama = self.llama or discovered_llama
            return self.comfy

    async def warm_storyteller(self) -> None:
        """Best-effort startup warm-up; failures are reported but never stop the app."""
        settings = read_settings(self.db)
        model_id = settings.get("storyteller_model_id") or Path(settings.get("storyteller_model_path", "")).stem
        configured = Path(settings.get("llama_executable", "")).is_file() and Path(settings.get("storyteller_model_path", "")).is_file()
        if not model_id:
            return
        existing = LlamaClient(settings.get("llama_url", "http://127.0.0.1:8080"), model_id)
        if not configured and not await existing.health():
            return
        try:
            self.transition_reason = "application startup warm-up"
            await self._ensure_storyteller()
            if self.current_job_id is None:
                await self._set_state("idle")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = f"Storyteller startup failed: {exc}"
            if self.current_job_id is None:
                await self._set_state("runtime_error", detail=message)
            await self.events.publish("error", {"source": "storyteller_startup", "message": message})

    async def _ensure_storyteller(
        self, job_id: str | None = None, runtime_mode: str = "normal"
    ) -> tuple[LlamaClient, ComfyClient | None]:
        llama = await self._ensure_llama_runtime(runtime_mode)
        status = await llama.model_status() if hasattr(llama, "model_status") else None
        ready = status in {"loaded", "running", "ready"}
        should_load = not ready if status is not None else self.gpu_owner != "storyteller"
        if should_load:
            await self._set_state("loading_storyteller", job_id)
            self.transition_reason = "storyteller requested while model was unloaded"
            await llama.load()
            self.load_count += 1
        self.gpu_owner = "storyteller"
        return llama, self.comfy

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            self.current_job_id = job_id
            cancel_event = self.cancel_events.setdefault(job_id, asyncio.Event())
            job = self.db.get_job(job_id)
            if not job or job["status"] == "cancelled" or cancel_event.is_set():
                self.queue.task_done()
                self.current_job_id = None
                continue
            self.db.update_job(job_id, "running")
            await self.events.publish("job", {"job_id": job_id, "status": "running"})
            try:
                if job["kind"] == "story":
                    await self._story(job, cancel_event)
                elif job["kind"] == "image":
                    await self._image(job, cancel_event)
                else:
                    await self._planning(job, cancel_event)
            except asyncio.CancelledError:
                if self.worker and asyncio.current_task() is self.worker and not cancel_event.is_set():
                    raise
                self.db.update_job(job_id, "cancelled")
                self._finish_image_suggestion(job, "cancelled")
                self._finish_planning_stage(job, "cancelled")
                if job.get("payload", {}).get("minigame_session_id"):
                    self.db.execute(
                        "UPDATE minigame_sessions SET status='cancelled',updated_at=? WHERE job_id=? AND status='resolved'",
                        (utc_now(), job_id),
                    )
                self._discard_materialized_input(job)
                await self.events.publish("job", {"job_id": job_id, "status": "cancelled"})
                if job["kind"] == "image":
                    await self.events.publish("image", {"job_id": job_id, "status": "cancelled"})
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                self.db.update_job(job_id, "failed", error=message)
                self._finish_image_suggestion(job, "failed")
                self._finish_planning_stage(job, "failed")
                await self._set_state("runtime_error", job_id, message)
                await self.events.publish("error", {"job_id": job_id, "message": message})
                if job["kind"] == "image":
                    await self.events.publish("image", {"job_id": job_id, "status": "failed", "error": message})
            finally:
                self._finalize_metrics(job_id)
                self.cancel_events.pop(job_id, None)
                self._scheduled_job_ids.discard(job_id)
                self.current_job_id = None
                self.queue.task_done()
                if self.state != "runtime_error":
                    await self._set_state("idle")

    def _discard_materialized_input(self, job: dict[str, Any]) -> None:
        node_id = job.get("payload", {}).get("user_node_id")
        if not node_id or job.get("payload", {}).get("minigame_session_id"):
            return
        node = self.db.fetch_one("SELECT id,parent_id FROM story_nodes WHERE id=?", (node_id,))
        project = self.db.fetch_one("SELECT active_node_id FROM projects WHERE id=?", (job["project_id"],))
        if not node or not project or project.get("active_node_id") != node_id:
            return
        self.db.execute("UPDATE projects SET active_node_id=?,updated_at=? WHERE id=?", (node.get("parent_id"), utc_now(), job["project_id"]))
        self.db.execute("DELETE FROM story_nodes WHERE id=?", (node_id,))

    def _finish_image_suggestion(self, job: dict[str, Any], status: str) -> None:
        if job["kind"] != "image":
            return
        suggestion_id = job.get("payload", {}).get("suggestion_id")
        if suggestion_id:
            self.db.execute(
                "UPDATE image_suggestions SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), suggestion_id),
            )
        asset_id = job.get("payload", {}).get("media_asset_id")
        if asset_id:
            self.db.execute("UPDATE entity_media_assets SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), asset_id))
        plan_id = job.get("payload", {}).get("planning_image_plan_id")
        if not plan_id and asset_id:
            plan = self.db.fetch_one("SELECT id FROM planning_image_plans WHERE media_asset_id=? AND generation_job_id=?", (asset_id, job["id"]))
            plan_id = plan.get("id") if plan else None
        if plan_id:
            planning_status = "failed" if status in {"failed", "cancelled", "interrupted"} else status
            self.db.execute("UPDATE planning_image_plans SET status=?,error=?,updated_at=? WHERE id=?", (planning_status, job.get("error") or ("Image generation was cancelled" if status == "cancelled" else None), utc_now(), plan_id))

    def _finish_planning_stage(self, job: dict[str, Any], status: str) -> None:
        if job["kind"] != "planning":
            return
        payload = job.get("payload", {})
        self.db.execute(
            "UPDATE planning_stages SET status = ?, active_job_id = NULL, updated_at = ? "
            "WHERE session_id = ? AND stage_number = ? AND active_job_id = ?",
            (status, utc_now(), payload.get("session_id"), payload.get("stage_number"), job["id"]),
        )
        self.db.execute("UPDATE planning_stage_revisions SET status = ?, updated_at = ? WHERE job_id = ?", (status, utc_now(), job["id"]))

    async def _materialize_story_action(self, job: dict[str, Any]) -> bool:
        """Attach queued player input to the shared head only when it reaches the FIFO worker."""
        payload = job.get("payload", {})
        pending = payload.get("pending_action")
        if not pending:
            return False
        now = utc_now()
        with self.db.connect() as connection:
            project = connection.execute("SELECT active_node_id FROM projects WHERE id=?", (job["project_id"],)).fetchone()
            if not project:
                raise RuntimeFailure("Story no longer exists")
            parent_id = project["active_node_id"] if payload.get("use_latest_head", True) else payload.get("requested_parent_id")
            action = str(pending.get("action") or "do")
            content = str(pending.get("content") or "").strip()
            if action == "manual_story":
                node_id = new_id()
                connection.execute(
                    "INSERT INTO story_nodes(id,project_id,parent_id,role,content,status,created_at,pov_character_id,narration_mode,action_kind,author_user_id,author_name_snapshot) "
                    "VALUES(?,?,?,'assistant',?,'complete',?,?,?,'manual_story',?,?)",
                    (node_id, job["project_id"], parent_id, content, now, payload.get("pov_character_id"), payload.get("narration_mode") or "third_limited", job.get("requested_by_user_id"), job.get("requester_name_snapshot")),
                )
                connection.execute("UPDATE projects SET active_node_id=?,updated_at=? WHERE id=?", (node_id, now, job["project_id"]))
                payload["materialized_node_id"] = node_id
                payload.pop("pending_action", None)
                connection.execute("UPDATE generation_jobs SET payload_json=?,updated_at=? WHERE id=?", (json.dumps(payload), now, job["id"]))
                job["payload"] = payload
                node = dict(connection.execute("SELECT * FROM story_nodes WHERE id=?", (node_id,)).fetchone())
            else:
                node_id = new_id()
                connection.execute(
                    "INSERT INTO story_nodes(id,project_id,parent_id,role,content,status,created_at,pov_character_id,narration_mode,action_kind,author_user_id,author_name_snapshot) "
                    "VALUES(?,?,?,'user',?,'complete',?,?,?,?,?,?)",
                    (node_id, job["project_id"], parent_id, content, now, payload.get("pov_character_id"), payload.get("narration_mode") or "third_limited", action, job.get("requested_by_user_id"), job.get("requester_name_snapshot")),
                )
                connection.execute("UPDATE projects SET active_node_id=?,updated_at=? WHERE id=?", (node_id, now, job["project_id"]))
                payload["user_node_id"] = node_id
                payload.pop("pending_action", None)
                connection.execute("UPDATE generation_jobs SET payload_json=?,updated_at=? WHERE id=?", (json.dumps(payload), now, job["id"]))
                job["payload"] = payload
                node = dict(connection.execute("SELECT * FROM story_nodes WHERE id=?", (node_id,)).fetchone())
        await self.events.publish("story", {"job_id": job["id"], "project_id": job["project_id"], "node": node, "source": "player"})
        await self.events.publish("world_head", {"job_id": job["id"], "project_id": job["project_id"], "node_id": node["id"]})
        if action == "manual_story":
            self.db.update_job(job["id"], "completed", result={"story_node_id": node["id"]})
            await self.events.publish("job", {"job_id": job["id"], "project_id": job["project_id"], "status": "completed", "result": {"story_node_id": node["id"]}})
            return True
        return False

    async def _story(self, job: dict[str, Any], cancel_event: asyncio.Event) -> None:
        if await self._materialize_story_action(job):
            return
        llama, _ = await self._ensure_storyteller(job["id"], "normal")
        started = time.monotonic()
        self._job_metrics[job["id"]] = {
            "model_request_count": 0, "phase_durations_ms": {},
            "load_count_at_start": self.load_count, "unload_count_at_start": self.unload_count,
        }
        payload = job["payload"]
        session_ids = list(payload.get("minigame_session_ids") or [])
        if payload.get("minigame_session_id") and payload["minigame_session_id"] not in session_ids:
            session_ids.append(payload["minigame_session_id"])
        resume_sessions = [self.minigames.get_session(str(session_id)) for session_id in session_ids]
        if any(not session or session["status"] not in {"resolved", "committed"} for session in resume_sessions):
            raise RuntimeFailure("A minigame result is not ready to resume")
        resume_sessions = [session for session in resume_sessions if session]
        resume_session = resume_sessions[-1] if resume_sessions else None
        retry_preserved_games = bool(payload.get("retry_preserved_minigames"))
        user_node_id = payload.get("user_node_id")
        head_node_id = resume_session.get("parent_node_id") if resume_session else (user_node_id or payload.get("parent_node_id"))
        path = self.db.story_path(head_node_id)
        user_node = self.db.fetch_one("SELECT * FROM story_nodes WHERE id = ?", (user_node_id,)) if user_node_id else {}
        user_node = user_node or {}
        action = str(payload.get("action") or user_node.get("action_kind") or "do")
        action_prefixes = {
            "say": "The player wants their POV character to say",
            "do": "The player attempts",
            "guide": "The player gives this out-of-story direction",
            "continue": "Continue the current scene naturally",
        }
        instruction = str(payload.get("guidance") or user_node.get("content", ""))
        user_request = action_prefixes.get(action, "Player input") + (f": {instruction}" if instruction else ".")
        pov_character_id = payload.get("pov_character_id") or user_node.get("pov_character_id")
        narration_mode = payload.get("narration_mode") or user_node.get("narration_mode") or "third_limited"
        summary = self._summary_for_path(job["project_id"], path)
        context_limit = int(read_settings(self.db)["context_tokens"])
        custom_instructions = str(payload.get("ai_instructions", "")).strip()
        feedback = "\n".join(value for value in (custom_instructions, str(payload.get("replan_feedback", ""))) if value)
        mode = str(payload.get("generation_mode") or "low")
        if mode not in {"direct", "low", "smart"}:
            mode = "low"
        response_max_tokens = min(1400, max(64, int(payload.get("response_max_tokens") or 300)))

        async def tool_event(update: dict[str, Any]) -> None:
            if update.get("phase") == "model_request":
                self._model_request(job["id"])
            await self.events.publish("tool", {"job_id": job["id"], **update})

        await self._set_state("preparing_context", job["id"])
        await self._job_phase(job["id"], "preparing_context", "Preparing relevant world context")
        raw_mutations = list((resume_session or {}).get("staged_mutations") or payload.get("approved_mutations") or [])
        mutations: list[NormalizedMutation] = []
        scene_intent = str(payload.get("scene_intent") or user_request)
        if raw_mutations:
            mutations = self.world.normalize_mutations(job["project_id"], head_node_id, raw_mutations)
        elif mode != "direct" and not resume_session:
            phase = "thinking_low" if mode == "low" else "thinking_smart"
            await self._set_state(phase, job["id"])
            await self._job_phase(job["id"], phase, "Thinking briefly" if mode == "low" else "Building a detailed scene plan")
            settings = read_settings(self.db)
            memory_provider = provider_for(settings.get("memory_provider", "builtin"), self.db, self.world)
            try:
                semantic_ids = await memory_provider.candidates(job["project_id"], user_request, 12)
            except Exception as exc:
                semantic_ids = []
                await self.events.publish("tool", {"job_id": job["id"], "phase": "memory", "status": "fallback", "message": str(exc)})
            try:
                async with asyncio.timeout(45 if mode == "low" else 180):
                    plan = await self.story_planner.plan(
                        llama, job["project_id"], head_node_id, user_request, pov_character_id,
                        narration_mode, context_limit, tool_event, feedback, semantic_ids, cancel_event,
                        max_rounds=2 if mode == "low" else 4,
                        max_tokens=240 if mode == "low" else 480,
                        time_budget_seconds=45 if mode == "low" else 180,
                    )
                scene_intent = str(plan.get("scene_intent") or user_request)
                raw_mutations = list(plan.get("mutations") or [])
                if raw_mutations:
                    mutations = self.world.normalize_mutations(job["project_id"], head_node_id, raw_mutations)
            except TimeoutError:
                await self.events.publish("notice", {"job_id": job["id"], "message": f"{mode.title()} planning reached its time budget; continuing directly."})
            except WorldValidationError as exc:
                await self.events.publish("notice", {"job_id": job["id"], "message": f"The preliminary plan was omitted: {exc}"})

        requested = payload.get("requested_ability")
        if requested:
            mutations.extend(self.world.normalize_mutations(
                job["project_id"], head_node_id, [{"tool": "useAbility", "arguments": requested}],
                provenance="player", staged=mutations,
            ))
        interventions: list[dict[str, Any]] = list((resume_session or {}).get("interventions") or [])

        package = self.world.context_package(
            job["project_id"], head_node_id, user_request, pov_character_id,
            narration_mode, min(1800, max(700, context_limit // 5)),
        )
        mutation_data = self._serialize_mutations(mutations)
        transient_instruction = user_request if action in {"guide", "continue"} else ""
        messages = narrative_messages(package, path, summary, scene_intent, mutation_data, interventions, transient_instruction)
        if custom_instructions:
            messages[0]["content"] += "\n\n# Project storyteller instructions\nFollow these persistent player-authored directions when they do not conflict with canonical state or safety validation:\n" + custom_instructions[:4000]
        npc_packets, npc_facts = self._npc_packets(job["project_id"], head_node_id, pov_character_id, job["id"])
        eligible_games = [] if retry_preserved_games else self.minigames.eligible_for_prompt(job["project_id"], head_node_id, action, instruction)
        messages[0]["content"] += self._inline_protocol_prompt(npc_packets, eligible_games)
        if retry_preserved_games and resume_sessions:
            messages.append({"role": "user", "content": "Write a complete replacement response informed by these immutable prior challenge results. Do not start another minigame and do not mention this instruction: " + json.dumps([{"invocation": session["invocation"], "result": session["result"]} for session in resume_sessions])})
        elif resume_session:
            messages.extend([
                {"role": "assistant", "content": resume_session["partial_prose"]},
                {"role": "user", "content": "The player completed the challenge. Continue exactly after the partial prose without repeating it. The result is authoritative. You may start a later distinct eligible challenge if the continuing scene requires one. Result: " + json.dumps(resume_session["result"])},
            ])
        prompt_budget = max(1024, context_limit - response_max_tokens - 768)
        messages = self._truncate_messages(messages, prompt_budget)
        count_tokens = getattr(llama, "count_tokens", None)

        async def guarded_prompt_tokens() -> int:
            counted = await count_tokens(messages) if count_tokens else messages_tokens(messages)
            characters = sum(len(str(message.get("content", ""))) for message in messages)
            return max(int(counted) + 384, (characters + 1) // 2)

        prompt_tokens = await guarded_prompt_tokens()
        while prompt_tokens > prompt_budget and len(messages) > 2:
            # Remove oldest branch history while retaining the system packet and
            # the newest player/resume instruction.
            del messages[1]
            prompt_tokens = await guarded_prompt_tokens()
        if prompt_tokens > prompt_budget:
            raise RuntimeFailure(
                f"Story context needs about {prompt_tokens} tokens but only {prompt_budget} are available in the "
                f"configured {context_limit}-token window. StoryStudio already removed older transcript turns. "
                "Reduce Storyteller context instructions or enabled minigames, or increase llama.cpp context size."
            )
        await self._job_phase(
            job["id"], "preparing_context",
            f"Story context {prompt_tokens:,}/{context_limit:,} tokens; reserving up to {response_max_tokens:,} for prose",
        )
        await self._set_state("generating_story", job["id"])
        await self._job_phase(job["id"], "streaming_prose", "Streaming story")
        chunks: list[str] = [resume_session["partial_prose"]] if resume_session and not retry_preserved_games else []
        persisted_chars = len("".join(chunks))
        inline_suggestion: dict[str, str] | None = (resume_session or {}).get("suggestion")
        major_mutations: list[NormalizedMutation] = [mutation for mutation in mutations if mutation.major]
        temporary_ids: dict[str, str] = {}
        repairs = 0
        first_token_at: float | None = None
        checkpoint: dict[str, Any] | None = None
        stop_requested = False
        while True:
            parser = InlineToolParser()
            invalid: dict[str, Any] | None = None
            if repairs:
                await self._set_state("generating_story", job["id"])
                await self._job_phase(job["id"], "streaming_prose", "Streaming corrected continuation")
            self._model_request(job["id"])
            try:
                stream = llama.chat_stream(messages, max_tokens=response_max_tokens, cancel_event=cancel_event)
            except TypeError:
                stream = llama.chat_stream(messages, cancel_event=cancel_event)
            try:
                async for token in stream:
                    visible, calls, parser_errors = parser.feed(token)
                    if visible:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                            self._job_metrics[job["id"]]["time_to_first_token_ms"] = round((first_token_at - started) * 1000)
                            self._save_metrics(job["id"])
                        chunks.append(visible)
                        await self.events.publish("token", {"job_id": job["id"], "text": visible})
                        current_chars = sum(len(part) for part in chunks)
                        if current_chars - persisted_chars >= 256:
                            self.db.update_job_partial_output(job["id"], "".join(chunks))
                            persisted_chars = current_chars
                    for parser_error in parser_errors:
                        invalid = parser_error.payload()
                        break
                    if invalid:
                        break
                    for call in calls:
                        try:
                            await self._set_state("validating_action", job["id"])
                            await self._job_phase(job["id"], "validating_action", f"Validating {call['name']}")
                            result = self._accept_inline_action(
                                job, head_node_id, call, mutations, major_mutations,
                                interventions, npc_packets, npc_facts, temporary_ids, action,
                            )
                            if result and result.get("_checkpoint"):
                                checkpoint = result["invocation"]
                            elif result:
                                inline_suggestion = result
                            await self.events.publish("tool", {"job_id": job["id"], "phase": "inline", "tool": call["name"], "status": "accepted"})
                            await self._set_state("generating_story", job["id"])
                            await self._job_phase(job["id"], "streaming_prose", "Streaming story")
                        except WorldValidationError as exc:
                            invalid = self._inline_error(call, exc)
                            await self.events.publish("tool", {"job_id": job["id"], "phase": "inline", "tool": call["name"], "status": "rejected", "error": invalid})
                            break
                        if checkpoint:
                            break
                    if invalid or checkpoint:
                        break
            except asyncio.CancelledError:
                if not cancel_event.is_set():
                    raise
                stop_requested = True
            if stop_requested:
                break
            tail, tail_errors = parser.finish()
            if tail:
                chunks.append(tail)
                await self.events.publish("token", {"job_id": job["id"], "text": tail})
            if not invalid and tail_errors:
                invalid = tail_errors[0].payload()
            if checkpoint:
                self.db.update_job_partial_output(job["id"], "".join(chunks).strip())
                session = self.minigames.create_session(
                    job["project_id"], job["id"], head_node_id, checkpoint, "".join(chunks).strip(),
                    self._serialize_mutations(mutations), interventions, inline_suggestion,
                )
                await self._set_state("awaiting_minigame", job["id"], "Waiting for player")
                await self.events.publish("minigame", {"job_id": job["id"], "status": "awaiting_input", "session": session})
                await self.events.publish("job", {"job_id": job["id"], "status": "awaiting_minigame"})
                return
            if not invalid or repairs >= 2:
                if invalid:
                    await self.events.publish("notice", {"job_id": job["id"], "message": "An invalid world action was omitted after two repair attempts."})
                break
            repairs += 1
            await self._set_state("repairing_action", job["id"])
            await self._job_phase(job["id"], "repairing_action", f"Repairing invalid action ({repairs}/2)")
            await self.events.publish("notice", {"job_id": job["id"], "message": invalid["explanation"] + " The storyteller is continuing with a correction."})
            messages = [*messages, {"role": "assistant", "content": "".join(chunks)}, {
                "role": "user",
                "content": json.dumps({
                    "instruction": "Continue exactly where the partial prose ends. Retry the rejected action safely or omit it. Do not repeat prose.",
                    "validation_error": invalid,
                    "allowed_inline_tools": self._inline_tool_names(),
                }),
            }]
        if stop_requested or cancel_event.is_set():
            stopped_content = self._complete_sentences("".join(chunks))
            if not stopped_content:
                raise asyncio.CancelledError
            await self._commit_stopped_story(
                job, head_node_id, stopped_content, pov_character_id, narration_mode,
                [session["id"] for session in resume_sessions], mutations,
            )
            return
        content = "".join(chunks).strip()
        if not content:
            raise RuntimeFailure("The storyteller returned an empty response")
        self.db.update_job_partial_output(job["id"], content)
        await self._set_state("finalizing_story", job["id"])
        await self._job_phase(job["id"], "finalizing_story", "Saving story and validated actions")
        environment_settings = self.db.fetch_one("SELECT enabled FROM project_environment_settings WHERE project_id=?", (job["project_id"],))
        if environment_settings and environment_settings["enabled"] and not any(item.tool == "setSceneEnvironment" for item in mutations):
            preview = self.world.preview(job["project_id"], head_node_id, mutations)
            focus = preview["entities"].get(pov_character_id)
            if not focus or focus.get("kind") != "character" or not focus.get("state", {}).get("player_controlled"):
                focus = preview["entities"].get(preview.get("focused_character_id"))
            if not focus:
                focus = next((item for item in preview["entities"].values() if item.get("kind") == "character" and item.get("state", {}).get("player_controlled")), None)
            if focus:
                mutations.extend(self.world.normalize_mutations(job["project_id"], head_node_id, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": focus["id"], "player_action": "standing"}}], provenance="system", staged=mutations))
        routine_mutations, major_mutations = self._split_review_mutations(mutations)
        appearances = self._encounter_appearances(job["project_id"], head_node_id, content, routine_mutations)
        assistant, transaction = self.world.commit_story_turn(
            job["project_id"], head_node_id, content, routine_mutations,
            pov_character_id=pov_character_id, narration_mode=narration_mode,
            status="awaiting_resolution" if major_mutations else "complete",
            interventions=interventions, appearances=appearances,
            minigame_session_ids=[session["id"] for session in resume_sessions],
        )
        self._ensure_encounter_assets(job["project_id"], assistant["id"], appearances)
        await self._queue_environment_backgrounds(job["project_id"], assistant["id"], routine_mutations)
        suggestion = self._create_suggestion(assistant, inline_suggestion)
        await self._sync_theme_cue(job["project_id"], routine_mutations)
        result = {"story_node_id": assistant["id"], "suggestion_id": suggestion["id"],
                  "minigame_session_id": resume_session["id"] if resume_session else None,
                  "minigame_session_ids": [session["id"] for session in resume_sessions]}
        if major_mutations:
            review = self._create_review(job, "reconciliation", major_mutations, assistant["id"])
            self.db.update_job(job["id"], "awaiting_review", result=result)
            await self._set_state("awaiting_review", job["id"], review["reason"])
            await self.events.publish("reconciliation_warning", {"job_id": job["id"], "review": review})
        else:
            self.db.update_job(job["id"], "completed", result=result)
        await self.events.publish("story", {"job_id": job["id"], "node": assistant})
        if interventions:
            await self.events.publish("npc", {"job_id": job["id"], "interventions": interventions})
        if appearances:
            await self.events.publish("encounter", {"job_id": job["id"], "appearances": appearances})
        await self.events.publish("suggestion", {"job_id": job["id"], "suggestion": suggestion})
        await self.events.publish("memory_changed", {
            "job_id": job["id"], "transaction_id": transaction["id"], "changes": self._serialize_mutations(routine_mutations),
        })
        await self.events.publish("world_head", {"project_id": job["project_id"], "node_id": assistant["id"]})
        await self.events.publish("job", {
            "job_id": job["id"], "status": "awaiting_review" if major_mutations else "completed", "result": result
        })
        if read_settings(self.db).get("memory_provider") == "cognee":
            asyncio.create_task(self._sync_memory(job["project_id"]), name=f"memory-sync-{job['project_id']}")

    async def _queue_environment_backgrounds(self, project_id: str, story_node_id: str, mutations: list[NormalizedMutation]) -> None:
        settings = self.db.fetch_one("SELECT enabled,auto_generate_backgrounds,background_workflow_id FROM project_environment_settings WHERE project_id=?", (project_id,))
        if not settings or not settings["enabled"] or not settings["auto_generate_backgrounds"] or not settings["background_workflow_id"]:
            return
        from app.services.environment import EnvironmentService
        environment = EnvironmentService(self.db)
        projection = self.world.projection(project_id)
        scene = environment.scene(project_id, projection)
        targets: list[tuple[str, str | None, str | None]] = []
        for mutation in mutations:
            if mutation.tool == "createEntity" and mutation.arguments.get("kind") == "location":
                targets.append((mutation.arguments["entity_id"], None, None))
        if scene.get("location"):
            targets.append((scene["location"]["id"], (scene.get("weather") or {}).get("id"), (scene.get("time_phase") or {}).get("id")))
        for location_id, weather_id, phase_id in dict.fromkeys(targets):
            existing = self.db.fetch_one(
                "SELECT b.id FROM location_backgrounds b WHERE b.project_id=? AND b.location_id=? AND b.weather_id IS ? AND b.time_phase_id IS ?",
                (project_id, location_id, weather_id, phase_id),
            )
            if existing:
                continue
            location = projection["entities"].get(location_id)
            if not location:
                continue
            prompt = environment.composed_background_prompt(project_id, location, weather_id, phase_id)
            asset_id, background_id, now = new_id(), new_id(), utc_now()
            self.db.execute(
                "INSERT INTO entity_media_assets(id,project_id,entity_id,kind,source,status,prompt,featured,source_story_node_id,created_at,updated_at) VALUES(?,?,?,'location','suggested','queued',?,0,?,?,?)",
                (asset_id, project_id, location_id, prompt, story_node_id, now, now),
            )
            self.db.execute(
                "INSERT INTO location_backgrounds(id,project_id,location_id,media_asset_id,weather_id,time_phase_id,position,created_at) VALUES(?,?,?,?,?,?,0,?)",
                (background_id, project_id, location_id, asset_id, weather_id, phase_id, now),
            )
            image_job = self.db.create_job(project_id, "image", {"media_asset_id": asset_id, "preset_id": settings["background_workflow_id"], "values": {"prompt": prompt}, "environment_background_id": background_id})
            await self.enqueue(image_job["id"])

    @staticmethod
    def _inline_tool_names() -> list[str]:
        return [
            "createEntity", "updateEntity", "moveCharacter", "setRelationship", "revealKnowledge",
            "advanceTime", "updatePlotBeat", "adjustStat", "useAbility", "selectTheme",
            "npcIntervention", "suggestIllustration",
            "startMinigame",
            "setSceneEnvironment", "proposeWeather",
        ]

    async def _sync_theme_cue(self, project_id: str, mutations: list[NormalizedMutation]) -> None:
        cue = next((mutation for mutation in reversed(mutations) if mutation.tool == "selectTheme"), None)
        if not cue:
            return
        theme_id = cue.arguments.get("theme_id")
        theme = self.db.fetch_one("SELECT id,name FROM music_themes WHERE id=?", (theme_id,))
        track = self.db.fetch_one("SELECT id,title FROM music_tracks WHERE theme_id=? ORDER BY position,title LIMIT 1", (theme_id,))
        if not theme or not track:
            return
        now = utc_now()
        self.db.execute(
            "INSERT INTO project_music_playback(project_id,theme_id,track_id,revision,updated_by_name_snapshot,updated_at) "
            "VALUES(?,?,?,1,'Storyteller',?) ON CONFLICT(project_id) DO UPDATE SET theme_id=excluded.theme_id,track_id=excluded.track_id,"
            "revision=project_music_playback.revision+1,updated_by_user_id=NULL,updated_by_name_snapshot='Storyteller',updated_at=excluded.updated_at",
            (project_id, theme_id, track["id"], now),
        )
        await self.events.publish("music", {
            "project_id": project_id, "action": "playback_changed", "shared_theme_id": theme_id,
            "current_track_id": track["id"], "playback_updated_by": "Storyteller",
            "theme_name": theme["name"], "track_title": track["title"],
        })

    def _inline_protocol_prompt(self, npc_packets: list[dict[str, Any]], eligible_games: list[dict[str, Any]] | None = None) -> str:
        compact_games = []
        for game in eligible_games or []:
            # The full UI configuration is intentionally not a prompt schema:
            # repeating actor/target/tag policy for every enabled game can use
            # most of an 8K context window before prose begins.
            compact_games.append({key: value for key, value in {
                "game_key": game.get("game_key"),
                "description": str(game.get("description") or "")[:140],
                "group": game.get("group"),
                "recommended": bool(game.get("recommended")),
                "difficulty": game.get("difficulty"),
                "participant_ids": [item.get("id") for item in list(game.get("participants") or [])[:3]],
                "actor_ids": [item.get("id") for item in list(game.get("actors") or [])[:4]],
                "timer_policy": game.get("timer_policy"),
                "attempt_guidance": game.get("attempt_guidance"),
                "parameter_guidance": game.get("parameter_guidance"),
                "combat_guidance": game.get("combat_guidance"),
            }.items() if value not in (None, [], {}, "")})
        return (
            "\n\n# Hidden inline actions\nStream the requested story immediately. When a canonical world change is explicit, "
            "insert a hidden literal JSON envelope: <ss-tool>{\"name\":\"updateEntity\",\"arguments\":{...}}</ss-tool>. "
            "Never show or explain these envelopes. Do not use expressions such as rnd(1,5). Allowed names: "
            + ", ".join(self._inline_tool_names())
            + ". New entities may include a temporary key that later actions reference. NPC packets: "
            + json.dumps(npc_packets)
            + ". You may pause more than once in a turn at separate uncertain player-facing actions with startMinigame, but only one challenge may be unresolved at a time and only using this eligible catalog: "
            + json.dumps(compact_games, separators=(",", ":"))
            + ". Any listed game may be requested at any point in the response, regardless of composer action. Entries marked recommended matched the current action, configured preference, or wording. Prefer a recommended entry when it represents the unresolved action; categories are browsing aids, not outcomes."
            + ". Copy IDs exactly from that catalog. actor_id is whoever performs the action; participant_id is the player-controlled character playing the challenge. Use optional target_id, integer difficulty, challenge_text, and boolean timed. For lockpicking only, attempt_limit may be 1 through 10 or null for infinite when the catalog permits it; canonical inventory overrides it. For circled_teeth only, the catalog lists optional teeth, empty_slots, time_seconds, and reverse_on_success overrides. For timed_attack, supply an owned ability_key when its profile fits; otherwise supply line_count and damage_per_line within the fallback range. For dodge_box, choose exactly one listed attack_id and supply hp or enemy_attack only when its catalog value is null. The system resolves player or enemy-forced modes and skills; never invent them. Omit other overrides unless they improve the scene and never exceed catalog ranges. "
            + "If the player explicitly asks to flip a coin, roll a die, perform a timing action, rapidly exert effort, fish, hold/release through changing danger signals, pick a lock, hack a circuit, operate a rotating circular lock, perform a timing-dependent attack, or evade an incoming attack and the matching game is eligible, you MUST call startMinigame and MUST NOT narrate or invent its outcome. In calm situations use timed=false; use timed=true only for pursuit, combat pressure, alarms, or high security. "
            + "The same rule applies to uncertainty you introduce yourself: if you make an enemy attack the player and dodge_box is listed, start that challenge before resolving the attack; likewise use an appropriate listed challenge before resolving newly introduced hacking, lockpicking, strength, reflex, fishing, chance, or player-attack tests. "
            + "If the catalog is empty, never call startMinigame. Place startMinigame exactly where the outcome becomes uncertain and write no prose after it. Example envelope: "
            + "<ss-tool>{\"name\":\"startMinigame\",\"arguments\":{\"game_key\":\"flip_coin\",\"actor_id\":\"copy-valid-actor-id\",\"participant_id\":\"copy-valid-participant-id\",\"target_id\":null,\"difficulty\":1,\"challenge_text\":\"Call the coin toss\"}}</ss-tool>. "
            + "Illustration prompts may reference known entities as {{Exact Name}} so their historical visual cards are expanded before image generation."
        )

    @staticmethod
    def _complete_sentences(content: str) -> str:
        """Keep streamed prose through its final completed period."""
        end = content.rfind(".")
        return content[:end + 1].strip() if end >= 0 else ""

    async def _commit_stopped_story(
        self, job: dict[str, Any], head_node_id: str | None, content: str,
        pov_character_id: str | None, narration_mode: str, minigame_session_ids: list[str],
        mutations: list[NormalizedMutation],
    ) -> None:
        await self._set_state("finalizing_story", job["id"])
        await self._job_phase(job["id"], "finalizing_story", "Saving completed sentences")
        assistant, transaction = self.world.commit_story_turn(
            job["project_id"], head_node_id, content, mutations, pov_character_id=pov_character_id,
            narration_mode=narration_mode, interventions=[], appearances=[],
            minigame_session_ids=minigame_session_ids,
        )
        result = {"story_node_id": assistant["id"], "suggestion_id": None,
                  "minigame_session_id": minigame_session_ids[-1] if minigame_session_ids else None,
                  "minigame_session_ids": minigame_session_ids, "stopped": True}
        self.db.update_job(job["id"], "completed", result=result)
        await self.events.publish("story", {"job_id": job["id"], "node": assistant, "stopped": True})
        await self.events.publish("world_head", {"project_id": job["project_id"], "node_id": assistant["id"]})
        await self.events.publish("memory_changed", {"job_id": job["id"], "transaction_id": transaction["id"], "changes": []})
        await self.events.publish("job", {"job_id": job["id"], "status": "completed", "result": result})

    def _npc_packets(self, project_id: str, head_node_id: str | None, pov_character_id: str | None, turn_key: str) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
        candidates = self.npc_director.eligible(project_id, head_node_id, pov_character_id, turn_key)
        facts_by_npc: dict[str, set[str]] = {}
        packets = []
        for npc in candidates:
            facts = self.world.search(project_id, "", head_node_id=head_node_id, pov_character_id=npc["id"], narration_mode="third_limited", kinds=["fact"], limit=30)
            facts_by_npc[npc["id"]] = {fact["id"] for fact in facts}
            packets.append({
                "npc_id": npc["id"], "name": npc["name"], "personality": npc.get("state", {}).get("personality", ""),
                "appearance": npc.get("state", {}).get("appearance", ""),
                "known_fact_ids": sorted(facts_by_npc[npc["id"]])[:12],
            })
        return packets, facts_by_npc

    def _accept_inline_action(
        self, job: dict[str, Any], head_node_id: str | None, call: dict[str, Any],
        mutations: list[NormalizedMutation], major_mutations: list[NormalizedMutation],
        interventions: list[dict[str, Any]], npc_packets: list[dict[str, Any]], npc_facts: dict[str, set[str]],
        temporary_ids: dict[str, str],
        action: str,
    ) -> dict[str, Any] | None:
        name, arguments = call["name"], dict(call.get("arguments") or {})
        for key, value in list(arguments.items()):
            if key.endswith("_id") and isinstance(value, str) and value in temporary_ids:
                arguments[key] = temporary_ids[value]
        if "rnd(" in json.dumps(arguments).casefold():
            raise WorldValidationError("Expressions are not allowed; provide literal values only")
        if name == "startMinigame":
            existing = self.db.fetch_one(
                "SELECT id FROM minigame_sessions WHERE job_id=? AND status='awaiting_input'", (job["id"],),
            )
            if existing:
                raise WorldValidationError("Resolve the current minigame before starting another")
            invocation = self.minigames.validate_invocation(job["project_id"], head_node_id, action, arguments, mutations)
            return {"_checkpoint": True, "invocation": invocation}
        if name == "suggestIllustration":
            prompt = str(arguments.get("prompt", "")).strip()
            if not prompt:
                raise WorldValidationError("suggestIllustration requires a non-empty prompt")
            return {"title": str(arguments.get("title") or "Illustration")[:200], "prompt": prompt[:20_000],
                    "negative_prompt": str(arguments.get("negative_prompt") or "")[:20_000]}
        if name == "npcIntervention":
            actor_id = str(arguments.get("npc_id") or arguments.get("actor_id") or "")
            allowed = {packet["npc_id"]: packet for packet in npc_packets}
            cited = {str(value) for value in arguments.get("cited_fact_ids", [])}
            if actor_id not in allowed:
                raise WorldValidationError("npcIntervention actor is absent, player-controlled, or not eligible this turn")
            if not cited.issubset(npc_facts.get(actor_id, set())):
                raise WorldValidationError("npcIntervention cites facts unavailable to that NPC")
            dialogue = str(arguments.get("dialogue") or "").strip()
            attempted = str(arguments.get("attempted_action") or "").strip()
            if not dialogue and not attempted:
                raise WorldValidationError("npcIntervention requires dialogue or an attempted action")
            ability = arguments.get("useAbility") or arguments.get("ability") or None
            ability_key = None
            if isinstance(ability, dict) and ability.get("ability_key"):
                ability_args = {"actor_id": actor_id, **ability}
                accepted = self.world.normalize_mutations(
                    job["project_id"], head_node_id, [{"tool": "useAbility", "arguments": ability_args}],
                    provenance="npc", staged=mutations,
                )
                mutations.extend(accepted)
                major_mutations.extend(item for item in accepted if item.major)
                ability_key = str(ability["ability_key"])
            interventions.append({"npc_id": actor_id, "npc_name": allowed[actor_id]["name"], "dialogue": dialogue[:4000],
                                  "attempted_action": attempted[:4000], "cited_fact_ids": sorted(cited), "ability_key": ability_key})
            return None
        if name not in self._inline_tool_names():
            raise WorldValidationError(f"Unknown or read-only inline tool: {name}")
        if name == "useAbility":
            actor_id = str(arguments.get("actor_id") or "")
            actor = self.world.preview(job["project_id"], head_node_id, mutations)["entities"].get(actor_id)
            requested = job.get("payload", {}).get("requested_ability") or {}
            if actor and actor.get("state", {}).get("player_controlled") and (
                requested.get("actor_id") != actor_id or requested.get("ability_key") != arguments.get("ability_key")
            ):
                raise WorldValidationError("A player-controlled character ability requires an explicit player request")
        accepted = self.world.normalize_mutations(
            job["project_id"], head_node_id, [{"tool": name, "arguments": arguments}],
            provenance="storyteller_inline", staged=mutations,
        )
        mutations.extend(accepted)
        major_mutations.extend(item for item in accepted if item.major)
        if name == "createEntity" and arguments.get("key") and accepted:
            temporary_ids[str(arguments["key"])] = str(accepted[0].arguments["entity_id"])
        return None

    @staticmethod
    def _inline_error(call: dict[str, Any], exc: WorldValidationError) -> dict[str, Any]:
        return {
            "tool_name": call.get("name", ""), "error_code": "world_validation_failed",
            "explanation": str(exc), "offending_fields": sorted((call.get("arguments") or {}).keys()),
            "safe_correction_hints": ["Use exact known IDs and literal values, or omit the action."],
        }

    @staticmethod
    def _split_review_mutations(mutations: list[NormalizedMutation]) -> tuple[list[NormalizedMutation], list[NormalizedMutation]]:
        reviewed = [mutation for mutation in mutations if mutation.major]
        blocked_ids = {
            str(mutation.arguments.get("entity_id")) for mutation in reviewed
            if mutation.tool == "createEntity" and mutation.arguments.get("entity_id")
        }
        changed = True
        while changed:
            changed = False
            for mutation in mutations:
                if mutation in reviewed:
                    continue
                encoded = json.dumps(mutation.arguments)
                if any(entity_id in encoded for entity_id in blocked_ids):
                    reviewed.append(mutation)
                    if mutation.tool == "createEntity" and mutation.arguments.get("entity_id"):
                        blocked_ids.add(str(mutation.arguments["entity_id"]))
                    changed = True
        return [mutation for mutation in mutations if mutation not in reviewed], reviewed

    @staticmethod
    def _truncate_messages(messages: list[dict[str, str]], token_budget: int) -> list[dict[str, str]]:
        trimmed = list(messages)
        while messages_tokens(trimmed) > token_budget and len(trimmed) > 3:
            del trimmed[1:3]
        return trimmed

    async def _sync_memory(self, project_id: str) -> None:
        provider = provider_for("cognee", self.db, self.world)
        result = await provider.index_project(project_id)
        if result.get("status") == "failed":
            await self.events.publish("tool", {"phase": "memory", "status": "fallback", **result})

    def _encounter_appearances(self, project_id: str, head_node_id: str, prose: str, mutations: list[NormalizedMutation]) -> list[dict[str, Any]]:
        projection = self.world.preview(project_id, head_node_id, mutations)
        ancestry = {node["id"] for node in self.db.story_path(head_node_id)}
        prior = {row["entity_id"] for row in self.db.fetch_all(
            "SELECT a.entity_id, a.story_node_id FROM scene_appearances a JOIN story_nodes n ON n.id = a.story_node_id WHERE n.project_id = ?", (project_id,)
        ) if row["story_node_id"] in ancestry}
        result = []
        folded = prose.casefold()
        for entity in projection["entities"].values():
            if entity["id"] in prior or entity["kind"] not in {"character", "location"} or entity["name"].casefold() not in folded:
                continue
            outfit_id = entity.get("state", {}).get("active_outfit_id") if entity["kind"] == "character" else None
            result.append({"entity_id": entity["id"], "entity_name": entity["name"], "outfit_id": outfit_id,
                           "encounter_kind": "character" if entity["kind"] == "character" else "location"})
        return result

    def _ensure_encounter_assets(self, project_id: str, story_node_id: str, appearances: list[dict[str, Any]]) -> None:
        now = utc_now()
        for appearance in appearances:
            kinds = ["portrait", "full_body"] if appearance["encounter_kind"] == "character" else ["location"]
            for kind in kinds:
                existing = self.db.fetch_one(
                    "SELECT id FROM entity_media_assets WHERE entity_id = ? AND kind = ? AND COALESCE(outfit_id, '') = COALESCE(?, '') AND featured = 1",
                    (appearance["entity_id"], kind, appearance.get("outfit_id")),
                )
                if existing:
                    continue
                entity = self.world.entity_card(project_id, appearance["entity_id"], story_node_id)
                prompt = entity["card"]["visual_description"] or entity["card"]["compact_text"]
                self.db.execute(
                    "INSERT INTO entity_media_assets(id, project_id, entity_id, outfit_id, kind, source, status, prompt, source_story_node_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'suggested', 'suggested', ?, ?, ?, ?)",
                    (new_id(), project_id, appearance["entity_id"], appearance.get("outfit_id"), kind, prompt, story_node_id, now, now),
                )

    @staticmethod
    def _serialize_mutations(mutations: list[NormalizedMutation]) -> list[dict[str, Any]]:
        return [
            {"tool": mutation.tool, "arguments": mutation.arguments, "major": mutation.major, "reason": mutation.reason}
            for mutation in mutations
        ]

    def _create_review(
        self, job: dict[str, Any], phase: str, mutations: list[NormalizedMutation], story_node_id: str | None
    ) -> dict[str, Any]:
        review_id, now = new_id(), utc_now()
        serialized = self._serialize_mutations(mutations)
        reasons = "; ".join(mutation.reason or mutation.tool for mutation in mutations if mutation.major)
        self.db.execute(
            "INSERT INTO pending_reviews(id, job_id, story_node_id, phase, status, mutations_json, reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (review_id, job["id"], story_node_id, phase, json.dumps(serialized), reasons, now, now),
        )
        return {"id": review_id, "job_id": job["id"], "story_node_id": story_node_id, "phase": phase,
                "status": "pending", "mutations": serialized, "reason": reasons}

    async def _generate_planning_json_raw(
        self, job: dict[str, Any], llama: Any, messages: list[dict[str, str]], context_tokens: int,
        cancel_event: asyncio.Event, stage_label: str, progress: Any,
    ) -> tuple[str, str | None, int, int]:
        """Generate one JSON object and extend token-limited output as a raw prompt prefix."""
        apply_template = getattr(llama, "apply_template", None)
        raw_complete = getattr(llama, "raw_complete_stream", None)
        if not apply_template or not raw_complete:
            raise RuntimeFailure(
                "The configured llama.cpp runtime does not support raw planning autocomplete. "
                "Update llama.cpp so /apply-template, /completion, and /props are available."
            )
        formatted_prompt = await apply_template(messages)
        count_prompt = getattr(llama, "count_prompt_tokens", None)
        prompt_tokens = int(await count_prompt(formatted_prompt)) if count_prompt else max(1, len(formatted_prompt) // 3)
        combined = ""
        last_allowance = 0
        for attempt in range(4):
            if cancel_event.is_set():
                raise asyncio.CancelledError
            full_prompt = formatted_prompt + combined
            used_tokens = int(await count_prompt(full_prompt)) if count_prompt else max(1, len(full_prompt) // 3)
            allowance = context_tokens - used_tokens - 128
            last_allowance = max(0, allowance)
            if allowance < 64:
                self.db.update_job_partial_output(job["id"], combined)
                return combined, (
                    f"{stage_label} exhausted its {context_tokens:,}-token planning context while autocomplete "
                    "was still incomplete. The partial JSON was preserved; use a larger planning context or generate a smaller set."
                ), prompt_tokens, last_allowance
            if attempt:
                await self._job_phase(
                    job["id"], "planning_generating",
                    f"{stage_label}: autocompleting unfinished JSON ({attempt}/3)",
                )
            self._model_request(job["id"])
            result = await raw_complete(
                full_prompt, n_predict=allowance, cache_prompt=True, id_slot=0,
                temperature=0.0 if attempt else None, cancel_event=cancel_event, progress=progress,
                stop_when=lambda suffix: _planning_json_error(combined + suffix) is None,
            )
            suffix = str(result.get("content") or "")
            if not suffix:
                # Clear prompt reuse for one retry so a stale slot or immediate
                # stop token cannot silently produce an empty planning draft.
                self._model_request(job["id"])
                result = await raw_complete(
                    full_prompt, n_predict=allowance, cache_prompt=False, id_slot=0,
                    temperature=0.0 if attempt else None, cancel_event=cancel_event, progress=progress,
                    stop_when=lambda retry_suffix: _planning_json_error(combined + retry_suffix) is None,
                )
                suffix = str(result.get("content") or "")
                if not suffix:
                    details = ", ".join(
                        f"{key}={result.get(key)!r}" for key in
                        ("stop_type", "truncated", "tokens_cached", "tokens_evaluated", "tokens_predicted", "n_ctx")
                    )
                    raise RuntimeFailure(
                        f"{stage_label} returned no raw completion after a cache-free retry ({details})"
                    )
            combined += suffix
            self.db.update_job_partial_output(job["id"], combined)
            metrics = self._job_metrics.setdefault(job["id"], {"model_request_count": 0, "phase_durations_ms": {}})
            metrics["planning_raw_completion"] = {
                "autocomplete_attempt": attempt,
                "tokens_cached": result.get("tokens_cached"),
                "tokens_evaluated": result.get("tokens_evaluated"),
                "tokens_predicted": result.get("tokens_predicted"),
                "effective_context_tokens": result.get("n_ctx") or context_tokens,
                "stop_type": result.get("stop_type"),
                "truncated": bool(result.get("truncated")),
            }
            self._save_metrics(job["id"])
            error = _planning_json_error(combined)
            if error is None:
                return combined, None, prompt_tokens, last_allowance
            stopped_for_limit = bool(result.get("truncated")) or result.get("stop_type") == "limit"
            if not stopped_for_limit and not _looks_like_token_truncation(combined, error):
                return combined, None, prompt_tokens, last_allowance
        return combined, (
            f"{stage_label} remained incomplete after three raw autocomplete attempts. "
            "The partial JSON was preserved for repair."
        ), prompt_tokens, last_allowance

    async def _planning(self, job: dict[str, Any], cancel_event: asyncio.Event) -> None:
        await self._set_state("planning_world", job["id"])
        llama, _ = await self._ensure_storyteller(job["id"], "planning")
        payload = job["payload"]
        if payload.get("action") == "random_direction":
            await self._job_phase(job["id"], "planning_generating", "Inventing a random story direction")
            messages = random_direction_messages(str(payload.get("theme") or ""))
            complete_stream = getattr(llama, "complete_stream", None)
            if complete_stream:
                raw = await complete_stream(messages, max_tokens=600, temperature=1.25, cancel_event=cancel_event)
            else:
                raw = await llama.complete(messages, max_tokens=600, temperature=1.25)
            direction = str(raw or "").strip()
            if not direction:
                raise RuntimeFailure("The storyteller returned an empty random direction")
            result = {"direction": direction, "temperature": 1.25}
            self.db.update_job(job["id"], "completed", result=result)
            await self.events.publish("job", {"job_id": job["id"], "project_id": job["project_id"], "status": "completed", "result": result})
            return
        session, stage, approved = self.planning.stage_for_generation(payload["session_id"], int(payload["stage_number"]))
        stage_number = int(stage["stage_number"])
        stage_name = str(stage["kind"]).replace("_", " ").title()
        stage_label = f"Stage {stage_number}/8 · {stage_name}"
        if stage.get("active_job_id") != job["id"]:
            self.db.update_job(job["id"], "cancelled", error="Superseded planning revision")
            return
        self.db.execute("UPDATE planning_stages SET status = 'generating', updated_at = ? WHERE id = ? AND active_job_id = ?", (utc_now(), stage["id"], job["id"]))
        await self._job_phase(job["id"], "planning_context", f"{stage_label}: preparing compact context")
        if cancel_event.is_set():
            raise asyncio.CancelledError

        async def planning_progress(update: dict[str, Any]) -> None:
            message = f"{stage_label}: generating structured draft"
            if update.get("tokens_cached") is not None or update.get("tokens_evaluated") is not None:
                message += (
                    f"; cached {int(update.get('tokens_cached') or 0):,}, "
                    f"evaluated {int(update.get('tokens_evaluated') or 0):,} prompt tokens"
                )
            self.db.update_job_progress(job["id"], "planning_generating", message, update.get("value"), update.get("max"))
            await self.events.publish("job", {
                "job_id": job["id"], "status": "running", "stage": "planning_generating",
                "message": message, "value": update.get("value"), "max": update.get("max"),
            })

        count_prompt_tokens = getattr(llama, "count_prompt_tokens", None)
        apply_template = getattr(llama, "apply_template", None)
        if not count_prompt_tokens or not apply_template:
            raise RuntimeFailure(
                "The configured llama.cpp runtime is missing raw planning autocomplete support. "
                "Update llama.cpp before generating structured planning stages."
            )
        context_tokens = int(read_settings(self.db).get("planning_context_tokens", read_settings(self.db)["context_tokens"]))
        desired_outputs = {1: 1000, 2: 2300, 3: 2400, 4: 1900, 5: 2200, 6: 2200, 7: 1800}
        desired_output = desired_outputs.get(stage_number, 900)
        focus = str(payload.get("focus") or "") or None
        append = bool(payload.get("append"))
        if append:
            desired_output = min(desired_output, 1200)
        if payload.get("repair"):
            desired_output = max(desired_output, 1200)
        if context_tokens < 2048:
            raise RuntimeFailure(
                f"The configured llama.cpp context ({context_tokens} tokens) is too small for preplanning. "
                "Use at least 2048 tokens in Runtime Settings."
            )
        # /tokenize commonly counts plain content but not the chat template. A
        # conservative character estimate and safety reserve prevent the server
        # from discovering an oversized prompt only after dispatch.
        available_prompt = max(768, context_tokens - desired_output - 768)
        character_budget = max(3_500, available_prompt * 2)
        inventory = self.planning.world_inventory(session["project_id"], include_catalogs=stage_number == 7, session_id=session["id"])
        repair_text = str(stage.get("raw_draft_text") or "") if payload.get("repair") else ""
        existing_draft = json.loads(stage["draft_json"]) if append and stage.get("draft_json") else None
        messages = stage_prompt(stage, session, approved, inventory, character_budget=character_budget, repair_text=repair_text,
                                focus=focus, existing_draft=existing_draft)
        await self._job_phase(job["id"], "planning_budget", f"{stage_label}: checking context budget")
        formatted_prompt = await apply_template(messages)
        prompt_tokens = int(await count_prompt_tokens(formatted_prompt))
        while prompt_tokens > available_prompt and character_budget > 3_500:
            character_budget = max(3_500, int(character_budget * 0.72))
            messages = stage_prompt(stage, session, approved, inventory, character_budget=character_budget, repair_text=repair_text,
                                    focus=focus, existing_draft=existing_draft)
            formatted_prompt = await apply_template(messages)
            prompt_tokens = int(await count_prompt_tokens(formatted_prompt))
        # max_tokens remains a required llama.cpp safety boundary, but no
        # longer imposes an arbitrary per-stage output cap. Streaming ends as
        # soon as the complete response parses as one JSON object.
        max_tokens = context_tokens - prompt_tokens - 512
        if max_tokens < 256:
            raise RuntimeFailure(
                f"{stage_label} needs about {prompt_tokens} prompt tokens, leaving too little of the "
                f"configured {context_tokens}-token context for a useful answer. Shorten the workshop direction "
                "or stage notes, clear unusually large approved drafts, or increase llama.cpp context size."
            )
        self.db.update_job_progress(
            job["id"], "planning_budget",
            f"{stage_label}: context {prompt_tokens:,}/{context_tokens:,} tokens; reserving up to {max_tokens:,} for the draft",
        )
        await self.events.publish("job", {
            "job_id": job["id"], "status": "running", "stage": "planning_budget",
            "message": f"{stage_label}: context {prompt_tokens:,}/{context_tokens:,} tokens; reserving up to {max_tokens:,} for the draft",
        })
        await self._job_phase(job["id"], "planning_generating", f"{stage_label}: generating structured draft")
        raw, generation_error, prompt_tokens, remaining_tokens = await self._generate_planning_json_raw(
            job, llama, messages, context_tokens, cancel_event, stage_label, planning_progress,
        )
        validation_error: WorldValidationError | None = None
        draft: dict[str, Any] = {}
        for empty_attempt in range(3):
            await self._job_phase(job["id"], "planning_validating", f"{stage_label}: validating generated structure")
            batch_has_content = False
            if generation_error:
                validation_error = WorldValidationError(generation_error)
                break
            try:
                draft = parse_json_object(raw)
                normalize_generated_defaults(stage_number, draft)
                if append:
                    batch_has_content = generated_stage_has_content(stage_number, draft, focus)
                    if batch_has_content:
                        draft = merge_generated_batch(stage_number, existing_draft or {}, draft, str(focus))
                self.planning.validate_draft(draft, stage_number, json.loads(session["settings_json"]))
            except WorldValidationError as exc:
                validation_error = exc
                if not append or batch_has_content:
                    break
            if (batch_has_content if append else generated_stage_has_content(stage_number, draft)):
                validation_error = None
                break
            if empty_attempt >= 2:
                validation_error = WorldValidationError(f"{stage_label} returned no usable stage resources after three attempts")
                break
            await self._job_phase(job["id"], "planning_generating", f"{stage_label}: retrying an empty or incomplete stage ({empty_attempt + 2}/3)")
            retry_messages = [*messages, {
                "role": "user",
                "content": (
                    f"Your previous answer contained no usable {focus or 'stage resources'} or returned only one nested record. "
                    "Generate the requested root object now, following the supplied JSON shape."
                ),
            }]
            self._model_request(job["id"])
            raw, generation_error, _, _ = await self._generate_planning_json_raw(
                job, llama, retry_messages, context_tokens, cancel_event, stage_label, planning_progress,
            )
        if validation_error:
            error = str(validation_error)
            if not self.planning.save_invalid_generated_draft(stage["id"], job["id"], raw, error):
                self.db.update_job(job["id"], "cancelled", error="Superseded planning revision")
                return
            self.db.update_job(job["id"], "completed", result={
                "stage_id": stage["id"], "invalid_structured_output": True, "validation_error": error,
            })
            await self.events.publish("planning", {
                "job_id": job["id"], "session_id": payload["session_id"], "stage_number": stage_number,
                "status": "ready", "raw_draft": raw, "validation_error": error,
            })
            await self.events.publish("notice", {
                "job_id": job["id"],
                "message": "The planning response was incomplete. It was preserved for manual editing or AI repair.",
            })
            await self.events.publish("job", {"job_id": job["id"], "status": "completed"})
            return
        current = self.db.fetch_one("SELECT active_job_id FROM planning_stages WHERE id = ?", (stage["id"],))
        if not current or current["active_job_id"] != job["id"]:
            self.db.update_job(job["id"], "cancelled", error="Superseded planning revision")
            return
        if not self.planning.save_generated_draft(stage["id"], job["id"], draft):
            self.db.update_job(job["id"], "cancelled", error="Superseded planning revision")
            return
        await self._job_phase(job["id"], "planning_saving", f"{stage_label}: saving editable draft")
        automation = None
        if payload.get("automate"):
            automation = await self._advance_planning_automation(job, session, stage_number, draft)
        self.db.update_job(job["id"], "completed", result={"stage_id": stage["id"], "automation": automation})
        await self.events.publish("planning", {"job_id": job["id"], "session_id": payload["session_id"],
                                                "stage_number": payload["stage_number"], "draft": draft})
        await self.events.publish("job", {"job_id": job["id"], "status": "completed"})

    async def _advance_planning_automation(
        self, job: dict[str, Any], session: dict[str, Any], stage_number: int, draft: dict[str, Any]
    ) -> dict[str, Any]:
        """Approve an unambiguous draft and enqueue the following stage."""
        conflicts = self.planning.preflight(session["id"], stage_number, draft)
        unresolved = [conflict for conflict in conflicts if not conflict.get("recommended_resolution")]
        if unresolved:
            await self.events.publish("notice", {
                "job_id": job["id"],
                "message": f"Automatic planning paused at stage {stage_number}: resolve {len(unresolved)} existing-world conflict(s).",
            })
            return {"status": "paused_for_conflicts", "count": len(unresolved)}
        resolutions = {
            conflict["entity_key"]: conflict["recommended_resolution"] for conflict in conflicts
            if conflict.get("recommended_resolution")
        }
        self.planning.approve_stage(session["id"], stage_number, draft, resolutions)
        if stage_number >= 7:
            self.planning.prepare_image_stage(session["id"])
            await self.events.publish("notice", {"job_id": job["id"], "message": "Automatic preplanning prepared all eight stages. Images are waiting for review."})
            return {"status": "completed"}

        next_stage = self.db.fetch_one(
            "SELECT * FROM planning_stages WHERE session_id=? AND stage_number>? AND status NOT IN ('approved','skipped') ORDER BY stage_number LIMIT 1",
            (session["id"], stage_number),
        )
        if not next_stage:
            return {"status": "completed"}
        next_number = int(next_stage["stage_number"])
        if next_stage["status"] == "stale":
            await self.events.publish("notice", {"job_id": job["id"], "message": f"Automatic planning paused at stale stage {next_number}. Revalidate, repair, or regenerate it."})
            return {"status": "paused_for_stale_dependency", "stage_number": next_number}
        if next_number == 8:
            self.planning.prepare_image_stage(session["id"])
            return {"status": "completed", "stage_number": 8}
        shared_prompt = str(job.get("payload", {}).get("automation_prompt") or "")
        next_job = self.db.create_job(session["project_id"], "planning", {
            "session_id": session["id"], "stage_number": next_number, "human_prompt": shared_prompt,
            "repair": False, "automate": True, "automation_prompt": shared_prompt,
        })
        now = utc_now()
        self.db.execute(
            "INSERT INTO planning_stage_revisions(id,stage_id,job_id,prompt,status,created_at,updated_at) VALUES(?,?,?,?, 'queued',?,?)",
            (new_id(), next_stage["id"], next_job["id"], shared_prompt, now, now),
        )
        self.db.execute(
            "UPDATE planning_stages SET human_prompt=?,status='queued',active_job_id=?,updated_at=? WHERE id=?",
            (shared_prompt, next_job["id"], now, next_stage["id"]),
        )
        await self.enqueue(next_job["id"])
        return {"status": "queued_next", "stage_number": next_number, "job_id": next_job["id"]}

    def _summary_for_path(self, project_id: str, path: list[dict[str, Any]]) -> dict[str, Any] | None:
        ids = {node["id"] for node in path}
        candidates = self.db.fetch_all(
            "SELECT * FROM branch_summaries WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
        )
        return next((row for row in candidates if row["through_node_id"] in ids), None)

    async def _summarize(
        self, project_id: str, path: list[dict[str, Any]], llama: LlamaClient, cancel_event: asyncio.Event | None = None
    ) -> dict[str, Any]:
        summarized_path = path[:-4]
        content = (await cancelable(llama.complete(summary_prompt(summarized_path)), cancel_event)).strip()
        summary = {
            "id": new_id(),
            "project_id": project_id,
            "leaf_id": path[-1]["id"],
            "through_node_id": summarized_path[-1]["id"],
            "content": content,
            "created_at": utc_now(),
        }
        self.db.execute(
            "INSERT INTO branch_summaries(id, project_id, leaf_id, through_node_id, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            tuple(summary.values()),
        )
        return summary

    def _create_suggestion(self, assistant: dict[str, Any], supplied: dict[str, str] | None = None) -> dict[str, Any]:
        if supplied:
            title = supplied["title"]
            prompt = supplied["prompt"]
            negative = supplied.get("negative_prompt", "")
        else:
            projection = self.world.projection(assistant["project_id"], assistant["id"])
            references = []
            prose = assistant["content"].casefold()
            for entity in projection["entities"].values():
                if entity["name"].casefold() not in prose:
                    continue
                card = self.world.entity_card(assistant["project_id"], entity["id"], assistant["id"])["card"]
                visual = card.get("visual_description", "")
                if visual:
                    references.append(visual)
            title = "Illustration idea"
            prompt = ". ".join([*references[:6], assistant["content"][-1600:]]).strip()
            negative = ""
        suggestion_id, now = new_id(), utc_now()
        self.db.execute(
            "INSERT INTO image_suggestions"
            "(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'suggested', ?, ?)",
            (suggestion_id, assistant["id"], title, prompt, negative, now, now),
        )
        return self.db.fetch_one("SELECT * FROM image_suggestions WHERE id = ?", (suggestion_id,)) or {}

    async def _image(self, job: dict[str, Any], cancel_event: asyncio.Event) -> None:
        payload = job["payload"]
        preset_raw = self.db.fetch_one("SELECT * FROM workflow_presets WHERE id = ?", (payload["preset_id"],))
        if not preset_raw:
            raise RuntimeFailure("The selected workflow preset no longer exists")
        # Validate everything possible before changing GPU ownership. Invalid
        # workflows therefore fail immediately instead of leaving the target queued.
        comfy = await self._ensure_comfy_runtime()
        graph = json.loads(preset_raw["graph_json"])
        mappings = WorkflowMappings.model_validate(json.loads(preset_raw["mappings_json"]))
        mapping_errors = validate_workflow(graph, mappings, await comfy.object_info())
        self.db.execute(
            "UPDATE workflow_presets SET validation_status = ?, validation_error = ?, updated_at = ? WHERE id = ?",
            ("invalid" if mapping_errors else "valid", "; ".join(mapping_errors) or None, utc_now(), payload["preset_id"]),
        )
        if mapping_errors:
            raise RuntimeFailure("Workflow validation failed: " + "; ".join(mapping_errors))
        llama = await self._ensure_llama_runtime(self.llama_runtime_mode)
        await self._set_state("switching_to_image", job["id"])
        self.db.update_job(job["id"], "switching")
        self.transition_reason = "validated image job requires exclusive GPU ownership"
        status = await llama.model_status() if hasattr(llama, "model_status") else None
        if status != "unloaded":
            await llama.unload()
            self.unload_count += 1
        self.gpu_owner = "image"
        failure: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            values = dict(payload["values"])
            values["positive_prompt"] = values.pop("prompt", values.get("positive_prompt", ""))
            rendered = inject_workflow(graph, mappings, values)
            output = rendered.get(mappings.image_output.node_id, {})
            if "filename_prefix" in output.get("inputs", {}) or "saveimage" in str(output.get("class_type", "")).replace("_", "").lower():
                output.setdefault("inputs", {})
                output["inputs"]["filename_prefix"] = f"StoryStudio_{job['id']}"
            await self._set_state("generating_image", job["id"])

            async def progress(update: dict[str, Any]) -> None:
                self.db.update_job_progress(job["id"], "generating_image", "Generating image", update.get("value"), update.get("max"))
                await self.events.publish("job", {"job_id": job["id"], "status": "running", **update})

            outputs = await comfy.run_workflow(
                rendered, mappings.image_output.node_id, progress, cancel_event
            )
            await self._job_phase(job["id"], "saving_image", "Saving generated image")
            paths: list[str] = []
            project_dir = self.db.images_dir / job["project_id"]
            project_dir.mkdir(parents=True, exist_ok=True)
            for index, (data, suffix) in enumerate(outputs):
                path = project_dir / f"{job['id']}-{index}{suffix}"
                path.write_bytes(data)
                paths.append(str(path.relative_to(self.db.data_dir)).replace("\\", "/"))
            if payload.get("suggestion_id"):
                self.db.execute(
                    "UPDATE image_suggestions SET status = 'generated', image_path = ?, updated_at = ? WHERE id = ?",
                    (paths[0], utc_now(), payload["suggestion_id"]),
                )
            if payload.get("media_asset_id"):
                self.db.execute("UPDATE entity_media_assets SET source = 'generated', status = 'generated', file_path = ?, mime_type = ?, updated_at = ? WHERE id = ?", (paths[0], "image/" + paths[0].rsplit(".", 1)[-1].replace("jpg", "jpeg"), utc_now(), payload["media_asset_id"]))
                plan_id = payload.get("planning_image_plan_id")
                if not plan_id:
                    plan = self.db.fetch_one("SELECT id FROM planning_image_plans WHERE media_asset_id=? AND generation_job_id=?", (payload["media_asset_id"], job["id"]))
                    plan_id = plan.get("id") if plan else None
                if plan_id:
                    self.db.execute("UPDATE planning_image_plans SET status='generated',media_asset_id=?,error=NULL,updated_at=? WHERE id=?", (payload["media_asset_id"], utc_now(), plan_id))
            result = {"image_paths": paths, "suggestion_id": payload.get("suggestion_id"), "media_asset_id": payload.get("media_asset_id"),
                      "prompt_references": payload.get("prompt_references", [])}
        except BaseException as exc:
            failure = exc
        finally:
            await self._set_state("restoring_storyteller", job["id"])
            try:
                await comfy.free()
            finally:
                await llama.load()
                self.load_count += 1
                self.gpu_owner = "storyteller"
                self.transition_reason = "image job finished; storyteller restored"
        if failure:
            raise failure
        if result is None:
            raise RuntimeFailure("Image generation finished without a result")
        self.db.update_job_progress(job["id"], "completed", "Image ready", 1, 1)
        self.db.update_job(job["id"], "completed", result=result)
        await self.events.publish("image", {"job_id": job["id"], **result})
        if payload.get("environment_background_id"):
            await self.events.publish("environment", {"project_id": job["project_id"], "action": "background_ready", "background_id": payload["environment_background_id"]})
        await self.events.publish("job", {"job_id": job["id"], "status": "completed", "result": result})
