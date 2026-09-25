from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.database import new_id, utc_now
from app.handlers.storyFinalizer import StoryFinalizer
from app.handlers.storyInlineActions import (
    INLINE_TOOL_NAMES,
    StoryInlineActions,
)
from app.managers.environmentManager import EnvironmentManager
from app.managers.storyManager import StoryManager
from app.services.storyStreamService import (
    StoryStreamCallbacks,
    StoryStreamRequest,
    StoryStreamService,
)
from app.services.job_handlers import (
    BaseJobHandler,
    JobExecutionContext,
)
from app.services.minigames import MinigameService
from app.services.npc import NpcDirector
from app.services.runtimes import RuntimeFailure
from app.services.world import (
    WorldEngine,
    WorldValidationError,
)


def _read_settings(
    context: JobExecutionContext,
) -> dict[str, Any]:
    row = (
        context.db.fetch_one(
            "SELECT * FROM runtime_settings WHERE id=1"
        )
        or {}
    )
    row["llama_extra_args"] = json.loads(
        row.pop("llama_extra_args_json", "[]")
    )
    row["comfy_command"] = json.loads(
        row.pop("comfy_command_json", "[]")
    )
    row["data_dir"] = str(context.db.data_dir)
    return row


class StoryJobHandler(BaseJobHandler):
    """Thin job/streaming adapter over the Phase 2 story managers."""

    def __init__(self) -> None:
        self._metrics: dict[str, dict[str, Any]] = {}

    async def run(
        self,
        context: JobExecutionContext,
    ) -> None:
        world = WorldEngine(context.db)
        environment = EnvironmentManager(
            context.db,
            world,
            events=context.events,
        )
        music = environment.music
        story = StoryManager(
            context.db,
            world=world,
            environment=environment,
        )
        npc_director = NpcDirector(world)
        minigames = MinigameService(
            context.db,
            world,
        )
        inline = StoryInlineActions(
            context.db,
            world,
            npc_director,
            minigames,
        )
        finalizer = StoryFinalizer(
            context.db,
            context.events,
            world,
            context.enqueue,
            environment=environment,
            music=music,
        )

        if await self._materialize_story_action(context):
            return

        llama = await context.ai.ensure_text_ready(
            "normal",
            reason="story generation requested",
        )

        started = time.monotonic()
        self._start_metrics(context, started)

        payload = context.payload
        settings = _read_settings(context)

        session_ids = list(
            payload.get("minigame_session_ids") or []
        )
        single_session_id = payload.get(
            "minigame_session_id"
        )
        if (
            single_session_id
            and single_session_id not in session_ids
        ):
            session_ids.append(single_session_id)

        resume_sessions = [
            minigames.get_session(str(session_id))
            for session_id in session_ids
        ]
        if any(
            not session
            or session["status"]
            not in {"resolved", "committed"}
            for session in resume_sessions
        ):
            raise RuntimeFailure(
                "A minigame result is not ready to resume"
            )

        resume_sessions = [
            session
            for session in resume_sessions
            if session
        ]
        resume_session = (
            resume_sessions[-1]
            if resume_sessions
            else None
        )
        retry_preserved_games = bool(
            payload.get("retry_preserved_minigames")
        )

        user_node_id = payload.get("user_node_id")
        head_node_id = (
            resume_session.get("parent_node_id")
            if resume_session
            else (
                user_node_id
                or payload.get("parent_node_id")
            )
        )

        user_node = (
            context.db.fetch_one(
                "SELECT * FROM story_nodes WHERE id=?",
                (user_node_id,),
            )
            if user_node_id
            else {}
        ) or {}

        request = story.build_request(
            project_id=context.project_id,
            payload=payload,
            user_node=user_node,
            head_node_id=head_node_id,
            context_limit=int(settings["context_tokens"]),
        )

        async def tool_event(
            update: dict[str, Any],
        ) -> None:
            if update.get("phase") == "model_request":
                self._model_request(context)
            await context.events.publish(
                "tool",
                {
                    "job_id": context.job_id,
                    **update,
                },
            )

        await context.state("preparing_context")
        await self._job_phase(
            context,
            "preparing_context",
            "Preparing relevant world context",
        )

        has_existing_plan = bool(
            (resume_session or {}).get("staged_mutations")
            or payload.get("approved_mutations")
        )
        if (
            request.generation_mode != "direct"
            and not resume_session
            and not has_existing_plan
        ):
            phase = (
                "thinking_low"
                if request.generation_mode == "low"
                else "thinking_smart"
            )
            await context.state(phase)
            await self._job_phase(
                context,
                phase,
                (
                    "Thinking briefly"
                    if request.generation_mode == "low"
                    else "Building a detailed scene plan"
                ),
            )

        plan = await story.plan_turn(
            llama=llama,
            request=request,
            approved_mutations=list(
                payload.get("approved_mutations") or []
            ),
            resume_mutations=list(
                (resume_session or {}).get("staged_mutations")
                or []
            ),
            interventions=list(
                (resume_session or {}).get("interventions")
                or []
            ),
            tool_event=tool_event,
            cancel_event=context.cancel_event,
            turn_key=context.job_id,
            skip_planning=bool(resume_session),
        )

        npc_packets, npc_facts = inline.npc_packets(
            context.project_id,
            head_node_id,
            request.pov_character_id,
            context.job_id,
        )

        eligible_games = (
            []
            if retry_preserved_games
            else minigames.eligible_for_prompt(
                context.project_id,
                head_node_id,
                request.action,
                request.instruction,
            )
        )

        extra_messages: list[dict[str, str]] = []
        if (
            retry_preserved_games
            and resume_sessions
        ):
            extra_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Write a complete replacement response informed by "
                        "these immutable prior challenge results. Do not "
                        "start another minigame and do not mention this "
                        "instruction: "
                        + json.dumps(
                            [
                                {
                                    "invocation": session["invocation"],
                                    "result": session["result"],
                                }
                                for session in resume_sessions
                            ]
                        )
                    ),
                }
            )
        elif resume_session:
            extra_messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": resume_session["partial_prose"],
                    },
                    {
                        "role": "user",
                        "content": (
                            "The player completed the challenge. Continue "
                            "exactly after the partial prose without "
                            "repeating it. The result is authoritative. "
                            "You may start a later distinct eligible "
                            "challenge if the continuing scene requires "
                            "one. Result: "
                            + json.dumps(resume_session["result"])
                        ),
                    },
                ]
            )

        prepared = await story.prepare_context(
            llama=llama,
            plan=plan,
            inline_protocol=inline.protocol_prompt(
                npc_packets,
                eligible_games,
            ),
            extra_messages=extra_messages,
        )

        messages = prepared.context.messages
        mutations = prepared.plan.mutations
        interventions = prepared.plan.interventions
        action = request.action
        pov_character_id = request.pov_character_id
        narration_mode = request.narration_mode
        response_max_tokens = request.response_max_tokens

        await self._job_phase(
            context,
            "preparing_context",
            (
                f"Story context "
                f"{prepared.context.prompt_tokens:,}/"
                f"{prepared.context.context_limit:,} tokens; "
                f"reserving up to "
                f"{prepared.context.response_max_tokens:,} for prose"
            ),
        )

        await context.state(
            "generating_story"
        )

        major_mutations = [
            mutation
            for mutation in mutations
            if mutation.major
        ]
        temporary_ids: dict[str, str] = {}

        async def stream_phase(
            phase: str,
            message: str,
        ) -> None:
            if phase == "validating_action":
                await context.state(
                    "validating_action"
                )
            elif phase == "repairing_action":
                await context.state(
                    "repairing_action"
                )
            else:
                await context.state(
                    "generating_story"
                )

            await self._job_phase(
                context,
                phase,
                message,
            )

        async def stream_token(
            text: str,
        ) -> None:
            await context.events.publish(
                "token",
                {
                    "job_id": context.job_id,
                    "text": text,
                },
            )

        async def stream_notice(
            message: str,
        ) -> None:
            await context.events.publish(
                "notice",
                {
                    "job_id": context.job_id,
                    "message": message,
                },
            )

        async def stream_tool(
            tool_name: str,
            status: str,
            error: dict[str, Any] | None,
        ) -> None:
            payload = {
                "job_id": context.job_id,
                "phase": "inline",
                "tool": tool_name,
                "status": status,
            }
            if error is not None:
                payload["error"] = error
            await context.events.publish(
                "tool",
                payload,
            )

        async def stream_inline_action(
            call: dict[str, Any],
        ) -> dict[str, Any] | None:
            try:
                return inline.accept(
                    job=context.job,
                    head_node_id=head_node_id,
                    call=call,
                    mutations=mutations,
                    major_mutations=major_mutations,
                    interventions=interventions,
                    npc_packets=npc_packets,
                    npc_facts=npc_facts,
                    temporary_ids=temporary_ids,
                    action=action,
                )
            except WorldValidationError as exc:
                normalized = inline.inline_error(
                    call,
                    exc,
                )
                wrapped = RuntimeError(
                    normalized["explanation"]
                )
                wrapped.story_stream_error = normalized
                raise wrapped from exc

        async def stream_partial(
            value: str,
        ) -> None:
            context.db.update_job_partial_output(
                context.job_id,
                value,
            )

        async def stream_model_request() -> None:
            self._model_request(context)

        async def stream_first_token(
            elapsed_ms: float,
        ) -> None:
            metrics = self._metrics.setdefault(
                context.job_id,
                {
                    "model_request_count": 0,
                    "phase_durations_ms": {},
                },
            )
            if "time_to_first_token_ms" not in metrics:
                metrics["time_to_first_token_ms"] = round(
                    elapsed_ms
                )
                self._save_metrics(context)

        stream_service = StoryStreamService(
            llama
        )
        stream_result = await stream_service.stream(
            StoryStreamRequest(
                messages=messages,
                response_max_tokens=response_max_tokens,
                cancel_event=context.cancel_event,
                initial_content=(
                    resume_session["partial_prose"]
                    if (
                        resume_session
                        and not retry_preserved_games
                    )
                    else ""
                ),
                initial_suggestion=(
                    (resume_session or {}).get(
                        "suggestion"
                    )
                ),
            ),
            StoryStreamCallbacks(
                on_phase=stream_phase,
                on_token=stream_token,
                on_notice=stream_notice,
                on_tool=stream_tool,
                on_inline_action=stream_inline_action,
                persist_partial=stream_partial,
                on_model_request=stream_model_request,
                on_first_token=stream_first_token,
            ),
        )

        inline_suggestion = (
            stream_result.inline_suggestion
        )
        checkpoint = stream_result.checkpoint

        if checkpoint:
            session = minigames.create_session(
                context.project_id,
                context.job_id,
                head_node_id,
                checkpoint,
                stream_result.content,
                finalizer.serialize_mutations(
                    mutations
                ),
                interventions,
                inline_suggestion,
            )

            await context.state(
                "awaiting_minigame",
                "Waiting for player",
            )
            await context.events.publish(
                "minigame",
                {
                    "job_id": context.job_id,
                    "status": "awaiting_input",
                    "session": session,
                },
            )
            await context.events.publish(
                "job",
                {
                    "job_id": context.job_id,
                    "status": "awaiting_minigame",
                },
            )
            return

        if (
            stream_result.stop_requested
            or context.cancel_event.is_set()
        ):
            # Preserve exactly the prose already streamed to the user.
            stopped_content = stream_result.content.strip()
            if not stopped_content:
                raise asyncio.CancelledError

            await finalizer.commit_stopped_story(
                context=context,
                head_node_id=head_node_id,
                content=stopped_content,
                pov_character_id=pov_character_id,
                narration_mode=narration_mode,
                minigame_session_ids=[
                    session["id"]
                    for session
                    in resume_sessions
                ],
                mutations=mutations,
            )
            return

        content = stream_result.content
        if not content:
            raise RuntimeFailure(
                "The storyteller returned an empty response"
            )

        context.db.update_job_partial_output(
            context.job_id,
            content,
        )
        await context.state(
            "finalizing_story"
        )
        await self._job_phase(
            context,
            "finalizing_story",
            "Saving story and validated actions",
        )

        mutations.extend(
            environment.ensure_story_scene(
                project_id=context.project_id,
                head_node_id=head_node_id,
                mutations=mutations,
                pov_character_id=pov_character_id,
            )
        )

        (
            routine_mutations,
            major_mutations,
        ) = finalizer.split_review_mutations(
            mutations
        )

        appearances = (
            finalizer.encounter_appearances(
                context.project_id,
                head_node_id,
                content,
                routine_mutations,
                pov_character_id=pov_character_id,
                interventions=interventions,
            )
        )

        assistant, transaction = (
            world.commit_story_turn(
                context.project_id,
                head_node_id,
                content,
                routine_mutations,
                pov_character_id=(
                    pov_character_id
                ),
                narration_mode=(
                    narration_mode
                ),
                status=(
                    "awaiting_resolution"
                    if major_mutations
                    else "complete"
                ),
                interventions=(
                    interventions
                ),
                appearances=appearances,
                minigame_session_ids=[
                    session["id"]
                    for session
                    in resume_sessions
                ],
            )
        )

        finalizer.ensure_encounter_assets(
            context.project_id,
            assistant["id"],
            appearances,
        )
        await finalizer.queue_environment_backgrounds(
            context.project_id,
            assistant["id"],
            routine_mutations,
        )
        suggestion = (
            finalizer.create_suggestion(
                assistant,
                inline_suggestion,
            )
        )
        await music.apply_story_mutations(
            context.project_id,
            routine_mutations,
        )
        await environment.sound.apply_story_mutations(
            context.project_id,
            routine_mutations,
        )

        result = {
            "story_node_id": assistant["id"],
            "suggestion_id": suggestion["id"],
            "minigame_session_id": (
                resume_session["id"]
                if resume_session
                else None
            ),
            "minigame_session_ids": [
                session["id"]
                for session
                in resume_sessions
            ],
        }

        if major_mutations:
            review = finalizer.create_review(
                context.job,
                "reconciliation",
                major_mutations,
                assistant["id"],
            )
            context.db.update_job(
                context.job_id,
                "awaiting_review",
                result=result,
            )
            await context.state(
                "awaiting_review",
                review["reason"],
            )
            await context.events.publish(
                "reconciliation_warning",
                {
                    "job_id": context.job_id,
                    "review": review,
                },
            )
        else:
            context.db.update_job(
                context.job_id,
                "completed",
                result=result,
            )

        await context.events.publish(
            "story",
            {
                "job_id": context.job_id,
                "node": assistant,
            },
        )

        if interventions:
            await context.events.publish(
                "npc",
                {
                    "job_id": context.job_id,
                    "interventions": interventions,
                },
            )

        if appearances:
            await context.events.publish(
                "encounter",
                {
                    "job_id": context.job_id,
                    "appearances": appearances,
                },
            )

        await context.events.publish(
            "suggestion",
            {
                "job_id": context.job_id,
                "suggestion": suggestion,
            },
        )
        await context.events.publish(
            "memory_changed",
            {
                "job_id": context.job_id,
                "transaction_id": transaction[
                    "id"
                ],
                "changes": (
                    finalizer.serialize_mutations(
                        routine_mutations
                    )
                ),
            },
        )
        await context.events.publish(
            "world_head",
            {
                "project_id": context.project_id,
                "node_id": assistant["id"],
            },
        )
        await context.events.publish(
            "job",
            {
                "job_id": context.job_id,
                "status": (
                    "awaiting_review"
                    if major_mutations
                    else "completed"
                ),
                "result": result,
            },
        )

        if (
            settings.get("memory_provider")
            == "cognee"
        ):
            asyncio.create_task(
                finalizer.sync_memory(
                    context.project_id
                ),
                name=(
                    "memory-sync-"
                    f"{context.project_id}"
                ),
            )

        self._finalize_metrics(context)

    async def cancel(
        self,
        context: JobExecutionContext,
    ) -> None:
        payload = context.payload

        context.db.execute(
            "UPDATE minigame_sessions "
            "SET status='cancelled',updated_at=? "
            "WHERE job_id=? AND status IN "
            "('awaiting_input','resolved')",
            (
                utc_now(),
                context.job_id,
            ),
        )
        # Do not delete the materialized user turn here.
        #
        # scheduler.cancel() calls this hook while run() may still be
        # unwinding the active text stream. The running coroutine decides
        # whether the already-streamed prose should be committed. Deleting
        # its parent here races with commit_stopped_story() and can cause
        # SQLite "FOREIGN KEY constraint failed".

    async def failed(
        self,
        context: JobExecutionContext,
        error: BaseException,
    ) -> None:
        self._discard_materialized_input(
            context
        )
        self._finalize_metrics(context)

    async def _materialize_story_action(
        self,
        context: JobExecutionContext,
    ) -> bool:
        payload = dict(
            context.job.get("payload") or {}
        )
        pending = payload.get(
            "pending_action"
        )
        if not pending:
            return False

        now = utc_now()

        with context.db.connect() as connection:
            project = connection.execute(
                "SELECT active_node_id "
                "FROM projects WHERE id=?",
                (context.project_id,),
            ).fetchone()
            if not project:
                raise RuntimeFailure(
                    "Story no longer exists"
                )

            parent_id = (
                project["active_node_id"]
                if payload.get(
                    "use_latest_head",
                    True,
                )
                else payload.get(
                    "requested_parent_id"
                )
            )

            action = str(
                pending.get("action") or "do"
            )
            content = str(
                pending.get("content") or ""
            ).strip()
            node_id = new_id()

            if action == "manual_story":
                connection.execute(
                    "INSERT INTO story_nodes"
                    "(id,project_id,parent_id,role,content,status,"
                    "created_at,pov_character_id,narration_mode,"
                    "action_kind,author_user_id,author_name_snapshot) "
                    "VALUES(?,?,?,'assistant',?,'complete',?,?,?,"
                    "'manual_story',?,?)",
                    (
                        node_id,
                        context.project_id,
                        parent_id,
                        content,
                        now,
                        payload.get(
                            "pov_character_id"
                        ),
                        payload.get(
                            "narration_mode"
                        )
                        or "third_limited",
                        context.job.get(
                            "requested_by_user_id"
                        ),
                        context.job.get(
                            "requester_name_snapshot"
                        ),
                    ),
                )
                payload[
                    "materialized_node_id"
                ] = node_id
            else:
                connection.execute(
                    "INSERT INTO story_nodes"
                    "(id,project_id,parent_id,role,content,status,"
                    "created_at,pov_character_id,narration_mode,"
                    "action_kind,author_user_id,author_name_snapshot) "
                    "VALUES(?,?,?,'user',?,'complete',?,?,?,?,?,?)",
                    (
                        node_id,
                        context.project_id,
                        parent_id,
                        content,
                        now,
                        payload.get(
                            "pov_character_id"
                        ),
                        payload.get(
                            "narration_mode"
                        )
                        or "third_limited",
                        action,
                        context.job.get(
                            "requested_by_user_id"
                        ),
                        context.job.get(
                            "requester_name_snapshot"
                        ),
                    ),
                )
                payload[
                    "user_node_id"
                ] = node_id

            connection.execute(
                "UPDATE projects "
                "SET active_node_id=?,updated_at=? "
                "WHERE id=?",
                (
                    node_id,
                    now,
                    context.project_id,
                ),
            )

            payload.pop(
                "pending_action",
                None,
            )
            connection.execute(
                "UPDATE generation_jobs "
                "SET payload_json=?,updated_at=? "
                "WHERE id=?",
                (
                    json.dumps(payload),
                    now,
                    context.job_id,
                ),
            )
            context.job["payload"] = payload

            node = dict(
                connection.execute(
                    "SELECT * FROM story_nodes "
                    "WHERE id=?",
                    (node_id,),
                ).fetchone()
            )

        await context.events.publish(
            "story",
            {
                "job_id": context.job_id,
                "project_id": context.project_id,
                "node": node,
                "source": "player",
            },
        )
        await context.events.publish(
            "world_head",
            {
                "job_id": context.job_id,
                "project_id": context.project_id,
                "node_id": node["id"],
            },
        )

        if action == "manual_story":
            result = {
                "story_node_id": node["id"],
            }
            context.db.update_job(
                context.job_id,
                "completed",
                result=result,
            )
            await context.events.publish(
                "job",
                {
                    "job_id": context.job_id,
                    "project_id": context.project_id,
                    "status": "completed",
                    "result": result,
                },
            )
            return True

        return False

    def _discard_materialized_input(
        self,
        context: JobExecutionContext,
    ) -> None:
        node_id = context.payload.get(
            "user_node_id"
        )
        if (
            not node_id
            or context.payload.get(
                "minigame_session_id"
            )
        ):
            return

        node = context.db.fetch_one(
            "SELECT id,parent_id "
            "FROM story_nodes WHERE id=?",
            (node_id,),
        )
        project = context.db.fetch_one(
            "SELECT active_node_id "
            "FROM projects WHERE id=?",
            (context.project_id,),
        )
        if (
            not node
            or not project
            or project.get(
                "active_node_id"
            )
            != node_id
        ):
            return

        context.db.execute(
            "UPDATE projects "
            "SET active_node_id=?,updated_at=? "
            "WHERE id=?",
            (
                node.get("parent_id"),
                utc_now(),
                context.project_id,
            ),
        )
        context.db.execute(
            "DELETE FROM story_nodes "
            "WHERE id=?",
            (node_id,),
        )

    @staticmethod
    def _complete_sentences(
        content: str,
    ) -> str:
        end = content.rfind(".")
        return (
            content[: end + 1].strip()
            if end >= 0
            else ""
        )

    async def _job_phase(
        self,
        context: JobExecutionContext,
        phase: str,
        message: str,
    ) -> None:
        metrics = self._metrics.setdefault(
            context.job_id,
            {
                "model_request_count": 0,
                "phase_durations_ms": {},
            },
        )
        now = time.monotonic()
        previous = metrics.pop(
            "_phase",
            None,
        )
        started = metrics.pop(
            "_phase_started",
            None,
        )
        if (
            previous
            and started is not None
        ):
            metrics[
                "phase_durations_ms"
            ][previous] = round(
                (now - started) * 1000
            )

        metrics["_phase"] = phase
        metrics["_phase_started"] = now
        self._save_metrics(context)

        context.db.update_job_progress(
            context.job_id,
            phase,
            message,
        )
        await context.events.publish(
            "job",
            {
                "job_id": context.job_id,
                "status": "running",
                "stage": phase,
                "message": message,
            },
        )

    def _start_metrics(
        self,
        context: JobExecutionContext,
        started: float,
    ) -> None:
        self._metrics[
            context.job_id
        ] = {
            "model_request_count": 0,
            "phase_durations_ms": {},
            "load_count_at_start": (
                context.ai.load_count
            ),
            "unload_count_at_start": (
                context.ai.unload_count
            ),
            "_started": started,
        }
        self._save_metrics(context)

    def _model_request(
        self,
        context: JobExecutionContext,
    ) -> None:
        metrics = self._metrics.setdefault(
            context.job_id,
            {
                "model_request_count": 0,
                "phase_durations_ms": {},
            },
        )
        metrics["model_request_count"] = (
            int(
                metrics.get(
                    "model_request_count",
                    0,
                )
            )
            + 1
        )
        self._save_metrics(context)

    def _mark_first_token(
        self,
        context: JobExecutionContext,
        started: float,
    ) -> None:
        metrics = self._metrics.setdefault(
            context.job_id,
            {
                "model_request_count": 0,
                "phase_durations_ms": {},
            },
        )
        if (
            "time_to_first_token_ms"
            in metrics
        ):
            return
        metrics[
            "time_to_first_token_ms"
        ] = round(
            (
                time.monotonic()
                - started
            )
            * 1000
        )
        self._save_metrics(context)

    def _finalize_metrics(
        self,
        context: JobExecutionContext,
    ) -> None:
        metrics = self._metrics.get(
            context.job_id
        )
        if not metrics:
            return

        now = time.monotonic()
        previous = metrics.pop(
            "_phase",
            None,
        )
        started = metrics.pop(
            "_phase_started",
            None,
        )
        if (
            previous
            and started is not None
        ):
            metrics[
                "phase_durations_ms"
            ][previous] = round(
                (now - started) * 1000
            )

        metrics["load_count"] = (
            context.ai.load_count
            - int(
                metrics.pop(
                    "load_count_at_start",
                    context.ai.load_count,
                )
            )
        )
        metrics["unload_count"] = (
            context.ai.unload_count
            - int(
                metrics.pop(
                    "unload_count_at_start",
                    context.ai.unload_count,
                )
            )
        )
        metrics.pop("_started", None)
        self._save_metrics(context)

    def _save_metrics(
        self,
        context: JobExecutionContext,
    ) -> None:
        metrics = {
            key: value
            for key, value
            in self._metrics.get(
                context.job_id,
                {},
            ).items()
            if not key.startswith("_")
        }
        context.db.update_job_metrics(
            context.job_id,
            metrics,
        )
