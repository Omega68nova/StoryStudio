from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.dataProvider import DataProvider


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
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.music
        self.world = world
        self.events = events

    def project_state(
        self,
        project_id: str,
        *,
        head_node_id: str | None = None,
    ) -> dict[str, Any]:
        settings = dict(self.repo.project_settings(project_id))
        settings["enabled_theme_ids"] = self.repo.enabled_theme_ids(project_id)
        projection = self.world.projection(project_id, head_node_id)
        settings["current_theme_id"] = projection.get("current_theme_id")
        playback = self.playback(project_id)
        settings["shared_theme_id"] = playback.theme_id
        settings["current_track_id"] = playback.track_id
        settings["playback_revision"] = playback.revision
        settings["playback_updated_by"] = playback.updated_by
        return settings

    def playback(self, project_id: str) -> MusicPlayback:
        row = self.repo.playback(project_id)
        return MusicPlayback(
            project_id=project_id,
            theme_id=row.get("theme_id"),
            track_id=row.get("track_id"),
            revision=int(row.get("revision") or 0),
            updated_by=row.get("updated_by_name_snapshot"),
            updated_at=row.get("updated_at"),
        )

    def available_themes(self, project_id: str) -> list[dict[str, Any]]:
        return self.repo.available_themes(project_id)

    def theme_tracks(self, theme_id: str) -> list[dict[str, Any]]:
        return self.repo.theme_tracks(theme_id)

    async def apply_storyteller_theme(
        self,
        project_id: str,
        theme_id: str,
    ) -> MusicPlayback | None:
        if not self.repo.theme_is_enabled(project_id, theme_id):
            return None
        theme = self.repo.theme(theme_id)
        track = self.repo.first_track(theme_id)
        if not theme or not track:
            return None

        self.repo.set_playback(
            project_id=project_id,
            theme_id=theme_id,
            track_id=track["id"],
            updated_by_user_id=None,
            updated_by_name="Storyteller",
        )
        playback = self.playback(project_id)

        if self.events is not None:
            await self.events.publish(
                "music",
                {
                    "project_id": project_id,
                    "action": "playback_changed",
                    "shared_theme_id": theme_id,
                    "current_track_id": track["id"],
                    "playback_updated_by": "Storyteller",
                    "playback_revision": playback.revision,
                    "theme_name": theme["name"],
                    "track_title": track["title"],
                },
            )
        return playback

    async def apply_story_mutations(
        self,
        project_id: str,
        mutations: list[Any],
    ) -> MusicPlayback | None:
        cue = next(
            (m for m in reversed(mutations) if m.tool == "selectTheme"),
            None,
        )
        if not cue:
            return None
        theme_id = cue.arguments.get("theme_id")
        if not theme_id:
            return None
        return await self.apply_storyteller_theme(project_id, str(theme_id))

    async def set_shared_playback(
        self,
        *,
        project_id: str,
        theme_id: str,
        track_id: str,
        updated_by_user_id: str | None,
        updated_by_name: str,
    ) -> MusicPlayback:
        if not self.repo.theme_is_enabled(project_id, theme_id):
            raise ValueError("Select an enabled theme and one of its tracks")
        track = self.repo.track(track_id, theme_id)
        theme = self.repo.theme(theme_id)
        if not track or not theme:
            raise ValueError("Select an enabled theme and one of its tracks")

        self.repo.set_playback(
            project_id=project_id,
            theme_id=theme_id,
            track_id=track_id,
            updated_by_user_id=updated_by_user_id,
            updated_by_name=updated_by_name,
        )
        playback = self.playback(project_id)

        if self.events is not None:
            await self.events.publish(
                "music",
                {
                    "project_id": project_id,
                    "action": "playback_changed",
                    "shared_theme_id": theme_id,
                    "current_track_id": track_id,
                    "playback_revision": playback.revision,
                    "playback_updated_by": updated_by_name,
                    "theme_name": theme["name"],
                    "track_title": track["title"],
                },
            )
        return playback
