from __future__ import annotations

import json
import math
import secrets
from datetime import UTC, datetime
from typing import Any

from app.database import Database, new_id, utc_now
from app.services.minigames.bullethell import BulletHellService, expand_hazards
from app.services.world import WorldEngine, WorldValidationError


MANIFESTS: dict[str, dict[str, Any]] = {
    "roll_d20": {"key": "roll_d20", "version": 1, "name": "Roll d20", "renderer": "dice", "sides": 20, "min_difficulty": 1, "max_difficulty": 19, "description": "A dramatic twenty-sided die challenge."},
    "roll_d6": {"key": "roll_d6", "version": 1, "name": "Roll d6", "renderer": "dice", "sides": 6, "min_difficulty": 1, "max_difficulty": 5, "description": "A quick six-sided die challenge."},
    "flip_coin": {"key": "flip_coin", "version": 1, "name": "Flip coin", "renderer": "coin", "min_difficulty": 1, "max_difficulty": 1, "description": "A binary chance challenge where the player calls heads or tails."},
    "timing_hit": {"key": "timing_hit", "version": 1, "name": "Timing hit", "renderer": "timing", "min_difficulty": 1, "max_difficulty": 10, "description": "Hit a moving marker inside a shrinking target."},
    "key_mash": {"key": "key_mash", "version": 1, "name": "Key mash", "renderer": "key_mash", "min_difficulty": 1, "max_difficulty": 10, "description": "Press rapidly for four seconds to overcome resistance."},
    "red_light": {"key": "red_light", "version": 1, "name": "Fishing / red light", "renderer": "red_light", "min_difficulty": 1, "max_difficulty": 10, "description": "Hold during green and release during red without exceeding the mistake threshold; useful for fishing, stealth, and tense resistance."},
    "lockpicking": {"key": "lockpicking", "version": 1, "name": "Lockpicking", "renderer": "lockpicking", "min_difficulty": 1, "max_difficulty": 10, "description": "Position a pick and apply torque to open a lock; use for doors, chests, and similar mechanical locks."},
    "hex_circuit": {"key": "hex_circuit", "version": 1, "name": "Hex circuit", "renderer": "hex_circuit", "min_difficulty": 1, "max_difficulty": 10, "description": "Rotate seven hexagonal circuit tiles until every connector matches a neighbor; use for hacking and circuit puzzles."},
    "circled_teeth": {"key": "circled_teeth", "version": 1, "name": "Circled teeth", "renderer": "circled_teeth", "min_difficulty": 1, "max_difficulty": 10, "description": "Time inputs against a rotating selector to push every occupied tooth inward; use for circular locks, machinery, and security mechanisms."},
    "timed_attack": {"key": "timed_attack", "version": 1, "name": "Timed attack", "renderer": "timed_attack", "min_difficulty": 1, "max_difficulty": 10, "description": "Strike one to eight overlapping attack cursors near the center; use when a player attack should depend on timing."},
    "dodge_box": {"key": "dodge_box", "version": 2, "name": "Dodge box", "renderer": "dodge_box", "min_difficulty": 1, "max_difficulty": 10, "description": "Survive a deterministic five-second bullet-hell attack using the participant's active mode and skills."},
}
MINIGAME_GROUPS: dict[str, dict[str, Any]] = {
    "chance": {"name": "Chance", "games": ["flip_coin", "roll_d6", "roll_d20"], "terms": ["chance", "random", "coin", "flip", "die", "dice", "roll"]},
    "cypher": {"name": "Cypher", "games": ["circled_teeth", "hex_circuit", "lockpicking"], "terms": ["hack", "hacking", "lock", "lockpick", "cipher", "cypher", "decipher", "decrypt", "intelligence", "circuit", "puzzle"]},
    "reflex": {"name": "Reflex", "games": ["timing_hit"], "terms": ["timing", "reflex", "react", "quick", "aim"]},
    "strength": {"name": "Strength / Effort", "games": ["key_mash"], "terms": ["strength", "effort", "push", "pull", "lift", "force", "struggle", "break", "resist"]},
    "fishing": {"name": "Fishing", "games": ["red_light"], "terms": ["fish", "fishing", "catch", "reel", "bite"]},
    "attack": {"name": "Attack", "games": ["timed_attack"], "terms": ["attack", "strike", "slash", "shoot", "hit", "offensive"]},
    "take_attack": {"name": "Take attack", "games": ["dodge_box"], "terms": ["dodge", "evade", "incoming", "being attacked", "defend", "avoid the attack", "take attack"]},
}
for group_key, group in MINIGAME_GROUPS.items():
    for game_key in group["games"]:
        MANIFESTS[game_key]["group"] = group_key
VIRTUAL_PLAYER_ID = "__player__"
HEX_COORDS = [(0, 0), (0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0)]
HEX_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def _default_options(game_key: str) -> dict[str, Any]:
    result = {
        "timer_policy": "ai_allowed" if game_key in {"lockpicking", "hex_circuit", "circled_teeth"} else "never",
        "fallback_attempts": 3,
        "allow_infinite_attempts": True,
    }
    if game_key == "circled_teeth":
        result.update({
            "allow_teeth_override": True, "min_teeth": 2, "max_teeth": 12,
            "allow_empty_slots_override": True, "min_empty_slots": 1, "max_empty_slots": 12,
            "allow_time_override": True, "min_time_seconds": 10, "max_time_seconds": 120,
            "allow_direction_reversal": True,
        })
    elif game_key == "timed_attack":
        result.update({"min_attack_lines": 1, "max_attack_lines": 8, "min_attack_damage": 1, "max_attack_damage": 100})
    elif game_key == "dodge_box":
        result.update({
            "dodge_control_mode": "pointer", "min_fallback_hp": 1, "max_fallback_hp": 999,
            "min_enemy_attack": 0, "max_enemy_attack": 999,
        })
    return result


def _strict_optional_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorldValidationError(f"{label} must be an integer")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise WorldValidationError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorldValidationError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise WorldValidationError(f"{label} must be finite")
    return number


