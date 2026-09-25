from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from app.database import Database, new_id, utc_now
from app.domain.world import Ability, EffectDefinition, Stat
from app.services.media import MediaValidationError, content_hash, validate_audio, validate_image
from app.services.npc import NpcDirector
from app.services.world import WorldEngine, WorldValidationError


def setup(path: Path):
    db = Database(path); db.initialize(); project = db.create_project("Expansion"); world = WorldEngine(db)
    return db, project, world


def entity(world, project_id, name, state):
    mutation = world.normalize_mutations(project_id, None, [{"tool": "createEntity", "arguments": {"kind": "character", "name": name, "state": state}}], provenance="author")
    world.commit_root(project_id, mutation, provenance="author", summary=name)
    return mutation[0].arguments["entity_id"]


def add_rules(world, project_id):
    for key, default in (("hp", 100), ("mana", 20)):
        world.data.rules.save_stat(Stat(project_id=project_id, stat_key=key, label=key.upper(), compatible_owner_kinds=["character"], default_value=default, minimum=0, maximum=100))
    world.data.rules.save_effect(EffectDefinition(project_id=project_id, effect_key="ward_heal", name="Ward healing", target_stat_key="hp", operation="add", formula={"kind": "constant", "value": 10}, duration=1, tick_interval=0))
    world.data.rules.save_ability(Ability(project_id=project_id, ability_key="ward", name="Ward", target_type="self", costs=[{"kind": "stat", "stat_key": "mana", "amount": 5}], actions=[{"kind": "apply_effect", "target": "actor", "effect_key": "ward_heal"}]))


def test_stats_ability_cost_temporary_effect_and_player_guard(tmp_path: Path) -> None:
    db, project, world = setup(tmp_path); add_rules(world, project["id"])
    hero = entity(world, project["id"], "Hero", {"player_controlled": True, "abilities": ["ward"]})
    user = db.create_story_node(project["id"], None, "user", "Ward", pov_character_id=hero)
    with pytest.raises(WorldValidationError, match="explicit player"):
        world.normalize_mutations(project["id"], user["id"], [{"tool": "useAbility", "arguments": {"actor_id": hero, "ability_key": "ward"}}], provenance="ai")
    use = world.normalize_mutations(project["id"], user["id"], [{"tool": "useAbility", "arguments": {"actor_id": hero, "ability_key": "ward"}}], provenance="player")
    reply, _ = world.commit_story_turn(project["id"], user["id"], "A ward rises.", use, pov_character_id=hero, narration_mode="third_limited")
    projected = world.projection(project["id"], reply["id"])
    current = projected["entities"][hero]
    assert current["stats"]["mana"] == 15 and world.effective_stats(project["id"], current)["hp"] == 100
    assert projected["active_effects"]
    next_user = db.create_story_node(project["id"], reply["id"], "user", "Wait")
    later, _ = world.commit_story_turn(project["id"], next_user["id"], "Time passes.", [], pov_character_id=hero, narration_mode="third_limited")
    assert not world.projection(project["id"], later["id"])["active_effects"]


@pytest.mark.asyncio
async def test_npc_director_filters_and_batches_valid_attempts(tmp_path: Path) -> None:
    _, project, world = setup(tmp_path)
    place = world.normalize_mutations(project["id"], None, [{"tool": "createEntity", "arguments": {"kind": "location", "name": "Hall", "entity_id": "hall", "state": {}}}], provenance="author"); world.commit_root(project["id"], place, provenance="author", summary="hall")
    player = entity(world, project["id"], "Player", {"player_controlled": True, "current_location_id": "hall"})
    npc = entity(world, project["id"], "Nia", {"autonomy_enabled": True, "intervention_frequency": "high", "current_location_id": "hall", "character_secrets": ["Nia hid the map"], "secrets_to_character": ["Nia is being followed"]})
    user = world.db.create_story_node(project["id"], None, "user", "Enter", pov_character_id=player)
    class Llama:
        messages = []
        async def complete(self, messages, **_kwargs):
            self.messages = messages
            return '{"interventions":[{"npc_id":"'+npc+'","dialogue":"Stop.","attempted_action":"I block the door.","cited_fact_ids":[]}]}'
    llama = Llama()
    interventions, mutations = await NpcDirector(world).generate(llama, project["id"], user["id"], player, "turn", "enter")
    assert interventions[0]["npc_id"] == npc and not mutations
    assert "Nia hid the map" in str(llama.messages)
    assert "Nia is being followed" not in str(llama.messages)
    assert all(item["id"] != player for item in NpcDirector(world).eligible(project["id"], user["id"], player, "turn"))


