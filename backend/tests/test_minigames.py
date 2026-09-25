from pathlib import Path

import pytest

from app.database import Database
from app.database import new_id, utc_now
from app.domain.world import Ability
from app.services.minigames import HEX_EDGES, MANIFESTS, VIRTUAL_PLAYER_ID, MinigameService, hex_is_solved, replay_circled_teeth, score_timed_attack
from app.services.world import WorldEngine, WorldValidationError


def setup_world(tmp_path: Path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Challenges")
    world = WorldEngine(db)
    world.commit_root(project["id"], world.normalize_mutations(project["id"], None, [
        {"tool": "createEntity", "arguments": {"entity_id": "hero", "kind": "character", "name": "Hero", "tags": ["adventurer"], "state": {"player_controlled": True}}},
        {"tool": "createEntity", "arguments": {"entity_id": "guard", "kind": "character", "name": "Guard", "tags": ["hostile"], "state": {}}},
    ]), provenance="test", summary="setup")
    return db, project, world, MinigameService(db, world)


def enable(service: MinigameService, project_id: str, key: str):
    config = next(row for row in service.configs(project_id) if row["game_key"] == key)
    config.update(enabled=True, allowed_actions=["do"])
    return service.update_config(project_id, key, config)


def test_all_games_disabled_by_default_and_eligibility_is_deterministic(tmp_path: Path):
    _, project, _, service = setup_world(tmp_path)
    assert len(service.configs(project["id"])) == len(MANIFESTS) == 11
    assert service.eligible_for_prompt(project["id"], None, "do") == []
    enable(service, project["id"], "roll_d20")
    eligible = service.eligible_for_prompt(project["id"], None, "do")
    assert [game["game_key"] for game in eligible] == ["roll_d20"]
    assert eligible[0]["participants"] == [{"id": "hero", "name": "Hero"}]
    assert any(actor["id"] == "hero" for actor in eligible[0]["actors"])
    assert [game["game_key"] for game in service.eligible_for_prompt(project["id"], None, "say")] == ["roll_d20"]


def test_groups_batch_toggle_and_rank_context_recommendations(tmp_path: Path):
    _, project, _, service = setup_world(tmp_path)
    configs = service.set_group_enabled(project["id"], "cypher", True)
    enabled = {row["game_key"] for row in configs if row["enabled"]}
    assert enabled == {"circled_teeth", "hex_circuit", "lockpicking"}
    eligible = service.eligible_for_prompt(project["id"], None, "continue", "The enemy terminal needs to be hacked and decrypted")
    assert {row["group"] for row in eligible} == {"cypher"}
    assert all(row["recommended"] for row in eligible)
    assert eligible[0]["game_key"] in enabled


def test_dice_checkpoint_is_idempotent_and_uses_strict_difficulty(tmp_path: Path):
    db, project, _, service = setup_world(tmp_path)
    enable(service, project["id"], "roll_d6")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "roll_d6", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 5, "challenge_text": "Lift the gate",
    })
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "The gate strains.", [], [], None)
    resolved, changed = service.resolve(session["id"], {})
    duplicate, changed_again = service.resolve(session["id"], {})
    assert changed and not changed_again
    assert resolved["result"] == duplicate["result"]
    assert 1 <= resolved["result"]["roll"] <= 6
    assert resolved["result"]["success"] is (resolved["result"]["roll"] > 5)


def test_invalid_direction_and_difficulty_are_rejected(tmp_path: Path):
    _, project, _, service = setup_world(tmp_path)
    config = enable(service, project["id"], "roll_d20")
    config["allowed_directions"] = ["player_acts"]
    service.update_config(project["id"], "roll_d20", config)
    with pytest.raises(WorldValidationError):
        service.validate_invocation(project["id"], None, "do", {"game_key": "roll_d20", "actor_id": "guard", "participant_id": "hero", "difficulty": 12, "challenge_text": "Attack"})
    with pytest.raises(WorldValidationError):
        service.validate_invocation(project["id"], None, "do", {"game_key": "roll_d20", "actor_id": "hero", "participant_id": "hero", "difficulty": 20, "challenge_text": "Impossible"})


