from pathlib import Path

import pytest

from app.database import Database
from app.services.minigames.bullethell import BulletHellService, expand_hazards
from app.services.minigames import simulate_bullethell
from app.services.world import WorldValidationError


def setup_service(tmp_path: Path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Bullet Hell")
    service = BulletHellService(db)
    service.update_project_settings(project["id"], {
        "default_mode_id": "builtin:base",
        "allowed_mode_ids": ["builtin:base", "builtin:blue"],
        "allowed_skill_ids": ["builtin:free_move", "builtin:blue_gravity", "builtin:roll"],
        "allowed_attack_ids": ["builtin:particle_rain", "builtin:third_beams"],
    })
    return db, project, service


def test_forced_mode_and_effective_skills_are_snapshotted(tmp_path: Path):
    _, project, service = setup_service(tmp_path)
    player = {"id": "hero", "state": {"bullethell_default_mode_id": "builtin:base", "bullethell_skill_ids": ["builtin:roll"]}}
    enemy = {"id": "guard", "state": {"bullethell_forced_mode_id": "builtin:blue"}}
    normal = service.snapshot(project["id"], "builtin:particle_rain", player, enemy)
    forced = service.snapshot(project["id"], "builtin:third_beams", player, enemy)
    assert normal["mode"]["id"] == "builtin:base"
    assert forced["mode"]["id"] == "builtin:blue"
    assert {skill["behavior"] for skill in forced["skills"]} == {"blue_gravity", "roll"}


def test_catalog_clones_are_editable_and_reference_protected(tmp_path: Path):
    _, project, service = setup_service(tmp_path)
    clone = service.clone("skills", "builtin:roll", "short_roll", "Short Roll")
    changed = service.update("skills", clone["id"], {"name": "Quick Roll", "behavior": "roll", "parameters": {"speed": 2, "duration_ms": 200, "cooldown_ms": 800}})
    assert changed["version"] == 2 and changed["parameters"]["duration_ms"] == 200
    settings = service.project_settings(project["id"])
    settings["allowed_skill_ids"].append(clone["id"])
    service.update_project_settings(project["id"], settings)
    with pytest.raises(WorldValidationError, match="referenced"):
        service.delete("skills", clone["id"])


def test_hazard_generation_and_authoritative_replay_are_deterministic(tmp_path: Path):
    _, project, service = setup_service(tmp_path)
    player = {"id": "hero", "state": {}}
    snapshot = service.snapshot(project["id"], "builtin:third_beams", player, None)
    assert expand_hazards(snapshot["attack"], 42) == expand_hazards(snapshot["attack"], 42)
    setup = {**snapshot, "hazards": [{"id": "beam", "type": "third_beam", "lane": 1, "direction": "vertical", "active_start_ms": 0, "active_end_ms": 5000, "damage_multiplier": 1}], "duration_ms": 5000, "control_mode": "pointer", "initial_hp": 10, "hp_source": "test", "enemy_attack": 2, "attack_source": "test"}
    result = simulate_bullethell(setup, [{"elapsed_ms": 0, "x": .5, "y": .5}, {"elapsed_ms": 5000, "x": .5, "y": .5}], [], 5000)
    assert result["collisions"] > 0 and result["remaining_hp"] < 10
    with pytest.raises(WorldValidationError, match="outside valid ranges"):
        simulate_bullethell(setup, [{"elapsed_ms": 0, "x": 2, "y": .5}], [], 5000)


def test_green_mode_blocks_only_the_facing_spear(tmp_path: Path):
    _, project, service = setup_service(tmp_path)
    service.update_project_settings(project["id"], {
        "default_mode_id": "builtin:green",
        "allowed_mode_ids": ["builtin:green"],
        "allowed_skill_ids": ["builtin:green_shield"],
        "allowed_attack_ids": ["builtin:spear_volley"],
    })
    snapshot = service.snapshot(project["id"], "builtin:spear_volley", {"id": "hero", "state": {}}, None)
    hazard = {"id": "north", "type": "spear_burst", "source_x": 0, "source_y": -1, "telegraph_start_ms": 0, "start_ms": 0, "speed": .7, "radius": .035, "damage_multiplier": 1}
    setup = {**snapshot, "hazards": [hazard], "duration_ms": 1200, "control_mode": "keyboard", "initial_hp": 10, "hp_source": "test", "enemy_attack": 3, "attack_source": "test"}
    facing = [{"elapsed_ms": 0, "x": .5, "y": .5, "shield_x": 0, "shield_y": -1}, {"elapsed_ms": 1200, "x": .5, "y": .5, "shield_x": 0, "shield_y": -1}]
    away = [{**sample, "shield_y": 1} for sample in facing]
    blocked = simulate_bullethell(setup, facing, [], 1200)
    struck = simulate_bullethell(setup, away, [], 1200)
    assert blocked["shield_blocks"] == 1 and blocked["remaining_hp"] == 10
    assert struck["shield_blocks"] == 0 and struck["remaining_hp"] < 10


def test_green_mode_rejects_player_displacement(tmp_path: Path):
    _, project, service = setup_service(tmp_path)
    service.update_project_settings(project["id"], {
        "default_mode_id": "builtin:green", "allowed_mode_ids": ["builtin:green"],
        "allowed_skill_ids": ["builtin:green_shield"], "allowed_attack_ids": ["builtin:spear_volley"],
    })
    snapshot = service.snapshot(project["id"], "builtin:spear_volley", {"id": "hero", "state": {}}, None)
    setup = {**snapshot, "hazards": [], "duration_ms": 5000, "control_mode": "pointer", "initial_hp": 10, "hp_source": "test", "enemy_attack": 1, "attack_source": "test"}
    with pytest.raises(WorldValidationError, match="fixed"):
        simulate_bullethell(setup, [{"elapsed_ms": 0, "x": .6, "y": .5}], [], 5000)
