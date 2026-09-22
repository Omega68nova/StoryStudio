from __future__ import annotations

from pathlib import Path

from app.database import Database
from app.managers.batchGenerationManager import BatchGenerationManager
from app.services.planning import PlanningService
from app.services.planningGenerationBridge import (
    PlanningGenerationBridge,
    PlanningStageCommitter,
)
from app.services.world import WorldEngine


def foundation_draft(premise: str = "A city under glass") -> dict:
    return {
        "summary": "Foundation",
        "notes": [],
        "foundation": {
            "premise": premise,
            "tone": "mysterious",
            "style": "close and atmospheric",
            "world_description": "A sealed city.",
            "character_description": "People living under pressure.",
            "genres": ["mystery"],
            "themes": ["freedom"],
            "narration_mode": "third_limited",
            "pov_strategy": "first_player",
        },
    }


def setup(tmp_path: Path):
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Bridge")
    world = WorldEngine(db)
    planning = PlanningService(db, world)
    session = planning.create_session(
        project["id"],
        {"direction": "A mystery"},
    )
    return db, project, planning, session


def test_imported_draft_becomes_generated_task(tmp_path: Path) -> None:
    db, _project, planning, session = setup(tmp_path)
    first = session["stages"][0]
    planning.save_draft(first["id"], foundation_draft())

    bridge = PlanningGenerationBridge(db)
    plan = bridge.import_session(session["id"])

    task = next(
        item for item in plan["tasks"]
        if item["target_key"] == "1"
    )
    assert task["source_kind"] == "planning_stage"
    assert task["source_id"] == first["id"]
    assert task["status"] == "generated"
    assert task["result"]["json"]["foundation"]["premise"] == (
        "A city under glass"
    )


def test_existing_approved_stage_imports_as_committed(tmp_path: Path) -> None:
    db, _project, planning, session = setup(tmp_path)
    draft = foundation_draft()
    planning.approve_stage(session["id"], 1, draft)

    bridge = PlanningGenerationBridge(db)
    plan = bridge.import_session(session["id"])

    task = next(
        item for item in plan["tasks"]
        if item["target_key"] == "1"
    )
    assert task["status"] == "committed"
    assert task["commit_metadata"]["source"] == "planning_v2"
    assert task["commit_metadata"]["imported_existing_commit"] is True


def test_phase4_commit_publishes_through_planning_service(
    tmp_path: Path,
) -> None:
    db, project, planning, session = setup(tmp_path)
    first = session["stages"][0]
    planning.save_draft(
        first["id"],
        foundation_draft("The moon has stopped moving"),
    )

    bridge = PlanningGenerationBridge(db)
    plan = bridge.import_session(session["id"])
    manager = BatchGenerationManager(db)

    task = next(
        item for item in plan["tasks"]
        if item["target_key"] == "1"
    )
    manager.approve_task(plan["id"], task["task_key"])
    committed = manager.commit_task(
        plan["id"],
        task["task_key"],
        PlanningStageCommitter(db),
    )

    task = next(
        item for item in committed["tasks"]
        if item["target_key"] == "1"
    )
    assert task["status"] == "committed"
    assert task["commit_metadata"]["planning_stage_id"] == first["id"]

    premise = db.fetch_one(
        "SELECT content FROM bible_documents "
        "WHERE project_id=? AND kind='premise'",
        (project["id"],),
    )
    assert premise
    assert "The moon has stopped moving" in premise["content"]

    refreshed = planning.get_session(session["id"])
    assert refreshed["stages"][0]["status"] == "approved"


def test_bridge_import_is_idempotent(tmp_path: Path) -> None:
    db, _project, planning, session = setup(tmp_path)
    bridge = PlanningGenerationBridge(db)
    first = bridge.import_session(session["id"])
    second = bridge.import_session(session["id"])
    assert first["id"] == second["id"]