def test_result_is_linked_to_the_atomic_story_transaction(tmp_path: Path):
    db, project, world, service = setup_world(tmp_path)
    enable(service, project["id"], "flip_coin")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "flip_coin", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 1, "challenge_text": "Trust to chance",
    })
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "A coin arcs upward.", [], [], None)
    resolved, _ = service.resolve(session["id"], {"choice": "heads"})
    node, transaction = world.commit_story_turn(
        project["id"], None, "A coin arcs upward. It lands.", [], pov_character_id="hero",
        narration_mode="third_limited", minigame_session_id=resolved["id"],
    )
    committed = service.get_session(session["id"])
    event = db.fetch_one("SELECT event_type,payload_json FROM world_events WHERE transaction_id=?", (transaction["id"],))
    assert committed and committed["status"] == "committed" and committed["story_node_id"] == node["id"]
    assert event and event["event_type"] == "minigame.completed"


def test_empty_world_uses_generic_player_for_enabled_games(tmp_path: Path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("No character sheet")
    service = MinigameService(db, WorldEngine(db))
    enable(service, project["id"], "flip_coin")
    eligible = service.eligible_for_prompt(project["id"], None, "do")
    assert eligible[0]["participants"] == [{"id": VIRTUAL_PLAYER_ID, "name": "Player"}]
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "flip_coin", "actor_id": VIRTUAL_PLAYER_ID, "participant_id": VIRTUAL_PLAYER_ID,
        "target_id": None, "difficulty": 1, "challenge_text": "Flip a coin",
    })
    assert invocation["participant_id"] == VIRTUAL_PLAYER_ID


def test_reflex_attempt_can_only_start_once_and_requires_start(tmp_path: Path):
    db, project, _, service = setup_world(tmp_path)
    enable(service, project["id"], "timing_hit")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "timing_hit", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 5, "challenge_text": "Catch the marker",
    })
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "Focus.", [], [], None)
    with pytest.raises(WorldValidationError, match="Start the minigame"):
        service.resolve(session["id"], {"position": 0, "elapsed_ms": 0})
    started, changed = service.start_attempt(session["id"])
    duplicate, changed_again = service.start_attempt(session["id"])
    assert changed and not changed_again
    assert started["attempt_started_at"] == duplicate["attempt_started_at"]


def test_red_light_uses_server_setup_and_loss_threshold(tmp_path: Path):
    db, project, _, service = setup_world(tmp_path)
    enable(service, project["id"], "red_light")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "red_light", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 6, "challenge_text": "Keep tension on the fishing line",
    })
    assert len(invocation["setup"]["phases"]) == 7
    assert 0 < invocation["setup"]["lose_threshold_ms"] < invocation["setup"]["duration_ms"]
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "The line pulls.", [], [], None)
    service.start_attempt(session["id"])
    resolved, changed = service.resolve(session["id"], {
        "violation_ms": 0, "elapsed_ms": invocation["setup"]["duration_ms"],
    })
    assert changed and resolved["result"]["success"] is True


def test_hex_circuit_generation_and_server_validation(tmp_path: Path):
    db, project, _, service = setup_world(tmp_path)
    enable(service, project["id"], "hex_circuit")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "hex_circuit", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 7, "timed": False, "challenge_text": "Bypass the terminal",
    })
    setup = invocation["setup"]
    assert len(HEX_EDGES) == 12 and hex_is_solved(setup["masks"], [0] * 7)
    assert not hex_is_solved(setup["masks"], setup["rotations"])
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "The terminal glows.", [], [], None)
    service.start_attempt(session["id"])
    resolved, _ = service.resolve(session["id"], {"rotations": [0] * 7, "move_count": 8, "elapsed_ms": 1000})
    assert resolved["result"]["success"] is True


