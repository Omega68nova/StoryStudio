from __future__ import annotations

from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import (
    GenerationPlanDefinition,
    GenerationPlanError,
    GenerationTaskDefinition,
)
from app.services.planning import PlanningService
from app.services.planningGenerationBridge import PlanningGenerationBridge
from app.services.world import WorldEngine


class BatchGenerationApiService:
    """HTTP-facing orchestration for the unified Phase 4 generation system."""

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
        self.planning = PlanningService(
            db,
            self.world,
            data_provider=self.data,
        )
        self.batch = BatchGenerationManager(
            db,
            data_provider=self.data,
        )
        self.bridge = PlanningGenerationBridge(
            db,
            data_provider=self.data,
            world=self.world,
        )

    def planning_session_view(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        session = self.planning.get_session(session_id)
        plan = self.data.batch_generation.plan_by_source(
            "planning_session",
            session_id,
        )
        if not plan:
            return session

        plan = self.batch.get_plan(plan["id"])
        by_source = {
            task.get("source_id"): task
            for task in plan["tasks"]
            if task.get("source_id")
        }

        for stage in session["stages"]:
            task = by_source.get(stage["id"])
            if not task:
                continue

            result = task.get("result") or {}
            if isinstance(result.get("json"), dict):
                stage["draft"] = result["json"]

            status = str(task["status"])
            if status == "committed":
                stage["status"] = "approved"
            elif status == "generated":
                stage["status"] = "ready"
            elif status == "queued":
                stage["status"] = "queued"
            elif status == "running":
                stage["status"] = "generating"
            elif status in {"failed", "cancelled", "stale"}:
                stage["status"] = status

            if task.get("active_job_id"):
                job = self.data.jobs.get(
                    task["active_job_id"]
                )
                if job:
                    stage["operation"] = {
                        key: job.get(key)
                        for key in (
                            "id",
                            "status",
                            "phase",
                            "progress_message",
                            "progress_current",
                            "progress_total",
                            "error",
                            "created_at",
                            "updated_at",
                        )
                    }

        session["generation_plan_id"] = plan["id"]
        return session

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
                        settings={
                            "generator_profile": "random_direction",
                        },
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
        session_id: str,
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
        if stage_number == 8:
            result = self.planning.prepare_image_stage(
                session_id
            )
            return {
                "deterministic": True,
                "stage": result["stages"][7],
                "image_plans": result.get(
                    "image_plans",
                    [],
                ),
            }

        plan = self.bridge.import_session(session_id)
        task = next(
            (
                item
                for item in plan["tasks"]
                if str(item.get("target_key"))
                == str(stage_number)
            ),
            None,
        )
        if not task:
            raise GenerationPlanError(
                f"Planning stage {stage_number} has no generation task"
            )

        if task.get("active_job_id"):
            active = self.data.jobs.get(
                task["active_job_id"]
            )
            if active and active["status"] in {
                "queued",
                "running",
            }:
                return {
                    "job": active,
                    "task": task,
                    "plan": plan,
                    "duplicate": True,
                }

        previous_result = dict(
            task.get("result") or {}
        )
        task_prompt = dict(task.get("prompt") or {})
        task_prompt.update(
            {
                "human_prompt": human_prompt,
                "append": append,
                "focus": focus,
                "automate": automate,
                "automation_prompt": automation_prompt,
            }
        )
        if append and isinstance(
            previous_result.get("json"),
            dict,
        ):
            task_prompt["existing_draft"] = (
                previous_result["json"]
            )
        if repair:
            task_prompt["repair_text"] = str(
                previous_result.get("raw") or ""
            )
            if not task_prompt["repair_text"]:
                stage = next(
                    (
                        item
                        for item in self.planning.get_session(
                            session_id
                        )["stages"]
                        if int(item["stage_number"])
                        == stage_number
                    ),
                    None,
                )
                if stage:
                    task_prompt["repair_text"] = str(
                        stage.get("raw_draft_text") or ""
                    )
            if not task_prompt.get("repair_text"):
                raise GenerationPlanError(
                    "There is no malformed draft to repair"
                )

        task_settings = dict(
            task.get("settings") or {}
        )
        task_settings["planning_bridge"] = True

        if task["status"] in {
            "generated",
            "approved",
            "committed",
            "failed",
            "cancelled",
            "stale",
        }:
            plan = self.batch.regenerate_task(
                plan["id"],
                task["task_key"],
                prompt=task_prompt,
                settings=task_settings,
                reason="planning stage regenerated",
            )
        else:
            self.data.batch_generation.configure_task(
                plan["id"],
                task["task_key"],
                prompt=task_prompt,
                settings=task_settings,
            )
            plan = self.batch.get_plan(plan["id"])

        job = self.batch.queue_task(
            plan["id"],
            task["task_key"],
            requested_by_user_id=requested_by_user_id,
            requester_name_snapshot=requester_name_snapshot,
        )
        return {
            "job": job,
            "task": self.data.batch_generation.task(
                plan["id"],
                task["task_key"],
            ),
            "plan": self.batch.get_plan(plan["id"]),
        }
