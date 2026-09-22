from __future__ import annotations

from pathlib import Path

from app.database import Database


APP = Path(__file__).resolve().parents[1] / "app"


def read(path: str) -> str:
    return (APP / path).read_text(encoding="utf-8")


def test_fresh_database_has_no_legacy_planning_state_tables(tmp_path: Path) -> None:
    db = Database(tmp_path)
    db.initialize()
    tables = {
        row["name"]
        for row in db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "generation_resource_keys" in tables
    assert "generation_image_plans" in tables
    for legacy in {
        "planning_sessions",
        "planning_stages",
        "planning_stage_revisions",
        "planning_conflicts",
        "planning_approval_claims",
        "planning_entity_keys",
        "planning_resource_keys",
        "planning_image_plans",
    }:
        assert legacy not in tables


def test_live_planning_service_has_no_legacy_table_dependency() -> None:
    source = read("services/planning.py")
    for legacy in (
        "planning_sessions",
        "planning_stages",
        "planning_conflicts",
        "planning_approval_claims",
        "planning_entity_keys",
        "planning_resource_keys",
        "planning_image_plans",
    ):
        assert legacy not in source


def test_planning_execution_uses_plan_identity() -> None:
    executor = read("services/planningBatchTaskExecutor.py")
    context = read("services/planningPlanContext.py")
    assert "planning_session_id" not in executor
    assert "plan_and_stage(" in context
    assert "planning_sessions" not in context


def test_bridge_runtime_is_removed() -> None:
    assert not (APP / "services" / "planningGenerationBridge.py").exists()
    generation_api = read("services/generationPlanApiService.py")
    batch_api = read("services/batchGenerationApiService.py")
    assert "PlanningGenerationBridge" not in generation_api
    assert "PlanningGenerationBridge" not in batch_api


def test_image_job_completion_uses_generation_owned_table() -> None:
    handler = read("handlers/imageJobHandler.py")
    assert "generation_image_plans" in handler
    assert "planning_image_plans" not in handler


def test_http_runtime_does_not_query_legacy_planning_tables() -> None:
    main = read("main.py")
    assert "FROM planning_sessions" not in main
    assert "FROM planning_stages" not in main
    assert "FROM planning_image_plans" not in main
    assert "data.planning" not in main
