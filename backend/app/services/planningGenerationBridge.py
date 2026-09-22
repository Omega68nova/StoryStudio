from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchCommit import BatchCommitResult, BatchTaskCommitter
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanDefinition,
    GenerationPlanError,
    GenerationTaskDefinition,
)
from app.services.planning import PlanningService
from app.services.world import WorldEngine, WorldValidationError


@dataclass(slots=True, frozen=True)
class ImportedPlanningTask:
    task_key: str
    source_stage_id: str
    stage_number: int
    source_status: str


class PlanningGenerationBridge:
    """One-way import/synchronization bridge from Planning v2."""

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

    @staticmethod
    def task_key(stage_number: int, kind: str) -> str:
        normalized = "_".join(
            str(kind or f"stage_{stage_number}")
            .strip().lower().replace("-", " ").split()
        )
        return f"planning_{stage_number:02d}_{normalized}"

    def import_session(
        self,
        session_id: str,
        *,
        name: str | None = None,
    ) -> dict[str, Any]:
        session = self.planning.get_session(session_id)
        existing = self.data.batch_generation.plan_by_source(
            "planning_session",
            session_id,
        )
        if existing:
            return self.sync_session(existing["id"], session_id)

        tasks: list[GenerationTaskDefinition] = []
        previous_key: str | None = None
        for stage in session["stages"]:
            number = int(stage["stage_number"])
            key = self.task_key(number, str(stage["kind"]))
            tasks.append(
                GenerationTaskDefinition(
                    key=key,
                    label=f"{number}. {stage['kind']}",
                    generator_kind="deterministic" if number == 8 else "text",
                    target_kind="planning_stage",
                    target_key=str(number),
                    prompt={
                        "planning_session_id": session_id,
                        "planning_stage_number": number,
                    },
                    settings={
                        "runtime_mode": "planning",
                        "parse_json": True,
                        "planning_bridge": True,
                    },
                    dependencies=(
                        [GenerationDependency(previous_key, "committed")]
                        if previous_key else []
                    ),
                )
            )
            previous_key = key

        plan = self.batch.create_plan(
            session["project_id"],
            GenerationPlanDefinition(
                name=name or f"Planning: {session['project_id']}",
                source_kind="planning_session",
                source_id=session_id,
                settings={
                    "planning_session_id": session_id,
                    "planning_schema_version": session.get("schema_version", 2),
                    "bridge_version": 1,
                },
                tasks=tasks,
            ),
        )
        for stage in session["stages"]:
            self.data.batch_generation.set_task_source(
                plan["id"],
                self.task_key(int(stage["stage_number"]), str(stage["kind"])),
                "planning_stage",
                stage["id"],
            )
        return self.sync_session(plan["id"], session_id)

    def sync_session(
        self,
        plan_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        plan = self.batch.get_plan(plan_id)
        session = self.planning.get_session(session_id)
        if plan.get("source_kind") != "planning_session":
            raise GenerationPlanError(
                "Generation plan is not a Planning v2 bridge"
            )
        if str(plan.get("source_id")) != str(session_id):
            raise GenerationPlanError(
                "Generation plan belongs to another planning session"
            )

        by_source = {
            task["source_id"]: task
            for task in plan["tasks"]
            if task.get("source_kind") == "planning_stage"
            and task.get("source_id")
        }
        for stage in session["stages"]:
            task = by_source.get(stage["id"])
            if not task or task["status"] in {"queued", "running"}:
                continue

            if stage["status"] in {"approved", "skipped"} and stage.get("approved"):
                self.data.batch_generation.import_task_state(
                    plan_id,
                    task["task_key"],
                    status="committed",
                    result={"json": stage["approved"]},
                    metadata={
                        "source": "planning_v2",
                        "planning_stage_id": stage["id"],
                        "transaction_id": stage.get("transaction_id"),
                        "imported_existing_commit": True,
                    },
                )
            elif stage.get("draft") is not None:
                self.data.batch_generation.import_task_state(
                    plan_id,
                    task["task_key"],
                    status="generated",
                    result={"json": stage["draft"]},
                    metadata=None,
                )
        return self.batch.get_plan(plan_id)


class PlanningStageCommitter(BatchTaskCommitter):
    """Publish one approved Phase 4 task through PlanningService."""

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
        self.world = world or WorldEngine(
            db,
            data_provider=self.data,
        )
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
        if task.get("source_kind") != "planning_stage":
            raise GenerationPlanError(
                "PlanningStageCommitter requires a planning_stage task"
            )
        session_id = str(
            plan.get("source_id")
            or plan.get("settings", {}).get("planning_session_id")
            or ""
        )
        if not session_id:
            raise GenerationPlanError("Planning bridge has no source session")

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
            session_id,
            stage_number,
            draft,
        )
        unresolved = [
            item for item in conflicts
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
        committed = self.planning.approve_stage(
            session_id,
            stage_number,
            draft,
            resolutions,
        )
        if stage_number == 7:
            self.planning.prepare_image_stage(session_id)

        tx = committed.get("transaction") or {}
        return BatchCommitResult(
            metadata={
                "source": "planning_v2",
                "planning_session_id": session_id,
                "planning_stage_id": task.get("source_id"),
                "stage_number": stage_number,
                "transaction_id": tx.get("id"),
                "duplicate": bool(committed.get("duplicate")),
            }
        )
