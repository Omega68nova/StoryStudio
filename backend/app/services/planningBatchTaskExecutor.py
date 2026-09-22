from __future__ import annotations

import json
from typing import Any

from app.data.dataProvider import DataProvider
from app.handlers.planningJobHandler import PlanningJobHandler
from app.services.planning import PlanningService, stage_prompt
from app.services.planning_v2 import (
    generated_stage_has_content,
    normalize_generated_defaults,
)
from app.services.runtimes import RuntimeFailure
from app.services.story_planner import parse_json_object
from app.services.world import WorldEngine, WorldValidationError


class PlanningBatchTaskExecutor:
    def __init__(self) -> None:
        self._legacy = PlanningJobHandler()

    async def generate(self, context, task: dict[str, Any]) -> dict[str, Any]:
        prompt = dict(task.get("prompt") or {})
        session_id = str(prompt.get("planning_session_id") or "")
        stage_number = int(
            prompt.get("planning_stage_number")
            or task.get("target_key")
        )
        if not session_id:
            raise RuntimeFailure("Planning batch task has no source session")
        if stage_number == 8:
            raise RuntimeFailure(
                "Planning stage 8 is deterministic and is prepared after stage 7 commit"
            )

        data = DataProvider(context.db)
        world = WorldEngine(context.db, data_provider=data)
        planning = PlanningService(
            context.db,
            world,
            data_provider=data,
        )
        session, stage, approved = planning.stage_for_generation(
            session_id,
            stage_number,
        )

        llama = await context.ai.ensure_text_ready(
            "planning",
            reason=f"Batch planning stage {stage_number} generation",
        )
        self._legacy._start_metrics(context)

        label = (
            f"Stage {stage_number}/8 · "
            f"{str(stage['kind']).replace('_', ' ').title()}"
        )
        await self._legacy._job_phase(
            context,
            "planning_context",
            f"{label}: preparing compact context",
        )

        settings = data.runtime.settings()
        context_tokens = int(
            settings.get(
                "planning_context_tokens",
                settings.get("context_tokens", 8192),
            )
        )
        desired_outputs = {
            1: 1000, 2: 2300, 3: 2400, 4: 1900,
            5: 2200, 6: 2200, 7: 1800,
        }
        desired_output = desired_outputs.get(stage_number, 900)
        available_prompt = max(
            768,
            context_tokens - desired_output - 768,
        )
        character_budget = max(3500, available_prompt * 2)

        inventory = planning.world_inventory(
            session["project_id"],
            include_catalogs=stage_number == 7,
            session_id=session["id"],
        )
        repair_text = str(prompt.get("repair_text") or "")
        messages = stage_prompt(
            stage,
            session,
            approved,
            inventory,
            character_budget=character_budget,
            repair_text=repair_text,
        )

        count_prompt_tokens = getattr(
            llama,
            "count_prompt_tokens",
            None,
        )
        apply_template = getattr(
            llama,
            "apply_template",
            None,
        )
        if not count_prompt_tokens or not apply_template:
            raise RuntimeFailure(
                "llama.cpp runtime is missing raw planning autocomplete support"
            )

        formatted = await apply_template(messages)
        prompt_tokens = int(await count_prompt_tokens(formatted))
        while (
            prompt_tokens > available_prompt
            and character_budget > 3500
        ):
            character_budget = max(
                3500,
                int(character_budget * 0.72),
            )
            messages = stage_prompt(
                stage,
                session,
                approved,
                inventory,
                character_budget=character_budget,
                repair_text=repair_text,
            )
            formatted = await apply_template(messages)
            prompt_tokens = int(
                await count_prompt_tokens(formatted)
            )

        if context_tokens - prompt_tokens - 512 < 256:
            raise RuntimeFailure(
                f"{label} leaves too little context for a useful answer"
            )

        async def progress(update: dict[str, Any]) -> None:
            context.db.update_job_progress(
                context.job_id,
                "planning_generating",
                f"{label}: generating structured draft",
                update.get("value"),
                update.get("max"),
            )

        raw, generation_error, _, _ = (
            await self._legacy._generate_planning_json_raw(
                context,
                llama,
                messages,
                context_tokens,
                label,
                progress,
            )
        )

        if generation_error:
            return {
                "raw": raw,
                "validation_error": generation_error,
                "invalid_structured_output": True,
                "stage_number": stage_number,
                "session_id": session_id,
            }

        validation_error: WorldValidationError | None = None
        draft: dict[str, Any] = {}

        for attempt in range(3):
            try:
                draft = parse_json_object(raw)
                normalize_generated_defaults(
                    stage_number,
                    draft,
                )
                planning.validate_draft(
                    draft,
                    stage_number,
                    json.loads(session["settings_json"]),
                )
                if generated_stage_has_content(
                    stage_number,
                    draft,
                ):
                    validation_error = None
                    break
                validation_error = WorldValidationError(
                    f"{label} returned no usable stage resources"
                )
            except WorldValidationError as exc:
                validation_error = exc

            if attempt >= 2:
                break

            retry_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "The previous answer contained no usable "
                        "stage resources or did not match the requested "
                        "root JSON shape. Generate the requested root object now."
                    ),
                },
            ]
            raw, generation_error, _, _ = (
                await self._legacy._generate_planning_json_raw(
                    context,
                    llama,
                    retry_messages,
                    context_tokens,
                    label,
                    progress,
                )
            )
            if generation_error:
                validation_error = WorldValidationError(
                    generation_error
                )
                break

        if validation_error:
            return {
                "raw": raw,
                "validation_error": str(validation_error),
                "invalid_structured_output": True,
                "stage_number": stage_number,
                "session_id": session_id,
            }

        return {
            "json": draft,
            "raw": raw,
            "stage_number": stage_number,
            "session_id": session_id,
            "invalid_structured_output": False,
        }
