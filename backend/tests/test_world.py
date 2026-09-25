from pathlib import Path
import sqlite3

import pytest

from app.database import Database, new_id, utc_now
from app.services.planning import PlanningService
from app.services.planningWorkspace import PlanningWorkspaceService
from app.services.story_planner import normalize_native_tool_calls, parse_json_object
from app.services.world import WorldEngine, WorldValidationError


def setup_world(path: Path):
    db = Database(path); db.initialize(); project = db.create_project("Temporal")
    return db, project, WorldEngine(db)


def create(engine: WorldEngine, project_id: str, **entity):
    mutations = engine.normalize_mutations(project_id, None, [{"tool": "createEntity", "arguments": entity}], provenance="author")
    engine.commit_root(project_id, mutations, provenance="author", summary="fixture")
    return mutations[0].arguments["entity_id"]


def test_canonical_rule_cleanup_uses_transaction_project_for_world_events(tmp_path: Path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Legacy effects")
    now = utc_now()
    transaction_id = new_id()
    db.execute(
        "INSERT INTO world_transactions(id,project_id,story_node_id,parent_node_id,branch_sequence,elapsed_minutes,display_time,provenance,status,summary,created_at) VALUES(?,?,NULL,NULL,0,0,NULL,'legacy','committed','legacy effects',?)",
        (transaction_id, project["id"], now),
    )
    db.execute(
        "INSERT INTO world_events(id,transaction_id,entity_id,event_type,ordinal,payload_json,created_at) VALUES(?,?,NULL,'effect.applied',0,'{}',?)",
        (new_id(), transaction_id, now),
    )
    db.execute(
        "INSERT INTO world_events(id,transaction_id,entity_id,event_type,ordinal,payload_json,created_at) VALUES(?,?,NULL,'entity.updated',1,?,?)",
        (new_id(), transaction_id, '{"patch":{"active_effects":[{"id":"legacy"}]}}', now),
    )
    db.execute(
        "CREATE TABLE stat_definitions_legacy_v2(id TEXT,project_id TEXT,stat_key TEXT,label TEXT,scope TEXT,default_value REAL,minimum REAL,maximum REAL,integer_only INTEGER,visibility TEXT,created_at TEXT,updated_at TEXT)"
    )

    with db.connect() as connection:
        db._migrate_canonical_rules(connection)

    assert not db.fetch_one("SELECT id FROM world_events WHERE event_type='effect.applied'")
    payload = db.fetch_one("SELECT payload_json FROM world_events WHERE event_type='entity.updated'")["payload_json"]
    assert "active_effects" not in payload
    warnings = db.fetch_all(
        "SELECT warning_kind,project_id FROM rule_migration_warnings WHERE project_id=?",
        (project["id"],),
    )
    kinds = {row["warning_kind"] for row in warnings}
    assert {"discarded_active_effects", "discarded_embedded_effects"} <= kinds


def test_stat_icon_migration_recovers_if_column_already_exists_without_version(tmp_path: Path) -> None:
    db = Database(tmp_path)
    db.initialize()
    db.execute("DELETE FROM schema_migrations WHERE version='043_stat_icons'")
    assert "icon" in {row["name"] for row in db.fetch_all("PRAGMA table_info(stat_definitions)")}

    db.initialize()

    assert db.fetch_one(
        "SELECT version FROM schema_migrations WHERE version='043_stat_icons'"
    )


def test_branch_replay_and_historical_lore_cards(tmp_path: Path) -> None:
    db, project, world = setup_world(tmp_path)
    character_id = create(world, project["id"], kind="character", name="Mara", aliases=[], tags=[], state={"wardrobe": "blue coat"})
    fork = db.create_story_node(project["id"], None, "user", "Choose")
    left = world.normalize_mutations(project["id"], fork["id"], [{"tool": "updateEntity", "arguments": {"entity_id": character_id, "patch": {"wardrobe": "red armor"}}}])
    left_node, _ = world.commit_story_turn(project["id"], fork["id"], "Left", left, pov_character_id=None, narration_mode="third_omniscient")
    right = world.normalize_mutations(project["id"], fork["id"], [{"tool": "updateEntity", "arguments": {"entity_id": character_id, "patch": {"wardrobe": "green cloak"}}}])
    right_node, _ = world.commit_story_turn(project["id"], fork["id"], "Right", right, pov_character_id=None, narration_mode="third_omniscient")
    assert world.projection(project["id"], left_node["id"])["entities"][character_id]["state"]["wardrobe"] == "red armor"
    assert world.projection(project["id"], right_node["id"])["entities"][character_id]["state"]["wardrobe"] == "green cloak"
    assert db.fetch_one("SELECT count(*) AS n FROM lore_card_versions WHERE entity_id = ?", (character_id,))["n"] == 3


def test_routes_cardinal_queries_and_movement_time(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    south = create(world, project["id"], kind="location", name="South", aliases=[], tags=[], state={"x": 0, "y": 0})
    north = create(world, project["id"], kind="location", name="North", aliases=[], tags=[], state={"x": 0, "y": 10})
    hero = create(world, project["id"], kind="character", name="Hero", aliases=[], tags=[], state={"current_location_id": south})
    route = world.normalize_mutations(project["id"], None, [{"tool": "setRelationship", "arguments": {"source_id": south, "target_id": north, "relation": "route", "travel_minutes": 75, "modes": ["walk"], "bidirectional": True}}], provenance="author")
    world.commit_root(project["id"], route, provenance="author", summary="road")
    assert world.nearby(project["id"], south, direction="north")[0]["id"] == north
    assert world.route(project["id"], south, north, mode="walk")["travel_minutes"] == 75
    movement = world.normalize_mutations(project["id"], None, [{"tool": "moveCharacter", "arguments": {"character_id": hero, "destination_id": north, "mode": "walk"}}])
    world.commit_root(project["id"], movement, provenance="ai", summary="travel")
    projection = world.projection(project["id"])
    assert projection["entities"][hero]["state"]["current_location_id"] == north
    assert projection["elapsed_minutes"] == 75


def test_knowledge_scope_major_change_and_budget(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    faction = create(world, project["id"], kind="faction", name="Wardens", aliases=[], tags=[], state={})
    pov = create(world, project["id"], kind="character", name="Player", aliases=[], tags=[], state={"player_controlled": True, "faction_ids": [faction]})
    secret = create(world, project["id"], kind="fact", name="Hidden crown", aliases=[], tags=["secret"], state={"visibility": "narrator"})
    assert not world.search(project["id"], "crown", pov_character_id=pov, narration_mode="first_person")
    faction_fact = create(world, project["id"], kind="fact", name="Warden password", aliases=[], tags=[], state={"visibility": "restricted", "known_faction_ids": [faction]})
    assert world.search(project["id"], "password", pov_character_id=pov, narration_mode="third_limited")[0]["id"] == faction_fact
    reveal = world.normalize_mutations(project["id"], None, [{"tool": "revealKnowledge", "arguments": {"fact_id": secret, "character_ids": [pov]}}])
    world.commit_root(project["id"], reveal, provenance="ai", summary="reveal")
    assert world.search(project["id"], "crown", pov_character_id=pov, narration_mode="first_person")[0]["id"] == secret
    change = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {"entity_id": pov, "patch": {"core_personality": "cruel"}}}])
    assert change[0].major and "personality" in change[0].reason
    package = world.context_package(project["id"], None, "crown", pov, "first_person", 1)
    assert package["entities"] and package["tokens_estimated"] >= 1


