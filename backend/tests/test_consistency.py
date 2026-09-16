import json
from pathlib import Path

from app.database import Database, new_id, utc_now
from app.services.lifecycle import DataLifecycle, LifecycleConflict
import pytest
from app.services.planning import PlanningService
from app.services.world import WorldEngine
from app import main as app_main
from app.schemas import StoryTurnCreate


def setup(path: Path):
    db = Database(path); db.initialize(); project = db.create_project("Consistency"); world = WorldEngine(db)
    return db, project, world, PlanningService(db, world)


def create_entity(world: WorldEngine, project_id: str, name: str, *, tags=None, state=None) -> str:
    mutations = world.normalize_mutations(project_id, None, [{"tool": "createEntity", "arguments": {
        "kind": "character", "name": name, "tags": tags or [], "state": state or {},
    }}], provenance="author")
    world.commit_root(project_id, mutations, provenance="author", summary=name)
    return mutations[0].arguments["entity_id"]


def test_planning_conflict_resolutions_and_idempotent_approval(tmp_path: Path) -> None:
    db, project, world, planning = setup(tmp_path)
    ids = {name: create_entity(world, project["id"], name, tags=["old"], state={"traits": ["old"]}) for name in ("Link", "Merge", "Rename", "Omit")}
    session = planning.create_session(project["id"], {})
    draft = {"summary": "Resolved", "entities": [
        {"key": name.casefold(), "kind": "character", "name": name, "aliases": [], "tags": ["new"], "state": {"traits": ["new"]}}
        for name in ids
    ], "relations": [{"source_key": "rename", "target_key": "omit", "relation": "friend"}]}
    conflicts = planning.preflight(session["id"], 1, draft)
    assert len(conflicts) == 4
    result = planning.approve_stage(session["id"], 1, draft, {
        "link": {"action": "link", "entity_id": ids["Link"]},
        "merge": {"action": "merge", "entity_id": ids["Merge"]},
        "rename": {"action": "rename", "new_name": "Renamed Copy"},
        "omit": {"action": "omit"},
    })
    projection = world.projection(project["id"], use_cache=False)
    assert projection["entities"][ids["Merge"]]["state"]["traits"] == ["old", "new"]
    assert any(entity["name"] == "Renamed Copy" for entity in projection["entities"].values())
    assert not projection["relations"]
    repeated = planning.approve_stage(session["id"], 1, draft)
    assert repeated["duplicate"] is True
    assert repeated["transaction"]["id"] == result["transaction"]["id"]


def test_reopen_uses_inactive_ledger_and_preserves_immutable_transaction(tmp_path: Path) -> None:
    _, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    draft = {"summary": "Root", "entities": [{"key": "hero", "kind": "character", "name": "Hero", "state": {}}], "relations": []}
    approved = planning.approve_stage(session["id"], 1, draft)
    planning.reopen_stage(session["id"], 1)
    assert world.db.fetch_one("SELECT transaction_id FROM inactive_world_transactions WHERE transaction_id=?", (approved["transaction"]["id"],))
    assert not world.projection(project["id"], use_cache=False)["entities"]


def test_restart_repairs_approved_json_stale_generation_and_current_stage(tmp_path: Path) -> None:
    db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    draft = {"summary": "Kept", "entities": [], "relations": []}
    approved = planning.approve_stage(session["id"], 1, draft)
    stage = db.fetch_one("SELECT id FROM planning_stages WHERE session_id=? AND stage_number=1", (session["id"],))
    db.execute("UPDATE planning_stages SET status='draft',transaction_id=NULL,approved_revision_hash=NULL WHERE id=?", (stage["id"],))
    second = db.fetch_one("SELECT id FROM planning_stages WHERE session_id=? AND stage_number=2", (session["id"],))
    job = db.create_job(project["id"], "planning", {"session_id": session["id"], "stage_number": 2})
    db.execute("UPDATE planning_stages SET status='generating',active_job_id=? WHERE id=?", (job["id"], second["id"]))
    db.execute("UPDATE planning_sessions SET current_stage=5 WHERE id=?", (session["id"],))
    db.initialize()
    repaired = planning.get_session(session["id"])
    assert repaired["stages"][0]["status"] == "approved"
    assert repaired["stages"][0]["transaction_id"] == approved["transaction"]["id"]
    assert repaired["stages"][1]["status"] == "cancelled"
    assert repaired["current_stage"] == 2


