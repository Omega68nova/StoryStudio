from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.context import messages_tokens
from app.managers.environmentManager import EnvironmentManager
from app.services.story_planner import narrative_messages
from app.services.world import NormalizedMutation, WorldEngine


@dataclass(slots=True)
class StoryContext:
    """Prepared storyteller context before streaming begins."""

    package: dict[str, Any]
    environment: dict[str, Any]
    messages: list[dict[str, str]]
    prompt_tokens: int
    prompt_budget: int
    context_limit: int
    response_max_tokens: int


class ContextBuilder:
    """Authoritative builder for compact StoryStudio storyteller context.

    Phase 2 goal:
      * StoryManager decides *what turn is happening*.
      * ContextBuilder decides *what the model is allowed to see*.
      * WorldEngine remains authoritative for canonical branch state.
      * EnvironmentManager remains authoritative for resolved scene state.

    No DB mutation is performed here.
    """

    def __init__(
        self,
        world: WorldEngine,
        environment: EnvironmentManager,
    ) -> None:
        self.world = world
        self.environment = environment

    async def build_story_context(
        self,
        *,
        llama: Any,
        project_id: str,
        head_node_id: str | None,
        path: list[dict[str, Any]],
        summary: dict[str, Any] | None,
        user_request: str,
        scene_intent: str,
        pov_character_id: str | None,
        narration_mode: str,
        context_limit: int,
        response_max_tokens: int,
        mutations: list[NormalizedMutation],
        interventions: list[dict[str, Any]],
        transient_instruction: str = "",
        custom_instructions: str = "",
        semantic_ids: list[str] | None = None,
        extra_messages: list[dict[str, str]] | None = None,
        inline_protocol: str = "",
    ) -> StoryContext:
        world_budget = min(
            1800,
            max(700, context_limit // 5),
        )

        package = self.world.context_package(
            project_id,
            head_node_id,
            user_request,
            pov_character_id,
            narration_mode,
            world_budget,
            semantic_ids,
        )

        # EnvironmentManager is the canonical runtime view for time/weather/location/sound/music.
        # WorldEngine still owns the underlying branch state.
        projection = self.world.preview(
            project_id,
            head_node_id,
            mutations,
        )
        environment = self.environment.scene(
            project_id,
            projection,
        )

        # context_package already exposes environment today, but replacing it
        # here makes ownership explicit and prevents two competing scene views.
        package["environment"] = environment

        mutation_data = [
            {
                "tool": mutation.tool,
                "arguments": mutation.arguments,
                "major": mutation.major,
                "reason": mutation.reason,
            }
            for mutation in mutations
        ]

        messages = narrative_messages(
            package,
            path,
            summary,
            scene_intent,
            mutation_data,
            interventions,
            transient_instruction,
        )

        if custom_instructions:
            messages[0]["content"] += (
                "\n\n# Project storyteller instructions\n"
                "Follow these persistent player-authored directions when "
                "they do not conflict with canonical state or validation:\n"
                + custom_instructions[:4000]
            )

        if inline_protocol:
            messages[0]["content"] += inline_protocol

        if extra_messages:
            messages.extend(extra_messages)

        prompt_budget = max(
            1024,
            context_limit - response_max_tokens - 768,
        )

        messages = self._truncate_history(
            messages,
            prompt_budget,
        )

        prompt_tokens = await self._guarded_prompt_tokens(
            llama,
            messages,
        )

        while (
            prompt_tokens > prompt_budget
            and len(messages) > 2
        ):
            # Keep system context and the newest instruction/result while
            # dropping oldest transcript material first.
            del messages[1]
            prompt_tokens = await self._guarded_prompt_tokens(
                llama,
                messages,
            )

        if prompt_tokens > prompt_budget:
            raise ValueError(
                f"Story context needs about {prompt_tokens} tokens but only "
                f"{prompt_budget} are available in the configured "
                f"{context_limit}-token window."
            )

        return StoryContext(
            package=package,
            environment=environment,
            messages=messages,
            prompt_tokens=prompt_tokens,
            prompt_budget=prompt_budget,
            context_limit=context_limit,
            response_max_tokens=response_max_tokens,
        )

    async def _guarded_prompt_tokens(
        self,
        llama: Any,
        messages: list[dict[str, str]],
    ) -> int:
        count_tokens = getattr(
            llama,
            "count_tokens",
            None,
        )
        counted = (
            await count_tokens(messages)
            if count_tokens
            else messages_tokens(messages)
        )

        # Retain the current scheduler's conservative protection against
        # llama.cpp template/tokenizer underestimation.
        characters = sum(
            len(str(message.get("content", "")))
            for message in messages
        )
        return max(
            int(counted) + 384,
            (characters + 1) // 2,
        )

    @staticmethod
    def _truncate_history(
        messages: list[dict[str, str]],
        token_budget: int,
    ) -> list[dict[str, str]]:
        trimmed = list(messages)
        while (
            messages_tokens(trimmed) > token_budget
            and len(trimmed) > 3
        ):
            # Preserve the system prompt and newest turn. The old scheduler
            # removed pairs because historical user/assistant turns normally
            # occur together.
            del trimmed[1:3]
        return trimmed