def test_scene_context_separates_actor_party_and_interaction_targets(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    location = create(world, project["id"], kind="location", name="Square", aliases=[], tags=[], state={})
    other_location = create(world, project["id"], kind="location", name="Inn", aliases=[], tags=[], state={})
    actor = create(world, project["id"], kind="character", name="Hero", aliases=[], tags=[], state={"player_controlled": True, "current_location_id": location})
    ally = create(world, project["id"], kind="character", name="Ally", aliases=[], tags=[], state={"current_location_id": location})
    away_ally = create(world, project["id"], kind="character", name="Away", aliases=[], tags=[], state={"current_location_id": other_location})
    stranger = create(world, project["id"], kind="character", name="Merchant", aliases=[], tags=[], state={"current_location_id": location})
    update = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {"entity_id": actor, "patch": {"party_ids": [ally, away_ally]}}}], provenance="author")
    world.commit_root(project["id"], update, provenance="author", summary="party")

    package = world.context_package(
        project["id"], None, "Talk to Merchant", actor, "third_limited", 1800, [stranger]
    )
    scene = package["scene_context"]
    assert scene["actor"]["id"] == actor
    assert [item["id"] for item in scene["party"]] == [ally]
    assert [item["id"] for item in scene["interacting"]] == [stranger]
    assert stranger in {item["id"] for item in scene["present_non_party"]}


