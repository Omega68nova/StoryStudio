from __future__ import annotations

from pathlib import Path

import pytest

from app.database import Database
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanCycleError,
    GenerationPlanDefinition,
    GenerationTaskDefinition,
    topological_layers,
)


def sample_definition() -> GenerationPlanDefinition:
    return GenerationPlanDefinition(
        name="Character package",
        source_kind="manual",
        tasks=[
            GenerationTaskDefinition(
                key="foundation",
                generator_kind="text",
                target_kind="foundation",
                prompt={"instruction": "Establish premise"},
            ),
            GenerationTaskDefinition(
                key="character",
                generator_kind="text",
                target_kind="character",
                target_key="hero",
                dependencies=[
                    GenerationDependency(
                        "foundation",
                        "generated",
                    )
                ],
            ),
            GenerationTaskDefinition(
                key="portrait",
                generator_kind="image",
                target_kind="portrait",
                target_key="hero",
                dependencies=[
                    GenerationDependency(
                        "character",
                        "approved",
                    )
                ],
            ),
        ],
    )


def setup_manager(tmp_path: Path) -> tuple[Database, dict, BatchGenerationManager]:
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Batch generation")
    return db, project, BatchGenerationManager(db)


def test_topological_layers_are_deterministic() -> None:
    definition = sample_definition()
    assert topological_layers(definition.tasks) == [
        ["foundation"],
        ["character"],
        ["portrait"],
    ]


def test_cycle_detection_names_cycle_members() -> None:
    definition = GenerationPlanDefinition(
        name="Cycle",
        tasks=[
            GenerationTaskDefinition(
                key="a",
                generator_kind="text",
                target_kind="test",
                dependencies=[GenerationDependency("b")],
            ),
            GenerationTaskDefinition(
                key="b",
                generator_kind="text",
                target_kind="test",
                dependencies=[GenerationDependency("a")],
            ),
        ],
    )
    with pytest.raises(GenerationPlanCycleError) as exc:
        definition.validate()
    assert exc.value.task_keys == ["a", "b"]


def test_plan_persists_and_exposes_initial_ready_task(tmp_path: Path) -> None:
    _db, project, manager = setup_manager(tmp_path)
    plan = manager.create_plan(project["id"], sample_definition())

    assert plan["status"] == "ready"
    assert plan["ready_task_keys"] == ["foundation"]
    statuses = {
        task["task_key"]: task["status"]
        for task in plan["tasks"]
    }
    assert statuses == {
        "foundation": "ready",
        "character": "blocked",
        "portrait": "blocked",
    }


def test_dependency_required_state_controls_readiness(tmp_path: Path) -> None:
    _db, project, manager = setup_manager(tmp_path)
    plan = manager.create_plan(project["id"], sample_definition())
    plan_id = plan["id"]

    manager.repo.set_task_status(
        plan_id,
        "foundation",
        "generated",
        result={"premise": "A city"},
    )
    plan = manager.get_plan(plan_id)
    assert plan["ready_task_keys"] == ["character"]

    manager.repo.set_task_status(
        plan_id,
        "character",
        "generated",
        result={"name": "Hero"},
    )
    plan = manager.get_plan(plan_id)
    assert "portrait" not in plan["ready_task_keys"]

    manager.repo.set_task_status(
        plan_id,
        "character",
        "approved",
    )
    plan = manager.get_plan(plan_id)
    assert plan["ready_task_keys"] == ["portrait"]


def test_revising_task_invalidates_only_descendants(tmp_path: Path) -> None:
    _db, project, manager = setup_manager(tmp_path)
    plan = manager.create_plan(project["id"], sample_definition())
    plan_id = plan["id"]

    for key, state in (
        ("foundation", "generated"),
        ("character", "approved"),
        ("portrait", "generated"),
    ):
        manager.repo.set_task_status(
            plan_id,
            key,
            state,
            result={"key": key},
        )

    revised = manager.revise_task(
        plan_id,
        "character",
        prompt={"instruction": "Change the hero"},
        settings={"temperature": 0.7},
    )
    by_key = {
        task["task_key"]: task
        for task in revised["tasks"]
    }

    assert by_key["foundation"]["status"] == "generated"
    assert by_key["character"]["revision"] == 2
    assert by_key["character"]["result"] is None
    assert by_key["portrait"]["status"] == "stale"
    assert by_key["portrait"]["result"] is None
