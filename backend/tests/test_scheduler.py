from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.database import Database, new_id, utc_now
from app.services.events import EventHub
from app.services.scheduler import GenerationScheduler
from app.services.minigames import VIRTUAL_PLAYER_ID
from app.services.world import WorldEngine


class FakeLlama:
    def __init__(self) -> None:
        self.loads = 0
        self.unloads = 0
        self.chat_calls = 0
        self.complete_calls = 0

    async def health(self) -> bool: return True
    async def load(self) -> None: self.loads += 1
    async def unload(self) -> None: self.unloads += 1

    async def chat_stream(self, messages: list[dict[str, str]], *, max_tokens=1400, cancel_event=None):
        self.chat_calls += 1
        yield "A bright "
        yield "beginning."

    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        self.complete_calls += 1
        if json_mode:
            return '{"title":"Dawn","prompt":"A bright dawn","negative_prompt":"fog"}'
        return "A concise summary."


class FakeComfy:
    def __init__(self, fail: bool = False) -> None:
        self.frees = 0
        self.interrupts = 0
        self.fail = fail
        self.last_graph = None

    async def health(self) -> bool: return True
    async def free(self) -> None: self.frees += 1
    async def interrupt(self) -> None: self.interrupts += 1
    async def object_info(self): return {"Text": {}, "SaveImage": {}}

    async def run_workflow(self, graph, output_node_id, progress, cancel_event):
        self.last_graph = graph
        await progress({"stage": "running", "value": 1, "max": 1})
        if self.fail:
            raise RuntimeError("synthetic image failure")
        return [(b"image", ".png")]


class FakeSupervisor:
    def __init__(self, llama: FakeLlama, comfy: FakeComfy) -> None:
        self.llama, self.comfy = llama, comfy

    async def ensure_started(self, settings): return self.llama, self.comfy
    async def shutdown(self) -> None: pass


def setup_db(path: Path) -> tuple[Database, dict[str, Any]]:
    db = Database(path)
    db.initialize()
    return db, db.create_project("Scheduler")


@pytest.mark.asyncio
async def test_story_job_creates_reply_and_suggestion(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Begin")
    job = db.create_job(project["id"], "story", {"user_node_id": user["id"]})
    llama, comfy = FakeLlama(), FakeComfy()
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(llama, comfy))
    await scheduler.start()
    await scheduler.enqueue(job["id"])
    await asyncio.wait_for(scheduler.queue.join(), 2)
    await scheduler.stop()
    saved = db.get_job(job["id"])
    assert saved and saved["status"] == "completed"
    assert db.fetch_one("SELECT content FROM story_nodes WHERE parent_id = ?", (user["id"],))["content"] == "A bright beginning."
    assert db.fetch_one("SELECT title FROM image_suggestions")["title"] == "Illustration idea"
    assert llama.loads == 1 and comfy.frees == 0


