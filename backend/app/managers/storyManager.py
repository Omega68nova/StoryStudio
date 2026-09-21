from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.managers.contextBuilder import ContextBuilder, StoryContext
from app.managers.environmentManager import EnvironmentManager
from app.services.memory import provider_for
from app.services.story_planner import StoryPlanner
from app.services.world import (
    NormalizedMutation,
    WorldEngine,
    WorldValidationError,
)


ToolEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class StoryTurnRequest:
    project_id: str
    head_node_id: str | None
    user_node_id: str | None
    action: str
    instruction: str
    user_request: str
    pov_character_id: str | None
    narration_mode: str
    generation_mode: str
    response_max_tokens: int
    context_limit: int
    custom_instructions: str
    replan_feedback: str
    requested_ability: dict[str, Any] | None = None
    scene_intent_override: str | None = None


@dataclass(slots=True)
class StoryTurnPlan:
    request: StoryTurnRequest
    path: list[dict[str, Any]]
    summary: dict[str, Any] | None
    scene_intent: str
    mutations: list[NormalizedMutation] = field(
        default_factory=list
    )
    interventions: list[dict[str, Any]] = field(
        default_factory=list
    )
    semantic_ids: list[str] = field(
        default_factory=list
    )


@dataclass(slots=True)
class PreparedStoryTurn:
    plan: StoryTurnPlan
    context: StoryContext


