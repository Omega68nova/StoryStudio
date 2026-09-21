from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database import utc_now


@dataclass(slots=True, frozen=True)
class MusicPlayback:
    project_id: str
    theme_id: str | None
    track_id: str | None
    revision: int
    updated_by: str | None
    updated_at: str | None


class MusicManager:
    """Owns music policy, canonical theme lookup and shared playback."""

    def __init__(
        self,
        db: Any,
        world: Any,
        events: Any | None = None,
    ) -> None:
        self.db = db
        self.world = world
        self.events = events

    def project_state(
        self,
        project_id: str,
        *,
        head_node_id: str | None = None,
    ) -> dict[str, Any]:
        settings = (
            self.db.fetch_one(
                "SELECT * "
                "FROM project_music_settings "
                "WHERE project_id=?",
                (project_id,),
            )
            or {
                "project_id": project_id,
                "mode": "disabled",
                "volume": 0.7,
                "manual_theme_id": None,
            }
        )

        settings[
            "enabled_theme_ids"
        ] = [
            row["theme_id"]
            for row in self.db.fetch_all(
                "SELECT theme_id "
                "FROM project_music_themes "
                "WHERE project_id=?",
                (project_id,),
            )
        ]

        projection = self.world.projection(
            project_id,
            head_node_id,
        )
        settings[
            "current_theme_id"
        ] = projection.get(
            "current_theme_id"
        )

        playback = self.playback(
            project_id
        )
        settings[
            "shared_theme_id"
        ] = playback.theme_id
        settings[
            "current_track_id"
        ] = playback.track_id
        settings[
            "playback_revision"
        ] = playback.revision
        settings[
            "playback_updated_by"
        ] = playback.updated_by

        return settings

    def playback(
        self,
        project_id: str,
    ) -> MusicPlayback:
        row = (
            self.db.fetch_one(
                "SELECT theme_id,track_id,"
                "revision,"
                "updated_by_name_snapshot,"
                "updated_at "
                "FROM project_music_playback "
                "WHERE project_id=?",
                (project_id,),
            )
            or {}
        )
        return MusicPlayback(
            project_id=project_id,
            theme_id=row.get("theme_id"),
            track_id=row.get("track_id"),
            revision=int(
                row.get("revision")
                or 0
            ),
            updated_by=row.get(
                "updated_by_name_snapshot"
            ),
            updated_at=row.get(
                "updated_at"
            ),
        )

    def available_themes(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT t.id,t.name,t.description,"
            "t.playback_mode "
            "FROM music_themes t "
            "JOIN project_music_themes p "
            "ON p.theme_id=t.id "
            "WHERE p.project_id=? "
            "ORDER BY t.name",
            (project_id,),
        )

    def theme_tracks(
        self,
        theme_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM music_tracks "
            "WHERE theme_id=? "
            "ORDER BY position,title",
            (theme_id,),
        )

    async def apply_storyteller_theme(
        self,
        project_id: str,
        theme_id: str,
    ) -> MusicPlayback | None:
        """Synchronize shared playback after a canonical selectTheme mutation."""
        allowed = self.db.fetch_one(
            "SELECT 1 FROM project_music_themes "
            "WHERE project_id=? AND theme_id=?",
            (
                project_id,
                theme_id,
            ),
        )
        theme = self.db.fetch_one(
            "SELECT id,name "
            "FROM music_themes "
            "WHERE id=?",
            (theme_id,),
        )
        track = self.db.fetch_one(
            "SELECT id,title "
            "FROM music_tracks "
            "WHERE theme_id=? "
            "ORDER BY position,title LIMIT 1",
            (theme_id,),
        )

        if (
            not allowed
            or not theme
            or not track
        ):
            return None

        now = utc_now()
        self.db.execute(
            "INSERT INTO project_music_playback"
            "(project_id,theme_id,track_id,revision,"
            "updated_by_name_snapshot,updated_at) "
            "VALUES(?,?,?,1,'Storyteller',?) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "theme_id=excluded.theme_id,"
            "track_id=excluded.track_id,"
            "revision="
            "project_music_playback.revision+1,"
            "updated_by_user_id=NULL,"
            "updated_by_name_snapshot="
            "'Storyteller',"
            "updated_at=excluded.updated_at",
            (
                project_id,
                theme_id,
                track["id"],
                now,
            ),
        )

        playback = self.playback(
            project_id
        )

        if self.events is not None:
            await self.events.publish(
                "music",
                {
                    "project_id": project_id,
                    "action": (
                        "playback_changed"
                    ),
                    "shared_theme_id": (
                        theme_id
                    ),
                    "current_track_id": (
                        track["id"]
                    ),
                    "playback_updated_by": (
                        "Storyteller"
                    ),
                    "playback_revision": (
                        playback.revision
                    ),
                    "theme_name": (
                        theme["name"]
                    ),
                    "track_title": (
                        track["title"]
                    ),
                },
            )

        return playback

    async def apply_story_mutations(
        self,
        project_id: str,
        mutations: list[Any],
    ) -> MusicPlayback | None:
        cue = next(
            (
                mutation
                for mutation
                in reversed(mutations)
                if mutation.tool
                == "selectTheme"
            ),
            None,
        )
        if not cue:
            return None

        theme_id = cue.arguments.get(
            "theme_id"
        )
        if not theme_id:
            return None

        return await self.apply_storyteller_theme(
            project_id,
            str(theme_id),
        )

    async def set_shared_playback(
        self,
        *,
        project_id: str,
        theme_id: str,
        track_id: str,
        updated_by_user_id: str | None,
        updated_by_name: str,
    ) -> MusicPlayback:
        allowed = self.db.fetch_one(
            "SELECT 1 "
            "FROM project_music_themes "
            "WHERE project_id=? "
            "AND theme_id=?",
            (
                project_id,
                theme_id,
            ),
        )
        track = self.db.fetch_one(
            "SELECT id,title "
            "FROM music_tracks "
            "WHERE id=? AND theme_id=?",
            (
                track_id,
                theme_id,
            ),
        )
        theme = self.db.fetch_one(
            "SELECT id,name "
            "FROM music_themes "
            "WHERE id=?",
            (theme_id,),
        )

        if (
            not allowed
            or not track
            or not theme
        ):
            raise ValueError(
                "Select an enabled theme and one of its tracks"
            )

        now = utc_now()
        self.db.execute(
            "INSERT INTO project_music_playback"
            "(project_id,theme_id,track_id,revision,"
            "updated_by_user_id,"
            "updated_by_name_snapshot,updated_at) "
            "VALUES(?,?,?,1,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "theme_id=excluded.theme_id,"
            "track_id=excluded.track_id,"
            "revision="
            "project_music_playback.revision+1,"
            "updated_by_user_id="
            "excluded.updated_by_user_id,"
            "updated_by_name_snapshot="
            "excluded.updated_by_name_snapshot,"
            "updated_at=excluded.updated_at",
            (
                project_id,
                theme_id,
                track_id,
                updated_by_user_id,
                updated_by_name,
                now,
            ),
        )

        playback = self.playback(
            project_id
        )

        if self.events is not None:
            await self.events.publish(
                "music",
                {
                    "project_id": project_id,
                    "action": (
                        "playback_changed"
                    ),
                    "shared_theme_id": (
                        theme_id
                    ),
                    "current_track_id": (
                        track_id
                    ),
                    "playback_revision": (
                        playback.revision
                    ),
                    "playback_updated_by": (
                        updated_by_name
                    ),
                    "theme_name": (
                        theme["name"]
                    ),
                    "track_title": (
                        track["title"]
                    ),
                },
            )

        return playback
