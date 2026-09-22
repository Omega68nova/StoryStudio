from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.database import Database
from app.handlers.batchGenerationJobHandler import BatchGenerationJobHandler
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanDefinition,
    GenerationTaskDefinition,
)
from app.services.job_handlers import JobExecutionContext


class DummyEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def publish(self, kind: str, payload: dict) -> None:
        self.items.append((kind, payload))


class DummyAI:
    pass


def setup(tmp_path: Path):
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Batch execution")
    manager = BatchGenerationManager(db)
    definition = GenerationPlanDefinition(
        name="Executable plan",
        tasks=[
            GenerationTaskDefinition(
                key="foundation",
                generator_kind="deterministic",
                target_kind="foundation",
                prompt={"value": {"premise": "A city"}},
            ),
            GenerationTaskDefinition(
                key="character",
                generator_kind="deterministic",
                target_kind="character",
                prompt={"value": {"name": "Hero"}},
                dependencies=[GenerationDependency("foundation")],
            ),
        ],
    )
    plan = manager.create_plan(project["id"], definition)
    return db, project, manager, plan


def test_queue_ready_only_queues_current_frontier(tmp_path: Path) -> None:
    db, _project, manager, plan = setup(tmp_path)

    jobs = manager.queue_ready(plan["id"])
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "batch_generation"
    assert jobs[0]["payload"] == {
        "plan_id": plan["id"],
        "task_key": "foundation",
    }

    refreshed = manager.get_plan(plan["id"])
    by_key = {task["task_key"]: task for task in refreshed["tasks"]}
    assert by_key["foundation"]["status"] == "queued"
    assert by_key["foundation"]["active_job_id"] == jobs[0]["id"]
    assert by_key["character"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_deterministic_job_advances_dependency_frontier(tmp_path: Path) -> None:
    db, _project, manager, plan = setup(tmp_path)
    job = manager.queue_task(plan["id"], "foundation")

    events = DummyEvents()

    async def set_state(*_args):
        return None

    async def enqueue(_job_id: str):
        return None

    context = JobExecutionContext(
        db=db,
        events=events,
        ai=DummyAI(),
        job=job,
        cancel_event=asyncio.Event(),
        set_runtime_state=set_state,
        enqueue=enqueue,
    )
    await BatchGenerationJobHandler().run(context)

    saved_job = db.get_job(job["id"])
    assert saved_job["status"] == "completed"

    refreshed = manager.get_plan(plan["id"])
    by_key = {task["task_key"]: task for task in refreshed["tasks"]}
    assert by_key["foundation"]["status"] == "generated"
    assert by_key["foundation"]["active_job_id"] is None
    assert by_key["foundation"]["result"] == {
        "value": {"premise": "A city"}
    }
    assert refreshed["ready_task_keys"] == ["character"]
    assert by_key["character"]["status"] == "ready"


def test_scheduler_registers_batch_handler() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "scheduler.py"
    ).read_text(encoding="utf-8")
    assert '"batch_generation": BatchGenerationJobHandler()' in source


def test_image_handler_reports_delegated_batch_task() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "handlers"
        / "imageJobHandler.py"
    ).read_text(encoding="utf-8")
    assert "batch_generation_plan_id" in source
    assert "batch_generation_task_key" in source
    assert "def _finish_batch_task(" in source