def test_character_secret_channels_are_scoped_by_narrator(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    pov = create(world, project["id"], kind="character", name="Mara", aliases=[], tags=[], state={
        "player_controlled": True,
        "character_secrets": ["Mara forged the letter"],
        "secrets_to_character": ["Mara is the missing heir"],
    })
    limited = world.context_package(project["id"], None, "Mara", pov, "third_limited", 1800)
    assert "forged the letter" not in str(limited)
    assert "missing heir" in str(limited.get("narrative_secrets"))
    omniscient = world.context_package(project["id"], None, "Mara", pov, "third_omniscient", 1800)
    assert "forged the letter" in str(omniscient.get("narrative_secrets"))


def test_illegal_movement_and_structured_tool_normalization(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    a = create(world, project["id"], kind="location", name="A", aliases=[], tags=[], state={})
    b = create(world, project["id"], kind="location", name="B", aliases=[], tags=[], state={})
    hero = create(world, project["id"], kind="character", name="Hero", aliases=[], tags=[], state={"current_location_id": a})
    with pytest.raises(WorldValidationError, match="No traversable route"):
        world.normalize_mutations(project["id"], None, [{"tool": "moveCharacter", "arguments": {"character_id": hero, "destination_id": b}}])
    invalid = world.normalize_mutations(project["id"], None, [{"tool": "createEntity", "arguments": {"kind": "character", "name": "Lost", "state": {"current_location_id": "missing"}}}], provenance="author")
    with pytest.raises(WorldValidationError, match="invalid current_location_id"):
        world.commit_root(project["id"], invalid, provenance="author", summary="invalid")
    reads, writes = normalize_native_tool_calls([
        {"id": "1", "function": {"name": "searchEntities", "arguments": '{"query":"Hero"}'}},
        {"id": "2", "function": {"name": "advanceTime", "arguments": {"minutes": 5}}},
    ])
    assert reads[0]["arguments"]["query"] == "Hero" and writes[0]["tool"] == "advanceTime"
    assert parse_json_object('```json\n{"scene_intent":"go"}\n```')["scene_intent"] == "go"


def test_planning_publication_becomes_root_transaction(tmp_path: Path) -> None:
    db, project, world = setup_world(tmp_path)
    planning = PlanningService(db, world)
    workspace = PlanningWorkspaceService(db, world=world)
    plan = workspace.create(
        project["id"],
        {
            "major_locations": 4,
            "secondary_locations": 12,
            "characters": 8,
        },
    )
    draft = {
        "summary": "A clockwork coast",
        "notes": [],
        "entities": [
            {
                "key": "aether",
                "kind": "lore_system",
                "name": "Aethercraft",
                "aliases": [],
                "tags": ["magic"],
                "state": {"rules": "Power has a memory cost"},
            }
        ],
        "relations": [],
    }

    result = planning.publish(plan["id"], 1, draft)

    assert (
        next(iter(world.projection(project["id"])["entities"].values()))["name"]
        == "Aethercraft"
    )
    assert result["transaction"]["story_node_id"] is None


def test_committed_events_are_database_immutable(tmp_path: Path) -> None:
    db, project, world = setup_world(tmp_path)
    create(world, project["id"], kind="item", name="Key", aliases=[], tags=[], state={})
    event = db.fetch_one("SELECT id FROM world_events")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE world_events SET event_type = 'tampered' WHERE id = ?", (event["id"],))
    db.execute("DELETE FROM projects WHERE id = ?", (project["id"],))
    assert not db.fetch_one("SELECT id FROM world_events WHERE id = ?", (event["id"],))


def test_story_and_events_roll_back_together(tmp_path: Path, monkeypatch) -> None:
    db, project, world = setup_world(tmp_path)
    user = db.create_story_node(project["id"], None, "user", "Begin")
    mutations = world.normalize_mutations(project["id"], user["id"], [{"tool": "createEntity", "arguments": {"kind": "character", "name": "Transient", "state": {}}}])
    monkeypatch.setattr("app.services.world.make_lore_card", lambda *_: (_ for _ in ()).throw(RuntimeError("card failure")))
    with pytest.raises(RuntimeError, match="card failure"):
        world.commit_story_turn(project["id"], user["id"], "Uncommitted prose", mutations, pov_character_id=None, narration_mode="third_omniscient")
    assert not db.fetch_one("SELECT id FROM story_nodes WHERE content = 'Uncommitted prose'")
    assert not db.fetch_one("SELECT id FROM world_entities WHERE canonical_name = 'Transient'")
    assert not db.fetch_one("SELECT id FROM world_transactions WHERE project_id = ?", (project["id"],))


def test_archive_releases_name_and_identity_edits_are_replayed(tmp_path: Path) -> None:
    db, project, world = setup_world(tmp_path)
    original = create(world, project["id"], kind="character", name="Mara", aliases=[], tags=[], state={})
    changes = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {
        "entity_id": original, "patch": {"archived": True}
    }}], provenance="author")
    world.commit_root(project["id"], changes, provenance="author", summary="archive")
    replacement = create(world, project["id"], kind="character", name="Mara", aliases=[], tags=[], state={})
    assert replacement != original
    rename = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {
        "entity_id": replacement, "patch": {}, "name": "Mara the Younger", "aliases": ["Mara"]
    }}], provenance="author")
    world.commit_root(project["id"], rename, provenance="author", summary="rename")
    assert world.projection(project["id"])["entities"][replacement]["name"] == "Mara the Younger"
    assert db.fetch_one("SELECT canonical_name FROM world_entities WHERE id = ?", (replacement,))["canonical_name"] == "Mara the Younger"


