from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from app.database import Database, new_id, utc_now


DEFAULT_PHASES = (("Morning", 180), ("Day", 180), ("Noon", 120), ("Afternoon", 360), ("Night", 600))


def _json(value: str | None) -> list[Any]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


class EnvironmentService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.sound_root = Path(__file__).resolve().parents[3] / "public" / "sounds"

    def ensure_project(self, project_id: str) -> None:
        if self.db.fetch_one("SELECT project_id FROM project_environment_settings WHERE project_id=?", (project_id,)):
            return
        now, weather_id = utc_now(), new_id()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO weather_definitions(id,project_id,name,description,created_at,updated_at) VALUES(?,?, 'Sunny','Clear, neutral weather with no environmental effects.',?,?)",
                (weather_id, project_id, now, now),
            )
            connection.execute(
                "INSERT INTO project_environment_settings(project_id,enabled,initial_weather_id,updated_at) VALUES(?,1,?,?)",
                (project_id, weather_id, now),
            )
            for position, (name, duration) in enumerate(DEFAULT_PHASES):
                connection.execute(
                    "INSERT INTO time_phases(id,project_id,name,duration_minutes,position) VALUES(?,?,?,?,?)",
                    (new_id(), project_id, name, duration, position),
                )

    def index_sounds(self, project_id: str) -> None:
        now = utc_now()
        present: set[str] = set()
        if self.sound_root.is_dir():
            for path in self.sound_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".mp3", ".wav", ".ogg", ".m4a"}:
                    continue
                relative = path.relative_to(self.sound_root).as_posix()
                present.add(relative)
                row = self.db.fetch_one(
                    "SELECT id FROM ambient_variants WHERE project_id=? AND source_path=? AND playback_rate=1 AND derived=0",
                    (project_id, relative),
                )
                if row:
                    self.db.execute("UPDATE ambient_variants SET available=1,updated_at=? WHERE id=?", (now, row["id"]))
                else:
                    label = path.stem.replace("-", " ").replace("_", " ").title()
                    tags = [part.lower() for part in path.relative_to(self.sound_root).parts[:-1]]
                    self.db.execute(
                        "INSERT INTO ambient_variants(id,project_id,source_path,label,tags_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (new_id(), project_id, relative, label, json.dumps(tags), now, now),
                    )
        rows = self.db.fetch_all("SELECT id,source_path FROM ambient_variants WHERE project_id=?", (project_id,))
        for row in rows:
            self.db.execute("UPDATE ambient_variants SET available=?,updated_at=? WHERE id=?", (int(row["source_path"] in present), now, row["id"]))

    def settings(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        settings = self.db.fetch_one("SELECT * FROM project_environment_settings WHERE project_id=?", (project_id,)) or {}
        for key in ("enabled", "ai_create_locations", "ai_propose_weather", "auto_generate_backgrounds"):
            settings[key] = bool(settings.get(key))
        weather = self.db.fetch_all("SELECT * FROM weather_definitions WHERE project_id=? ORDER BY name COLLATE NOCASE", (project_id,))
        transitions = self.db.fetch_all("SELECT source_weather_id,target_weather_id FROM weather_transitions WHERE project_id=?", (project_id,))
        outgoing: dict[str, list[str]] = {}
        for edge in transitions:
            outgoing.setdefault(edge["source_weather_id"], []).append(edge["target_weather_id"])
        for item in weather:
            item["tags"] = _json(item.pop("tags_json", "[]"))
            item["image_tags"] = _json(item.pop("image_tags_json", "[]"))
            item["enabled"] = bool(item["enabled"])
            item["transition_ids"] = outgoing.get(item["id"], [])
        phases = self.db.fetch_all("SELECT * FROM time_phases WHERE project_id=? ORDER BY position", (project_id,))
        for phase in phases:
            phase["enabled"] = bool(phase["enabled"])
        settings["weather"] = weather
        settings["time_phases"] = phases
        return settings

    def phase(self, project_id: str, elapsed_minutes: int) -> dict[str, Any] | None:
        phases = self.db.fetch_all("SELECT id,name,duration_minutes,position FROM time_phases WHERE project_id=? AND enabled=1 ORDER BY position", (project_id,))
        total = sum(int(item["duration_minutes"]) for item in phases)
        if not phases or total <= 0:
            return None
        offset = max(0, int(elapsed_minutes)) % total
        for item in phases:
            duration = int(item["duration_minutes"])
            if offset < duration:
                return {**item, "minute": offset, "cycle_minutes": total}
            offset -= duration
        return phases[0]

    def _location(self, projection: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        focus_id = projection.get("focused_character_id")
        focus = projection["entities"].get(focus_id)
        if not focus or focus.get("kind") != "character" or not focus.get("state", {}).get("player_controlled"):
            focus = next((item for item in projection["entities"].values() if item.get("kind") == "character" and item.get("state", {}).get("player_controlled")), None)
        location = projection["entities"].get((focus or {}).get("state", {}).get("current_location_id"))
        return focus, location if location and location.get("kind") == "location" else None

    def _weather(self, project_id: str, projection: dict[str, Any]) -> dict[str, Any] | None:
        settings = self.db.fetch_one("SELECT initial_weather_id FROM project_environment_settings WHERE project_id=?", (project_id,)) or {}
        weather_id = projection.get("current_weather_id") or settings.get("initial_weather_id")
        row = self.db.fetch_one("SELECT id,name,description,tags_json,image_tags_json FROM weather_definitions WHERE id=? AND project_id=? AND enabled=1", (weather_id, project_id))
        if not row:
            row = self.db.fetch_one("SELECT id,name,description,tags_json,image_tags_json FROM weather_definitions WHERE project_id=? AND enabled=1 ORDER BY name LIMIT 1", (project_id,))
        if row:
            row["tags"], row["image_tags"] = _json(row.pop("tags_json")), _json(row.pop("image_tags_json"))
        return row

    def _ancestry(self, projection: dict[str, Any], location: dict[str, Any] | None) -> list[dict[str, str]]:
        result, seen = [], set()
        current = location
        while current and current["id"] not in seen:
            seen.add(current["id"])
            result.append({"id": current["id"], "name": current["name"]})
            current = projection["entities"].get(current.get("state", {}).get("parent_location_id"))
        return list(reversed(result))

    def resolved_ambient(self, project_id: str, projection: dict[str, Any], location: dict[str, Any] | None, weather: dict[str, Any] | None, phase: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not location:
            return []
        state = location.get("state", {})
        exposure = str(state.get("exposure") or "outdoor")
        tags = {str(value).casefold() for value in [*location.get("tags", []), *state.get("tags", []), *state.get("image_tags", [])]}
        action = str(projection.get("player_action") or "standing").casefold()
        assignments = self.db.fetch_all("SELECT * FROM ambient_assignments WHERE project_id=?", (project_id,))
        matched: set[str] = set()
        for rule in assignments:
            owner_type, owner_id = rule["owner_type"], str(rule["owner_id"])
            if owner_type == "location":
                owner_match = owner_id == location["id"]
            elif exposure == "isolated" and owner_type in {"weather", "time"}:
                owner_match = False
            elif owner_type == "weather":
                owner_match = bool(weather and owner_id == weather["id"])
            elif owner_type == "time":
                owner_match = bool(phase and owner_id == phase["id"])
            else:
                owner_match = owner_type == "action" and owner_id.casefold() == action
            selector = rule["selector_type"]
            selector_match = selector == "default" or selector == exposure or (selector == "tag" and str(rule.get("selector_value") or "").casefold() in tags)
            condition_match = (not rule.get("weather_id") or (weather and rule["weather_id"] == weather["id"])) and (not rule.get("time_phase_id") or (phase and rule["time_phase_id"] == phase["id"]))
            if owner_match and selector_match and condition_match:
                matched.add(rule["variant_id"])
        if not matched:
            return []
        placeholders = ",".join("?" for _ in matched)
        rows = self.db.fetch_all(f"SELECT id,source_path,label,playback_rate,default_gain,tags_json FROM ambient_variants WHERE id IN ({placeholders}) AND enabled=1 AND available=1", tuple(matched))
        for row in rows:
            row["url"] = "/sounds/" + row["source_path"]
            row["tags"] = _json(row.pop("tags_json"))
        return rows

    def ambient_sets(self, project_id: str, owner_type: str, owner_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT selector_type,selector_value,weather_id,time_phase_id,variant_id FROM ambient_assignments "
            "WHERE project_id=? AND owner_type=? AND owner_id=? ORDER BY id",
            (project_id, owner_type, owner_id),
        )
        grouped: dict[tuple[str, str | None, str | None, str | None], list[str]] = {}
        for row in rows:
            key = (row["selector_type"], row.get("selector_value"), row.get("weather_id"), row.get("time_phase_id"))
            grouped.setdefault(key, []).append(row["variant_id"])
        return [
            {"selector_type": key[0], "selector_value": key[1], "weather_id": key[2], "time_phase_id": key[3], "variant_ids": list(dict.fromkeys(values))}
            for key, values in grouped.items()
        ]

    def replace_ambient_sets(self, project_id: str, owner_type: str, owner_id: str, sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if owner_type not in {"weather", "time", "location", "action"}:
            raise ValueError("Unsupported ambient owner")
        if owner_type == "weather":
            owner = self.db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=?", (owner_id, project_id))
        elif owner_type == "time":
            owner = self.db.fetch_one("SELECT id FROM time_phases WHERE id=? AND project_id=?", (owner_id, project_id))
        elif owner_type == "location":
            owner = self.db.fetch_one("SELECT id FROM world_entities WHERE id=? AND project_id=? AND kind='location'", (owner_id, project_id))
        else:
            owner = {"id": owner_id} if owner_id.strip() else None
        if not owner:
            raise ValueError("Ambient owner not found")
        variants = {row["id"] for row in self.db.fetch_all("SELECT id FROM ambient_variants WHERE project_id=?", (project_id,))}
        weather = {row["id"] for row in self.db.fetch_all("SELECT id FROM weather_definitions WHERE project_id=?", (project_id,))}
        phases = {row["id"] for row in self.db.fetch_all("SELECT id FROM time_phases WHERE project_id=?", (project_id,))}
        normalized: dict[tuple[str, str | None, str | None, str | None], set[str]] = {}
        for sound_set in sets:
            selector = str(sound_set.get("selector_type") or "default")
            selector_value = str(sound_set.get("selector_value") or "").strip() or None
            weather_id, phase_id = sound_set.get("weather_id"), sound_set.get("time_phase_id")
            if selector not in {"default", "indoor", "outdoor", "isolated", "tag"}:
                raise ValueError("Invalid ambient selector")
            if selector == "tag" and not selector_value:
                raise ValueError("Tag selectors require a tag")
            if selector != "tag":
                selector_value = None
            if weather_id and weather_id not in weather:
                raise ValueError("Weather condition not found")
            if phase_id and phase_id not in phases:
                raise ValueError("Time condition not found")
            selected = set(sound_set.get("variant_ids") or [])
            if not selected <= variants:
                raise ValueError("Ambient variant not found")
            normalized.setdefault((selector, selector_value, weather_id, phase_id), set()).update(selected)
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM ambient_assignments WHERE project_id=? AND owner_type=? AND owner_id=?", (project_id, owner_type, owner_id))
            for key, variant_ids in normalized.items():
                for variant_id in sorted(variant_ids):
                    connection.execute(
                        "INSERT INTO ambient_assignments(id,project_id,owner_type,owner_id,selector_type,selector_value,weather_id,time_phase_id,variant_id) VALUES(?,?,?,?,?,?,?,?,?)",
                        (new_id(), project_id, owner_type, owner_id, key[0], key[1], key[2], key[3], variant_id),
                    )
        return self.ambient_sets(project_id, owner_type, owner_id)

    @staticmethod
    def location_enabled(projection: dict[str, Any], location_id: str | None) -> bool:
        seen: set[str] = set()
        current = projection.get("entities", {}).get(location_id)
        while current and current.get("kind") == "location" and current["id"] not in seen:
            seen.add(current["id"])
            if not current.get("state", {}).get("enabled", True):
                return False
            current = projection["entities"].get(current.get("state", {}).get("parent_location_id"))
        return True

    def composed_background_prompt(self, project_id: str, location: dict[str, Any], weather_id: str | None, phase_id: str | None) -> str:
        state = location.get("state", {})
        weather = self.db.fetch_one("SELECT description,imagegen_description,image_tags_json FROM weather_definitions WHERE id=? AND project_id=?", (weather_id, project_id)) if weather_id else None
        phase = self.db.fetch_one("SELECT description,imagegen_description FROM time_phases WHERE id=? AND project_id=?", (phase_id, project_id)) if phase_id else None
        pieces = [
            location.get("name", ""), state.get("imagegen_description") or state.get("description") or "environment background",
            (weather or {}).get("imagegen_description") or (weather or {}).get("description"),
            (phase or {}).get("imagegen_description") or (phase or {}).get("description"),
            *map(str, state.get("image_tags", [])), *map(str, _json((weather or {}).get("image_tags_json"))),
        ]
        return ", ".join(str(value).strip() for value in pieces if value and str(value).strip())

    def background(self, project_id: str, location_id: str | None, weather_id: str | None, phase_id: str | None) -> dict[str, Any] | None:
        if not location_id:
            return None
        rows = self.db.fetch_all(
            "SELECT b.*,m.file_path,m.status FROM location_backgrounds b JOIN entity_media_assets m ON m.id=b.media_asset_id WHERE b.project_id=? AND b.location_id=? AND m.status='generated' AND m.file_path IS NOT NULL ORDER BY b.position,b.created_at",
            (project_id, location_id),
        )
        def score(item: dict[str, Any]) -> int:
            if item.get("weather_id") == weather_id and item.get("time_phase_id") == phase_id and item.get("weather_id") and item.get("time_phase_id"): return 4
            if item.get("weather_id") == weather_id and item.get("weather_id") and not item.get("time_phase_id"): return 3
            if item.get("time_phase_id") == phase_id and item.get("time_phase_id") and not item.get("weather_id"): return 2
            if not item.get("weather_id") and not item.get("time_phase_id"): return 1
            return 0
        candidates = [item for item in rows if score(item)]
        if not candidates:
            return None
        selected = max(candidates, key=score)
        return {"id": selected["id"], "url": "/media/" + selected["file_path"], "weather_id": selected.get("weather_id"), "time_phase_id": selected.get("time_phase_id")}

    def scene(self, project_id: str, projection: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings(project_id)
        if not settings["enabled"]:
            return {"enabled": False, "revision": settings.get("revision", 1), "ambient": []}
        focus, location = self._location(projection)
        weather, phase = self._weather(project_id, projection), self.phase(project_id, projection.get("elapsed_minutes", 0))
        next_ids = [row["target_weather_id"] for row in self.db.fetch_all("SELECT target_weather_id FROM weather_transitions WHERE project_id=? AND source_weather_id=?", (project_id, (weather or {}).get("id")))]
        next_weather = self.db.fetch_all("SELECT id,name FROM weather_definitions WHERE project_id=? AND enabled=1 AND id IN (SELECT target_weather_id FROM weather_transitions WHERE project_id=? AND source_weather_id=?)", (project_id, project_id, (weather or {}).get("id")))
        location_data = None
        if location:
            state = location.get("state", {})
            location_data = {"id": location["id"], "name": location["name"], "description": state.get("description") or state.get("summary") or "", "tags": location.get("tags", []), "exposure": state.get("exposure", "outdoor"), "parent_location_id": state.get("parent_location_id")}
        return {
            "enabled": True, "revision": settings.get("revision", 1),
            "focused_character": {"id": focus["id"], "name": focus["name"]} if focus else None,
            "player_action": projection.get("player_action") or "standing", "location": location_data,
            "location_ancestry": self._ancestry(projection, location), "weather": weather, "time_phase": phase,
            "allowed_next_weather": next_weather, "background": self.background(project_id, (location or {}).get("id"), (weather or {}).get("id"), (phase or {}).get("id")),
            "ambient": self.resolved_ambient(project_id, projection, location, weather, phase),
        }

    def map_layer(self, project_id: str, projection: dict[str, Any], parent_id: str | None, *, admin: bool) -> dict[str, Any]:
        settings = self.db.fetch_one("SELECT enabled FROM project_environment_settings WHERE project_id=?", (project_id,))
        if not admin and settings and not settings["enabled"]:
            return {"enabled": False, "parent": None, "breadcrumbs": [], "locations": [], "routes": []}
        locations = []
        for item in projection["entities"].values():
            if item.get("kind") != "location" or item.get("state", {}).get("archived"):
                continue
            state = item.get("state", {})
            if state.get("parent_location_id") != parent_id:
                continue
            effectively_enabled = self.location_enabled(projection, item["id"])
            if not admin and (not effectively_enabled or not state.get("discovered", not state.get("random_encounter", False))):
                continue
            locations.append({"id": item["id"], "name": item["name"], "x": state.get("x"), "y": state.get("y"), "has_children": any(child.get("kind") == "location" and child.get("state", {}).get("parent_location_id") == item["id"] for child in projection["entities"].values()), "exposure": state.get("exposure", "outdoor"), "enabled": bool(state.get("enabled", True)), "effectively_enabled": effectively_enabled})
        locations.sort(key=lambda item: item["name"].casefold())
        occupied: set[tuple[int, int]] = set()
        for index, item in enumerate(locations):
            x, y = item.get("x"), item.get("y")
            cell = (int(x), int(y)) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else (index % 4, index // 4)
            while cell in occupied:
                cell = ((cell[0] + 1) % 4, cell[1] + (1 if cell[0] == 3 else 0))
            occupied.add(cell); item["x"], item["y"] = cell
        visible = {item["id"] for item in locations}
        routes = [{"id": relation["id"], "source_id": relation["source_id"], "target_id": relation["target_id"]} for relation in projection["relations"].values() if relation.get("relation") == "route" and relation.get("source_id") in visible and relation.get("target_id") in visible]
        parent = projection["entities"].get(parent_id) if parent_id else None
        return {"parent": {"id": parent["id"], "name": parent["name"], "parent_id": parent.get("state", {}).get("parent_location_id")} if parent else None, "breadcrumbs": self._ancestry(projection, parent), "locations": locations, "routes": routes}

    def user_preferences(self, user_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT enabled,master_volume FROM user_ambient_preferences WHERE user_id=?", (user_id,))
        return {"enabled": bool(row["enabled"]) if row else True, "master_volume": float(row["master_volume"]) if row else 1.0}