@pytest.mark.asyncio
async def test_image_failure_still_restores_storyteller(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Begin")
    assistant = db.create_story_node(project["id"], user["id"], "assistant", "Scene")
    suggestion_id, preset_id, now = new_id(), new_id(), utc_now()
    db.execute(
        "INSERT INTO image_suggestions(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) VALUES (?, ?, 'Scene', 'prompt', '', 'suggested', ?, ?)",
        (suggestion_id, assistant["id"], now, now),
    )
    graph = {"6": {"class_type": "Text", "inputs": {"text": "default prompt"}}, "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "%date:yyyy-MM-dd%"}}}
    mappings = {"positive_prompt": {"node_id": "6", "input_name": "text"}, "image_output": {"node_id": "9"}}
    db.execute(
        "INSERT INTO workflow_presets(id, name, graph_json, mappings_json, created_at, updated_at) VALUES (?, 'Test', ?, ?, ?, ?)",
        (preset_id, json.dumps(graph), json.dumps(mappings), now, now),
    )
    job = db.create_job(project["id"], "image", {"suggestion_id": suggestion_id, "preset_id": preset_id, "values": {"positive_prompt": "scene"}})
    llama, comfy = FakeLlama(), FakeComfy(fail=True)
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(llama, comfy))
    await scheduler.start()
    await scheduler.enqueue(job["id"])
    await asyncio.wait_for(scheduler.queue.join(), 2)
    await scheduler.stop()
    assert db.get_job(job["id"])["status"] == "failed"
    assert llama.unloads == 1 and llama.loads == 1
    assert comfy.frees == 1


@pytest.mark.asyncio
async def test_entity_media_image_attaches_output_and_restores_storyteller(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path); now = utc_now(); world = WorldEngine(db)
    created = world.normalize_mutations(project["id"], None, [{"tool": "createEntity", "arguments": {"kind": "location", "name": "Old Gate"}}], provenance="author")
    world.commit_root(project["id"], created, provenance="author", summary="location")
    entity_id, asset_id, preset_id = created[0].arguments["entity_id"], new_id(), new_id()
    db.execute("INSERT INTO entity_media_assets(id, project_id, entity_id, kind, source, status, prompt, created_at, updated_at) VALUES (?, ?, ?, 'location', 'suggested', 'queued', 'an old gate', ?, ?)", (asset_id, project["id"], entity_id, now, now))
    graph = {"6": {"class_type": "Text", "inputs": {"text": "default prompt"}}, "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "%date:yyyy-MM-dd%"}}}
    mappings = {"positive_prompt": {"node_id": "6", "input_name": "text"}, "image_output": {"node_id": "9"}}
    db.execute("INSERT INTO workflow_presets(id, name, graph_json, mappings_json, created_at, updated_at) VALUES (?, 'Entity image', ?, ?, ?, ?)", (preset_id, json.dumps(graph), json.dumps(mappings), now, now))
    job = db.create_job(project["id"], "image", {"media_asset_id": asset_id, "preset_id": preset_id, "values": {"prompt": "an old gate"}})
    llama, comfy = FakeLlama(), FakeComfy(); scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(llama, comfy))
    await scheduler.start(); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()
    asset = db.fetch_one("SELECT * FROM entity_media_assets WHERE id = ?", (asset_id,))
    assert asset and asset["status"] == "generated" and asset["source"] == "generated"
    assert (db.data_dir / asset["file_path"]).read_bytes() == b"image"
    assert comfy.last_graph["6"]["inputs"]["text"] == "an old gate"
    assert comfy.last_graph["9"]["inputs"]["filename_prefix"] == f"StoryStudio_{job['id']}"
    assert llama.unloads == 1 and llama.loads == 1 and comfy.frees == 1


@pytest.mark.asyncio
async def test_invalid_workflow_finishes_job_and_suggestion(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path); now = utc_now()
    user = db.create_story_node(project["id"], None, "user", "Begin")
    assistant = db.create_story_node(project["id"], user["id"], "assistant", "Scene")
    suggestion_id, preset_id = new_id(), new_id()
    db.execute(
        "INSERT INTO image_suggestions(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) VALUES (?, ?, 'Scene', 'prompt', '', 'queued', ?, ?)",
        (suggestion_id, assistant["id"], now, now),
    )
    graph = {"9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test"}}}
    mappings = {"positive_prompt": {"node_id": "missing", "input_name": "text"}, "image_output": {"node_id": "9"}}
    db.execute(
        "INSERT INTO workflow_presets(id, name, graph_json, mappings_json, created_at, updated_at) VALUES (?, 'Invalid', ?, ?, ?, ?)",
        (preset_id, json.dumps(graph), json.dumps(mappings), now, now),
    )
    job = db.create_job(project["id"], "image", {"suggestion_id": suggestion_id, "preset_id": preset_id, "values": {"prompt": "scene"}})
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(FakeLlama(), FakeComfy()))
    await scheduler.start(); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()
    assert db.get_job(job["id"])["status"] == "failed"
    assert db.fetch_one("SELECT status FROM image_suggestions WHERE id=?", (suggestion_id,))["status"] == "failed"