def test_reference_counted_files_fts_cleanup_and_relocation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("STORYSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    db = Database(); db.initialize(); project = db.create_project("Files"); lifecycle = DataLifecycle(db); world = WorldEngine(db)
    create_entity(world, project["id"], "Indexed")
    assert db.fetch_one("SELECT COUNT(*) n FROM lore_card_search WHERE project_id=?", (project["id"],))["n"] > 0
    db.music_dir.mkdir(parents=True, exist_ok=True); shared = db.music_dir / "shared.ogg"; shared.write_bytes(b"OggSdata")
    now, themes = utc_now(), [new_id(), new_id()]
    for index, theme in enumerate(themes):
        db.execute("INSERT INTO music_themes(id,name,description,created_at,updated_at) VALUES(?,?, '',?,?)", (theme, f"Theme {index}", now, now))
        db.execute("INSERT INTO music_tracks(id,theme_id,title,file_path,mime_type,sha256,position,created_at) VALUES(?,?,?,'music/shared.ogg','audio/ogg','hash',0,?)", (new_id(), theme, "Shared", now))
    first = db.fetch_one("SELECT id FROM music_tracks WHERE theme_id=?", (themes[0],))
    db.execute("DELETE FROM music_tracks WHERE id=?", (first["id"],)); lifecycle.release_paths(["music/shared.ogg"])
    assert shared.exists()
    db.execute("DELETE FROM music_tracks"); lifecycle.release_paths(["music/shared.ogg"])
    assert not shared.exists()
    lifecycle.purge_project(project["id"])
    assert db.fetch_one("SELECT COUNT(*) n FROM lore_card_search WHERE project_id=?", (project["id"],))["n"] == 0
    destination = tmp_path / "relocated"; (db.music_dir / "keep.wav").write_bytes(b"RIFF")
    db.relocate(destination)
    assert (destination / "music" / "keep.wav").exists()


def test_relationship_removal_is_branch_event(tmp_path: Path) -> None:
    _, project, world, _ = setup(tmp_path)
    one = create_entity(world, project["id"], "One"); two = create_entity(world, project["id"], "Two")
    relation = world.normalize_mutations(project["id"], None, [{"tool": "setRelationship", "arguments": {"id": "bond", "source_id": one, "target_id": two, "relation": "friend"}}], provenance="author")
    world.commit_root(project["id"], relation, provenance="author", summary="set")
    removed = world.normalize_mutations(project["id"], None, [{"tool": "removeRelationship", "arguments": {"relationship_id": "bond"}}], provenance="author")
    world.commit_root(project["id"], removed, provenance="author", summary="remove")
    assert "bond" not in world.projection(project["id"], use_cache=False)["relations"]
    assert world.db.fetch_one("SELECT id FROM world_events WHERE event_type='relationship.removed'")


def test_bulk_cleanup_protects_active_jobs_and_preserves_shared_data(tmp_path: Path) -> None:
    db, project, _, _ = setup(tmp_path); lifecycle = DataLifecycle(db); now = utc_now()
    theme = new_id(); db.execute("INSERT INTO music_themes(id,name,description,created_at,updated_at) VALUES(?,'Shared','',?,?)", (theme, now, now))
    job = db.create_job(project["id"], "story", {})
    with pytest.raises(LifecycleConflict): lifecycle.clear_all_story_content()
    db.update_job(job["id"], "completed")
    result = lifecycle.clear_all_story_content()
    assert result["projects_removed"] == 1
    assert db.fetch_one("SELECT id FROM music_themes WHERE id=?", (theme,))
    assert db.fetch_one("SELECT id FROM runtime_settings WHERE id=1")


def test_restart_repairs_orphaned_queued_image_status(tmp_path: Path) -> None:
    db, project, _, _ = setup(tmp_path); now = utc_now()
    user = db.create_story_node(project["id"], None, "user", "Begin")
    assistant = db.create_story_node(project["id"], user["id"], "assistant", "Scene")
    suggestion_id = new_id()
    db.execute(
        "INSERT INTO image_suggestions(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) VALUES (?, ?, 'Scene', 'prompt', '', 'queued', ?, ?)",
        (suggestion_id, assistant["id"], now, now),
    )
    db.create_job(project["id"], "image", {"suggestion_id": suggestion_id, "preset_id": "missing", "values": {}})
    db.initialize()
    assert db.fetch_one("SELECT status FROM image_suggestions WHERE id=?", (suggestion_id,))["status"] == "interrupted"


@pytest.mark.asyncio
async def test_workflow_deletion_ignores_terminal_history_but_blocks_active_jobs(tmp_path: Path, monkeypatch) -> None:
    db, project, _, _ = setup(tmp_path); now = utc_now(); monkeypatch.setattr(app_main, "db", db)
    workflow_id = new_id()
    db.execute(
        "INSERT INTO workflow_presets(id,name,graph_json,mappings_json,created_at,updated_at) VALUES(?,'Old workflow','{}','{}',?,?)",
        (workflow_id, now, now),
    )
    terminal = db.create_job(project["id"], "image", {"preset_id": workflow_id})
    db.update_job(terminal["id"], "failed")
    await app_main.delete_workflow(workflow_id)
    assert not db.fetch_one("SELECT id FROM workflow_presets WHERE id=?", (workflow_id,))

    active_workflow_id = new_id()
    db.execute(
        "INSERT INTO workflow_presets(id,name,graph_json,mappings_json,created_at,updated_at) VALUES(?,'Active workflow','{}','{}',?,?)",
        (active_workflow_id, now, now),
    )
    db.create_job(project["id"], "image", {"preset_id": active_workflow_id})
    with pytest.raises(app_main.HTTPException) as conflict:
        await app_main.delete_workflow(active_workflow_id)
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_guide_and_continue_are_transient_and_not_story_messages(tmp_path: Path, monkeypatch) -> None:
    db, project, world, _ = setup(tmp_path)

    class SchedulerStub:
        def __init__(self): self.world = world; self.enqueued = []
        async def enqueue(self, job_id): self.enqueued.append(job_id)

    scheduler = SchedulerStub(); monkeypatch.setattr(app_main, "db", db); monkeypatch.setattr(app_main, "scheduler", scheduler)
    root = db.create_story_node(project["id"], None, "assistant", "Opening")
    db.execute("UPDATE projects SET active_node_id=? WHERE id=?", (root["id"], project["id"]))
    before = int(db.fetch_one("SELECT COUNT(*) n FROM story_nodes")["n"])
    guided = await app_main.create_turn(project["id"], StoryTurnCreate(parent_id=root["id"], content="Make the door ominous", action="guide"))
    assert guided["user_node"] is None
    assert int(db.fetch_one("SELECT COUNT(*) n FROM story_nodes")["n"]) == before
    guide_job = db.get_job(guided["job"]["id"]); assert guide_job["payload"]["guidance"] == "Make the door ominous"

    generated = db.create_story_node(project["id"], root["id"], "assistant", "The door waits.")
    db.update_job(guide_job["id"], "completed", result={"story_node_id": generated["id"]})
    db.execute("UPDATE projects SET active_node_id=? WHERE id=?", (generated["id"], project["id"]))
    continued = await app_main.create_turn(project["id"], StoryTurnCreate(parent_id=generated["id"], action="continue"))
    assert continued["user_node"] is None
    assert int(db.fetch_one("SELECT COUNT(*) n FROM story_nodes")["n"]) == before + 1
    assert "guidance" not in db.get_job(guide_job["id"])["payload"]