def test_lockpicking_uses_and_stages_physical_inventory(tmp_path: Path):
    db, project, world, service = setup_world(tmp_path)
    inventory_setup = world.normalize_mutations(project["id"], None, [
        {"tool": "createEntity", "arguments": {"entity_id": "picks", "kind": "item", "name": "Iron lockpick", "tags": ["lockpick"], "state": {}}},
        {"tool": "updateEntity", "arguments": {"entity_id": "hero", "patch": {"inventory": [{"item_id": "picks", "quantity": 3}]}}},
    ], provenance="author")
    world.commit_root(project["id"], inventory_setup, provenance="author", summary="Give lockpicks")
    enable(service, project["id"], "lockpicking")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "lockpicking", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 5, "attempt_limit": None, "timed": False, "challenge_text": "Open the chest",
    })
    assert invocation["setup"]["attempt_source"] == "inventory" and invocation["setup"]["attempt_limit"] == 3
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "The pick catches.", [], [], None)
    service.start_attempt(session["id"])
    resolved, _ = service.resolve(session["id"], {
        "broken_picks": 1, "final_angle": invocation["setup"]["sweet_center"],
        "lock_rotation": 90, "elapsed_ms": 1200,
    })
    assert resolved["result"]["success"] is True
    staged = world.normalize_mutations(project["id"], None, resolved["staged_mutations"])
    node, _ = world.commit_story_turn(project["id"], None, "The chest opens.", staged, pov_character_id="hero", narration_mode="third_limited", minigame_session_id=session["id"])
    projection = world.projection(project["id"], node["id"])
    assert projection["entities"]["hero"]["state"]["inventory"] == [{"item_id": "picks", "quantity": 2}]


def test_circled_teeth_optional_overrides_and_explicit_time_win(tmp_path: Path):
    _, project, _, service = setup_world(tmp_path)
    config = enable(service, project["id"], "circled_teeth")
    config.update(timer_policy="never", min_teeth=3, max_teeth=9, min_empty_slots=2, max_empty_slots=8,
                  min_time_seconds=15, max_time_seconds=90)
    saved = service.update_config(project["id"], "circled_teeth", config)
    assert saved["allow_teeth_override"] and saved["allow_empty_slots_override"] and saved["allow_time_override"]
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "circled_teeth", "actor_id": "hero", "participant_id": "hero",
        "difficulty": 6, "teeth": 8, "empty_slots": 5, "time_seconds": 35,
        "reverse_on_success": True, "challenge_text": "Bypass the circular lock",
    })
    setup = invocation["setup"]
    assert invocation["timed"] is True and invocation["requested_overrides"]["time_seconds"] == 35
    assert setup["slot_count"] == 13 and setup["tooth_count"] == 8 and setup["empty_slot_count"] == 5
    assert setup["time_limit_ms"] == 35_000 and setup["reverse_on_success"] is True
    assert len(setup["occupied_slots"]) == 8 and len(set(setup["occupied_slots"])) == 8


def test_circled_teeth_rejects_disabled_and_oversized_overrides(tmp_path: Path):
    _, project, _, service = setup_world(tmp_path)
    config = enable(service, project["id"], "circled_teeth")
    config.update(allow_teeth_override=False)
    service.update_config(project["id"], "circled_teeth", config)
    base = {"game_key": "circled_teeth", "actor_id": "hero", "participant_id": "hero", "difficulty": 4, "challenge_text": "Turn the lock"}
    with pytest.raises(WorldValidationError, match="teeth is disabled"):
        service.validate_invocation(project["id"], None, "do", {**base, "teeth": 6})
    config.update(allow_teeth_override=True, max_teeth=23, max_empty_slots=22)
    service.update_config(project["id"], "circled_teeth", config)
    with pytest.raises(WorldValidationError, match="between 4 and 24"):
        service.validate_invocation(project["id"], None, "do", {**base, "teeth": 20, "empty_slots": 10})


def test_circled_teeth_server_replays_insert_pullout_and_empty_inputs():
    setup = {
        "slot_count": 4, "occupied_slots": [0, 1], "initial_angle": 0,
        "initial_direction": 1, "revolution_ms": 1000, "hit_window_fraction": .5,
        "strike_limit": 3, "reverse_on_success": False,
    }
    result = replay_circled_teeth(setup, [
        {"elapsed_ms": 0, "slot_index": 0, "action": "insert"},
        {"elapsed_ms": 1000, "slot_index": 0, "action": "pull_out"},
        {"elapsed_ms": 1125, "slot_index": None, "action": "empty"},
        {"elapsed_ms": 1250, "slot_index": 1, "action": "insert"},
        {"elapsed_ms": 2000, "slot_index": 0, "action": "insert"},
    ], 2000, False)
    assert result == {
        "inserted_count": 2, "tooth_count": 2, "pull_outs": 1, "empty_presses": 1,
        "strikes": 2, "strike_limit": 3, "direction_reversals": 0,
        "elapsed_ms": 2000, "timed_out": False, "success": True,
    }


