from __future__ import annotations

import ast
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _calls_named(source: str, name: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == name
            )
        )
    ]


def test_story_planner_uses_the_ai_world_tool_boundary() -> None:
    source = (APP / "services" / "story_planner.py").read_text(
        encoding="utf-8"
    )

    assert "AIWorldToolService" in source
    assert ".db.fetch_one(" not in source
    assert ".db.fetch_all(" not in source
    assert ".db.execute(" not in source
    assert "self.world.execute_read_tool(" not in source


def test_image_jobs_execute_through_image_manager() -> None:
    source = (APP / "handlers" / "imageJobHandler.py").read_text(
        encoding="utf-8"
    )

    assert "ImageManager(context.ai).generate_generic(" in source
    assert not _calls_named(source, "generate_image")


def test_planning_task_metadata_is_outside_the_studio_component() -> None:
    studio = (FRONTEND / "PlanningStudio.tsx").read_text(
        encoding="utf-8"
    )
    model = (FRONTEND / "planningTaskModel.ts").read_text(
        encoding="utf-8"
    )

    assert "PLANNING_TASK_NAMES" in model
    assert "emptyPlanningTask" in model
    assert "planningGenerationPlanView" in model
    assert "const STAGE_NAMES" not in studio
    assert "function emptyStage" not in studio
    assert "Start eight-stage workshop" not in studio
