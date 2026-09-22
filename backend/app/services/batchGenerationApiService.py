from __future__ import annotations

from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import (
    GenerationPlanDefinition,
    GenerationTaskDefinition,
)
from app.services.planningWorkspace import PlanningWorkspaceService
from app.services.world import WorldEngine


class BatchGenerationApiService:
    """HTTP-facing orchestration for generic generation plans."""

    def __init__(
        self,
        db: Any,
        *,
        data_provider: DataProvider | None = None,
        world: WorldEngine | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.world = world or WorldEngine(
            db,
            data_provider=self.data,
        )
        self.batch = BatchGenerationManager(
            db,
            data_provider=self.data,
        )
        self.workspace = PlanningWorkspaceService(
            db,
            data_provider=self.data,
            world=self.world,
        )

    def planning_session_view(self, plan_id: str) -> dict[str, Any]:
        # Temporary UI-shape adapter; the id is a GenerationPlan id.
        return self.workspace.view(plan_id)

    def queue_random_direction(
        self,
        project_id: str,
        theme: str,
        *,
        requested_by_user_id: str | None = None,
        requester_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        plan = self.batch.create_plan(
            project_id,
            GenerationPlanDefinition(
                name="Random story direction",
                source_kind="random_direction",
                settings={"ephemeral": True},
                tasks=[
                    GenerationTaskDefinition(
                        key="random_direction",
                        generator_kind="text",
                        target_kind="creative_direction",
                        prompt={"theme": theme.strip()},
                        settings={"generator_profile": "random_direction"},
                    )
                ],
            ),
        )
        return self.batch.queue_task(
            plan["id"],
            "random_direction",
            requested_by_user_id=requested_by_user_id,
            requester_name_snapshot=requester_name_snapshot,
        )

    def queue_planning_stage(
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
