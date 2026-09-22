from __future__ import annotations

import json
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import GenerationPlanError
from app.services.planning_v2 import PLANNING_STAGES


class PlanningPlanContext:
    """Build planning prompt context directly from a GenerationPlan."""

    def __init__(self, db: Any, *, data_provider: DataProvider | None = None) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.batch = BatchGenerationManager(db, data_provider=self.data)

    def plan_and_stage(
        self,
        plan_id: str,
        stage_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        plan = self.batch.get_plan(plan_id)
        if plan.get("source_kind") != "planning_workspace":
            raise GenerationPlanError("Generation plan is not a planning workspace")

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

        kind, description = next(
            (str(item[1]), str(item[2]))
            for item in PLANNING_STAGES
            if int(item[0]) == int(stage_number)
        )
        stage = {
            "id": task["id"],
            "stage_number": stage_number,
            "kind": kind,
            "description": description,
            "human_prompt": str(
                (task.get("prompt") or {}).get("human_prompt") or ""
            ),
        }
        session = {
            "id": plan_id,
            "project_id": plan["project_id"],
            "settings_json": json.dumps(plan.get("settings") or {}),
        }

        approved: list[dict[str, Any]] = []
        for prior in sorted(
            (
                item
                for item in plan["tasks"]
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
