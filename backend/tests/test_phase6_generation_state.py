from __future__ import annotations

from pathlib import Path

from app.database import Database
from app.services.generationPlanApiService import GenerationPlanApiService


ROOT = Path(__file__).resolve().parents[1]


def test_planning_manual_save_survives_append_handoff(tmp_path: Path) -> None:
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Planning save handoff")
    service = GenerationPlanApiService(db)
    plan = service.workspace.create(project["id"], {})

    saved = {
        "summary": "Keep these results",
        "notes": [],
        "foundation": {
            "premise": "Existing premise",
            "genres": [],
            "themes": [],
            "tone": "",
            "style": "",
            "world_description": "",
            "character_description": "",
            "narration_mode": "third_limited",
            "pov_strategy": "first_player",
        },
    }

    service.save_planning_result(plan["id"], 1, saved)
    _plan, task = service.workspace.task(plan["id"], 1)

    assert task["status"] == "generated"
    assert task["result"]["json"] == saved

    queued = service.workspace.queue_stage(
        plan["id"],
        1,
        append=True,
        focus="foundation",
    )
    assert queued["job"]["id"]

    _plan, queued_task = service.workspace.task(plan["id"], 1)
    assert queued_task["prompt"]["append"] is True
    assert queued_task["prompt"]["existing_draft"] == saved


def test_character_image_generation_tracks_terminal_job_and_refreshes_media() -> None:
    source = (ROOT / "frontend" / "src" / "CharacterStudio.tsx").read_text(
        encoding="utf-8"
    )
    editor = (ROOT / "frontend" / "src" / "CharacterEditorForm.tsx").read_text(
        encoding="utf-8"
    )
    surface = (
        ROOT
        / "frontend"
        / "src"
        / "customComponents"
        / "EntityImageSurface.tsx"
    ).read_text(encoding="utf-8")

    assert "setMediaJobs" in source
    assert "/jobs/${job.id}" in source
    assert "await refreshMedia(draft.id!)" in source
    assert "revision, draft?.id" in source
    assert "loading={Boolean(portraitJob)}" in editor
    assert "CircularProgress" in surface
    assert "disabled={loading}" in surface