def test_media_signature_validation_and_hashing() -> None:
    stream = BytesIO(); Image.new("RGB", (32, 48), "red").save(stream, "PNG"); data = stream.getvalue()
    assert validate_image(data) == ("image/png", ".png", 32, 48)
    assert content_hash(data) == content_hash(data)
    assert validate_audio(b"RIFF" + b"\0" * 4 + b"WAVE" + b"x" * 20, "theme.wav") == ("audio/wav", ".wav")
    with pytest.raises(MediaValidationError): validate_audio(b"not audio", "theme.mp3")


def test_ai_theme_must_be_enabled(tmp_path: Path) -> None:
    db, project, world = setup(tmp_path); theme, now = new_id(), utc_now()
    db.execute("INSERT INTO music_themes(id, name, description, created_at, updated_at) VALUES (?, 'Ruins', '', ?, ?)", (theme, now, now))
    db.execute("INSERT INTO project_music_settings(project_id, mode) VALUES (?, 'ai_managed')", (project["id"],))
    with pytest.raises(WorldValidationError): world.normalize_mutations(project["id"], None, [{"tool": "selectTheme", "arguments": {"theme_id": theme}}])
    db.execute("INSERT INTO project_music_themes(project_id, theme_id) VALUES (?, ?)", (project["id"], theme))
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "selectTheme", "arguments": {"theme_id": theme}}])
    world.commit_root(project["id"], mutation, provenance="ai", summary="music")
    assert world.projection(project["id"])["current_theme_id"] == theme


def test_relationship_ability_uses_relation_event_key_and_validates_operation(tmp_path: Path) -> None:
    _, project, world = setup(tmp_path)
    world.data.rules.save_stat(Stat(project_id=project["id"], stat_key="favorability", label="Favorability", compatible_owner_kinds=["relationship"], default_value=0, minimum=-100, maximum=100))
    actor = entity(world, project["id"], "Mira", {"abilities": ["charm"]}); target = entity(world, project["id"], "Ren", {})
    relation_id = f"{actor}:affection:{target}"
    relation = world.normalize_mutations(project["id"], None, [{"tool": "setRelationship", "arguments": {"id": relation_id, "source_id": actor, "target_id": target, "relation": "affection"}}], provenance="author")
    world.commit_root(project["id"], relation, provenance="author", summary="relation")
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="charm_favor", name="Charm favor", target_stat_key="favorability", operation="add", formula={"kind": "constant", "value": 5}))
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="charm", name="Charm", target_type="relationship", actions=[{"kind": "apply_effect", "target": "target", "effect_key": "charm_favor"}]))
    use = world.normalize_mutations(project["id"], None, [{"tool": "useAbility", "arguments": {"actor_id": actor, "target_id": relation_id, "ability_key": "charm"}}], provenance="author")
    assert use[0].arguments["effects"][0]["relation_id"] == relation_id
    world.commit_root(project["id"], use, provenance="author", summary="charm")
    assert world.projection(project["id"])["relations"][relation_id]["stats"]["favorability"] == 5
    with pytest.raises(ValidationError, match="operation"):
        EffectDefinition(project_id=project["id"], effect_key="invalid", name="Invalid", target_stat_key="favorability", operation="unsupported", formula={"kind": "constant", "value": 2})


def test_audio_hash_can_be_reused_by_multiple_theme_rows(tmp_path: Path) -> None:
    db, _, _ = setup(tmp_path); now = utc_now(); first, second = new_id(), new_id()
    db.execute("INSERT INTO music_themes(id, name, description, created_at, updated_at) VALUES (?, 'City', '', ?, ?)", (first, now, now))
    db.execute("INSERT INTO music_themes(id, name, description, created_at, updated_at) VALUES (?, 'Ruins', '', ?, ?)", (second, now, now))
    for theme in (first, second):
        db.execute("INSERT INTO music_tracks(id, theme_id, title, file_path, mime_type, sha256, position, created_at) VALUES (?, ?, 'Shared', 'music/shared.ogg', 'audio/ogg', 'same-hash', 0, ?)", (new_id(), theme, now))
    assert len(db.fetch_all("SELECT * FROM music_tracks WHERE sha256 = 'same-hash'")) == 2
