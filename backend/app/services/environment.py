from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.data.dataProvider import DataProvider
from app.database import Database
from app.domain.adapters import entity_from_projection
from app.domain.world import Character, Location, Weather


def _json(value: str | None) -> list[Any]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


class EnvironmentService:
    def __init__(
        self,
        db: Database,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.environment
        self.sound_repo = self.data.sound
        self.sound_root = Path(__file__).resolve().parents[3] / "public" / "sounds"

    def ensure_project(self, project_id: str) -> None:
        self.repo.ensure_project(project_id)

    def index_sounds(self, project_id: str) -> None:
        present: set[str] = set()
        if self.sound_root.is_dir():
            for path in self.sound_root.rglob("*"):
                if (
                    not path.is_file()
                    or path.suffix.lower() not in {".mp3", ".wav", ".ogg", ".m4a"}
                ):
                    continue
                relative = path.relative_to(self.sound_root).as_posix()
                present.add(relative)
                row = self.sound_repo.source_variant(project_id, relative)
                if row:
                    self.sound_repo.set_available(row["id"], True)
                else:
                    self.sound_repo.create_source_variant(
                        project_id=project_id,
                        source_path=relative,
                        label=path.stem.replace("-", " ").replace("_", " ").title(),
                        tags=[
                            part.lower()
                            for part in path.relative_to(self.sound_root).parts[:-1]
                        ],
                    )
        for row in self.sound_repo.project_sources(project_id):
            self.sound_repo.set_available(
                row["id"],
                row["source_path"] in present,
            )

    def settings(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        settings = self.repo.settings_row(project_id)
        for key in (
            "enabled",
            "ai_create_locations",
            "ai_propose_weather",
            "auto_generate_backgrounds",
        ):
            settings[key] = bool(settings.get(key))

        weather = self.repo.weather_definitions(project_id)
        transitions = self.repo.weather_transitions(project_id)
        outgoing: dict[str, list[str]] = {}
        for edge in transitions:
            outgoing.setdefault(edge["source_weather_id"], []).append(
                edge["target_weather_id"]
            )
        for item in weather:
            item["tags"] = _json(item.pop("tags_json", "[]"))
            item["image_tags"] = _json(item.pop("image_tags_json", "[]"))
            item["enabled"] = bool(item["enabled"])
            item["transition_ids"] = outgoing.get(item["id"], [])

        phases = self.repo.phases(project_id)
        for phase in phases:
            phase["enabled"] = bool(phase["enabled"])

        settings["weather"] = weather
        settings["time_phases"] = phases
        return settings

    def phase(self, project_id: str, elapsed_minutes: int) -> dict[str, Any] | None:
        phases = self.repo.phases(project_id, enabled_only=True)
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

    def _location(
        self,
        projection: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        focus_id = projection.get("focused_character_id")
        focus = projection["entities"].get(focus_id)
        if (
            not focus
            or focus.get("kind") != "character"
            or not focus.get("state", {}).get("player_controlled")
        ):
            focus = next(
                (
                    item
                    for item in projection["entities"].values()
                    if item.get("kind") == "character"
                    and item.get("state", {}).get("player_controlled")
                ),
                None,
            )
        location = projection["entities"].get(
            (focus or {}).get("state", {}).get("current_location_id")
        )
        return focus, location if location and location.get("kind") == "location" else None

    def location_models(
        self,
        projection: dict[str, Any],
    ) -> tuple[Character | None, Location | None]:
        """Resolve the scene focus and location as typed read-only views."""
        focus, location = self._location(projection)
        typed_focus = entity_from_projection(focus) if focus else None
        typed_location = entity_from_projection(location) if location else None
        return (
            typed_focus if isinstance(typed_focus, Character) else None,
            typed_location if isinstance(typed_location, Location) else None,
        )

    def _weather(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> dict[str, Any] | None:
        weather_id = (
            projection.get("current_weather_id")
            or self.repo.initial_weather_id(project_id)
        )
        row = self.repo.weather(project_id, weather_id)
        if row:
            row["tags"] = _json(row.pop("tags_json"))
            row["image_tags"] = _json(row.pop("image_tags_json"))
        return row

    @staticmethod
    def weather_model(
        project_id: str,
        weather: dict[str, Any] | None,
    ) -> Weather | None:
        """Create a typed view while preserving the existing scene payload."""
        if not weather:
            return None
        return Weather.model_validate({
            **weather,
            "project_id": project_id,
            "enabled": bool(weather.get("enabled", True)),
        })

    def _ancestry(
        self,
        projection: dict[str, Any],
        location: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        current = location
        while current and current["id"] not in seen:
            seen.add(current["id"])
            result.append({"id": current["id"], "name": current["name"]})
            current = projection["entities"].get(
                current.get("state", {}).get("parent_location_id")
            )
        return list(reversed(result))

    def resolved_ambient(
        self,
        project_id: str,
        projection: dict[str, Any],
        location: dict[str, Any] | None,
        weather: dict[str, Any] | None,
        phase: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not location:
            return []
        state = location.get("state", {})
        exposure = str(state.get("exposure") or "outdoor")
        tags = {
            str(value).casefold()
            for value in [
                *location.get("tags", []),
                *state.get("tags", []),
                *state.get("image_tags", []),
            ]
        }
        action = str(projection.get("player_action") or "standing").casefold()
        matched: set[str] = set()

        for rule in self.repo.ambient_assignments(project_id):
            owner_type = rule["owner_type"]
            owner_id = str(rule["owner_id"])
            if owner_type == "location":
                owner_match = owner_id == location["id"]
            elif exposure == "isolated" and owner_type in {"weather", "time"}:
                owner_match = False
            elif owner_type == "weather":
                owner_match = bool(weather and owner_id == weather["id"])
            elif owner_type == "time":
                owner_match = bool(phase and owner_id == phase["id"])
            else:
                owner_match = (
                    owner_type == "action"
                    and owner_id.casefold() == action
                )

            selector = rule["selector_type"]
            selector_match = (
                selector == "default"
                or selector == exposure
                or (
                    selector == "tag"
                    and str(rule.get("selector_value") or "").casefold() in tags
                )
            )
            condition_match = (
                (
                    not rule.get("weather_id")
                    or (weather and rule["weather_id"] == weather["id"])
                )
                and (
                    not rule.get("time_phase_id")
                    or (phase and rule["time_phase_id"] == phase["id"])
                )
            )
            if owner_match and selector_match and condition_match:
                matched.add(rule["variant_id"])

        rows = self.sound_repo.enabled_variants(matched)
        for row in rows:
            row["url"] = "/sounds/" + row["source_path"]
            row["tags"] = _json(row.pop("tags_json"))
        return rows

    def ambient_sets(
        self,
        project_id: str,
        owner_type: str,
        owner_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.repo.ambient_assignments(project_id, owner_type, owner_id)
        grouped: dict[
            tuple[str, str | None, str | None, str | None],
            list[str],
        ] = {}
        for row in rows:
            key = (
                row["selector_type"],
                row.get("selector_value"),
                row.get("weather_id"),
                row.get("time_phase_id"),
            )
            grouped.setdefault(key, []).append(row["variant_id"])
        return [
            {
                "selector_type": key[0],
                "selector_value": key[1],
                "weather_id": key[2],
                "time_phase_id": key[3],
                "variant_ids": list(dict.fromkeys(values)),
            }
            for key, values in grouped.items()
        ]

    def replace_ambient_sets(
        self,
        project_id: str,
        owner_type: str,
        owner_id: str,
        sets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if owner_type not in {"weather", "time", "location", "action"}:
            raise ValueError("Unsupported ambient owner")
        if not self.repo.owner_exists(project_id, owner_type, owner_id):
            raise ValueError("Ambient owner not found")

        variants = self.repo.variant_ids(project_id)
        weather = self.repo.weather_ids(project_id)
        phases = self.repo.phase_ids(project_id)
        normalized: dict[
            tuple[str, str | None, str | None, str | None],
            set[str],
        ] = {}

        for sound_set in sets:
            selector = str(sound_set.get("selector_type") or "default")
            selector_value = (
                str(sound_set.get("selector_value") or "").strip() or None
            )
            weather_id = sound_set.get("weather_id")
            phase_id = sound_set.get("time_phase_id")

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

            normalized.setdefault(
                (selector, selector_value, weather_id, phase_id),
                set(),
            ).update(selected)

        self.repo.replace_ambient_assignments(
            project_id=project_id,
            owner_type=owner_type,
            owner_id=owner_id,
            normalized=normalized,
        )
        return self.ambient_sets(project_id, owner_type, owner_id)

    @staticmethod
    def location_enabled(
        projection: dict[str, Any],
        location_id: str | None,
    ) -> bool:
        seen: set[str] = set()
        current = projection.get("entities", {}).get(location_id)
        while (
            current
            and current.get("kind") == "location"
            and current["id"] not in seen
        ):
            seen.add(current["id"])
            if not current.get("state", {}).get("enabled", True):
                return False
            current = projection["entities"].get(
                current.get("state", {}).get("parent_location_id")
            )
        return True

    def composed_background_prompt(
        self,
        project_id: str,
        location: dict[str, Any],
        weather_id: str | None,
        phase_id: str | None,
    ) -> str:
        state = location.get("state", {})
        weather = self.repo.prompt_weather(project_id, weather_id)
        phase = self.repo.prompt_phase(project_id, phase_id)
        pieces = [
            location.get("name", ""),
            state.get("imagegen_description")
            or state.get("description")
            or "environment background",
            (weather or {}).get("imagegen_description")
            or (weather or {}).get("description"),
            (phase or {}).get("imagegen_description")
            or (phase or {}).get("description"),
            *map(str, state.get("image_tags", [])),
            *map(str, _json((weather or {}).get("image_tags_json"))),
        ]
        return ", ".join(
            str(value).strip()
            for value in pieces
            if value and str(value).strip()
        )

    def background(
        self,
        project_id: str,
        location_id: str | None,
        weather_id: str | None,
        phase_id: str | None,
    ) -> dict[str, Any] | None:
        if not location_id:
            return None
        rows = self.repo.backgrounds(project_id, location_id)

        def score(item: dict[str, Any]) -> int:
            if (
                item.get("weather_id") == weather_id
                and item.get("time_phase_id") == phase_id
                and item.get("weather_id")
                and item.get("time_phase_id")
            ):
                return 4
            if (
                item.get("weather_id") == weather_id
                and item.get("weather_id")
                and not item.get("time_phase_id")
            ):
                return 3
            if (
                item.get("time_phase_id") == phase_id
                and item.get("time_phase_id")
                and not item.get("weather_id")
            ):
                return 2
            if not item.get("weather_id") and not item.get("time_phase_id"):
                return 1
            return 0

        candidates = [item for item in rows if score(item)]
        if not candidates:
            return None
        selected = max(candidates, key=score)
        return {
            "id": selected["id"],
            "url": "/media/" + selected["file_path"],
            "weather_id": selected.get("weather_id"),
            "time_phase_id": selected.get("time_phase_id"),
        }

    def scene(
        self,
        project_id: str,
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        settings = self.settings(project_id)
        if not settings["enabled"]:
            return {
                "enabled": False,
                "revision": settings.get("revision", 1),
                "ambient": [],
            }

        focus_model, location_model = self.location_models(projection)
        location = (
            projection["entities"].get(location_model.id)
            if location_model else None
        )
        weather = self._weather(project_id, projection)
        weather_model = self.weather_model(project_id, weather)
        phase = self.phase(project_id, projection.get("elapsed_minutes", 0))
        next_weather = self.repo.allowed_next_weather(
            project_id,
            weather_model.id if weather_model else None,
        )

        location_data = None
        if location_model:
            state = location_model.state
            location_data = {
                "id": location_model.id,
                "name": location_model.name,
                "description": (
                    state.description
                    or str(getattr(state, "summary", "") or "")
                ),
                "tags": location_model.tags,
                "exposure": state.exposure,
                "parent_location_id": state.parent_location_id,
            }

        return {
            "enabled": True,
            "revision": settings.get("revision", 1),
            "focused_character": (
                {"id": focus_model.id, "name": focus_model.name}
                if focus_model else None
            ),
            "player_action": projection.get("player_action") or "standing",
            "location": location_data,
            "location_ancestry": self._ancestry(projection, location),
            "weather": weather,
            "time_phase": phase,
            "allowed_next_weather": next_weather,
            "background": self.background(
                project_id,
                location_model.id if location_model else None,
                weather_model.id if weather_model else None,
                (phase or {}).get("id"),
            ),
            "ambient": self.resolved_ambient(
                project_id,
                projection,
                location,
                weather,
                phase,
            ),
        }

    def map_layer(
        self,
        project_id: str,
        projection: dict[str, Any],
        parent_id: str | None,
        *,
        admin: bool,
    ) -> dict[str, Any]:
        if not admin and not self.repo.enabled(project_id):
            return {
                "enabled": False,
                "parent": None,
                "breadcrumbs": [],
                "locations": [],
                "routes": [],
            }

        locations: list[dict[str, Any]] = []
        for item in projection["entities"].values():
            if (
                item.get("kind") != "location"
                or item.get("state", {}).get("archived")
            ):
                continue
            state = item.get("state", {})
            if state.get("parent_location_id") != parent_id:
                continue
            effectively_enabled = self.location_enabled(projection, item["id"])
            if (
                not admin
                and (
                    not effectively_enabled
                    or not state.get(
                        "discovered",
                        not state.get("random_encounter", False),
                    )
                )
            ):
                continue
            locations.append({
                "id": item["id"],
                "name": item["name"],
                "x": state.get("x"),
                "y": state.get("y"),
                "has_children": any(
                    child.get("kind") == "location"
                    and child.get("state", {}).get("parent_location_id") == item["id"]
                    for child in projection["entities"].values()
                ),
                "exposure": state.get("exposure", "outdoor"),
                "enabled": bool(state.get("enabled", True)),
                "effectively_enabled": effectively_enabled,
            })

        locations.sort(key=lambda item: item["name"].casefold())
        occupied: set[tuple[int, int]] = set()
        for index, item in enumerate(locations):
            x, y = item.get("x"), item.get("y")
            cell = (
                (int(x), int(y))
                if isinstance(x, (int, float)) and isinstance(y, (int, float))
                else (index % 4, index // 4)
            )
            while cell in occupied:
                cell = (
                    (cell[0] + 1) % 4,
                    cell[1] + (1 if cell[0] == 3 else 0),
                )
            occupied.add(cell)
            item["x"], item["y"] = cell

        visible = {item["id"] for item in locations}
        routes = [
            {
                "id": relation["id"],
                "source_id": relation["source_id"],
                "target_id": relation["target_id"],
            }
            for relation in projection["relations"].values()
            if relation.get("relation") == "route"
            and relation.get("source_id") in visible
            and relation.get("target_id") in visible
        ]
        parent = projection["entities"].get(parent_id) if parent_id else None
        return {
            "parent": (
                {
                    "id": parent["id"],
                    "name": parent["name"],
                    "parent_id": parent.get("state", {}).get("parent_location_id"),
                }
                if parent else None
            ),
            "breadcrumbs": self._ancestry(projection, parent),
            "locations": locations,
            "routes": routes,
        }

    def user_preferences(self, user_id: str) -> dict[str, Any]:
        row = self.repo.user_preferences(user_id)
        return {
            "enabled": bool(row["enabled"]) if row else True,
            "master_volume": float(row["master_volume"]) if row else 1.0,
        }
