from __future__ import annotations

import json
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanDefinition,
    GenerationPlanError,
    GenerationTaskDefinition,
    descendant_keys,
)
from app.services.planning import PlanningService
from app.services.planning_v2 import (
    PLANNING_STAGES,
    empty_draft,
    normalized_settings,
    validate_stage,
)
from app.services.world import WorldEngine, WorldValidationError


class PlanningWorkspaceService:
    """GenerationPlan-backed planning workspace compatibility projection."""

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

    @staticmethod
    def task_key(stage_number: int, kind: str) -> str:
        normalized = "_".join(
            str(kind or f"stage_{stage_number}")
            .strip().lower().replace("-", " ").split()
        )
        return f"planning_{stage_number:02d}_{normalized}"

    def create(
        self,
        project_id: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        active = self.db.fetch_one(
            "SELECT id FROM generation_plans "
            "WHERE project_id=? AND source_kind='planning_workspace' "
            "AND status NOT IN ('completed','cancelled') "
            "ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )
        if active:
            return self.view(str(active["id"]))

        normalized = normalized_settings(settings)
        tasks: list[GenerationTaskDefinition] = []
        previous_key: str | None = None
        for number, kind, _description in PLANNING_STAGES:
            key = self.task_key(int(number), str(kind))
            tasks.append(
                GenerationTaskDefinition(
                    key=key,
                    label=f"{number}. {kind}",
                    generator_kind=(
                        "deterministic" if int(number) == 8 else "text"
                    ),
                    target_kind="planning_stage",
                    target_key=str(number),
                    prompt={
                        "planning_stage_number": int(number),
                        "human_prompt": "",
                    },
                    settings={
                        "runtime_mode": "planning",
                        "parse_json": True,
                        "planning_workspace": True,
                    },
                    dependencies=(
                        [GenerationDependency(previous_key, "committed")]
                        if previous_key else []
                    ),
                )
            )
            previous_key = key

        plan = self.batch.create_plan(
            project_id,
            GenerationPlanDefinition(
                name=f"Planning: {project_id}",
                source_kind="planning_workspace",
                settings={
                    **normalized,
                    "planning_schema_version": 3,
                },
                tasks=tasks,
            ),
        )
        return self.view(plan["id"])

    def latest_plan_id(self, project_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT id FROM generation_plans "
            "WHERE project_id=? AND source_kind='planning_workspace' "
            "ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )
        return str(row["id"]) if row else None

    def plan(self, plan_id: str) -> dict[str, Any]:
        plan = self.batch.get_plan(plan_id)
        if plan.get("source_kind") != "planning_workspace":
            raise GenerationPlanError("Generation plan is not a planning workspace")
        return plan

    def task(
        self,
        plan_id: str,
        stage_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        plan = self.plan(plan_id)
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
                f"Planning stage {stage_number} has no generation task"
            )
        return plan, task

    @staticmethod
    def _stage_status(task: dict[str, Any]) -> str:
        state = str(task["status"])
        if state == "committed":
            return "approved"
        if state == "generated":
            return "ready"
        if state == "running":
            return "generating"
        if state == "blocked":
            return "pending"
        return state

    def view(self, plan_id: str) -> dict[str, Any]:
        plan = self.plan(plan_id)
        stages: list[dict[str, Any]] = []
        by_number = {
            int(item[0]): (str(item[1]), str(item[2]))
            for item in PLANNING_STAGES
        }
        for task in sorted(
            plan["tasks"],
            key=lambda item: int(item.get("target_key") or 999),
        ):
            try:
                number = int(task.get("target_key"))
            except (TypeError, ValueError):
                continue
            if number not in by_number:
                continue
            kind, description = by_number[number]
            result = dict(task.get("result") or {})
            draft = result.get("json")
            if not isinstance(draft, dict):
                draft = None
            operation = None
            if task.get("active_job_id"):
                job = self.data.jobs.get(task["active_job_id"])
                if job:
                    operation = {
                        key: job.get(key)
                        for key in (
                            "id", "status", "phase", "progress_message",
                            "progress_current", "progress_total", "error",
                            "created_at", "updated_at",
                        )
                    }
            stages.append(
                {
                    "id": task["id"],
                    "stage_number": number,
                    "kind": kind,
                    "description": description,
                    "status": self._stage_status(task),
                    "draft": draft,
                    "approved": draft if task["status"] == "committed" else None,
                    "human_prompt": str(
                        (task.get("prompt") or {}).get("human_prompt") or ""
                    ),
                    "raw_draft_text": result.get("raw"),
                    "validation_error": task.get("error"),
                    "active_job_id": task.get("active_job_id"),
                    "operation": operation,
                    "conflicts": [],
                    "dependency_snapshot": {},
                    "published_domains": {},
                }
            )

        current_stage = next(
            (
                stage["stage_number"]
                for stage in stages
                if stage["status"] not in {"approved", "skipped"}
            ),
            8,
        )
        image_plans = self.db.fetch_all(
            "SELECT * FROM generation_image_plans "
            "WHERE generation_plan_id=? ORDER BY created_at,id",
            (plan_id,),
        )
        return {
            "id": plan_id,
            "generation_plan_id": plan_id,
            "project_id": plan["project_id"],
            "status": "completed" if plan["status"] == "completed" else "active",
            "current_stage": current_stage,
            "schema_version": 3,
            "settings": dict(plan.get("settings") or {}),
            "stages": stages,
            "image_plans": image_plans,
            "recovery_warnings": [],
        }

    def queue_stage(
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
        plan, task = self.task(plan_id, stage_number)

        if stage_number == 8:
            prepared = self.planning.prepare_image_stage(
                plan_id,
                (task.get("result") or {}).get("json"),
            )
            self.data.batch_generation.replace_generated_result(
                plan_id,
                task["task_key"],
                {"json": prepared["draft"]},
            )
            return {
                "deterministic": True,
                "stage": self.view(plan_id)["stages"][7],
                "image_plans": prepared["image_plans"],
            }

        if task.get("active_job_id"):
            active = self.data.jobs.get(task["active_job_id"])
            if active and active["status"] in {"queued", "running"}:
                return {
                    "job": active,
                    "task": task,
                    "plan": plan,
                    "duplicate": True,
                }

        previous_result = dict(task.get("result") or {})
        task_prompt = dict(task.get("prompt") or {})
        task_prompt.update(
            {
                "planning_stage_number": stage_number,
                "human_prompt": human_prompt,
                "append": append,
                "focus": focus,
                "automate": automate,
                "automation_prompt": automation_prompt,
            }
        )
        if append and isinstance(previous_result.get("json"), dict):
            task_prompt["existing_draft"] = previous_result["json"]
        if repair:
            task_prompt["repair_text"] = str(previous_result.get("raw") or "")
            if not task_prompt["repair_text"]:
                raise GenerationPlanError(
                    "There is no malformed draft to repair"
                )

        task_settings = dict(task.get("settings") or {})
        task_settings.pop("planning_bridge", None)
        task_settings["planning_workspace"] = True

        if task["status"] in {
            "generated", "approved", "committed", "failed",
            "cancelled", "stale",
        }:
            plan = self.batch.regenerate_task(
                plan_id,
                task["task_key"],
                prompt=task_prompt,
                settings=task_settings,
                reason="planning stage regenerated",
            )
        else:
            self.data.batch_generation.configure_task(
                plan_id,
                task["task_key"],
                prompt=task_prompt,
                settings=task_settings,
            )
            plan = self.batch.get_plan(plan_id)

        job = self.batch.queue_task(
            plan_id,
            task["task_key"],
            requested_by_user_id=requested_by_user_id,
            requester_name_snapshot=requester_name_snapshot,
        )
        return {
            "job": job,
            "task": self.data.batch_generation.task(
                plan_id,
                task["task_key"],
            ),
            "plan": self.batch.get_plan(plan_id),
        }

    def skip(self, plan_id: str, stage_number: int) -> dict[str, Any]:
        _plan, task = self.task(plan_id, stage_number)
        if task.get("active_job_id"):
            raise GenerationPlanError(
                "Cancel active generation before skipping this stage"
            )
        self.data.batch_generation.import_task_state(
            plan_id,
            task["task_key"],
            status="committed",
            result={"json": empty_draft(stage_number)},
            metadata={"skipped": True},
        )
        return self.view(plan_id)

    def reopen(self, plan_id: str, stage_number: int) -> dict[str, Any]:
        _plan, task = self.task(plan_id, stage_number)
        if task.get("active_job_id"):
            raise GenerationPlanError(
                "Cancel active generation before reopening this stage"
            )
        self.batch.regenerate_task(
            plan_id,
            task["task_key"],
            reason="planning stage reopened",
        )
        return self.view(plan_id)

    def revalidate(self, plan_id: str, stage_number: int) -> dict[str, Any]:
        plan, task = self.task(plan_id, stage_number)
        if task["status"] != "stale":
            raise GenerationPlanError("Only stale stages can be revalidated")
        result = dict(task.get("result") or {})
        draft = result.get("json")
        if not isinstance(draft, dict):
            raise GenerationPlanError("Stale stage has no draft to revalidate")
        validate_stage(
            stage_number,
            draft,
            dict(plan.get("settings") or {}),
        )
        self.data.batch_generation.import_task_state(
            plan_id,
            task["task_key"],
            status="committed",
            result=result,
            metadata={
                **dict(task.get("commit_metadata") or {}),
                "revalidated": True,
            },
        )
        return self.view(plan_id)

    def dependency_impact(
        self,
        plan_id: str,
        stage_number: int,
    ) -> dict[str, Any]:
        plan, task = self.task(plan_id, stage_number)
        deps = {
            item["task_key"]: item["dependencies"]
            for item in plan["tasks"]
        }
        descendants = descendant_keys(task["task_key"], deps)
        by_key = {item["task_key"]: item for item in plan["tasks"]}
        return {
            "stage_number": stage_number,
            "changed_domains": [],
            "affected_stages": [
                {
                    "stage_number": int(by_key[key].get("target_key") or 0),
                    "kind": str(by_key[key].get("label") or ""),
                    "status": self._stage_status(by_key[key]),
                }
                for key in descendants
            ],
        }

    def revisions(self, plan_id: str) -> list[dict[str, Any]]:
        plan = self.plan(plan_id)
        result: list[dict[str, Any]] = []
        for task in plan["tasks"]:
            for revision in self.batch.revisions(
                plan_id,
                task["task_key"],
            ):
                result.append(
                    {
                        **revision,
                        "stage_number": int(task.get("target_key") or 0),
                        "task_key": task["task_key"],
                    }
                )
        return result

    def image_plan(self, image_plan_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM generation_image_plans WHERE id=?",
            (image_plan_id,),
        )

    def image_plan_ids(self, plan_id: str) -> set[str]:
        return {
            str(row["id"])
            for row in self.db.fetch_all(
                "SELECT id FROM generation_image_plans "
                "WHERE generation_plan_id=?",
                (plan_id,),
            )
        }

    def ready_image_plan_ids(self, plan_id: str) -> list[str]:
        return [
            str(row["id"])
            for row in self.db.fetch_all(
                "SELECT id FROM generation_image_plans "
                "WHERE generation_plan_id=? AND status='ready' "
                "ORDER BY created_at,id",
                (plan_id,),
            )
        ]

    def update_image_plan(
        self,
        image_plan_id: str,
        *,
        prompt: str,
        negative_prompt: str,
        workflow_preset_id: str | None,
        width: int | None,
        height: int | None,
        prompt_revision: str,
        status: str,
    ) -> dict[str, Any]:
        self.db.execute(
            "UPDATE generation_image_plans SET prompt=?,negative_prompt=?,"
            "workflow_preset_id=?,width=?,height=?,prompt_revision=?,status=?,"
            "error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                prompt, negative_prompt, workflow_preset_id, width, height,
                prompt_revision, status, image_plan_id,
            ),
        )
        return self.image_plan(image_plan_id) or {}

    def delete_image_plan(self, image_plan_id: str) -> None:
        self.db.execute(
            "DELETE FROM generation_image_plans WHERE id=?",
            (image_plan_id,),
        )

    def mark_image_plan_queued(
        self,
        image_plan_id: str,
        *,
        media_asset_id: str,
        generation_job_id: str,
    ) -> None:
        self.db.execute(
            "UPDATE generation_image_plans SET status='queued',"
            "media_asset_id=?,generation_job_id=?,error=NULL,"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (media_asset_id, generation_job_id, image_plan_id),
        )

    def clear_revisions(self, plan_id: str) -> int:
        rows = self.db.fetch_one(
            "SELECT COUNT(*) n FROM generation_task_revisions "
            "WHERE task_id IN (SELECT id FROM generation_plan_tasks "
            "WHERE plan_id=?)",
            (plan_id,),
        ) or {"n": 0}
        self.db.execute(
            "DELETE FROM generation_task_revisions "
            "WHERE task_id IN (SELECT id FROM generation_plan_tasks "
            "WHERE plan_id=?)",
            (plan_id,),
        )
        return int(rows["n"])

    def delete(self, plan_id: str) -> None:
        self.plan(plan_id)
        self.db.execute(
            "DELETE FROM generation_plans WHERE id=?",
            (plan_id,),
        )
