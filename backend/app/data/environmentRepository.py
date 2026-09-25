from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now

DEFAULT_PHASES = (
    ("Morning", 180), ("Day", 180), ("Noon", 120),
    ("Afternoon", 360), ("Night", 600),
)


class EnvironmentRepository(BaseRepository):
    def ensure_project(self, project_id: str) -> None:
        if self.db.fetch_one(
            "SELECT project_id FROM project_environment_settings WHERE project_id=?",
            (project_id,),
        ):
            return
        now, weather_id = utc_now(), new_id()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO weather_definitions"
                "(id,project_id,name,description,created_at,updated_at) "
                "VALUES(?,?,'Sunny','Clear, neutral weather with no environmental effects.',?,?)",
                (weather_id, project_id, now, now),
            )
            connection.execute(
                "INSERT INTO project_environment_settings"
                "(project_id,enabled,initial_weather_id,updated_at) VALUES(?,1,?,?)",
                (project_id, weather_id, now),
            )
            for position, (name, duration) in enumerate(DEFAULT_PHASES):
                connection.execute(
                    "INSERT INTO time_phases"
                    "(id,project_id,name,duration_minutes,position) VALUES(?,?,?,?,?)",
                    (new_id(), project_id, name, duration, position),
                )

    def settings_row(self, project_id: str) -> dict[str, Any]:
        return self.db.fetch_one(
            "SELECT * FROM project_environment_settings WHERE project_id=?",
            (project_id,),
        ) or {}

    def enabled(self, project_id: str) -> bool:
        row = self.db.fetch_one(
            "SELECT enabled FROM project_environment_settings WHERE project_id=?",
            (project_id,),
        )
        return bool(row and row["enabled"])

    def weather_definitions(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM weather_definitions "
            "WHERE project_id=? ORDER BY name COLLATE NOCASE",
            (project_id,),
        )

    def weather_transitions(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT source_weather_id,target_weather_id "
            "FROM weather_transitions WHERE project_id=?",
            (project_id,),
        )

    def phases(self, project_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        if enabled_only:
            return self.db.fetch_all(
                "SELECT id,name,duration_minutes,position FROM time_phases "
                "WHERE project_id=? AND enabled=1 ORDER BY position",
                (project_id,),
            )
        return self.db.fetch_all(
            "SELECT * FROM time_phases WHERE project_id=? ORDER BY position",
            (project_id,),
        )

    def initial_weather_id(self, project_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT initial_weather_id FROM project_environment_settings WHERE project_id=?",
            (project_id,),
        ) or {}
        return row.get("initial_weather_id")

    def weather(self, project_id: str, weather_id: str | None) -> dict[str, Any] | None:
        row = None
        if weather_id:
            row = self.db.fetch_one(
                "SELECT id,name,description,tags_json,image_tags_json "
                "FROM weather_definitions "
                "WHERE id=? AND project_id=? AND enabled=1",
                (weather_id, project_id),
            )
        return row or self.db.fetch_one(
            "SELECT id,name,description,tags_json,image_tags_json "
            "FROM weather_definitions "
            "WHERE project_id=? AND enabled=1 ORDER BY name LIMIT 1",
            (project_id,),
        )

    def allowed_next_weather(
        self, project_id: str, source_weather_id: str | None
    ) -> list[dict[str, Any]]:
        if not source_weather_id:
            return []
        return self.db.fetch_all(
            "SELECT id,name FROM weather_definitions "
            "WHERE project_id=? AND enabled=1 "
            "AND id IN (SELECT target_weather_id FROM weather_transitions "
            "WHERE project_id=? AND source_weather_id=?)",
            (project_id, project_id, source_weather_id),
        )

    def owner_exists(self, project_id: str, owner_type: str, owner_id: str) -> bool:
        if owner_type == "weather":
            row = self.db.fetch_one(
                "SELECT id FROM weather_definitions WHERE id=? AND project_id=?",
                (owner_id, project_id),
            )
        elif owner_type == "time":
            row = self.db.fetch_one(
                "SELECT id FROM time_phases WHERE id=? AND project_id=?",
                (owner_id, project_id),
            )
        elif owner_type == "location":
            row = self.db.fetch_one(
                "SELECT id FROM world_entities "
                "WHERE id=? AND project_id=? AND kind='location'",
                (owner_id, project_id),
            )
        elif owner_type == "action":
            return bool(owner_id.strip())
        else:
            return False
        return bool(row)

    def weather_ids(self, project_id: str) -> set[str]:
        return {r["id"] for r in self.db.fetch_all(
            "SELECT id FROM weather_definitions WHERE project_id=?", (project_id,)
        )}

    def phase_ids(self, project_id: str) -> set[str]:
        return {r["id"] for r in self.db.fetch_all(
            "SELECT id FROM time_phases WHERE project_id=?", (project_id,)
        )}

    def variant_ids(self, project_id: str) -> set[str]:
        return {r["id"] for r in self.db.fetch_all(
            "SELECT id FROM ambient_variants WHERE project_id=?", (project_id,)
        )}

    def ambient_assignments(
        self,
        project_id: str,
        owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if owner_type is None:
            return self.db.fetch_all(
                "SELECT * FROM ambient_assignments WHERE project_id=?",
                (project_id,),
            )
        return self.db.fetch_all(
            "SELECT selector_type,selector_value,weather_id,time_phase_id,variant_id "
            "FROM ambient_assignments "
            "WHERE project_id=? AND owner_type=? AND owner_id=? ORDER BY id",
            (project_id, owner_type, owner_id),
        )

    def replace_ambient_assignments(
        self,
        *,
        project_id: str,
        owner_type: str,
        owner_id: str,
        normalized: dict[tuple[str, str | None, str | None, str | None], set[str]],
    ) -> None:
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "DELETE FROM ambient_assignments "
                "WHERE project_id=? AND owner_type=? AND owner_id=?",
                (project_id, owner_type, owner_id),
            )
            for key, variant_ids in normalized.items():
                for variant_id in sorted(variant_ids):
                    connection.execute(
                        "INSERT INTO ambient_assignments"
                        "(id,project_id,owner_type,owner_id,selector_type,"
                        "selector_value,weather_id,time_phase_id,variant_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (new_id(), project_id, owner_type, owner_id,
                         key[0], key[1], key[2], key[3], variant_id),
                    )

    def prompt_weather(self, project_id: str, weather_id: str | None) -> dict[str, Any] | None:
        if not weather_id:
            return None
        return self.db.fetch_one(
            "SELECT description,imagegen_description,image_tags_json "
            "FROM weather_definitions WHERE id=? AND project_id=?",
            (weather_id, project_id),
        )

    def prompt_phase(self, project_id: str, phase_id: str | None) -> dict[str, Any] | None:
        if not phase_id:
            return None
        return self.db.fetch_one(
            "SELECT description,imagegen_description FROM time_phases "
            "WHERE id=? AND project_id=?",
            (phase_id, project_id),
        )

    def backgrounds(self, project_id: str, location_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT b.*,m.file_path,m.status FROM location_backgrounds b "
            "JOIN entity_media_assets m ON m.id=b.media_asset_id "
            "WHERE b.project_id=? AND b.location_id=? "
            "AND m.status='generated' AND m.file_path IS NOT NULL "
            "ORDER BY b.position,b.created_at",
            (project_id, location_id),
        )

    def user_preferences(self, user_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT enabled,master_volume FROM user_ambient_preferences WHERE user_id=?",
            (user_id,),
        )