class StoryManager:
    """Phase 2 story-domain coordinator.

    It owns story-turn interpretation, optional scene planning, canonical
    context preparation, and requested-player-action staging.

    It deliberately does NOT own:
      * generation job queue/status
      * websocket/event transport
      * runtime process switching
      * inline streaming parser
      * story persistence/final commit (migrated in the next step)

    Those boundaries keep it reusable outside GenerationScheduler jobs.
    """

    def __init__(
        self,
        db: Any,
        world: WorldEngine | None = None,
        environment: EnvironmentManager | None = None,
    ) -> None:
        self.db = db
        self.world = world or WorldEngine(db)
        self.environment = (
            environment
            or EnvironmentManager(
                db,
                self.world,
            )
        )
        self.story_planner = StoryPlanner(self.world)
        self.context_builder = ContextBuilder(
            self.world,
            self.environment,
        )

    def build_request(
        self,
        *,
        project_id: str,
        payload: dict[str, Any],
        user_node: dict[str, Any] | None,
        head_node_id: str | None,
        context_limit: int,
    ) -> StoryTurnRequest:
        user_node = user_node or {}

        action = str(
            payload.get("action")
            or user_node.get("action_kind")
            or "do"
        )

        instruction = str(
            payload.get("guidance")
            or user_node.get("content")
            or ""
        )

        action_prefixes = {
            "say": (
                "The player wants their POV character to say"
            ),
            "do": "The player attempts",
            "guide": (
                "The player gives this out-of-story direction"
            ),
            "continue": (
                "Continue the current scene naturally"
            ),
        }
        user_request = (
            action_prefixes.get(
                action,
                "Player input",
            )
            + (
                f": {instruction}"
                if instruction
                else "."
            )
        )

        mode = str(
            payload.get("generation_mode")
            or "low"
        )
        if mode not in {
            "direct",
            "low",
            "smart",
        }:
            mode = "low"

        return StoryTurnRequest(
            project_id=project_id,
            head_node_id=head_node_id,
            user_node_id=payload.get("user_node_id"),
            action=action,
            instruction=instruction,
            user_request=user_request,
            pov_character_id=(
                payload.get("pov_character_id")
                or user_node.get("pov_character_id")
            ),
            narration_mode=(
                payload.get("narration_mode")
                or user_node.get("narration_mode")
                or "third_limited"
            ),
            generation_mode=mode,
            response_max_tokens=min(
                1400,
                max(
                    64,
                    int(
                        payload.get(
                            "response_max_tokens"
                        )
                        or 300
                    ),
                ),
            ),
            context_limit=int(context_limit),
            custom_instructions=str(
                payload.get("ai_instructions")
                or ""
            ).strip(),
            replan_feedback=str(
                payload.get("replan_feedback")
                or ""
            ),
            requested_ability=(
                payload.get("requested_ability")
            ),
            scene_intent_override=(
                str(payload.get("scene_intent") or "").strip()
                or None
            ),
        )

    async def plan_turn(
        self,
        *,
        llama: Any,
        request: StoryTurnRequest,
        approved_mutations: list[dict[str, Any]] | None = None,
        resume_mutations: list[dict[str, Any]] | None = None,
        interventions: list[dict[str, Any]] | None = None,
        tool_event: ToolEvent,
        cancel_event: asyncio.Event | None = None,
        turn_key: str = "",
        skip_planning: bool = False,
    ) -> StoryTurnPlan:
        path = self.db.story_path(
            request.head_node_id
        )
        summary = self._summary_for_path(
            request.project_id,
            path,
        )

        raw_mutations = list(
            resume_mutations
            or approved_mutations
            or []
        )
        mutations: list[
            NormalizedMutation
        ] = []

        scene_intent = (
            request.scene_intent_override
            or request.user_request
        )
        semantic_ids: list[str] = []

        if raw_mutations:
            mutations = (
                self.world.normalize_mutations(
                    request.project_id,
                    request.head_node_id,
                    raw_mutations,
                )
            )

        elif (
            request.generation_mode != "direct"
            and not skip_planning
        ):
            feedback = "\n".join(
                value
                for value in (
                    request.custom_instructions,
                    request.replan_feedback,
                )
                if value
            )

            settings = self._runtime_settings()
            memory_provider = provider_for(
                settings.get(
                    "memory_provider",
                    "builtin",
                ),
                self.db,
                self.world,
            )

            try:
                semantic_ids = (
                    await memory_provider.candidates(
                        request.project_id,
                        request.user_request,
                        12,
                    )
                )
            except Exception as exc:
                semantic_ids = []
                await tool_event(
                    {
                        "phase": "memory",
                        "status": "fallback",
                        "message": str(exc),
                    }
                )

            try:
                low = (
                    request.generation_mode
                    == "low"
                )
                async with asyncio.timeout(
                    45 if low else 180
                ):
                    plan = (
                        await self.story_planner.plan(
                            llama,
                            request.project_id,
                            request.head_node_id,
                            request.user_request,
                            request.pov_character_id,
                            request.narration_mode,
                            request.context_limit,
                            tool_event,
                            feedback,
                            semantic_ids,
                            cancel_event,
                            max_rounds=(
                                2 if low else 4
                            ),
                            max_tokens=(
                                240 if low else 480
                            ),
                            time_budget_seconds=(
                                45 if low else 180
                            ),
                        )
                    )

                scene_intent = str(
                    plan.get("scene_intent")
                    or request.user_request
                )
                raw_mutations = list(
                    plan.get("mutations")
                    or []
                )
                if raw_mutations:
                    mutations = (
                        self.world.normalize_mutations(
                            request.project_id,
                            request.head_node_id,
                            raw_mutations,
                        )
                    )

            except TimeoutError:
                await tool_event(
                    {
                        "phase": "planning",
                        "status": "timeout",
                        "message": (
                            f"{request.generation_mode.title()} "
                            "planning reached its time budget; "
                            "continuing directly."
                        ),
                    }
                )
            except WorldValidationError as exc:
                await tool_event(
                    {
                        "phase": "planning",
                        "status": "omitted",
                        "message": (
                            "The preliminary plan was omitted: "
                            f"{exc}"
                        ),
                    }
                )

        if request.requested_ability:
            mutations.extend(
                self.world.normalize_mutations(
                    request.project_id,
                    request.head_node_id,
                    [
                        {
                            "tool": "useAbility",
                            "arguments": (
                                request.requested_ability
                            ),
                        }
                    ],
                    provenance="player",
                    staged=mutations,
                )
            )

        return StoryTurnPlan(
            request=request,
            path=path,
            summary=summary,
            scene_intent=scene_intent,
            mutations=mutations,
            interventions=list(
                interventions or []
            ),
            semantic_ids=semantic_ids,
        )

    async def prepare_context(
        self,
        *,
        llama: Any,
        plan: StoryTurnPlan,
        inline_protocol: str = "",
        extra_messages: list[dict[str, str]] | None = None,
    ) -> PreparedStoryTurn:
        request = plan.request

        transient_instruction = (
            request.user_request
            if request.action
            in {
                "guide",
                "continue",
            }
            else ""
        )

        context = await self.context_builder.build_story_context(
            llama=llama,
            project_id=request.project_id,
            head_node_id=request.head_node_id,
            path=plan.path,
            summary=plan.summary,
            user_request=request.user_request,
            scene_intent=plan.scene_intent,
            pov_character_id=request.pov_character_id,
            narration_mode=request.narration_mode,
            context_limit=request.context_limit,
            response_max_tokens=request.response_max_tokens,
            mutations=plan.mutations,
            interventions=plan.interventions,
            transient_instruction=transient_instruction,
            custom_instructions=request.custom_instructions,
            semantic_ids=plan.semantic_ids,
            extra_messages=extra_messages,
            inline_protocol=inline_protocol,
        )

        return PreparedStoryTurn(
            plan=plan,
            context=context,
        )

    async def prepare_turn(
        self,
        *,
        llama: Any,
        project_id: str,
        payload: dict[str, Any],
        user_node: dict[str, Any] | None,
        head_node_id: str | None,
        context_limit: int,
        approved_mutations: list[dict[str, Any]] | None,
        resume_mutations: list[dict[str, Any]] | None,
        interventions: list[dict[str, Any]] | None,
        tool_event: ToolEvent,
        cancel_event: asyncio.Event | None,
        inline_protocol: str = "",
        extra_messages: list[dict[str, str]] | None = None,
        turn_key: str = "",
        skip_planning: bool = False,
    ) -> PreparedStoryTurn:
        request = self.build_request(
            project_id=project_id,
            payload=payload,
            user_node=user_node,
            head_node_id=head_node_id,
            context_limit=context_limit,
        )

        plan = await self.plan_turn(
            llama=llama,
            request=request,
            approved_mutations=approved_mutations,
            resume_mutations=resume_mutations,
            interventions=interventions,
            tool_event=tool_event,
            cancel_event=cancel_event,
            turn_key=turn_key,
            skip_planning=skip_planning,
        )

        return await self.prepare_context(
            llama=llama,
            plan=plan,
            inline_protocol=inline_protocol,
            extra_messages=extra_messages,
        )

    def _summary_for_path(
        self,
        project_id: str,
        path: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        ids = {
            node["id"]
            for node in path
        }
        candidates = self.db.fetch_all(
            "SELECT * FROM branch_summaries "
            "WHERE project_id=? "
            "ORDER BY created_at DESC",
            (project_id,),
        )
        return next(
            (
                row
                for row in candidates
                if row["through_node_id"]
                in ids
            ),
            None,
        )

    def _runtime_settings(
        self,
    ) -> dict[str, Any]:
        import json

        row = (
            self.db.fetch_one(
                "SELECT * FROM runtime_settings WHERE id=1"
            )
            or {}
        )
        row["llama_extra_args"] = json.loads(
            row.pop(
                "llama_extra_args_json",
                "[]",
            )
        )
        row["comfy_command"] = json.loads(
            row.pop(
                "comfy_command_json",
                "[]",
            )
        )
        row["data_dir"] = str(self.db.data_dir)
        return row
