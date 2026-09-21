from __future__ import annotations

from pathlib import Path
import shutil
import sys

TARGET = Path("backend/app/main.py")
BACKUP = TARGET.with_suffix(".py.phase3a-integration-backup")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}. No changes were written.")
    return text.replace(old, new, 1)

def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found. No changes were written.")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found. No changes were written.")
    return text[:start] + replacement + text[end:]

def main() -> int:
    if not TARGET.is_file():
        print(f"Could not find {TARGET}. Run this script from the StoryStudio repo root.", file=sys.stderr)
        return 2
    original = TARGET.read_text(encoding="utf-8")
    updated = original

    if "from app.data.dataProvider import DataProvider\n" not in updated:
        updated = replace_once(
            updated,
            "from app.services.environment import EnvironmentService\n",
            "from app.services.environment import EnvironmentService\n"
            "from app.data.dataProvider import DataProvider\n"
            "from app.services.routeDataService import RouteDataService\n",
            "repository imports",
        )

    if "data = DataProvider(db)\n" not in updated:
        updated = replace_once(
            updated,
            "environment = EnvironmentService(db)\n",
            "environment = EnvironmentService(db)\n"
            "data = DataProvider(db)\n"
            "route_data = RouteDataService(data)\n",
            "repository singletons",
        )

    updated = replace_between(
        updated,
        '@app.get("/api/projects")\n',
        '\n\n@app.post("/api/projects", status_code=201)\n',
        '@app.get("/api/projects")\n'
        'async def list_projects() -> list[dict[str, Any]]:\n'
        '    user = current_user()\n'
        '    return route_data.list_projects(admin=user.admin, user_id=user.id)\n',
        "project listing",
    )

    updated = replace_between(
        updated,
        '@app.get("/api/workflows")\n',
        '\n\n@app.get("/api/workflows/metadata")\n',
        '@app.get("/api/workflows")\n'
        'async def list_workflows() -> list[dict[str, Any]]:\n'
        '    return data.workflows.list(admin=current_user().admin)\n',
        "workflow listing",
    )

    updated = replace_between(
        updated,
        '@app.delete("/api/workflows/{workflow_id}", status_code=204)\n',
        '\n\n@app.get("/api/workflows/{workflow_id}/delete-impact")\n',
        '@app.delete("/api/workflows/{workflow_id}", status_code=204)\n'
        'async def delete_workflow(workflow_id: str) -> None:\n'
        '    if not data.workflows.exists(workflow_id):\n'
        '        raise HTTPException(404, "Workflow preset not found")\n'
        '    active = data.workflows.active_job(workflow_id)\n'
        '    if active:\n'
        '        raise HTTPException(409, {"message": "Workflow is used by an active image job", "recovery_actions": ["cancel_job", "retry_after_completion"]})\n'
        '    data.workflows.delete(workflow_id)\n',
        "workflow delete",
    )

    updated = replace_between(
        updated,
        '@app.get("/api/workflows/{workflow_id}/delete-impact")\n',
        '\n\n@app.get("/api/jobs")\n',
        '@app.get("/api/workflows/{workflow_id}/delete-impact")\n'
        'async def workflow_delete_impact(workflow_id: str) -> dict[str, Any]:\n'
        '    workflow = data.workflows.get(workflow_id)\n'
        '    if not workflow:\n'
        '        raise HTTPException(404, "Workflow preset not found")\n'
        '    return {"workflow_id": workflow_id, "name": workflow["name"], "confirmation": workflow["name"], "counts": {"historical_jobs": data.workflows.historical_job_count(workflow_id)}}\n',
        "workflow delete impact",
    )

    updated = replace_between(
        updated,
        '@app.get("/api/jobs")\n',
        '\n\n@app.get("/api/jobs/{job_id}")\n',
        '@app.get("/api/jobs")\n'
        'async def list_jobs(project_id: str | None = None) -> list[dict[str, Any]]:\n'
        '    user = current_user()\n'
        '    assigned = [] if user.admin else data.projects.assigned_project_ids(user.id)\n'
        '    try:\n'
        '        return route_data.list_jobs(admin=user.admin, assigned_project_ids=assigned, requested_project_id=project_id)\n'
        '    except PermissionError as exc:\n'
        '        raise HTTPException(403, str(exc)) from exc\n',
        "job listing",
    )

    updated = replace_between(
        updated,
        '@app.get("/api/jobs/{job_id}")\n',
        '\n\ndef _member_job_view',
        '@app.get("/api/jobs/{job_id}")\n'
        'async def get_job(job_id: str) -> dict[str, Any]:\n'
        '    job = route_data.get_job(job_id, admin=current_user().admin)\n'
        '    if not job:\n'
        '        raise HTTPException(404, "Generation job not found")\n'
        '    return job\n',
        "job get",
    )

    updated = replace_between(
        updated,
        '@app.post("/api/jobs/{job_id}/cancel", status_code=202)\n',
        '\n\n@app.delete("/api/jobs/history")\n',
        '@app.post("/api/jobs/{job_id}/cancel", status_code=202)\n'
        'async def cancel_job(job_id: str) -> dict[str, str]:\n'
        '    if not data.jobs.get(job_id):\n'
        '        raise HTTPException(404, "Generation job not found")\n'
        '    await scheduler.cancel(job_id)\n'
        '    return {"status": "cancellation_requested"}\n',
        "job cancel",
    )

    updated = replace_between(
        updated,
        '@app.delete("/api/jobs/history")\n',
        '\n\n@app.get("/api/data/summary")\n',
        '@app.delete("/api/jobs/history")\n'
        'async def clear_terminal_job_history(project_id: str | None = None) -> dict[str, int]:\n'
        '    if project_id:\n'
        '        require_project(project_id)\n'
        '    return {"removed": data.jobs.clear_terminal(TERMINAL_JOB_STATUSES, project_id=project_id)}\n',
        "job history",
    )

    if updated == original:
        print("Phase 3A integration already appears to be applied.")
        return 0
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
    TARGET.write_text(updated, encoding="utf-8")
    print(f"Updated: {TARGET}")
    print(f"Backup:  {BACKUP}")
    print("Integrated project listing, workflow read/delete routes, and job routes.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
