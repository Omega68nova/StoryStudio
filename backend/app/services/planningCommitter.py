from __future__ import annotations

from typing import Any

from app.data.dataProvider import DataProvider
from app.services.batchCommit import BatchCommitResult, BatchTaskCommitter
from app.services.batchGeneration import GenerationPlanError
from app.services.planning import PlanningService
from app.services.world import WorldEngine, WorldValidationError


class PlanningTaskCommitter(BatchTaskCommitter):
    """Publish an approved planning task into canonical project state."""

    def __init__(
        self,
        db: Any,
        *,
        data_provider: DataProvider | None = None,
        world: WorldEngine | None = None,
        resolutions: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.world = world or WorldEngine(db, data_provider=self.data)
        self.planning = PlanningService(
            db,
            self.world,
            data_provider=self.data,
        )
        self.resolutions = resolutions or {}

    def commit(
        self,
        *,
        plan: dict[str, Any],
        task: dict[str, Any],
    ) -> BatchCommitResult:
        if plan.get("source_kind") != "planning_workspace":
            raise GenerationPlanError(
                "PlanningTaskCommitter requires a planning workspace"
            )
        if task.get("target_kind") != "planning_stage":
            raise GenerationPlanError(
                "PlanningTaskCommitter requires a planning_stage task"
            )

        draft = (task.get("result") or {}).get("json")
        if not isinstance(draft, dict):
            raise GenerationPlanError(
                "Planning task result must contain a JSON draft"
            )
        try:
            stage_number = int(task.get("target_key"))
        except (TypeError, ValueError) as exc:
            raise GenerationPlanError(
                "Planning task has no valid stage number"
            ) from exc

        conflicts = self.planning.preflight(
            plan["id"],
            stage_number,
            draft,
        )
        unresolved = [
            item
            for item in conflicts
            if not (
                self.resolutions.get(item["entity_key"])
                or item.get("recommended_resolution")
            )
        ]
        if unresolved:
            raise WorldValidationError(
                "Planning task has unresolved canonical-world "
                f"conflicts: {len(unresolved)}"
            )

        resolutions = {
            item["entity_key"]: (
                self.resolutions.get(item["entity_key"])
                or item.get("recommended_resolution")
            )
            for item in conflicts
            if (
                self.resolutions.get(item["entity_key"])
                or item.get("recommended_resolution")
            )
        }
        committed = self.planning.publish(
            plan["id"],
            stage_number,
            draft,
            resolutions,
        )
        tx = committed.get("transaction") or {}
        return BatchCommitResult(
            metadata={
                "source": "planning_workspace",
                "generation_plan_id": plan["id"],
                "stage_number": stage_number,
                "transaction_id": tx.get("id"),
            }
        )
