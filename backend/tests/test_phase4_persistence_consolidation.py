from __future__ import annotations

from pathlib import Path


def app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def test_planning_generation_context_uses_generation_plan() -> None:
    executor = (
        app_root()
        / "services"
        / "planningBatchTaskExecutor.py"
    ).read_text(encoding="utf-8")

    assert "PlanningPlanContext" in executor
    assert ".stage_for_generation(" not in executor


def test_planning_bridge_is_one_time_import() -> None:
    bridge = (
        app_root()
        / "services"
        / "planningGenerationBridge.py"
    ).read_text(encoding="utf-8")

    assert "legacy_import_complete" in bridge
    assert "sync_legacy_state=False" in bridge


def test_generation_plan_owns_manual_draft_persistence() -> None:
    main = (
        app_root()
        / "main.py"
    ).read_text(encoding="utf-8")

    assert (
        '/api/generation-plans/planning/{session_id}/tasks/'
        '{stage_number}/result'
    ) in main

    assert (
        '@app.put("/api/planning/{session_id}/stages/{stage_number}")'
        not in main
    )


def test_generation_plan_commit_does_not_sync_legacy_lifecycle() -> None:
    planning = (
        app_root()
        / "services"
        / "planning.py"
    ).read_text(encoding="utf-8")

    assert "sync_legacy_state: bool = True" in planning
    assert "if sync_legacy_state:" in planning
