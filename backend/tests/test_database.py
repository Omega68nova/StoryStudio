from pathlib import Path

from app.database import Database


def test_migrations_defaults_and_branch_path(tmp_path: Path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("The Glass Sea")
    documents = db.fetch_all(
        "SELECT * FROM bible_documents WHERE project_id = ? ORDER BY position", (project["id"],)
    )
    assert [document["kind"] for document in documents] == [
        "premise", "style", "world", "characters", "continuity"
    ]
    root = db.create_story_node(project["id"], None, "user", "Begin")
    first = db.create_story_node(project["id"], root["id"], "assistant", "First")
    alternate = db.create_story_node(project["id"], root["id"], "assistant", "Alternate")
    assert [node["id"] for node in db.story_path(alternate["id"])] == [root["id"], alternate["id"]]
    assert first["id"] not in {node["id"] for node in db.story_path(alternate["id"])}


def test_initialize_marks_unfinished_jobs_interrupted(tmp_path: Path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Restart")
    job = db.create_job(project["id"], "story", {"user_node_id": "missing"})
    db.initialize()
    restored = db.get_job(job["id"])
    assert restored is not None
    assert restored["status"] == "interrupted"
    assert "restarted" in restored["error"]


def test_relocate_requires_unlocked_empty_destination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("STORYSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    db = Database()
    db.initialize()
    project = db.create_project("Portable")
    destination = tmp_path / "moved"
    db.relocate(destination)
    assert db.data_dir == destination.resolve()
    assert db.get_project(project["id"])["title"] == "Portable"
    assert (tmp_path / "local" / "StoryStudio" / "location.json").is_file()