@pytest.mark.asyncio
async def test_cancelling_queued_image_updates_its_target(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path); now = utc_now()
    user = db.create_story_node(project["id"], None, "user", "Begin")
    assistant = db.create_story_node(project["id"], user["id"], "assistant", "Scene")
    suggestion_id = new_id()
    db.execute(
        "INSERT INTO image_suggestions(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) VALUES (?, ?, 'Scene', 'prompt', '', 'queued', ?, ?)",
        (suggestion_id, assistant["id"], now, now),
    )
    job = db.create_job(project["id"], "image", {"suggestion_id": suggestion_id, "preset_id": "unused", "values": {}})
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(FakeLlama(), FakeComfy()))
    await scheduler.cancel(job["id"])
    assert db.get_job(job["id"])["status"] == "cancelled"
    assert db.fetch_one("SELECT status FROM image_suggestions WHERE id=?", (suggestion_id,))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_story_planner_omits_invalid_preplan_and_keeps_model_resident(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    first_user = db.create_story_node(project["id"], None, "user", "Begin")
    second_user = db.create_story_node(project["id"], None, "user", "Begin elsewhere")

    class RepairingLlama(FakeLlama):
        def __init__(self) -> None:
            super().__init__(); self.plans = 0

        async def complete(self, messages, *, json_mode=False, max_tokens=1000):
            if json_mode and "deterministic scene planner" in messages[0]["content"]:
                self.plans += 1
                if self.plans == 1:
                    return '{"scene_intent":"begin","queries":[],"mutations":[{"tool":"createEntity","arguments":{"kind":"","name":""}}]}'
                return '{"scene_intent":"begin","queries":[],"mutations":[]}'
            if json_mode and "Compare the prose" in messages[0]["content"]:
                return '{"mutations":[]}'
            if json_mode:
                return '{"title":"Dawn","prompt":"Dawn","negative_prompt":""}'
            return "summary"

    llama, comfy = RepairingLlama(), FakeComfy()
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(llama, comfy))
    await scheduler.start()
    for user in (first_user, second_user):
        job = db.create_job(project["id"], "story", {"user_node_id": user["id"]})
        await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2)
        assert db.get_job(job["id"])["status"] == "completed"
    await scheduler.stop()
    assert llama.plans == 2
    assert llama.loads == 1 and llama.unloads == 0 and comfy.frees == 0


@pytest.mark.asyncio
async def test_direct_story_is_one_request_and_hides_fragmented_inline_tools(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Meet someone")

    class InlineLlama(FakeLlama):
        async def chat_stream(self, messages, *, max_tokens=1400, cancel_event=None):
            self.chat_calls += 1
            yield "Mira steps closer. <ss-"
            yield 'tool>{"name":"createEntity","arguments":{"key":"mira","kind":"character","name":"Mira"}}</ss-tool>'
            yield '<ss-tool>{"name":"updateEntity","arguments":{"entity_id":"mira","patch":{"personality":"brave"}}}</ss-tool>'
            yield " She smiles."

    llama, comfy = InlineLlama(), FakeComfy()
    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(llama, comfy))
    job = db.create_job(project["id"], "story", {"user_node_id": user["id"], "generation_mode": "direct", "response_max_tokens": 300})
    await scheduler.start(); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()
    saved = db.get_job(job["id"])
    assistant = db.fetch_one("SELECT * FROM story_nodes WHERE parent_id=?", (user["id"],))
    assert saved["status"] == "completed" and llama.chat_calls == 1 and llama.complete_calls == 0, saved
    assert assistant["content"] == "Mira steps closer.  She smiles."
    assert "ss-tool" not in assistant["content"]
    assert db.fetch_one("SELECT id FROM world_entities WHERE canonical_name='Mira'")


@pytest.mark.asyncio
async def test_running_story_can_cancel_during_planning(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path); user = db.create_story_node(project["id"], None, "user", "Begin")

    class SlowLlama(FakeLlama):
        async def complete(self, messages, *, json_mode=False, max_tokens=1000):
            await asyncio.sleep(30)
            return '{}'

    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(SlowLlama(), FakeComfy()))
    job = db.create_job(project["id"], "story", {"user_node_id": user["id"]})
    await scheduler.start(); await scheduler.enqueue(job["id"])
    for _ in range(100):
        if db.get_job(job["id"])["status"] == "running": break
        await asyncio.sleep(.01)
    await scheduler.cancel(job["id"])
    await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()
    assert db.get_job(job["id"])["status"] == "cancelled"
    assert not db.fetch_one("SELECT id FROM story_nodes WHERE parent_id=?", (user["id"],))


