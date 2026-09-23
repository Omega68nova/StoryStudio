from __future__ import annotations

import ast
from pathlib import Path


def app_file(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "app" / name


def test_old_planning_generation_aliases_are_removed() -> None:
    main = app_file("main.py").read_text(encoding="utf-8")

    assert '/projects/{project_id}/planning/random-direction' not in main
    assert '/planning/{session_id}/stages/{stage_number}' not in main


def test_generation_plan_routes_exist() -> None:
    main = app_file("main.py").read_text(encoding="utf-8")

    required = (
        '/api/projects/{project_id}/generation-plans',
        '/api/generation-plans/{plan_id}',
        '/api/generation-plans/{plan_id}/generate-ready',
        '/api/generation-plans/planning/{session_id}/tasks/{task_number}/generate',
        '/api/generation-plans/planning/{session_id}/tasks/{task_number}/preflight',
        '/api/generation-plans/planning/{session_id}/tasks/{task_number}/approve',
        '/api/generation-plans/{plan_id}/tasks/{task_key}/revisions',
    )
    for route in required:
        assert route in main


def test_generation_plan_routes_are_member_resolvable() -> None:
    main = app_file("main.py").read_text(encoding="utf-8")

    assert (
        'r"^/api/generation-plans/planning/([^/]+)"'
        in main
    )
    assert (
        'r"^/api/generation-plans/([^/]+)"'
        in main
    )
    assert (
        'path.startswith("/api/generation-plans/")'
        in main
    )
    assert (
        'r"/api/projects/[^/]+/generation-plans"'
        in main
    )


def test_generation_plan_api_service_is_syntax_valid() -> None:
    service = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "generationPlanApiService.py"
    )
    ast.parse(
        service.read_text(encoding="utf-8"),
        filename=str(service),
    )
