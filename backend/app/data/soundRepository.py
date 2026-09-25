from __future__ import annotations

import json
from typing import Any, Iterable

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class SoundRepository(BaseRepository):
    def source_variant(self, project_id: str, source_path: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id FROM ambient_variants "
            "WHERE project_id=? AND source_path=? AND playback_rate=1 AND derived=0",
            (project_id, source_path),
        )

    def create_source_variant(
        self,
        *,
        project_id: str,
        source_path: str,
        label: str,
        tags: list[str],
    ) -> str:
        variant_id = new_id()
        now = utc_now()
        self.db.execute(
            "INSERT INTO ambient_variants"
            "(id,project_id,source_path,label,tags_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (variant_id, project_id, source_path, label, json.dumps(tags), now, now),
        )
        return variant_id

    def set_available(self, variant_id: str, available: bool) -> None:
        self.db.execute(
            "UPDATE ambient_variants SET available=?,updated_at=? WHERE id=?",
            (int(available), utc_now(), variant_id),
        )

    def project_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT id,source_path FROM ambient_variants WHERE project_id=?",
            (project_id,),
        )

    def assignments(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM ambient_assignments WHERE project_id=?",
            (project_id,),
        )

    def enabled_variants(self, variant_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(variant_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return self.db.fetch_all(
            "SELECT id,source_path,label,playback_rate,default_gain,tags_json "
            f"FROM ambient_variants WHERE id IN ({placeholders}) "
            "AND enabled=1 AND available=1",
            tuple(ids),
        )

    def variants(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM ambient_variants WHERE project_id=? ORDER BY source_path,label",
            (project_id,),
        )

    def owner_assignments(
        self,
        project_id: str,
        owner_type: str,
        owner_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT selector_type,selector_value,weather_id,time_phase_id,variant_id "
            "FROM ambient_assignments "
            "WHERE project_id=? AND owner_type=? AND owner_id=? ORDER BY id",
            (project_id, owner_type, owner_id),
        )

    def user_preferences(self, user_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT enabled,master_volume FROM user_ambient_preferences WHERE user_id=?",
            (user_id,),
        )

    def noise_source(
        self,
        project_id: str,
        source_path: str,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id FROM noise_variants "
            "WHERE project_id=? AND source_path=? AND playback_rate=1",
            (project_id, source_path),
        )

    def create_noise_source(
        self,
        *,
        project_id: str,
        source_path: str,
        label: str,
        tags: list[str],
    ) -> str:
        noise_id = new_id()
        now = utc_now()
        self.db.execute(
            "INSERT INTO noise_variants"
            "(id,project_id,source_path,label,tags_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                noise_id,
                project_id,
                source_path,
                label,
                json.dumps(tags),
                now,
                now,
            ),
        )
        return noise_id

    def noise_sources(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT id,source_path FROM noise_variants WHERE project_id=?",
            (project_id,),
        )

    def set_noise_available(self, noise_id: str, available: bool) -> None:
        self.db.execute(
            "UPDATE noise_variants SET available=?,updated_at=? WHERE id=?",
            (int(available), utc_now(), noise_id),
        )

    def noise_variants(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM noise_variants WHERE project_id=? "
            "ORDER BY source_path,label",
            (project_id,),
        )

    def noise_variant(
        self,
        project_id: str,
        noise_id: str,
        *,
        playable_only: bool = False,
    ) -> dict[str, Any] | None:
        suffix = " AND enabled=1 AND available=1" if playable_only else ""
        return self.db.fetch_one(
            "SELECT * FROM noise_variants WHERE project_id=? AND id=?" + suffix,
            (project_id, noise_id),
        )

    def update_noise_variant(
        self,
        project_id: str,
        noise_id: str,
        *,
        label: str,
        playback_rate: float,
        default_gain: float,
        tags: list[str],
        enabled: bool,
    ) -> None:
        self.db.execute(
            "UPDATE noise_variants SET label=?,playback_rate=?,default_gain=?,"
            "tags_json=?,enabled=?,updated_at=? WHERE id=? AND project_id=?",
            (
                label,
                playback_rate,
                default_gain,
                json.dumps(tags),
                int(enabled),
                utc_now(),
                noise_id,
                project_id,
            ),
        )

    def noise_preferences(self, user_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT enabled,master_volume FROM user_noise_preferences "
            "WHERE user_id=?",
            (user_id,),
        )

    def set_noise_preferences(
        self,
        user_id: str,
        *,
        enabled: bool,
        master_volume: float,
    ) -> None:
        self.db.execute(
            "INSERT INTO user_noise_preferences"
            "(user_id,enabled,master_volume,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,"
            "master_volume=excluded.master_volume,updated_at=excluded.updated_at",
            (
                user_id,
                int(enabled),
                master_volume,
                utc_now(),
            ),
        )
