from __future__ import annotations

from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import GenerationPlanError
from app.services.batchGenerationApiService import BatchGenerationApiService
from app.services.planning import PlanningService
from app.services.planningCommitter import PlanningTaskCommitter
from app.services.planningWorkspace import PlanningWorkspaceService
from app.services.world import WorldEngine


class GenerationPlanApiService:
    """First-class HTTP orchestration for GenerationPlan."""

    def __init__(
        self,
        db: Any,
        *,
        data_provider: DataProvider | None = None,
        world: WorldEngine | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.world = world or WorldEngine(db, data_provider=self.data)
        self.batch = BatchGenerationManager(db, data_provider=self.data)
        self.planning = PlanningService(
            db,
            self.world,
            data_provider=self.data,
        )
        self.workspace = PlanningWorkspaceService(
            db,
            data_provider=self.data,
            world=self.world,
        )
        self.compat = BatchGenerationApiService(
            db,
            data_provider=self.data,
            world=self.world,
        )

    def list_project(self, project_id: str) -> list[dict[str, Any]]:
        return self.batch.list_plans(project_id)

    def get(self, plan_id: str) -> dict[str, Any]:
        return self.batch.get_plan(plan_id)

    def planning_plan(self, plan_id: str) -> dict[str, Any]:
        return self.workspace.plan(plan_id)

    def queue_planning_task(
        self,
        plan_id: str,
        stage_number: int,
        *,
        human_prompt: str = "",
        repair: bool = False,
        append: bool = False,
        focus: str | None = None,
        automate: bool = False,
        automation_prompt: str = "",
        requested_by_user_id: str | None = None,
        requester_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        return self.workspace.queue_stage(
            plan_id,
            stage_number,
            human_prompt=human_prompt,
            repair=repair,
            append=append,
            focus=focus,
            automate=automate,
            automation_prompt=automation_prompt,
            requested_by_user_id=requested_by_user_id,
            requester_name_snapshot=requester_name_snapshot,
        )

    def planning_task(
        self,
        plan_id: str,
        stage_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.workspace.task(plan_id, stage_number)

    def save_planning_result(
        self,
        plan_id: str,
        stage_number: int,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        plan, task = self.planning_task(plan_id, stage_number)
        if task.get("active_job_id"):
            raise GenerationPlanError(
                "Cancel active generation before saving this task result"
            )
        self.data.batch_generation.import_task_state(
            plan["id"],
            task["task_key"],
            status="generated",
            result={"json": draft},
            metadata={
                **dict(task.get("commit_metadata") or {}),
                "manual_result_save": True,
            },
        )
        return self.batch.get_plan(plan["id"])

    def replace_generated_result(
        self,
        plan_id: str,
        task_key: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        self.data.batch_generation.replace_generated_result(
            plan_id,
            task_key,
            result,
        )
        return self.batch.get_plan(plan_id)

    def approve(
        self,
        plan_id: str,
        task_key: str,
        note: str = "",
    ) -> dict[str, Any]:
        return self.batch.approve_task(plan_id, task_key, note)

    def reject(
        self,
        plan_id: str,
        task_key: str,
        note: str = "",
    ) -> dict[str, Any]:
        return self.batch.reject_task(plan_id, task_key, note)

    def revisions(
        self,
        plan_id: str,
        task_key: str,
    ) -> list[dict[str, Any]]:
        return self.batch.revisions(plan_id, task_key)

    def preflight_planning(
        self,
        plan_id: str,
        stage_number: int,
        draft: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.planning.preflight(plan_id, stage_number, draft)

    def approve_and_commit_planning(
        self,
        plan_id: str,
        stage_number: int,
        *,
        draft: dict[str, Any],
        resolutions: dict[str, dict[str, Any]] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        plan, task = self.planning_task(plan_id, stage_number)
        self.data.batch_generation.replace_generated_result(
            plan["id"],
            task["task_key"],
            {"json": draft},
        )
        self.batch.approve_task(plan["id"], task["task_key"], note)
        return self.batch.commit_task(
            plan["id"],
            task["task_key"],
            PlanningTaskCommitter(
                self.db,
                data_provider=self.data,
                world=self.world,
                resolutions=resolutions or {},
            ),
        )
