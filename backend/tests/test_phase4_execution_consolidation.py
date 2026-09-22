from __future__ import annotations

import ast
from pathlib import Path


def app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def test_legacy_planning_job_handler_is_removed() -> None:
    app = app_root()
    assert not (
        app / "handlers" / "planningJobHandler.py"
    ).exists()

    scheduler = (
        app / "services" / "scheduler.py"
    ).read_text(encoding="utf-8")
    assert "planningJobHandler" not in scheduler
    assert '"planning": PlanningJobHandler()' not in scheduler


def test_application_no_longer_creates_legacy_planning_jobs() -> None:
    offenders: list[str] = []

    for path in app_root().rglob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            if not isinstance(func, ast.Attribute):
                continue

            # Database.create_job(project_id, kind, ...)
            if (
                func.attr == "create_job"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "planning"
            ):
                offenders.append(
                    f"{path.name}:{node.lineno}"
                )

            # JobRepository.create(project_id, kind, ...)
            if (
                func.attr == "create"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "planning"
            ):
                owner = func.value
                if (
                    isinstance(owner, ast.Attribute)
                    and owner.attr == "jobs"
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno}"
                    )

    assert not offenders, (
        "Legacy planning jobs are still created at: "
        f"{offenders}"
    )


def test_structured_planning_is_owned_by_batch_generation() -> None:
    app = app_root()

    assert (
        app
        / "services"
        / "planningGenerationCore.py"
    ).is_file()
    assert (
        app
        / "services"
        / "planningBatchTaskExecutor.py"
    ).is_file()
    assert (
        app
        / "services"
        / "batchGenerationApiService.py"
    ).is_file()

    handler = (
        app
        / "handlers"
        / "batchGenerationJobHandler.py"
    ).read_text(encoding="utf-8")
    assert "PlanningBatchTaskExecutor" in handler
    assert "PlanningGenerationCore" in handler
