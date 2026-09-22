from __future__ import annotations

from pathlib import Path

import pytest

from app.database import Database
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchCommit import NoopBatchCommitter
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanDefinition,
    GenerationPlanError,
    GenerationTaskDefinition,
)


def setup_manager(tmp_path: Path):
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Review lifecycle")
    manager = BatchGenerationManager(db)
    plan = manager.create_plan(
        project["id"],
        GenerationPlanDefinition(
            name="Review plan",
            tasks=[
                GenerationTaskDefinition(
                    key="foundation",
                    generator_kind="deterministic",
                    target_kind="artifact",
                    prompt={"value": {"premise": "City"}},
                ),
                GenerationTaskDefinition(
                    key="character",
                    generator_kind="deterministic",
                    target_kind="artifact",
                    prompt={"value": {"name": "Hero"}},
                    dependencies=[
                        GenerationDependency(
                            "foundation",
                            "approved",
                        )
                    ],
                ),
                GenerationTaskDefinition(
                    key="portrait",
                    generator_kind="deterministic",
                    target_kind="artifact",
                    prompt={"value": {"image": "hero.png"}},
                    dependencies=[
                        GenerationDependency(
                            "character",
                            "committed",
                        )
                    ],
                ),
            ],
        ),
    )
    return db, project, manager, plan


def test_approval_unlocks_approved_dependency(tmp_path: Path) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    manager.repo.set_task_status(
        plan["id"],
        "foundation",
        "generated",
        result={"premise": "City"},
    )

    pending = manager.get_plan(plan["id"])
    assert pending["status"] == "awaiting_review"
    assert pending["ready_task_keys"] == []

    approved = manager.approve_task(
        plan["id"],
        "foundation",
        "Looks good",
    )
    assert approved["ready_task_keys"] == ["character"]
    foundation = next(
        task for task in approved["tasks"]
        if task["task_key"] == "foundation"
    )
    assert foundation["status"] == "approved"
    assert foundation["approved_at"]


def test_rejection_archives_result_and_invalidates_descendants(
    tmp_path: Path,
) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    plan_id = plan["id"]

    manager.repo.set_task_status(
        plan_id,
        "foundation",
        "approved",
        result={"premise": "Old city"},
    )
    manager.repo.set_task_status(
        plan_id,
        "character",
        "generated",
        result={"name": "Old hero"},
    )

    regenerated = manager.reject_task(
        plan_id,
        "foundation",
        "Change the premise",
    )

    by_key = {
        task["task_key"]: task
        for task in regenerated["tasks"]
    }
    assert by_key["foundation"]["status"] == "ready"
    assert by_key["foundation"]["revision"] == 2
    assert by_key["foundation"]["result"] is None
    assert by_key["character"]["status"] == "stale"
    assert by_key["character"]["result"] is None

    revisions = manager.revisions(plan_id, "foundation")
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["result"] == {"premise": "Old city"}
    assert revisions[0]["reason"] == "rejected: Change the premise"


def test_commit_requires_approval_and_adapter(tmp_path: Path) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    plan_id = plan["id"]

    manager.repo.set_task_status(
        plan_id,
        "foundation",
        "generated",
        result={"premise": "City"},
    )
    with pytest.raises(
        GenerationPlanError,
        match="Only approved tasks",
    ):
        manager.commit_task(
            plan_id,
            "foundation",
            NoopBatchCommitter(),
        )

    manager.approve_task(plan_id, "foundation")
    committed = manager.commit_task(
        plan_id,
        "foundation",
        NoopBatchCommitter(),
    )
    task = next(
        item for item in committed["tasks"]
        if item["task_key"] == "foundation"
    )
    assert task["status"] == "committed"
    assert task["committed_at"]
    assert task["commit_metadata"]["mode"] == "noop"


def test_committed_dependency_unlocks_next_task(tmp_path: Path) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    plan_id = plan["id"]

    manager.repo.set_task_status(
        plan_id,
        "foundation",
        "approved",
        result={"premise": "City"},
    )
    manager.repo.set_task_status(
        plan_id,
        "character",
        "approved",
        result={"name": "Hero"},
    )

    before = manager.get_plan(plan_id)
    assert "portrait" not in before["ready_task_keys"]

    manager.commit_task(
        plan_id,
        "character",
        NoopBatchCommitter(),
    )
    after = manager.get_plan(plan_id)
    assert after["ready_task_keys"] == ["portrait"]


def test_plan_becomes_completed_only_when_all_tasks_committed(
    tmp_path: Path,
) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    plan_id = plan["id"]

    for key in ("foundation", "character", "portrait"):
        manager.repo.set_task_status(
            plan_id,
            key,
            "approved",
            result={"key": key},
        )
        manager.commit_task(
            plan_id,
            key,
            NoopBatchCommitter(),
        )

    completed = manager.get_plan(plan_id)
    assert completed["status"] == "completed"


def test_batch_approval_is_atomic_at_validation_boundary(
    tmp_path: Path,
) -> None:
    _db, _project, manager, plan = setup_manager(tmp_path)
    plan_id = plan["id"]

    manager.repo.set_task_status(
        plan_id,
        "foundation",
        "generated",
        result={"a": 1},
    )

    with pytest.raises(GenerationPlanError):
        manager.approve_many(
            plan_id,
            ["foundation", "character"],
        )

    unchanged = manager.get_plan(plan_id)
    foundation = next(
        task for task in unchanged["tasks"]
        if task["task_key"] == "foundation"
    )
    assert foundation["status"] == "generated"
