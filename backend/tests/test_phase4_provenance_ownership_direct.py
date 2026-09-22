from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_resource_resolution_uses_plan_source_as_legacy_fallback() -> None:
    source = read("services/planning_v2.py")
    assert "def _provenance_owner_ids(" in source
    assert "str(plan.get(\"source_id\") or owner_id)" in source
    assert "_resource_row(db, owner_id" in source


def test_runtime_does_not_overwrite_provenance_owner_id() -> None:
    source = read("services/planning_v2.py")
    assert "ambient_owner_id = resolve_resource(db, owner_id" in source
    assert "owner_id = resolve_resource(db, owner_id" not in source


def test_image_plan_update_backfills_generation_plan_owner() -> None:
    source = read("services/planning_v2.py")
    assert (
        "generation_plan_id=COALESCE(generation_plan_id,?)"
        in source
    )


def test_planning_publication_writes_generation_plan_provenance() -> None:
    source = read("services/planning.py")
    assert (
        "INSERT INTO planning_resource_keys("
        "session_id,generation_plan_id,resource_key"
    ) in source
    assert (
        "(generation_plan_id=? OR "
        in source
    )


def test_planning_committer_passes_generation_plan_id() -> None:
    source = read("services/planningGenerationBridge.py")
    assert 'generation_plan_id=plan["id"]' in source
