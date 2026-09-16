from __future__ import annotations

import json
import math
import random
from typing import Any

from app.database import Database, new_id, utc_now
from app.services.world import WorldValidationError


TABLES = {"skills": "bullethell_skills", "modes": "bullethell_modes", "attacks": "bullethell_attacks"}


def _json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (json.JSONDecodeError, TypeError):
        return fallback


class BulletHellService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def catalog(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for kind, table in TABLES.items():
            rows = self.db.fetch_all(f"SELECT * FROM {table} ORDER BY built_in DESC,name")
            for row in rows:
                row["built_in"] = bool(row["built_in"])
                for field in ("parameters", "allowed_skill_ids", "tags", "phases"):
                    key = field + "_json"
                    if key in row:
                        row[field] = _json(row.pop(key), [] if field in {"allowed_skill_ids", "tags", "phases"} else {})
                if "uses_enemy_forced_mode" in row:
                    row["uses_enemy_forced_mode"] = bool(row["uses_enemy_forced_mode"])
            result[kind] = rows
        return result

    def project_settings(self, project_id: str) -> dict[str, Any]:
        now = utc_now()
        self.db.execute("INSERT OR IGNORE INTO project_bullethell_settings(project_id,default_mode_id,updated_at) VALUES (?,'builtin:base',?)", (project_id, now))
        settings = self.db.fetch_one("SELECT * FROM project_bullethell_settings WHERE project_id=?", (project_id,)) or {}
        for kind, table in (("mode", "project_bullethell_modes"), ("skill", "project_bullethell_skills"), ("attack", "project_bullethell_attacks")):
            rows = self.db.fetch_all(f"SELECT {kind}_id id FROM {table} WHERE project_id=? ORDER BY {kind}_id", (project_id,))
            settings[f"allowed_{kind}_ids"] = [row["id"] for row in rows]
        return settings

    def update_project_settings(self, project_id: str, values: dict[str, Any]) -> dict[str, Any]:
        catalog = self.catalog()
        known = {kind: {row["id"] for row in rows} for kind, rows in catalog.items()}
        modes = list(dict.fromkeys(values.get("allowed_mode_ids", [])))
        skills = list(dict.fromkeys(values.get("allowed_skill_ids", [])))
        attacks = list(dict.fromkeys(values.get("allowed_attack_ids", [])))
        default = values.get("default_mode_id") or "builtin:base"
        if not set(modes) <= known["modes"] or not set(skills) <= known["skills"] or not set(attacks) <= known["attacks"]:
            raise WorldValidationError("Bullet-hell allowlist references an unavailable definition")
        if default not in known["modes"] or (modes and default not in modes):
            raise WorldValidationError("Default bullet-hell mode must be enabled for the project")
        mode_rows = {row["id"]: row for row in catalog["modes"]}
        missing_movement = [mode_rows[mode_id]["movement_skill_id"] for mode_id in modes if mode_rows[mode_id]["movement_skill_id"] not in skills]
        if missing_movement:
            raise WorldValidationError(f"Enable each mode's movement skill first: {', '.join(dict.fromkeys(missing_movement))}")
        if attacks and not modes:
            raise WorldValidationError("Enable at least one movement mode before enabling attacks")
        with self.db._lock, self.db.connect() as connection:
            connection.execute("INSERT INTO project_bullethell_settings(project_id,default_mode_id,updated_at) VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET default_mode_id=excluded.default_mode_id,updated_at=excluded.updated_at", (project_id, default, utc_now()))
            for table in ("project_bullethell_modes", "project_bullethell_skills", "project_bullethell_attacks"):
                connection.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            connection.executemany("INSERT INTO project_bullethell_modes VALUES (?,?)", [(project_id, value) for value in modes])
            connection.executemany("INSERT INTO project_bullethell_skills VALUES (?,?)", [(project_id, value) for value in skills])
            connection.executemany("INSERT INTO project_bullethell_attacks VALUES (?,?)", [(project_id, value) for value in attacks])
        return self.project_settings(project_id)

    def clone(self, kind: str, source_id: str, definition_key: str, name: str) -> dict[str, Any]:
        table = TABLES.get(kind)
        if not table:
            raise WorldValidationError("Unknown bullet-hell catalog")
        source = self.db.fetch_one(f"SELECT * FROM {table} WHERE id=?", (source_id,))
        if not source:
            raise WorldValidationError("Bullet-hell definition not found")
        if not definition_key or not name:
            raise WorldValidationError("Clone requires a stable key and name")
        identifier, now = new_id(), utc_now()
        columns = [key for key in source if key not in {"id", "definition_key", "name", "built_in", "created_at", "updated_at"}]
        values = [source[key] for key in columns]
        placeholders = ",".join("?" for _ in range(len(columns) + 6))
        self.db.execute(f"INSERT INTO {table}(id,definition_key,name,{','.join(columns)},built_in,created_at,updated_at) VALUES ({placeholders})", (identifier, definition_key, name, *values, 0, now, now))
        return next(row for row in self.catalog()[kind] if row["id"] == identifier)

    def update(self, kind: str, identifier: str, values: dict[str, Any]) -> dict[str, Any]:
        table = TABLES.get(kind)
        row = self.db.fetch_one(f"SELECT * FROM {table} WHERE id=?", (identifier,)) if table else None
        if not row:
            raise WorldValidationError("Bullet-hell definition not found")
        if row["built_in"]:
            raise WorldValidationError("Built-in definitions are immutable; clone one first")
        name = str(values.get("name") or "").strip()
        if not name:
            raise WorldValidationError("Definition name is required")
        if kind == "skills":
            behavior = str(values.get("behavior"))
            if behavior not in {"free_move", "blue_gravity", "roll"}:
                raise WorldValidationError("Unsupported bullet-hell skill behavior")
            parameters = self._validate_parameters(behavior, values.get("parameters") or {})
            self.db.execute("UPDATE bullethell_skills SET name=?,behavior=?,parameters_json=?,version=version+1,updated_at=? WHERE id=?", (name, behavior, json.dumps(parameters), utc_now(), identifier))
        elif kind == "modes":
            movement = str(values.get("movement_skill_id") or "")
            allowed = list(dict.fromkeys(values.get("allowed_skill_ids", [])))
            known = {item["id"]: item for item in self.catalog()["skills"]}
            if movement not in known or known[movement]["behavior"] not in {"free_move", "blue_gravity"} or not set(allowed) <= set(known):
                raise WorldValidationError("Mode references invalid movement or allowed skills")
            if movement not in allowed:
                allowed.insert(0, movement)
            self.db.execute("UPDATE bullethell_modes SET name=?,movement_skill_id=?,allowed_skill_ids_json=?,parameters_json=?,version=version+1,updated_at=? WHERE id=?", (name, movement, json.dumps(allowed), json.dumps(values.get("parameters") or {}), utc_now(), identifier))
        else:
            phases = self._validate_phases(values.get("phases") or [])
            immunity = int(values.get("hit_immunity_ms", 500))
            if not 0 <= immunity <= 5000:
                raise WorldValidationError("Hit immunity must be between 0 and 5000 ms")
            self.db.execute("UPDATE bullethell_attacks SET name=?,ai_description=?,tags_json=?,uses_enemy_forced_mode=?,hit_immunity_ms=?,phases_json=?,version=version+1,updated_at=? WHERE id=?", (name, str(values.get("ai_description", ""))[:2000], json.dumps(values.get("tags") or []), int(bool(values.get("uses_enemy_forced_mode"))), immunity, json.dumps(phases), utc_now(), identifier))
        return next(item for item in self.catalog()[kind] if item["id"] == identifier)

    @staticmethod
    def _validate_parameters(behavior: str, values: dict[str, Any]) -> dict[str, Any]:
        bounds = {"speed": (.1, 5), "gravity": (.1, 5), "jump_strength": (.1, 5), "max_jump_hold_ms": (50, 1000), "duration_ms": (50, 1000), "cooldown_ms": (0, 5000), "green_shield": (0, 1)}
        result = {}
        for key, value in values.items():
            if key not in bounds or not bounds[key][0] <= float(value) <= bounds[key][1]:
                raise WorldValidationError(f"Invalid {behavior} parameter: {key}")
            result[key] = float(value)
        return result

    @staticmethod
    def _validate_phases(phases: list[Any]) -> list[dict[str, Any]]:
        if not isinstance(phases, list) or not 1 <= len(phases) <= 20:
            raise WorldValidationError("Attack requires between 1 and 20 phases")
        result = []
        for phase in phases:
            if not isinstance(phase, dict) or phase.get("type") not in {"particle_rain", "third_beam", "spear_burst"}:
                raise WorldValidationError("Unsupported bullet-hell phase")
            item = dict(phase)
            def number(key: str, default: float, low: float, high: float) -> float:
                try:
                    value = float(item.get(key, default))
                except (TypeError, ValueError) as exc:
                    raise WorldValidationError(f"Invalid {item['type']} phase value: {key}") from exc
                if not math.isfinite(value) or not low <= value <= high:
                    raise WorldValidationError(f"Invalid {item['type']} phase value: {key}")
                return value
            item["start_ms"] = number("start_ms", 0, 0, 5000)
            item["duration_ms"] = number("duration_ms", 5000, 1, 5000)
            item["damage_multiplier"] = number("damage_multiplier", 1, 0, 100)
            if item["type"] == "particle_rain":
                item["density"] = number("density", 12, 1, 60)
                item["radius"] = number("radius", .025, .005, .15)
                item["speed"] = number("speed", .34, .05, 2)
            elif item["type"] == "third_beam":
                item["repetitions"] = int(number("repetitions", 1, 1, 20))
                item["spacing_ms"] = number("spacing_ms", 1000, 100, 5000)
                item["telegraph_ms"] = number("telegraph_ms", 650, 100, 3000)
                item["active_ms"] = number("active_ms", 300, 50, 2000)
                if item.get("direction", "vertical") not in {"vertical", "horizontal"}:
                    raise WorldValidationError("Beam direction must be vertical or horizontal")
                item["direction"] = item.get("direction", "vertical")
            else:
                item["repetitions"] = int(number("repetitions", 8, 1, 40))
                item["spacing_ms"] = number("spacing_ms", 450, 100, 5000)
                item["telegraph_ms"] = number("telegraph_ms", 300, 50, 2000)
                item["speed"] = number("speed", .75, .1, 2)
                item["radius"] = number("radius", .035, .01, .12)
            result.append(item)
        return result

    def delete(self, kind: str, identifier: str) -> None:
        table = TABLES.get(kind)
        row = self.db.fetch_one(f"SELECT * FROM {table} WHERE id=?", (identifier,)) if table else None
        if not row:
            raise WorldValidationError("Bullet-hell definition not found")
        if row["built_in"]:
            raise WorldValidationError("Built-in definitions cannot be deleted")
        references = 0
        if kind == "skills":
            references += int((self.db.fetch_one("SELECT COUNT(*) n FROM project_bullethell_skills WHERE skill_id=?", (identifier,)) or {"n": 0})["n"])
            references += int((self.db.fetch_one("SELECT COUNT(*) n FROM bullethell_modes WHERE movement_skill_id=? OR allowed_skill_ids_json LIKE ?", (identifier, f'%"{identifier}"%')) or {"n": 0})["n"])
        elif kind == "modes":
            references += int((self.db.fetch_one("SELECT COUNT(*) n FROM project_bullethell_modes WHERE mode_id=?", (identifier,)) or {"n": 0})["n"])
            references += int((self.db.fetch_one("SELECT COUNT(*) n FROM project_bullethell_settings WHERE default_mode_id=?", (identifier,)) or {"n": 0})["n"])
        else:
            references += int((self.db.fetch_one("SELECT COUNT(*) n FROM project_bullethell_attacks WHERE attack_id=?", (identifier,)) or {"n": 0})["n"])
        references += int((self.db.fetch_one("SELECT COUNT(*) n FROM ability_definitions WHERE minigame_profile_json LIKE ?", (f'%"{identifier}"%',)) or {"n": 0})["n"])
        references += int((self.db.fetch_one("SELECT COUNT(*) n FROM world_events WHERE payload_json LIKE ?", (f'%"{identifier}"%',)) or {"n": 0})["n"])
        if references:
            raise WorldValidationError(f"Definition is still referenced in {references} place(s)")
        self.db.execute(f"DELETE FROM {table} WHERE id=?", (identifier,))

    def snapshot(self, project_id: str, attack_id: str, participant: dict[str, Any], enemy: dict[str, Any] | None) -> dict[str, Any]:
        settings = self.project_settings(project_id)
        if attack_id not in settings["allowed_attack_ids"]:
            raise WorldValidationError("Bullet-hell attack is not enabled for this project")
        catalog = self.catalog()
        attacks = {row["id"]: row for row in catalog["attacks"]}; modes = {row["id"]: row for row in catalog["modes"]}; skills = {row["id"]: row for row in catalog["skills"]}
        attack = attacks.get(attack_id)
        player_mode = participant.get("state", {}).get("bullethell_default_mode_id")
        forced = enemy.get("state", {}).get("bullethell_forced_mode_id") if enemy and attack and attack["uses_enemy_forced_mode"] else None
        mode_id = next((candidate for candidate in (forced, player_mode, settings.get("default_mode_id"), "builtin:base") if candidate in settings["allowed_mode_ids"] and candidate in modes), None)
        if not attack or not mode_id:
            raise WorldValidationError("Bullet-hell attack or resolved mode is unavailable to this project")
        direct = set(participant.get("state", {}).get("bullethell_skill_ids", []))
        owned = set(participant.get("state", {}).get("abilities", []))
        for row in self.db.fetch_all("SELECT ability_key,name,minigame_profile_json FROM ability_definitions WHERE project_id=?", (project_id,)):
            if {row["ability_key"], row["name"]} & owned:
                direct.update(_json(row["minigame_profile_json"], {}).get("bullethell_skill_ids", []))
        mode = modes[mode_id]
        if mode["movement_skill_id"] not in settings["allowed_skill_ids"]:
            raise WorldValidationError("The resolved mode's movement skill is not enabled for this project")
        permitted = set(mode["allowed_skill_ids"]) & set(settings["allowed_skill_ids"])
        effective = (direct & permitted) | {mode["movement_skill_id"]}
        return {"attack": attack, "mode": mode, "skills": [skills[value] for value in sorted(effective) if value in skills], "seed": random.SystemRandom().randrange(1, 2**31)}


def expand_hazards(attack: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    rng, hazards = random.Random(seed), []
    for phase_index, phase in enumerate(attack["phases"]):
        kind = phase["type"]
        if kind == "particle_rain":
            count = max(1, min(200, round(float(phase.get("density", 12)) * float(phase.get("duration_ms", 5000)) / 1000)))
            for index in range(count):
                hazards.append({"id": f"r{phase_index}:{index}", "type": kind, "x": rng.random(), "start_ms": float(phase.get("start_ms", 0)) + rng.random() * float(phase.get("duration_ms", 5000)), "speed": float(phase.get("speed", .34)), "radius": float(phase.get("radius", .025)), "damage_multiplier": float(phase.get("damage_multiplier", 1))})
        elif kind == "third_beam":
            repetitions = max(1, min(20, int(phase.get("repetitions", 1))))
            for index in range(repetitions):
                warning = float(phase.get("telegraph_ms", 650)); active = float(phase.get("active_ms", 300))
                telegraph = float(phase.get("start_ms", 0)) + index * float(phase.get("spacing_ms", 1000))
                hazards.append({"id": f"b{phase_index}:{index}", "type": kind, "lane": rng.randrange(3), "direction": phase.get("direction", "vertical"), "telegraph_start_ms": telegraph, "active_start_ms": telegraph + warning, "active_end_ms": telegraph + warning + active, "damage_multiplier": float(phase.get("damage_multiplier", 1))})
        else:
            repetitions = max(1, min(40, int(phase.get("repetitions", 8))))
            for index in range(repetitions):
                direction_index = rng.randrange(8)
                angle = direction_index * math.pi / 4
                telegraph = float(phase.get("start_ms", 0)) + index * float(phase.get("spacing_ms", 450))
                start = telegraph + float(phase.get("telegraph_ms", 300))
                hazards.append({"id": f"s{phase_index}:{index}", "type": kind, "source_x": math.cos(angle), "source_y": math.sin(angle), "telegraph_start_ms": telegraph, "start_ms": start, "speed": float(phase.get("speed", .75)), "radius": float(phase.get("radius", .035)), "damage_multiplier": float(phase.get("damage_multiplier", 1))})
    return hazards