def test_timed_attack_ability_profile_precedes_ai_values(tmp_path: Path):
    db, project, world, service = setup_world(tmp_path)
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="rapid_slash", name="Rapid Slash", target_type="character", timed_attack_line_count=4, timed_attack_damage_per_line=12))
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {"entity_id": "hero", "patch": {"abilities": ["rapid_slash"]}}}], provenance="test")
    world.commit_root(project["id"], mutation, provenance="test", summary="Learn attack")
    enable(service, project["id"], "timed_attack")
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "timed_attack", "actor_id": "hero", "participant_id": "hero", "target_id": "guard",
        "difficulty": 5, "ability_key": "rapid_slash", "line_count": 1, "damage_per_line": 1,
        "challenge_text": "Strike the guard",
    })
    assert invocation["setup"]["line_count"] == 4
    assert invocation["setup"]["damage_per_line"] == 12
    assert invocation["setup"]["parameter_source"] == "ability"


def test_timed_attack_scoring_uses_rightmost_cursor_and_center_accuracy():
    setup = {
        "lines": [{"id": 0, "start_ms": 0, "traversal_ms": 1000}, {"id": 1, "start_ms": 200, "traversal_ms": 1000}],
        "damage_per_line": 10, "success_threshold": 50, "duration_ms": 1200,
    }
    result = score_timed_attack(setup, [
        {"line_id": 0, "elapsed_ms": 500},
        {"line_id": 1, "elapsed_ms": 700},
    ], 700)
    assert result["lines_hit"] == 2 and result["lines_missed"] == 0
    assert result["attack_power"] == 100 and result["damage"] == 20 and result["success"] is True
    with pytest.raises(WorldValidationError, match="rightmost"):
        score_timed_attack(setup, [{"line_id": 1, "elapsed_ms": 700}], 1200)


def test_dodge_box_uses_bounded_fallbacks_and_fixed_duration(tmp_path: Path):
    db, project, _, service = setup_world(tmp_path)
    config = enable(service, project["id"], "dodge_box")
    config.update(dodge_control_mode="keyboard", min_fallback_hp=10, max_fallback_hp=50, min_enemy_attack=2, max_enemy_attack=20)
    service.update_config(project["id"], "dodge_box", config)
    service.bullethell.update_project_settings(project["id"], {
        "default_mode_id": "builtin:base", "allowed_mode_ids": ["builtin:base"],
        "allowed_skill_ids": ["builtin:free_move"], "allowed_attack_ids": ["builtin:particle_rain"],
    })
    invocation = service.validate_invocation(project["id"], None, "do", {
        "game_key": "dodge_box", "actor_id": "guard", "participant_id": "hero", "target_id": "hero",
        "difficulty": 8, "hp": 50, "enemy_attack": 2, "attack_id": "builtin:particle_rain", "challenge_text": "Evade the assault",
    })
    assert invocation["setup"]["duration_ms"] == 5000
    assert invocation["setup"]["attack"]["id"] == "builtin:particle_rain"
    assert invocation["setup"]["mode"]["id"] == "builtin:base"
    assert invocation["setup"]["initial_hp"] == 50 and invocation["setup"]["enemy_attack"] == 2
    job = db.create_job(project["id"], "story", {"action": "do"})
    session = service.create_session(project["id"], job["id"], None, invocation, "The attack begins.", [], [], None)
    service.start_attempt(session["id"])
    resolved, changed = service.resolve(session["id"], {"elapsed_ms": 5000, "samples": [{"elapsed_ms": 0, "x": .5, "y": .5}, {"elapsed_ms": 5000, "x": .5, "y": .5}], "skill_events": []})
    assert changed and resolved["result"]["success"] is True
    assert resolved["result"]["remaining_hp"] >= 1 and resolved["result"]["enemy_attack"] == 2
    with pytest.raises(WorldValidationError, match="hp must be between"):
        service.validate_invocation(project["id"], None, "do", {
            "game_key": "dodge_box", "actor_id": "guard", "participant_id": "hero", "target_id": "hero",
            "difficulty": 8, "hp": 2, "enemy_attack": 12, "attack_id": "builtin:particle_rain", "challenge_text": "Evade",
        })