@pytest.mark.asyncio
async def test_stopping_stream_keeps_only_complete_sentences(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Begin")

    class StoppableLlama(FakeLlama):
        async def chat_stream(self, messages, *, max_tokens=1400, cancel_event=None):
            yield "The first sentence is complete. "
            yield "The unfinished sentence"
            await cancel_event.wait()
            raise asyncio.CancelledError

    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(StoppableLlama(), FakeComfy()))
    job = db.create_job(project["id"], "story", {"user_node_id": user["id"], "generation_mode": "direct"})
    await scheduler.start(); await scheduler.enqueue(job["id"])
    for _ in range(100):
        if db.get_job(job["id"])["status"] == "running":
            await asyncio.sleep(.02)
            break
        await asyncio.sleep(.01)
    await scheduler.cancel(job["id"])
    await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()
    assistant = db.fetch_one("SELECT content FROM story_nodes WHERE parent_id=?", (user["id"],))
    assert assistant and assistant["content"] == "The first sentence is complete."
    assert db.get_job(job["id"])["status"] == "completed"
    assert db.get_job(job["id"])["result"]["stopped"] is True


def test_sentence_cutoff_discards_incomplete_tail() -> None:
    assert GenerationScheduler._complete_sentences("One. Two unfinished") == "One."
    assert GenerationScheduler._complete_sentences("No completed sentence") == ""


@pytest.mark.asyncio
async def test_story_can_pause_for_multiple_minigames(tmp_path: Path) -> None:
    db, project = setup_db(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Try two challenges", action_kind="do")

    class TwoGameLlama(FakeLlama):
        async def chat_stream(self, messages, *, max_tokens=1400, cancel_event=None):
            self.chat_calls += 1
            if self.chat_calls == 1:
                yield "The coin rises."
                yield f'<ss-tool>{{"name":"startMinigame","arguments":{{"game_key":"flip_coin","actor_id":"{VIRTUAL_PLAYER_ID}","participant_id":"{VIRTUAL_PLAYER_ID}","target_id":null,"difficulty":1,"challenge_text":"Call the coin"}}}}</ss-tool>'
            elif self.chat_calls == 2:
                yield " Next comes the die."
                yield f'<ss-tool>{{"name":"startMinigame","arguments":{{"game_key":"roll_d6","actor_id":"{VIRTUAL_PLAYER_ID}","participant_id":"{VIRTUAL_PLAYER_ID}","target_id":null,"difficulty":3,"challenge_text":"Roll the die"}}}}</ss-tool>'
            else:
                yield " The sequence ends."

    scheduler = GenerationScheduler(db, EventHub(), FakeSupervisor(TwoGameLlama(), FakeComfy()))
    for key in ("flip_coin", "roll_d6"):
        config = next(row for row in scheduler.minigames.configs(project["id"]) if row["game_key"] == key)
        config["enabled"] = True
        scheduler.minigames.update_config(project["id"], key, config)
    job = db.create_job(project["id"], "story", {"user_node_id": user["id"], "generation_mode": "direct"})
    await scheduler.start(); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2)

    first = scheduler.minigames.get_session(db.fetch_one("SELECT id FROM minigame_sessions WHERE job_id=? AND status='awaiting_input'", (job["id"],))["id"])
    first, _ = scheduler.minigames.resolve(first["id"], {"choice": "heads"})
    payload = db.get_job(job["id"])["payload"] | {"minigame_session_id": first["id"], "minigame_session_ids": [first["id"]]}
    db.update_job_payload(job["id"], payload); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2)

    second_row = db.fetch_one("SELECT id FROM minigame_sessions WHERE job_id=? AND status='awaiting_input'", (job["id"],))
    second, _ = scheduler.minigames.resolve(second_row["id"], {})
    payload = db.get_job(job["id"])["payload"] | {"minigame_session_id": second["id"], "minigame_session_ids": [first["id"], second["id"]]}
    db.update_job_payload(job["id"], payload); await scheduler.enqueue(job["id"]); await asyncio.wait_for(scheduler.queue.join(), 2); await scheduler.stop()

    saved = db.get_job(job["id"])
    sessions = db.fetch_all("SELECT status,story_node_id FROM minigame_sessions WHERE job_id=? ORDER BY created_at", (job["id"],))
    assistant = db.fetch_one("SELECT content FROM story_nodes WHERE parent_id=? AND role='assistant'", (user["id"],))
    assert saved["status"] == "completed" and len(saved["result"]["minigame_session_ids"]) == 2
    assert assistant["content"] == "The coin rises. Next comes the die. The sequence ends."
    assert len(sessions) == 2 and all(session["status"] == "committed" and session["story_node_id"] for session in sessions)
