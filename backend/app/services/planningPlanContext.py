from __future__ import annotations

import json
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import GenerationPlanError
from app.services.planning_v2 import PLANNING_STAGES
from app.services.world import WorldValidationError


class PlanningPlanContext:
    """Read planning generation context from GenerationPlan, not stage lifecycle."""

    def __init__(self, db: Any, *, data_provider: DataProvider | None = None) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.batch = BatchGenerationManager(db, data_provider=self.data)

    def session_and_stage(
        self,
        session_id: str,
        stage_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        session = self.data.planning.session(session_id)
        if not session:
            raise WorldValidationError("Planning session not found")

        plan = self.data.batch_generation.plan_by_source(
            "planning_session",
            session_id,
        )
        if not plan:
            raise GenerationPlanError(
                "Planning session has no GenerationPlan"
            )
        plan = self.batch.get_plan(plan["id"])

        task = next(
            (
                item
                for item in plan["tasks"]
                if str(item.get("target_key")) == str(stage_number)
            ),
            None,
        )
        if not task:
            raise GenerationPlanError(
                f"Planning stage {stage_number} has no GenerationPlan task"
            )

        stage_row = self.data.planning.stage(session_id, stage_number)
        if not stage_row:
            raise WorldValidationError("Planning stage not found")

        stage = dict(stage_row)
        stage["description"] = next(
            item[2]
            for item in PLANNING_STAGES
            if int(item[0]) == int(stage_number)
        )
        stage["human_prompt"] = str(
            (task.get("prompt") or {}).get("human_prompt") or ""
        )

        approved: list[dict[str, Any]] = []
        for prior in sorted(
            (
                item for item in plan["tasks"]
                if int(item.get("target_key") or 999) < int(stage_number)
            ),
            key=lambda item: int(item.get("target_key") or 999),
        ):
            if prior["status"] != "committed":
                continue
            result = prior.get("result") or {}
            draft = result.get("json")
            if not isinstance(draft, dict):
                continue

            prior_number = int(prior["target_key"])
            prior_kind = str(
                next(
                    item[1]
                    for item in PLANNING_STAGES
                    if int(item[0]) == prior_number
                )
            )
            approved.append(
                {
                    "stage_number": prior_number,
                    "kind": prior_kind,
                    "approved_json": json.dumps(draft),
                }
            )

        return session, stage, approved
