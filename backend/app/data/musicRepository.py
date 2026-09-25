from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import utc_now


class MusicRepository(BaseRepository):
    def project_settings(self, project_id: str) -> dict[str, Any]:
        return self.db.fetch_one(
            "SELECT * FROM project_music_settings WHERE project_id=?",
            (project_id,),
        ) or {
            "project_id": project_id,
            "mode": "disabled",
            "volume": 0.7,
            "manual_theme_id": None,
        }

    def enabled_theme_ids(self, project_id: str) -> list[str]:
        return [
            row["theme_id"]
            for row in self.db.fetch_all(
                "SELECT theme_id FROM project_music_themes WHERE project_id=?",
                (project_id,),
            )
        ]

    def playback(self, project_id: str) -> dict[str, Any]:
        return self.db.fetch_one(
            "SELECT theme_id,track_id,revision,updated_by_name_snapshot,updated_at "
            "FROM project_music_playback WHERE project_id=?",
            (project_id,),
        ) or {}

    def available_themes(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT t.id,t.name,t.description,t.playback_mode "
            "FROM music_themes t JOIN project_music_themes p ON p.theme_id=t.id "
            "WHERE p.project_id=? ORDER BY t.name",
            (project_id,),
        )

    def theme_tracks(self, theme_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM music_tracks WHERE theme_id=? ORDER BY position,title",
            (theme_id,),
        )

    def theme(self, theme_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id,name FROM music_themes WHERE id=?",
            (theme_id,),
        )

    def theme_is_enabled(self, project_id: str, theme_id: str) -> bool:
        return bool(self.db.fetch_one(
            "SELECT 1 FROM project_music_themes WHERE project_id=? AND theme_id=?",
            (project_id, theme_id),
        ))

    def first_track(self, theme_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id,title FROM music_tracks "
            "WHERE theme_id=? ORDER BY position,title LIMIT 1",
            (theme_id,),
        )

    def track(self, track_id: str, theme_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id,title FROM music_tracks WHERE id=? AND theme_id=?",
            (track_id, theme_id),
        )

    def set_playback(
        self,
        *,
        project_id: str,
        theme_id: str,
        track_id: str,
        updated_by_user_id: str | None,
        updated_by_name: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO project_music_playback"
            "(project_id,theme_id,track_id,revision,updated_by_user_id,"
            "updated_by_name_snapshot,updated_at) VALUES(?,?,?,1,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "theme_id=excluded.theme_id,track_id=excluded.track_id,"
            "revision=project_music_playback.revision+1,"
            "updated_by_user_id=excluded.updated_by_user_id,"
            "updated_by_name_snapshot=excluded.updated_by_name_snapshot,"
            "updated_at=excluded.updated_at",
            (
                project_id,
                theme_id,
                track_id,
                updated_by_user_id,
                updated_by_name,
                utc_now(),
            ),
        )