def replay_circled_teeth(setup: dict[str, Any], events: list[Any], elapsed_ms: float, timed_out: bool) -> dict[str, Any]:
    if not isinstance(events, list) or len(events) > 256:
        raise WorldValidationError("Circled-teeth result requires at most 256 input events")
    slot_count = int(setup["slot_count"])
    occupied = {int(value) for value in setup["occupied_slots"]}
    inserted: set[int] = set()
    angle = float(setup["initial_angle"])
    direction = int(setup["initial_direction"])
    revolution_ms = float(setup["revolution_ms"])
    hit_radius = float(setup["hit_window_fraction"]) / (2 * slot_count)
    previous = 0.0
    strikes = pull_outs = empty_presses = reversals = 0
    resolved = False
    for raw in events:
        if resolved or not isinstance(raw, dict):
            raise WorldValidationError("Circled-teeth input events are malformed or continue after resolution")
        try:
            at = float(raw["elapsed_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorldValidationError("Every circled-teeth event requires elapsed_ms") from exc
        if not math.isfinite(at) or at < previous or at > 3_600_000 or at > elapsed_ms + 100:
            raise WorldValidationError("Circled-teeth event timing is outside valid ranges")
        angle = (angle + direction * ((at - previous) / revolution_ms)) % 1
        previous = at
        nearest = math.floor(angle * slot_count + .5) % slot_count
        distance = abs(angle - nearest / slot_count)
        distance = min(distance, 1 - distance)
        if distance <= hit_radius and nearest in occupied:
            if nearest in inserted:
                inserted.remove(nearest); strikes += 1; pull_outs += 1; action = "pull_out"
            else:
                inserted.add(nearest); action = "insert"
                if bool(setup.get("reverse_on_success")):
                    direction *= -1; reversals += 1
        else:
            strikes += 1; empty_presses += 1; action = "empty"
        if "slot_index" in raw and raw["slot_index"] != (nearest if distance <= hit_radius else None):
            raise WorldValidationError("Circled-teeth slot telemetry does not match the saved puzzle")
        if "action" in raw and raw["action"] != action:
            raise WorldValidationError("Circled-teeth action telemetry does not match the saved puzzle")
        resolved = inserted == occupied or strikes >= int(setup["strike_limit"])
    timeout = bool(timed_out)
    success = inserted == occupied and not timeout and strikes < int(setup["strike_limit"])
    if not success and not timeout and strikes < int(setup["strike_limit"]):
        raise WorldValidationError("Circled-teeth attempt has not reached a terminal state")
    return {
        "inserted_count": len(inserted), "tooth_count": len(occupied),
        "pull_outs": pull_outs, "empty_presses": empty_presses, "strikes": strikes,
        "strike_limit": int(setup["strike_limit"]), "direction_reversals": reversals,
        "elapsed_ms": round(elapsed_ms), "timed_out": timeout, "success": success,
    }


def score_timed_attack(setup: dict[str, Any], events: list[Any], elapsed_ms: float, forfeited: bool = False) -> dict[str, Any]:
    if not isinstance(events, list) or len(events) > 64:
        raise WorldValidationError("Timed-attack result requires at most 64 input events")
    lines = list(setup["lines"])
    consumed: dict[int, dict[str, Any]] = {}
    previous = 0.0
    for raw in events:
        if not isinstance(raw, dict):
            raise WorldValidationError("Timed-attack input events are malformed")
        try:
            at, submitted_id = float(raw["elapsed_ms"]), int(raw["line_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorldValidationError("Timed-attack events require elapsed_ms and line_id") from exc
        if not math.isfinite(at) or at < previous or at > elapsed_ms + 100:
            raise WorldValidationError("Timed-attack event timing is outside valid ranges")
        active = []
        for line in lines:
            line_id = int(line["id"])
            if line_id in consumed:
                continue
            progress = (at - float(line["start_ms"])) / float(line["traversal_ms"])
            if 0 <= progress <= 1:
                active.append((progress, line_id))
        if not active:
            raise WorldValidationError("Timed-attack input occurred while no cursor was active")
        progress, line_id = max(active)
        if submitted_id != line_id:
            raise WorldValidationError("Timed-attack input did not consume the rightmost active cursor")
        accuracy = max(0.0, 1 - 2 * abs(progress - .5))
        consumed[line_id] = {"line_id": line_id, "hit": True, "position": progress, "accuracy": accuracy}
        previous = at
    results = []
    incomplete = False
    for line in lines:
        line_id = int(line["id"])
        if line_id in consumed:
            results.append(consumed[line_id])
        elif forfeited or elapsed_ms >= float(line["start_ms"]) + float(line["traversal_ms"]) - 50:
            results.append({"line_id": line_id, "hit": False, "position": None, "accuracy": 0.0})
        else:
            incomplete = True
    if incomplete and not forfeited:
        raise WorldValidationError("Timed-attack attempt has not finished")
    total_accuracy = sum(float(item["accuracy"]) for item in results)
    attack_power = total_accuracy / len(lines) * 100
    damage = round(total_accuracy * float(setup["damage_per_line"]))
    threshold = float(setup["success_threshold"])
    return {
        "lines": [{**item, "accuracy": round(float(item["accuracy"]) * 100, 2)} for item in results],
        "lines_hit": sum(1 for item in results if item["hit"]), "lines_missed": sum(1 for item in results if not item["hit"]),
        "attack_power": round(attack_power, 2), "success_threshold": round(threshold, 2),
        "damage_per_line": float(setup["damage_per_line"]), "damage": damage,
        "elapsed_ms": round(elapsed_ms), "forfeited": forfeited, "success": not forfeited and attack_power >= threshold,
    }


def simulate_bullethell(setup: dict[str, Any], samples: list[Any], skill_events: list[Any], elapsed_ms: float, forfeited: bool = False) -> dict[str, Any]:
    if not isinstance(samples, list) or not 1 <= len(samples) <= 256 or not isinstance(skill_events, list) or len(skill_events) > 50:
        raise WorldValidationError("Bullet-hell telemetry is missing or too large")
    path = []
    previous = -1.0
    for raw in samples:
        try:
            at, x, y = float(raw["elapsed_ms"]), float(raw["x"]), float(raw["y"])
            shield_x, shield_y = float(raw.get("shield_x", 0)), float(raw.get("shield_y", -1))
        except (KeyError, TypeError, ValueError) as exc:
            raise WorldValidationError("Movement samples require elapsed_ms, x, and y") from exc
        if not all(math.isfinite(value) for value in (at, x, y, shield_x, shield_y)) or at < previous or not 0 <= x <= 1 or not 0 <= y <= 1 or math.hypot(shield_x, shield_y) > 1.1 or at > elapsed_ms + 100:
            raise WorldValidationError("Bullet-hell movement sample is outside valid ranges")
        path.append((at, x, y, shield_x, shield_y)); previous = at
    distance_moved = 0.0
    keyboard_physics = setup.get("control_mode") == "keyboard" or any(skill.get("behavior") == "blue_gravity" for skill in setup.get("skills", []))
    movement = next((skill for skill in setup.get("skills", []) if skill.get("behavior") in {"free_move", "blue_gravity"}), {})
    maximum_speed = max(1.0, float(movement.get("parameters", {}).get("speed", 1)))
    for before, after in zip(path, path[1:]):
        segment = math.hypot((after[1] - before[1]) * 300, (after[2] - before[2]) * 180)
        distance_moved += segment
        if keyboard_physics and segment > 20 + maximum_speed * 450 * max(0, after[0] - before[0]) / 1000:
            raise WorldValidationError("Bullet-hell movement exceeds the active mode's speed")
    available = {skill["id"]: skill for skill in setup.get("skills", [])}
    rolls = []
    last_roll = -1e9
    roll_skill = next((skill for skill in available.values() if skill.get("behavior") == "roll"), None)
    for raw in skill_events:
        try:
            at = float(raw["elapsed_ms"]); skill_id = str(raw["skill_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorldValidationError("Skill events require elapsed_ms and skill_id") from exc
        if skill_id not in available or available[skill_id].get("behavior") != "roll" or not 0 <= at <= elapsed_ms + 100:
            raise WorldValidationError("Unavailable bullet-hell skill was submitted")
        try:
            direction_x, direction_y = float(raw.get("direction_x", 0)), float(raw.get("direction_y", 0))
        except (TypeError, ValueError) as exc:
            raise WorldValidationError("Roll direction is invalid") from exc
        if not all(math.isfinite(value) for value in (direction_x, direction_y)) or math.hypot(direction_x, direction_y) > 1.5:
            raise WorldValidationError("Roll direction is invalid")
        parameters = roll_skill.get("parameters", {}) if roll_skill else {}
        cooldown, duration = float(parameters.get("cooldown_ms", 1000)), float(parameters.get("duration_ms", 350))
        if at < last_roll + cooldown:
            raise WorldValidationError("Roll was used before its cooldown finished")
        rolls.append((at, at + duration)); last_roll = at
    green_mode = any(float(skill.get("parameters", {}).get("green_shield", 0)) >= .5 for skill in setup.get("skills", []))
    if green_mode and any(math.hypot(sample[1] - .5, sample[2] - .5) > .02 for sample in path):
        raise WorldValidationError("Green mode keeps the participant fixed at the arena center")
    def position_at(at: float) -> tuple[float, float, float, float]:
        before = path[0]
        for after in path[1:]:
            if after[0] >= at:
                span = after[0] - before[0]
                ratio = 0 if span <= 0 else (at - before[0]) / span
                return before[1] + (after[1] - before[1]) * ratio, before[2] + (after[2] - before[2]) * ratio, before[3], before[4]
            before = after
        return before[1], before[2], before[3], before[4]
    hp = float(setup["initial_hp"]); initial_hp = hp; enemy_attack = float(setup["enemy_attack"])
    immunity = float(setup["attack"].get("hit_immunity_ms", 500)); last_hit = -1e9
    collision_ids: list[str] = []
    hit_hazards: set[str] = set()
    blocked_hazards: set[str] = set()
    duration = min(float(setup.get("duration_ms", 5000)), elapsed_ms)
    for step in range(int(duration // (1000 / 60)) + 1):
        at = step * (1000 / 60); x, y, shield_x, shield_y = position_at(at)
        if any(start <= at <= end for start, end in rolls):
            continue
        hit = None
        for hazard in setup.get("hazards", []):
            if hazard["id"] in blocked_hazards:
                continue
            if hazard["type"] == "particle_rain":
                age = (at - float(hazard["start_ms"])) / 1000
                if age >= 0:
                    hy = age * float(hazard["speed"])
                    if hy <= 1.1 and math.hypot(x - float(hazard["x"]), y - hy) <= .03 + float(hazard["radius"]):
                        hit = hazard
            elif hazard["type"] == "third_beam" and float(hazard["active_start_ms"]) <= at <= float(hazard["active_end_ms"]):
                lane = int(hazard["lane"])
                coordinate = x if hazard.get("direction") == "vertical" else y
                if lane / 3 <= coordinate <= (lane + 1) / 3:
                    hit = hazard
            elif hazard["type"] == "spear_burst":
                age = (at - float(hazard["start_ms"])) / 1000
                if age >= 0:
                    distance = .7 - age * float(hazard["speed"])
                    hx = .5 + float(hazard["source_x"]) * distance
                    hy = .5 + float(hazard["source_y"]) * distance
                    if math.hypot(x - hx, y - hy) <= .035 + float(hazard["radius"]):
                        shield_length = math.hypot(shield_x, shield_y)
                        alignment = 0 if shield_length < .5 else (shield_x * float(hazard["source_x"]) + shield_y * float(hazard["source_y"])) / shield_length
                        if green_mode and alignment >= math.cos(math.pi / 8):
                            blocked_hazards.add(str(hazard["id"])); hit_hazards.add(str(hazard["id"])); continue
                        hit = hazard
            if hit:
                break
        if hit and at >= last_hit + immunity:
            damage = max(0.0, enemy_attack * float(hit.get("damage_multiplier", 1)))
            hp -= damage; last_hit = at; collision_ids.append(str(hit["id"])); hit_hazards.add(str(hit["id"]))
            if hp < 1:
                break
    completed = elapsed_ms >= float(setup.get("duration_ms", 5000)) - 100
    return {
        "initial_hp": initial_hp, "remaining_hp": round(hp, 2), "damage_taken": round(initial_hp - hp, 2),
        "hp_source": setup["hp_source"], "enemy_attack": enemy_attack, "attack_source": setup["attack_source"],
        "attack_id": setup["attack"]["id"], "attack_name": setup["attack"]["name"], "mode_id": setup["mode"]["id"], "mode_name": setup["mode"]["name"],
        "collisions": len(collision_ids), "collision_ids": collision_ids, "shield_blocks": len(blocked_hazards), "avoided_hazards": max(0, len(setup.get("hazards", [])) - len(hit_hazards)),
        "rolls": len(rolls), "distance_moved": round(distance_moved, 2), "elapsed_ms": round(elapsed_ms), "forfeited": forfeited,
        "success": completed and not forfeited and hp >= 1,
    }


def _hex_edges() -> list[tuple[int, int, int]]:
    by_coordinate = {coordinate: index for index, coordinate in enumerate(HEX_COORDS)}
    result = []
    for source, (q, r) in enumerate(HEX_COORDS):
        for direction, (dq, dr) in enumerate(HEX_DIRECTIONS):
            target = by_coordinate.get((q + dq, r + dr))
            if target is not None and source < target:
                result.append((source, target, direction))
    return result


HEX_EDGES = _hex_edges()


def hex_is_solved(masks: list[int], rotations: list[int]) -> bool:
    if len(masks) != 7 or len(rotations) != 7:
        return False
    neighbors: dict[tuple[int, int], tuple[int, int]] = {}
    for source, target, direction in HEX_EDGES:
        neighbors[(source, direction)] = (target, (direction + 3) % 6)
        neighbors[(target, (direction + 3) % 6)] = (source, direction)
    displayed = [{(direction + rotations[index]) % 6 for direction in range(6) if masks[index] & (1 << direction)} for index in range(7)]
    for tile, directions in enumerate(displayed):
        for direction in directions:
            neighbor = neighbors.get((tile, direction))
            if not neighbor or neighbor[1] not in displayed[neighbor[0]]:
                return False
    return True


def generate_hex_setup(difficulty: int) -> dict[str, Any]:
    target_edges = 6 + round((difficulty - 1) * 4 / 9)
    for _ in range(100):
        parent = list(range(7))
        degree = [0] * 7
        chosen: list[tuple[int, int, int]] = []

        def root(value: int) -> int:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        for edge in sorted(HEX_EDGES, key=lambda _: secrets.randbits(32)):
            source, target, _direction = edge
            left, right = root(source), root(target)
            if left != right and degree[source] < 3 and degree[target] < 3:
                parent[left] = right
                degree[source] += 1; degree[target] += 1; chosen.append(edge)
        if len(chosen) != 6:
            continue
        extras = [edge for edge in HEX_EDGES if edge not in chosen]
        for edge in sorted(extras, key=lambda _: secrets.randbits(32)):
            if len(chosen) >= target_edges:
                break
            source, target, _direction = edge
            if degree[source] < 3 and degree[target] < 3:
                degree[source] += 1; degree[target] += 1; chosen.append(edge)
        masks = [0] * 7
        for source, target, direction in chosen:
            masks[source] |= 1 << direction
            masks[target] |= 1 << ((direction + 3) % 6)
        minimum_scramble = 3 + difficulty // 2
        for _ in range(100):
            rotations = [secrets.randbelow(6) for _ in range(7)]
            distance = sum(min(value, 6 - value) for value in rotations)
            if distance >= minimum_scramble and not hex_is_solved(masks, rotations):
                return {"masks": masks, "rotations": rotations, "coordinates": HEX_COORDS}
    raise WorldValidationError("Could not generate a nontrivial hex puzzle")


def _json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


class MinigameService:
    def __init__(self, db: Database, world: WorldEngine) -> None:
        self.db, self.world = db, world
        self.bullethell = BulletHellService(db)

    def ensure_configs(self, project_id: str) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            for game in MANIFESTS.values():
                connection.execute(
                    "INSERT OR IGNORE INTO project_minigame_configs(project_id,game_key,enabled,ai_description,min_difficulty,max_difficulty,updated_at) VALUES (?,?,0,?,?,?,?)",
                    (project_id, game["key"], game["description"], game["min_difficulty"], game["max_difficulty"], now),
                )

    def manifests(self) -> list[dict[str, Any]]:
        return list(MANIFESTS.values())

    def groups(self) -> list[dict[str, Any]]:
        return [{"key": key, "name": value["name"], "game_keys": value["games"]} for key, value in MINIGAME_GROUPS.items()]

    def set_group_enabled(self, project_id: str, group_key: str, enabled: bool) -> list[dict[str, Any]]:
        group = MINIGAME_GROUPS.get(group_key)
        if not group:
            raise WorldValidationError("Unknown minigame group")
        self.ensure_configs(project_id)
        placeholders = ",".join("?" for _ in group["games"])
        self.db.execute(
            f"UPDATE project_minigame_configs SET enabled=?,updated_at=? WHERE project_id=? AND game_key IN ({placeholders})",
            (int(enabled), utc_now(), project_id, *group["games"]),
        )
        return self.configs(project_id)

    def configs(self, project_id: str) -> list[dict[str, Any]]:
        self.ensure_configs(project_id)
        rows = self.db.fetch_all("SELECT * FROM project_minigame_configs WHERE project_id=? ORDER BY game_key", (project_id,))
        result = []
        for row in rows:
            item = dict(row)
            for field in ("allowed_directions", "allowed_actions", "required_actor_tags", "forbidden_actor_tags", "required_target_tags", "forbidden_target_tags", "required_location_tags", "forbidden_location_tags"):
                item[field] = _json(item.pop(field + "_json"), [])
            item["enabled"] = bool(item["enabled"])
            item["manifest"] = MANIFESTS.get(item["game_key"])
            item.update({**_default_options(item["game_key"]), **_json(item.pop("options_json", None), {})})
            result.append(item)
        return result

    def update_config(self, project_id: str, game_key: str, values: dict[str, Any]) -> dict[str, Any]:
        if game_key not in MANIFESTS:
            raise WorldValidationError("Unknown built-in minigame")
        self.ensure_configs(project_id)
        manifest = MANIFESTS[game_key]
        minimum, maximum = int(values.get("min_difficulty", manifest["min_difficulty"])), int(values.get("max_difficulty", manifest["max_difficulty"]))
        if minimum < manifest["min_difficulty"] or maximum > manifest["max_difficulty"] or minimum > maximum:
            raise WorldValidationError(f"Difficulty must be between {manifest['min_difficulty']} and {manifest['max_difficulty']}")
        directions = list(dict.fromkeys(values.get("allowed_directions", [])))
        actions = list(dict.fromkeys(values.get("allowed_actions", [])))
        if not set(directions).issubset({"player_acts", "acted_on"}) or not set(actions).issubset({"story", "say", "do", "guide", "continue"}):
            raise WorldValidationError("Unsupported minigame eligibility option")
        tag_fields = ("required_actor_tags", "forbidden_actor_tags", "required_target_tags", "forbidden_target_tags", "required_location_tags", "forbidden_location_tags")
        tags = {field: sorted({str(tag).strip().casefold() for tag in values.get(field, []) if str(tag).strip()}) for field in tag_fields}
        timer_policy = str(values.get("timer_policy", _default_options(game_key)["timer_policy"]))
        fallback_attempts = int(values.get("fallback_attempts", 3))
        allow_infinite = bool(values.get("allow_infinite_attempts", True))
        if timer_policy not in {"never", "ai_allowed", "always"}:
            raise WorldValidationError("Timer policy must be never, ai_allowed, or always")
        if not 1 <= fallback_attempts <= 10:
            raise WorldValidationError("Fallback lockpick attempts must be between 1 and 10")
        options = {"timer_policy": timer_policy, "fallback_attempts": fallback_attempts, "allow_infinite_attempts": allow_infinite}
        if game_key == "circled_teeth":
            defaults = _default_options(game_key)
            ranges = {}
            for low, high, floor, ceiling in (
                ("min_teeth", "max_teeth", 2, 23),
                ("min_empty_slots", "max_empty_slots", 1, 22),
                ("min_time_seconds", "max_time_seconds", 1, 3600),
            ):
                lower = _strict_optional_int(values.get(low, defaults[low]), low)
                upper = _strict_optional_int(values.get(high, defaults[high]), high)
                if lower is None or upper is None or lower < floor or upper > ceiling or lower > upper:
                    raise WorldValidationError(f"{low} and {high} must form a valid range between {floor} and {ceiling}")
                ranges.update({low: lower, high: upper})
            options.update(ranges)
            options.update({field: bool(values.get(field, defaults[field])) for field in (
                "allow_teeth_override", "allow_empty_slots_override", "allow_time_override", "allow_direction_reversal",
            )})
        elif game_key == "timed_attack":
            defaults = _default_options(game_key)
            line_min = _strict_optional_int(values.get("min_attack_lines", defaults["min_attack_lines"]), "min_attack_lines")
            line_max = _strict_optional_int(values.get("max_attack_lines", defaults["max_attack_lines"]), "max_attack_lines")
            damage_min = _finite_number(values.get("min_attack_damage", defaults["min_attack_damage"]), "min_attack_damage")
            damage_max = _finite_number(values.get("max_attack_damage", defaults["max_attack_damage"]), "max_attack_damage")
            if line_min is None or line_max is None or not 1 <= line_min <= line_max <= 8:
                raise WorldValidationError("Attack line range must be between 1 and 8")
            if not 0 <= damage_min <= damage_max <= 1_000_000:
                raise WorldValidationError("Attack damage range must be ordered between 0 and 1000000")
            for row in self.db.fetch_all("SELECT ability_key,minigame_profile_json FROM ability_definitions WHERE project_id=?", (project_id,)):
                profile = _json(row["minigame_profile_json"], {}).get("timed_attack")
                if profile and not (line_min <= int(profile["line_count"]) <= line_max and damage_min <= float(profile["damage_per_line"]) <= damage_max):
                    raise WorldValidationError(f"Attack ranges exclude the existing ability profile '{row['ability_key']}'")
            options.update({"min_attack_lines": line_min, "max_attack_lines": line_max, "min_attack_damage": damage_min, "max_attack_damage": damage_max})
        elif game_key == "dodge_box":
            defaults = _default_options(game_key)
            control = str(values.get("dodge_control_mode", defaults["dodge_control_mode"]))
            hp_min = _finite_number(values.get("min_fallback_hp", defaults["min_fallback_hp"]), "min_fallback_hp")
            hp_max = _finite_number(values.get("max_fallback_hp", defaults["max_fallback_hp"]), "max_fallback_hp")
            attack_min = _finite_number(values.get("min_enemy_attack", defaults["min_enemy_attack"]), "min_enemy_attack")
            attack_max = _finite_number(values.get("max_enemy_attack", defaults["max_enemy_attack"]), "max_enemy_attack")
            if control not in {"pointer", "keyboard"}:
                raise WorldValidationError("Dodge control mode must be pointer or keyboard")
            if not 1 <= hp_min <= hp_max <= 1_000_000 or not 0 <= attack_min <= attack_max <= 1_000_000:
                raise WorldValidationError("Dodge HP or attack fallback range is invalid")
            options.update({"dodge_control_mode": control, "min_fallback_hp": hp_min, "max_fallback_hp": hp_max, "min_enemy_attack": attack_min, "max_enemy_attack": attack_max})
        self.db.execute(
            "UPDATE project_minigame_configs SET enabled=?,ai_description=?,allowed_directions_json=?,allowed_actions_json=?,required_actor_tags_json=?,forbidden_actor_tags_json=?,required_target_tags_json=?,forbidden_target_tags_json=?,required_location_tags_json=?,forbidden_location_tags_json=?,min_difficulty=?,max_difficulty=?,options_json=?,updated_at=? WHERE project_id=? AND game_key=?",
            (int(bool(values.get("enabled"))), str(values.get("ai_description", ""))[:2000], json.dumps(directions), json.dumps(actions), *(json.dumps(tags[field]) for field in tag_fields), minimum, maximum, json.dumps(options), utc_now(), project_id, game_key),
        )
        return next(row for row in self.configs(project_id) if row["game_key"] == game_key)

    @staticmethod
    def _tags(entity: dict[str, Any] | None) -> set[str]:
        return {str(tag).casefold() for tag in (entity or {}).get("tags", [])}

    @staticmethod
    def _tags_match(tags: set[str], required: list[str], forbidden: list[str]) -> bool:
        return set(required).issubset(tags) and not tags.intersection(forbidden)

    def eligible_for_prompt(self, project_id: str, head_node_id: str | None, action: str, user_request: str = "") -> list[dict[str, Any]]:
        projection = self.world.projection(project_id, head_node_id)
        active = [e for e in projection["entities"].values() if not e.get("state", {}).get("archived")]
        players = [e for e in active if e["kind"] == "character" and e.get("state", {}).get("player_controlled")]
        characters = [e for e in active if e["kind"] == "character"]
        if not players:
            virtual_player = {"id": VIRTUAL_PLAYER_ID, "kind": "character", "name": "Player", "aliases": [], "tags": [], "state": {"player_controlled": True, "virtual": True}}
            players = [virtual_player]
            characters.append(virtual_player)
        result = []
        for config in self.configs(project_id):
            if not config["enabled"] or not players:
                continue
            valid_players = [player for player in players if self._tags_match(
                self._tags(projection["entities"].get(player.get("state", {}).get("current_location_id"))),
                config["required_location_tags"], config["forbidden_location_tags"],
            )]
            if not valid_players:
                continue
            target_candidates = [entity for entity in active if self._tags_match(
                self._tags(entity), config["required_target_tags"], config["forbidden_target_tags"],
            )]
            if config["required_target_tags"] and not target_candidates:
                continue
            can_player_act = "player_acts" in config["allowed_directions"] and any(
                self._tags_match(self._tags(player), config["required_actor_tags"], config["forbidden_actor_tags"])
                for player in valid_players
            )
            can_be_acted_on = "acted_on" in config["allowed_directions"] and any(
                self._tags_match(self._tags(actor), config["required_actor_tags"], config["forbidden_actor_tags"])
                for actor in characters if not actor.get("state", {}).get("player_controlled")
            ) and any(self._tags_match(self._tags(player), config["required_target_tags"], config["forbidden_target_tags"]) for player in valid_players)
            if not (can_player_act or can_be_acted_on):
                continue
            eligible_actors = [entity for entity in characters if self._tags_match(
                self._tags(entity), config["required_actor_tags"], config["forbidden_actor_tags"],
            ) and (entity.get("state", {}).get("player_controlled") or "acted_on" in config["allowed_directions"])]
            combat_guidance = None
            if config["game_key"] == "timed_attack":
                definitions = self.db.fetch_all("SELECT ability_key,name,minigame_profile_json FROM ability_definitions WHERE project_id=?", (project_id,))
                profiles = []
                for entity in eligible_actors:
                    owned = {str(value) for value in entity.get("state", {}).get("abilities", [])}
                    for definition in definitions:
                        profile = _json(definition["minigame_profile_json"], {}).get("timed_attack")
                        if profile and ({definition["ability_key"], definition["name"]} & owned):
                            profiles.append({"actor_id": entity["id"], "ability_key": definition["ability_key"], **profile})
                combat_guidance = {
                    "ability_profiles": profiles,
                    "fallback": {"line_count": [config["min_attack_lines"], config["max_attack_lines"]], "damage_per_line": [config["min_attack_damage"], config["max_attack_damage"]]},
                    "rule": "Use an owned profiled ability when applicable; otherwise supply both fallback values.",
                }
            elif config["game_key"] == "dodge_box":
                bullet_settings = self.bullethell.project_settings(project_id)
                bullet_catalog = self.bullethell.catalog()
                participant_stats = []
                for player in valid_players:
                    stats = {} if player["id"] == VIRTUAL_PLAYER_ID else self.world.effective_stats(project_id, player)
                    participant_stats.append({"id": player["id"], "hp": stats.get("hp")})
                actor_stats = []
                for entity in eligible_actors:
                    stats = {} if entity["id"] == VIRTUAL_PLAYER_ID else self.world.effective_stats(project_id, entity)
                    actor_stats.append({"id": entity["id"], "attack": stats.get("attack")})
                combat_guidance = {
                    "control_mode": config["dodge_control_mode"], "duration_seconds": 5,
                    "attacks": [{"id": item["id"], "name": item["name"], "description": item["ai_description"], "tags": item["tags"]} for item in bullet_catalog["attacks"] if item["id"] in bullet_settings["allowed_attack_ids"]],
                    "modes": [{"id": item["id"], "name": item["name"]} for item in bullet_catalog["modes"] if item["id"] in bullet_settings["allowed_mode_ids"]],
                    "participants": participant_stats, "actors": actor_stats,
                    "fallback_hp": [config["min_fallback_hp"], config["max_fallback_hp"]],
                    "fallback_enemy_attack": [config["min_enemy_attack"], config["max_enemy_attack"]],
                    "rule": "Choose exactly one listed attack_id. Supply hp or enemy_attack only when the corresponding canonical value is null.",
                }
            group_key = str(config["manifest"].get("group", ""))
            terms = MINIGAME_GROUPS.get(group_key, {}).get("terms", [])
            request_text = user_request.casefold()
            explicit = config["game_key"].replace("_", " ") in request_text or config["manifest"]["name"].casefold() in request_text
            matched_terms = [term for term in terms if term in request_text]
            result.append({
                "game_key": config["game_key"], "description": config["ai_description"],
                "group": group_key, "recommended": bool(explicit or matched_terms or action in config["allowed_actions"]), "recommendation_terms": matched_terms[:5],
                "preferred_actions": config["allowed_actions"],
                "directions": config["allowed_directions"], "difficulty": [config["min_difficulty"], config["max_difficulty"]],
                "participants": [{"id": player["id"], "name": player["name"]} for player in valid_players],
                "actors": [{"id": entity["id"], "name": entity["name"], "player_controlled": bool(entity.get("state", {}).get("player_controlled"))} for entity in eligible_actors],
                "targets": [{"id": entity["id"], "name": entity["name"], "kind": entity["kind"]} for entity in target_candidates[:20]],
                "timer_policy": config["timer_policy"],
                "timer_guidance": "Use timed=true only during pursuit, combat pressure, alarms, or high security." if config["timer_policy"] == "ai_allowed" else f"Timer is {config['timer_policy']}.",
                "attempt_guidance": ({"default": config["fallback_attempts"], "maximum": 10, "infinite_allowed": config["allow_infinite_attempts"]} if config["game_key"] == "lockpicking" else None),
                "parameter_guidance": ({
                    "optional_arguments": {
                        "teeth": [config["min_teeth"], config["max_teeth"]] if config["allow_teeth_override"] else None,
                        "empty_slots": [config["min_empty_slots"], config["max_empty_slots"]] if config["allow_empty_slots_override"] else None,
                        "time_seconds": [config["min_time_seconds"], config["max_time_seconds"]] if config["allow_time_override"] else None,
                        "reverse_on_success": config["allow_direction_reversal"],
                    },
                    "total_slots": [4, 24],
                    "rule": "Omit any override to use its difficulty-derived default. Explicit time_seconds forces a timed puzzle.",
                } if config["game_key"] == "circled_teeth" else None),
                "combat_guidance": combat_guidance,
            })
        return sorted(result, key=lambda item: (not item["recommended"], item["group"], item["game_key"]))

    def validate_invocation(self, project_id: str, head_node_id: str | None, action: str, arguments: dict[str, Any], staged: list[Any] | None = None) -> dict[str, Any]:
        game_key = str(arguments.get("game_key", ""))
        manifest = MANIFESTS.get(game_key)
        config = next((row for row in self.configs(project_id) if row["game_key"] == game_key), None)
        if not manifest or not config or not config["enabled"]:
            raise WorldValidationError("The requested minigame is not enabled")
        if action not in config["allowed_actions"]:
            raise WorldValidationError("This minigame is not allowed for the current composer action")
        try:
            difficulty = int(arguments.get("difficulty", 1))
        except (TypeError, ValueError) as exc:
            raise WorldValidationError("Minigame difficulty must be an integer") from exc
        if not config["min_difficulty"] <= difficulty <= config["max_difficulty"]:
            raise WorldValidationError("Minigame difficulty is outside the configured range")
        projection = self.world.preview(project_id, head_node_id, staged or []) if staged else self.world.projection(project_id, head_node_id)
        entities = projection["entities"]
        actor_id, participant_id = str(arguments.get("actor_id") or ""), str(arguments.get("participant_id") or "")
        target_id = str(arguments.get("target_id") or "") or None
        has_canonical_player = any(entity["kind"] == "character" and entity.get("state", {}).get("player_controlled") and not entity.get("state", {}).get("archived") for entity in entities.values())
        virtual_player = {"id": VIRTUAL_PLAYER_ID, "kind": "character", "name": "Player", "aliases": [], "tags": [], "state": {"player_controlled": True, "virtual": True}}
        if not has_canonical_player:
            if participant_id == VIRTUAL_PLAYER_ID:
                entities = {**entities, VIRTUAL_PLAYER_ID: virtual_player}
            if actor_id == VIRTUAL_PLAYER_ID:
                entities = {**entities, VIRTUAL_PLAYER_ID: virtual_player}
            if target_id == VIRTUAL_PLAYER_ID:
                entities = {**entities, VIRTUAL_PLAYER_ID: virtual_player}
        actor, participant, target = entities.get(actor_id), entities.get(participant_id), entities.get(target_id) if target_id else None
        if not actor or actor["kind"] != "character" or not participant or participant["kind"] != "character":
            raise WorldValidationError("Minigame actor and participant must be available characters")
        if actor.get("state", {}).get("archived") or participant.get("state", {}).get("archived") or (target and target.get("state", {}).get("archived")):
            raise WorldValidationError("Archived entities are unavailable for minigames")
        if not participant.get("state", {}).get("player_controlled"):
            raise WorldValidationError("Minigame participant must be player controlled")
        if target_id and not target:
            raise WorldValidationError("Minigame target is unavailable on this branch")
        direction = "player_acts" if actor_id == participant_id else "acted_on"
        if direction not in config["allowed_directions"]:
            raise WorldValidationError("This direction is disabled for the minigame")
        if direction == "acted_on":
            if target_id not in {None, participant_id}:
                raise WorldValidationError("An acted-on challenge must target the player participant")
            target_id, target = participant_id, participant
        location_id = participant.get("state", {}).get("current_location_id")
        location = entities.get(location_id)
        checks = ((actor, "actor"), (target, "target"), (location, "location"))
        for entity, label in checks:
            required, forbidden = config[f"required_{label}_tags"], config[f"forbidden_{label}_tags"]
            if required and not entity:
                raise WorldValidationError(f"The minigame requires a {label}")
            if not self._tags_match(self._tags(entity), required, forbidden):
                raise WorldValidationError(f"The {label} does not satisfy this minigame's tag rules")
        challenge = str(arguments.get("challenge_text") or "").strip()
        if not challenge:
            raise WorldValidationError("startMinigame requires challenge_text")
        timer_policy = config["timer_policy"]
        requested_timed = arguments.get("timed", False)
        if not isinstance(requested_timed, bool):
            raise WorldValidationError("Minigame timed must be true or false")
        timed = timer_policy == "always" or (timer_policy == "ai_allowed" and requested_timed)
        invocation = {"game_key": game_key, "actor_id": actor_id, "participant_id": participant_id, "target_id": target_id, "difficulty": difficulty, "challenge_text": challenge[:1000], "direction": direction, "timed": timed}
        if game_key == "timing_hit":
            width = .40 - (difficulty - 1) * (.28 / 9)
            center = width / 2 + secrets.randbelow(1_000_001) / 1_000_000 * (1 - width)
            invocation["setup"] = {"target_start": center - width / 2, "target_end": center + width / 2, "traversal_ms": round(1800 - (difficulty - 1) * (1100 / 9))}
        elif game_key == "key_mash":
            invocation["setup"] = {"duration_ms": 4000, "target": 8 + 2 * difficulty}
        elif game_key == "red_light":
            base_duration = 1500 - (difficulty - 1) * (650 / 9)
            warning_ms = round(420 - (difficulty - 1) * (200 / 9))
            phases = []
            for index in range(7):
                variation = .82 + secrets.randbelow(361) / 1000
                phases.append({
                    "color": "green" if index % 2 == 0 else "red",
                    "duration_ms": round(base_duration * variation),
                    "warning_ms": warning_ms,
                })
            invocation["setup"] = {
                "phases": phases,
                "duration_ms": sum(phase["duration_ms"] for phase in phases),
                "lose_threshold_ms": round(1100 - (difficulty - 1) * (800 / 9)),
            }
        elif game_key == "lockpicking":
            inventory: list[dict[str, Any]] = []
            for entry in participant.get("state", {}).get("inventory", []):
                item = entities.get(str(entry.get("item_id")))
                quantity = int(entry.get("quantity", 0))
                if item and item["kind"] == "item" and "lockpick" in {str(tag).casefold() for tag in item.get("tags", [])} and quantity > 0:
                    inventory.append({"item_id": item["id"], "quantity": quantity})
            physical_count = sum(entry["quantity"] for entry in inventory)
            requested_limit = arguments.get("attempt_limit", config["fallback_attempts"])
            if physical_count:
                attempt_limit: int | None = physical_count
                attempt_source = "inventory"
            else:
                if requested_limit is None:
                    if not config["allow_infinite_attempts"]:
                        raise WorldValidationError("Infinite lockpicks are disabled; request between 1 and 10 attempts")
                    attempt_limit = None
                else:
                    if isinstance(requested_limit, bool):
                        raise WorldValidationError("Lockpick attempt_limit must be between 1 and 10 or null")
                    attempt_limit = int(requested_limit)
                    if not 1 <= attempt_limit <= 10:
                        raise WorldValidationError("Lockpick attempt_limit must be between 1 and 10")
                attempt_source = "story"
            width = 40 - (difficulty - 1) * (34 / 9)
            center = -90 + width / 2 + secrets.randbelow(1_000_001) / 1_000_000 * (180 - width)
            invocation["setup"] = {
                "sweet_center": center, "sweet_width": width,
                "pick_durability_ms": round(1200 - (difficulty - 1) * (750 / 9)),
                "attempt_limit": attempt_limit, "attempt_source": attempt_source,
                "inventory": inventory,
                "time_limit_ms": round((50 - (difficulty - 1) * (32 / 9)) * 1000) if timed else None,
            }
        elif game_key == "hex_circuit":
            setup = generate_hex_setup(difficulty)
            setup["time_limit_ms"] = round((60 - (difficulty - 1) * (40 / 9)) * 1000) if timed else None
            invocation["setup"] = setup
        elif game_key == "circled_teeth":
            defaults = {
                "teeth": round(4 + (difficulty - 1) * (6 / 9)),
                "empty_slots": 4,
                "time_seconds": round(45 - (difficulty - 1) * (27 / 9)),
            }
            requested: dict[str, int | bool] = {}
            resolved: dict[str, int] = {}
            for argument, allowed, low, high in (
                ("teeth", "allow_teeth_override", "min_teeth", "max_teeth"),
                ("empty_slots", "allow_empty_slots_override", "min_empty_slots", "max_empty_slots"),
                ("time_seconds", "allow_time_override", "min_time_seconds", "max_time_seconds"),
            ):
                value = _strict_optional_int(arguments.get(argument), argument)
                if value is not None:
                    if not config[allowed]:
                        raise WorldValidationError(f"AI override {argument} is disabled for this project")
                    if not int(config[low]) <= value <= int(config[high]):
                        raise WorldValidationError(f"{argument} must be between {config[low]} and {config[high]}")
                    requested[argument] = value
                resolved[argument] = defaults[argument] if value is None else value
            reverse = arguments.get("reverse_on_success", False)
            if not isinstance(reverse, bool):
                raise WorldValidationError("reverse_on_success must be true or false")
            if reverse and not config["allow_direction_reversal"]:
                raise WorldValidationError("Direction reversal is disabled for this project")
            slot_count = resolved["teeth"] + resolved["empty_slots"]
            if not 4 <= slot_count <= 24:
                raise WorldValidationError("teeth plus empty_slots must create between 4 and 24 total slots")
            explicit_time = "time_seconds" in requested
            effective_timed = explicit_time or timed
            invocation["timed"] = effective_timed
            invocation["requested_overrides"] = {**requested, **({"reverse_on_success": True} if reverse else {})}
            invocation["setup"] = {
                "slot_count": slot_count, "tooth_count": resolved["teeth"], "empty_slot_count": resolved["empty_slots"],
                "occupied_slots": sorted(secrets.SystemRandom().sample(range(slot_count), resolved["teeth"])),
                "revolution_ms": round(2800 - (difficulty - 1) * (1600 / 9)),
                "strike_limit": round(5 - (difficulty - 1) * (3 / 9)),
                "hit_window_fraction": .65 - (difficulty - 1) * (.30 / 9),
                "initial_angle": secrets.randbelow(1_000_000) / 1_000_000,
                "initial_direction": -1 if secrets.randbelow(2) else 1,
                "reverse_on_success": reverse,
                "time_limit_ms": resolved["time_seconds"] * 1000 if effective_timed else None,
                "resolved_parameters": resolved,
            }
        elif game_key == "timed_attack":
            ability_key = str(arguments.get("ability_key") or "").strip() or None
            profile = None
            if ability_key:
                ability = self.db.fetch_one("SELECT ability_key,name,minigame_profile_json FROM ability_definitions WHERE project_id=? AND ability_key=?", (project_id, ability_key))
                owned = {str(value) for value in actor.get("state", {}).get("abilities", [])}
                if not ability or not ({ability["ability_key"], ability["name"]} & owned):
                    raise WorldValidationError("Timed-attack ability must be owned by the actor")
                profile = _json(ability["minigame_profile_json"], {}).get("timed_attack")
            if profile:
                line_count = int(profile["line_count"])
                damage_per_line = _finite_number(profile["damage_per_line"], "ability damage_per_line")
                parameter_source = "ability"
            else:
                line_count = _strict_optional_int(arguments.get("line_count"), "line_count")
                if line_count is None or not int(config["min_attack_lines"]) <= line_count <= int(config["max_attack_lines"]):
                    raise WorldValidationError(f"line_count must be between {config['min_attack_lines']} and {config['max_attack_lines']}")
                if arguments.get("damage_per_line") is None:
                    raise WorldValidationError("damage_per_line is required without a profiled ability")
                damage_per_line = _finite_number(arguments["damage_per_line"], "damage_per_line")
                if not float(config["min_attack_damage"]) <= damage_per_line <= float(config["max_attack_damage"]):
                    raise WorldValidationError(f"damage_per_line must be between {config['min_attack_damage']} and {config['max_attack_damage']}")
                parameter_source = "ai_fallback"
            base_traversal = 1600 - (difficulty - 1) * (800 / 9)
            start_ms = 0
            lines = []
            for index in range(line_count):
                if index:
                    start_ms += 120 + secrets.randbelow(141)
                variation = .92 + secrets.randbelow(161) / 1000
                lines.append({"id": index, "start_ms": start_ms, "traversal_ms": round(base_traversal * variation)})
            invocation["ability_key"] = ability_key
            invocation["setup"] = {
                "lines": lines, "line_count": line_count, "damage_per_line": damage_per_line,
                "parameter_source": parameter_source, "sweet_width": .35 - (difficulty - 1) * (.23 / 9),
                "success_threshold": 35 + (difficulty - 1) * (35 / 9),
                "duration_ms": max(line["start_ms"] + line["traversal_ms"] for line in lines),
            }
        elif game_key == "dodge_box":
            participant_stats = {} if participant_id == VIRTUAL_PLAYER_ID else self.world.effective_stats(project_id, participant)
            if "hp" in participant_stats:
                hp, hp_source = float(participant_stats["hp"]), "canonical"
            else:
                if arguments.get("hp") is None:
                    raise WorldValidationError("hp is required because the participant has no canonical hp stat")
                hp, hp_source = _finite_number(arguments["hp"], "hp"), "ai_fallback"
                if not float(config["min_fallback_hp"]) <= hp <= float(config["max_fallback_hp"]):
                    raise WorldValidationError(f"hp must be between {config['min_fallback_hp']} and {config['max_fallback_hp']}")
            if hp < 1:
                raise WorldValidationError("A dodge challenge cannot start below 1 HP")
            attacker = actor if actor_id != participant_id else target if target and target.get("kind") == "character" else None
            attacker_stats = self.world.effective_stats(project_id, attacker) if attacker else {}
            if "attack" in attacker_stats:
                enemy_attack, attack_source = float(attacker_stats["attack"]), "canonical"
            else:
                if arguments.get("enemy_attack") is None:
                    raise WorldValidationError("enemy_attack is required because the attacker has no canonical attack stat")
                enemy_attack, attack_source = _finite_number(arguments["enemy_attack"], "enemy_attack"), "ai_fallback"
                if not float(config["min_enemy_attack"]) <= enemy_attack <= float(config["max_enemy_attack"]):
                    raise WorldValidationError(f"enemy_attack must be between {config['min_enemy_attack']} and {config['max_enemy_attack']}")
            attack_id = str(arguments.get("attack_id") or "")
            snapshot = self.bullethell.snapshot(project_id, attack_id, participant, attacker)
            movement = next((skill for skill in snapshot["skills"] if skill["id"] == snapshot["mode"]["movement_skill_id"]), None)
            control_mode = "keyboard" if movement and movement["behavior"] == "blue_gravity" else config["dodge_control_mode"]
            invocation["attack_id"] = attack_id
            invocation["setup"] = {
                "duration_ms": 5000, "time_limit_ms": 5000, "control_mode": control_mode,
                "initial_hp": hp, "hp_source": hp_source, "enemy_attack": enemy_attack, "attack_source": attack_source,
                **snapshot, "hazards": expand_hazards(snapshot["attack"], snapshot["seed"]),
            }
        return invocation

    def create_session(self, project_id: str, job_id: str, parent_node_id: str | None, invocation: dict[str, Any], partial: str, mutations: list[dict[str, Any]], interventions: list[dict[str, Any]], suggestion: dict[str, Any] | None) -> dict[str, Any]:
        session_id, now = new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute("INSERT INTO minigame_sessions(id,project_id,job_id,parent_node_id,game_key,game_version,status,invocation_json,partial_prose,staged_mutations_json,interventions_json,suggestion_json,created_at,updated_at) VALUES (?,?,?,?,?,1,'awaiting_input',?,?,?,?,?,?,?)", (session_id, project_id, job_id, parent_node_id, invocation["game_key"], json.dumps(invocation), partial, json.dumps(mutations), json.dumps(interventions), json.dumps(suggestion) if suggestion else None, now, now))
            connection.execute("UPDATE generation_jobs SET status='awaiting_minigame',phase='awaiting_minigame',progress_message='Waiting for player',updated_at=? WHERE id=?", (now, job_id))
        return self.get_session(session_id) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT s.*,j.status job_status FROM minigame_sessions s LEFT JOIN generation_jobs j ON j.id=s.job_id WHERE s.id=?", (session_id,))
        if not row:
            return None
        for field in ("invocation", "result", "staged_mutations", "interventions", "suggestion"):
            row[field] = _json(row.pop(field + "_json"), None if field in {"result", "suggestion"} else [])
        return row

    def start_attempt(self, session_id: str) -> tuple[dict[str, Any], bool]:
        session = self.get_session(session_id)
        if not session:
            raise WorldValidationError("Minigame checkpoint not found")
        if session["game_key"] not in {"timing_hit", "key_mash", "red_light", "lockpicking", "hex_circuit", "circled_teeth", "timed_attack", "dodge_box"}:
            raise WorldValidationError("Only interactive minigames have an explicit start")
        if session["status"] != "awaiting_input":
            raise WorldValidationError("This minigame can no longer be started")
        if session.get("attempt_started_at"):
            return session, False
        now = utc_now()
        self.db.execute(
            "UPDATE minigame_sessions SET attempt_started_at=?,updated_at=? "
            "WHERE id=? AND status='awaiting_input' AND attempt_started_at IS NULL",
            (now, now, session_id),
        )
        started = self.get_session(session_id) or {}
        return started, started.get("attempt_started_at") == now

    def resolve(self, session_id: str, submission: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        session = self.get_session(session_id)
        if not session:
            raise WorldValidationError("Minigame checkpoint not found")
        if session["status"] in {"resolved", "committed"}:
            return session, False
        if session["status"] != "awaiting_input":
            raise WorldValidationError("This minigame can no longer be resolved")
        key, invocation = session["game_key"], session["invocation"]
        difficulty = int(invocation["difficulty"])
        if key in {"timing_hit", "key_mash", "red_light", "lockpicking", "hex_circuit", "circled_teeth", "timed_attack", "dodge_box"} and not session.get("attempt_started_at"):
            raise WorldValidationError("Start the minigame before submitting its result")
        setup = invocation.get("setup") or {}
        server_elapsed = 0.0
        if session.get("attempt_started_at"):
            server_elapsed = max(0.0, (datetime.now(UTC) - datetime.fromisoformat(session["attempt_started_at"])).total_seconds() * 1000)
        time_limit = setup.get("time_limit_ms")
        server_timeout = bool(time_limit and server_elapsed > float(time_limit) + 250)
        if key in {"roll_d20", "roll_d6"}:
            sides = int(MANIFESTS[key]["sides"])
            roll = secrets.randbelow(sides) + 1
            result = {"roll": roll, "sides": sides, "difficulty": difficulty, "success": roll > difficulty}
        elif key == "flip_coin":
            choice = str(submission.get("choice", "")).casefold()
            if choice not in {"heads", "tails"}:
                raise WorldValidationError("Choose heads or tails")
            flip = ("heads", "tails")[secrets.randbelow(2)]
            result = {"choice": choice, "flip": flip, "success": choice == flip}
        elif key == "timing_hit":
            try:
                position, elapsed = float(submission["position"]), float(submission["elapsed_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorldValidationError("Timing result requires numeric position and elapsed_ms") from exc
            if not 0 <= position <= 1 or not 0 <= elapsed <= 60_000:
                raise WorldValidationError("Timing result is outside valid ranges")
            setup = invocation["setup"]
            center = (setup["target_start"] + setup["target_end"]) / 2
            result = {"position": position, "distance": abs(position - center), "elapsed_ms": elapsed, "success": setup["target_start"] <= position <= setup["target_end"]}
        elif key == "key_mash":
            try:
                count, elapsed = int(submission["count"]), float(submission["elapsed_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorldValidationError("Key-mash result requires count and elapsed_ms") from exc
            if not 0 <= count <= 100_000 or not 0 <= elapsed <= 60_000:
                raise WorldValidationError("Key-mash result is outside valid ranges")
            target = int(invocation["setup"]["target"])
            result = {"count": count, "target": target, "elapsed_ms": elapsed, "success": count >= target}
        elif key == "red_light":
            try:
                violation, elapsed = float(submission["violation_ms"]), float(submission["elapsed_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorldValidationError("Red-light result requires numeric violation_ms and elapsed_ms") from exc
            setup = invocation["setup"]
            duration, threshold = float(setup["duration_ms"]), float(setup["lose_threshold_ms"])
            if not 0 <= violation <= 60_000 or not 0 <= elapsed <= duration + 5_000:
                raise WorldValidationError("Red-light result is outside valid ranges")
            completed = elapsed >= duration - 100
            result = {
                "violation_ms": round(violation), "lose_threshold_ms": round(threshold),
                "elapsed_ms": round(elapsed), "completed": completed,
                "success": completed and violation < threshold,
            }
        elif key == "lockpicking":
            try:
                broken = int(submission["broken_picks"])
                angle = float(submission["final_angle"])
                rotation = float(submission["lock_rotation"])
                elapsed = float(submission["elapsed_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WorldValidationError("Lockpicking result requires broken_picks, final_angle, lock_rotation, and elapsed_ms") from exc
            attempt_limit = setup.get("attempt_limit")
            if broken < 0 or broken > 10_000 or not -90 <= angle <= 90 or not 0 <= rotation <= 90 or not 0 <= elapsed <= 3_600_000:
                raise WorldValidationError("Lockpicking result is outside valid ranges")
            if attempt_limit is not None and broken > int(attempt_limit):
                raise WorldValidationError("Broken lockpick count exceeds the available attempts")
            angle_error = abs(angle - float(setup["sweet_center"]))
            timed_out = server_timeout or bool(submission.get("timeout"))
            has_pick = attempt_limit is None or broken < int(attempt_limit)
            opened = has_pick and rotation >= 88 and angle_error <= float(setup["sweet_width"]) / 2
            result = {
                "broken_picks": broken, "attempt_limit": attempt_limit,
                "attempt_source": setup.get("attempt_source", "story"),
                "final_angle": angle, "angular_error": angle_error,
                "lock_rotation": rotation, "elapsed_ms": round(elapsed),
                "timed_out": timed_out, "success": opened and not timed_out,
            }
            remaining = broken
            staged_mutations = list(session.get("staged_mutations") or [])
            if setup.get("attempt_source") == "inventory":
                for entry in setup.get("inventory", []):
                    consumed = min(remaining, int(entry["quantity"]))
                    if consumed:
                        staged_mutations.append({"tool": "adjustInventory", "arguments": {
                            "character_id": invocation["participant_id"], "item_id": entry["item_id"], "delta": -consumed,
                        }})
                        remaining -= consumed
                    if remaining <= 0:
                        break
                if remaining:
                    raise WorldValidationError("Broken lockpick count exceeds canonical inventory")
            session["staged_mutations"] = staged_mutations
        elif key == "hex_circuit":
            rotations = submission.get("rotations")
            try:
                rotations = [int(value) for value in rotations]
                move_count, elapsed = int(submission["move_count"]), float(submission["elapsed_ms"])
            except (TypeError, ValueError, KeyError) as exc:
                raise WorldValidationError("Hex-circuit result requires seven rotations, move_count, and elapsed_ms") from exc
            if len(rotations) != 7 or any(value < 0 or value > 5 for value in rotations) or move_count < 0 or move_count > 100_000 or not 0 <= elapsed <= 3_600_000:
                raise WorldValidationError("Hex-circuit result is outside valid ranges")
            timed_out = server_timeout or bool(submission.get("timeout"))
            solved = hex_is_solved([int(value) for value in setup["masks"]], rotations)
            result = {"rotations": rotations, "move_count": move_count, "elapsed_ms": round(elapsed), "timed_out": timed_out, "success": solved and not timed_out}
        elif key == "circled_teeth":
            try:
                elapsed = float(submission["elapsed_ms"])
            except (TypeError, ValueError, KeyError) as exc:
                raise WorldValidationError("Circled-teeth result requires events and elapsed_ms") from exc
            if not math.isfinite(elapsed) or not 0 <= elapsed <= 3_600_000:
                raise WorldValidationError("Circled-teeth elapsed time is outside valid ranges")
            timed_out = server_timeout or bool(submission.get("timeout"))
            result = replay_circled_teeth(setup, submission.get("events"), elapsed, timed_out)
        elif key == "timed_attack":
            elapsed = _finite_number(submission.get("elapsed_ms"), "elapsed_ms")
            if not 0 <= elapsed <= 60_000:
                raise WorldValidationError("Timed-attack elapsed time is outside valid ranges")
            result = score_timed_attack(setup, submission.get("events"), elapsed, bool(submission.get("timeout")))
        elif key == "dodge_box":
            elapsed = _finite_number(submission.get("elapsed_ms"), "elapsed_ms")
            forfeited = bool(submission.get("timeout"))
            if not 0 <= elapsed <= 60_000:
                raise WorldValidationError("Dodge-box telemetry is outside valid ranges")
            complete = elapsed >= float(setup["duration_ms"]) - 100
            if not complete and not forfeited:
                raise WorldValidationError("Dodge-box attempt has not completed its five seconds")
            result = simulate_bullethell(setup, submission.get("samples"), submission.get("skill_events") or [], elapsed, forfeited)
        else:
            raise WorldValidationError("Unsupported minigame result")
        now = utc_now()
        self.db.execute("UPDATE minigame_sessions SET status='resolved',result_json=?,staged_mutations_json=?,resolved_at=?,updated_at=? WHERE id=? AND status='awaiting_input'", (json.dumps(result), json.dumps(session.get("staged_mutations") or []), now, now, session_id))
        return self.get_session(session_id) or {}, True
