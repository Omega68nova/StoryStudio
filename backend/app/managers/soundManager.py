from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.data.dataProvider import DataProvider


def _json_list(value: str | None) -> list[Any]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


class SoundManager:
    """Owns ambient/environment sound discovery and resolution."""

    def __init__(
        self,
        db: Any,
        sound_root: Path | None = None,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.sound
        self.sound_root = sound_root or Path(__file__).resolve().parents[3] / "public" / "sounds"

    def index_sources(self, project_id: str) -> None:
        present: set[str] = set()
        if self.sound_root.is_dir():
            for path in self.sound_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".mp3", ".wav", ".ogg", ".m4a"}:
                    continue
                relative = path.relative_to(self.sound_root).as_posix()
                present.add(relative)
                row = self.repo.source_variant(project_id, relative)
                if row:
                    self.repo.set_available(row["id"], True)
                    continue
                label = path.stem.replace("-", " ").replace("_", " ").title()
                tags = [part.lower() for part in path.relative_to(self.sound_root).parts[:-1]]
                self.repo.create_source_variant(
                    project_id=project_id,
                    source_path=relative,
                    label=label,
                    tags=tags,
                )
        for row in self.repo.project_sources(project_id):
            self.repo.set_available(row["id"], row["source_path"] in present)

    def resolve_ambient(
        self,
        *,
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

        for rule in self.repo.assignments(project_id):
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
                owner_match = owner_type == "action" and owner_id.casefold() == action

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
                (not rule.get("weather_id") or (weather and rule["weather_id"] == weather["id"]))
                and (not rule.get("time_phase_id") or (phase and rule["time_phase_id"] == phase["id"]))
            )
            if owner_match and selector_match and condition_match:
                matched.add(rule["variant_id"])

        rows = self.repo.enabled_variants(matched)
        for row in rows:
            row["url"] = "/sounds/" + row["source_path"]
            row["tags"] = _json_list(row.pop("tags_json", "[]"))
        return rows

    def list_variants(self, project_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh:
            self.index_sources(project_id)
        rows = self.repo.variants(project_id)
        for row in rows:
            row["tags"] = _json_list(row.pop("tags_json", "[]"))
            row["enabled"] = bool(row["enabled"])
            row["available"] = bool(row["available"])
            row["url"] = "/sounds/" + row["source_path"]
        return rows

    def ambient_sets(self, project_id: str, owner_type: str, owner_id: str) -> list[dict[str, Any]]:
        rows = self.repo.owner_assignments(project_id, owner_type, owner_id)
        grouped: dict[tuple[str, str | None, str | None, str | None], list[str]] = {}
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

    def user_preferences(self, user_id: str) -> dict[str, Any]:
        row = self.repo.user_preferences(user_id)
        return {
            "enabled": bool(row["enabled"]) if row else True,
            "master_volume": float(row["master_volume"]) if row else 1.0,
        }
