from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class MediaRepository(BaseRepository):
    def prior_appearances(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT a.entity_id,a.story_node_id "
            "FROM scene_appearances a "
            "JOIN story_nodes n ON n.id=a.story_node_id "
            "WHERE n.project_id=?",
            (project_id,),
        )

    def featured_asset(
        self,
        entity_id: str,
        kind: str,
        outfit_id: str | None,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id FROM entity_media_assets "
            "WHERE entity_id=? AND kind=? "
            "AND COALESCE(outfit_id,'')=COALESCE(?, '') AND featured=1",
            (entity_id, kind, outfit_id),
        )

    def create_suggested_asset(
        self,
        *,
        project_id: str,
        entity_id: str,
        outfit_id: str | None,
        kind: str,
        prompt: str,
        story_node_id: str,
    ) -> str:
        asset_id, now = new_id(), utc_now()
        self.db.execute(
            "INSERT INTO entity_media_assets"
            "(id,project_id,entity_id,outfit_id,kind,source,status,prompt,"
            "source_story_node_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'suggested','suggested',?,?,?,?)",
            (
                asset_id, project_id, entity_id, outfit_id, kind,
                prompt, story_node_id, now, now,
            ),
        )
        return asset_id

    def create_suggestion(
        self,
        *,
        story_node_id: str,
        title: str,
        prompt: str,
        negative_prompt: str,
    ) -> dict[str, Any]:
        suggestion_id, now = new_id(), utc_now()
        self.db.execute(
            "INSERT INTO image_suggestions"
            "(id,story_node_id,title,prompt,negative_prompt,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'suggested',?,?)",
            (
                suggestion_id, story_node_id, title, prompt,
                negative_prompt, now, now,
            ),
        )
        return self.db.fetch_one(
            "SELECT * FROM image_suggestions WHERE id=?",
            (suggestion_id,),
        ) or {}

    def environment_settings(self, project_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT enabled,auto_generate_backgrounds,background_workflow_id "
            "FROM project_environment_settings WHERE project_id=?",
            (project_id,),
        )

    def background_exists(
        self,
        *,
        project_id: str,
        location_id: str,
        weather_id: str | None,
        phase_id: str | None,
    ) -> bool:
        return bool(self.db.fetch_one(
            "SELECT b.id FROM location_backgrounds b "
            "WHERE b.project_id=? AND b.location_id=? "
            "AND b.weather_id IS ? AND b.time_phase_id IS ?",
            (project_id, location_id, weather_id, phase_id),
        ))

    def create_queued_background(
        self,
        *,
        project_id: str,
        location_id: str,
        prompt: str,
        story_node_id: str,
        weather_id: str | None,
        phase_id: str | None,
    ) -> tuple[str, str]:
        asset_id, background_id, now = new_id(), new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO entity_media_assets"
                "(id,project_id,entity_id,kind,source,status,prompt,featured,"
                "source_story_node_id,created_at,updated_at) "
                "VALUES(?,?,?,'location','suggested','queued',?,0,?,?,?)",
                (
                    asset_id, project_id, location_id, prompt,
                    story_node_id, now, now,
                ),
            )
            connection.execute(
                "INSERT INTO location_backgrounds"
                "(id,project_id,location_id,media_asset_id,weather_id,"
                "time_phase_id,position,created_at) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (
                    background_id, project_id, location_id, asset_id,
                    weather_id, phase_id, now,
                ),
            )
        return asset_id, background_id
