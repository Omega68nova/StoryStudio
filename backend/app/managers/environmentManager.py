from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.musicManager import MusicManager
from app.managers.soundManager import SoundManager
from app.services.environment import EnvironmentService


@dataclass(slots=True)
class ResolvedEnvironment:
    enabled: bool
    focused_character: dict[str, Any] | None
    player_action: str
    location: dict[str, Any] | None
    location_ancestry: list[dict[str, str]]
    weather: dict[str, Any] | None
    time_phase: dict[str, Any] | None
    allowed_next_weather: list[dict[str, Any]]
    background: dict[str, Any] | None
    ambient: list[dict[str, Any]]
    music: dict[str, Any]
    revision: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "focused_character": self.focused_character,
            "player_action": self.player_action,
            "location": self.location,
            "location_ancestry": self.location_ancestry,
            "weather": self.weather,
            "time_phase": self.time_phase,
            "allowed_next_weather": self.allowed_next_weather,
            "background": self.background,
            "ambient": self.ambient,
            "music": self.music,
            "revision": self.revision,
        }


class EnvironmentManager:
    """Authoritative resolved scene/environment facade."""

    def __init__(
        self,
        db: Any,
        world: Any,
        *,
        environment_service: EnvironmentService | None = None,
        sound_manager: SoundManager | None = None,
        music_manager: MusicManager | None = None,
        events: Any | None = None,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.environment
        self.world = world
        self.service = environment_service or EnvironmentService(db)
        self.sound = sound_manager or SoundManager(
            db,
            events=events,
            data_provider=self.data,
        )
        self.music = music_manager or MusicManager(db, world, events, data_provider=self.data)

    def resolve(self, project_id: str, projection: dict[str, Any] | None = None) -> ResolvedEnvironment:
        projection = projection or self.world.projection(project_id)
        settings = self.service.settings(project_id)
        revision = int(settings.get("revision") or 1)

        if not settings["enabled"]:
            return ResolvedEnvironment(
                enabled=False,
                focused_character=None,
                player_action=str(projection.get("player_action") or "standing"),
                location=None,
                location_ancestry=[],
                weather=None,
                time_phase=None,
                allowed_next_weather=[],
                background=None,
                ambient=[],
                music=self.music.project_state(project_id, head_node_id=projection.get("head_node_id")),
                revision=revision,
            )

        focus_model, location_model = self.service.location_models(projection)
        location = (
            projection["entities"].get(location_model.id)
            if location_model else None
        )
        weather = self.service._weather(project_id, projection)
        weather_model = self.service.weather_model(project_id, weather)
        phase = self.service.phase(project_id, projection.get("elapsed_minutes", 0))
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

        ambient = self.sound.resolve_ambient(
            project_id=project_id,
            projection=projection,
            location=location,
            weather=weather,
            phase=phase,
        )
        background = self.service.background(
            project_id,
            location_model.id if location_model else None,
            weather_model.id if weather_model else None,
            (phase or {}).get("id"),
        )
        music = self.music.project_state(project_id, head_node_id=projection.get("head_node_id"))

        return ResolvedEnvironment(
            enabled=True,
            focused_character=(
                {"id": focus_model.id, "name": focus_model.name}
                if focus_model else None
            ),
            player_action=str(projection.get("player_action") or "standing"),
            location=location_data,
            location_ancestry=self.service._ancestry(projection, location),
            weather=weather,
            time_phase=phase,
            allowed_next_weather=next_weather,
            background=background,
            ambient=ambient,
            music=music,
            revision=revision,
        )

    def ensure_story_scene(
        self,
        *,
        project_id: str,
        head_node_id: str | None,
        mutations: list[Any],
        pov_character_id: str | None,
    ) -> list[Any]:
        if not self.repo.enabled(project_id) or any(
            item.tool == "setSceneEnvironment" for item in mutations
        ):
            return []

        preview = self.world.preview(project_id, head_node_id, mutations)
        focus = preview.get("entities", {}).get(pov_character_id)
        if (
            not focus
            or focus.get("kind") != "character"
            or not focus.get("state", {}).get("player_controlled")
        ):
            focus = preview.get("entities", {}).get(preview.get("focused_character_id"))

        if not focus:
            focus = next(
                (
                    item
                    for item in preview.get("entities", {}).values()
                    if item.get("kind") == "character"
                    and item.get("state", {}).get("player_controlled")
                ),
                None,
            )
        if not focus:
            return []

        return self.world.normalize_mutations(
            project_id,
            head_node_id,
            [{
                "tool": "setSceneEnvironment",
                "arguments": {
                    "focused_character_id": focus["id"],
                    "player_action": "standing",
                },
            }],
            provenance="system",
            staged=mutations,
        )

    def scene(self, project_id: str, projection: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.resolve(project_id, projection).as_dict()

    def composed_background_prompt(
        self,
        project_id: str,
        location: dict[str, Any],
        weather_id: str | None,
        phase_id: str | None,
    ) -> str:
        return self.service.composed_background_prompt(
            project_id,
            location,
            weather_id,
            phase_id,
        )

    def map_layer(
        self,
        project_id: str,
        projection: dict[str, Any],
        parent_id: str | None,
        *,
        admin: bool,
    ) -> dict[str, Any]:
        return self.service.map_layer(project_id, projection, parent_id, admin=admin)

    def settings(self, project_id: str) -> dict[str, Any]:
        return self.service.settings(project_id)