def test_editor_invariants_and_atomic_relationship_replacement(tmp_path: Path) -> None:
    _, project, world = setup_world(tmp_path)
    with pytest.raises(WorldValidationError, match="Player-controlled characters"):
        world.normalize_mutations(project["id"], None, [{"tool": "createEntity", "arguments": {
            "kind": "character", "name": "Invalid hero",
            "state": {"player_controlled": True, "autonomy_enabled": True},
        }}], provenance="author")

    hero = create(world, project["id"], kind="character", name="Hero", aliases=[], tags=[], state={
        "player_controlled": True, "autonomy_enabled": False, "custom_plugin_state": {"rank": 7},
    })
    with pytest.raises(WorldValidationError, match="Player-controlled characters"):
        world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {
            "entity_id": hero, "patch": {"autonomy_enabled": True},
        }}], provenance="author")

    update = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {
        "entity_id": hero, "patch": {"description": "Still remembers custom data."},
    }}], provenance="author")
    world.commit_root(project["id"], update, provenance="author", summary="structured edit")
    assert world.projection(project["id"])["entities"][hero]["state"]["custom_plugin_state"] == {"rank": 7}

    target_a = create(world, project["id"], kind="faction", name="First faction", aliases=[], tags=[], state={})
    target_b = create(world, project["id"], kind="faction", name="Second faction", aliases=[], tags=[], state={})
    initial = world.normalize_mutations(project["id"], None, [{"tool": "setRelationship", "arguments": {
        "id": "old-edge", "source_id": hero, "target_id": target_a, "relation": "member_of",
    }}], provenance="author")
    world.commit_root(project["id"], initial, provenance="author", summary="initial edge")
    replacement = world.normalize_mutations(project["id"], None, [
        {"tool": "removeRelationship", "arguments": {"relationship_id": "old-edge"}},
        {"tool": "setRelationship", "arguments": {
            "id": "new-edge", "source_id": hero, "target_id": target_b, "relation": "allied_with",
        }},
    ], provenance="author")
    world.commit_root(project["id"], replacement, provenance="author", summary="replace edge")
    relations = world.projection(project["id"])["relations"]
    assert "old-edge" not in relations
    assert relations["new-edge"]["target_id"] == target_b
