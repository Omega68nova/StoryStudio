from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_restart_recovery_no_longer_rebuilds_legacy_planning_state() -> None:
    assert "self._repair_planning_state(connection)" not in read("database.py")


def test_resource_provenance_is_generation_plan_aware() -> None:
    source = read("services/planning_v2.py")
    assert "def _provenance_owner_ids(" in source
    assert "generation_plan_id" in source
    assert "def record_resource(" in source


def test_generation_plan_id_reaches_canonical_publisher() -> None:
    planning = read("services/planning.py")
    bridge = read("services/planningGenerationBridge.py")
    assert "generation_plan_id: str | None = None" in planning
    assert "provenance_owner = generation_plan_id or session_id" in planning
    assert 'generation_plan_id=plan["id"]' in bridge


def test_stage8_image_plans_are_generation_plan_owned() -> None:
    handler = read("handlers/batchGenerationJobHandler.py")
    source = read("services/planning_v2.py")
    assert "generation_plan_id=plan_id" in handler
    assert "generation_plan_id=COALESCE(generation_plan_id,?)" in source
