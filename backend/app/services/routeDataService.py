from __future__ import annotations

import json
from typing import Any, Callable

from app.data.dataProvider import DataProvider

_MEMBER_JOB_FIELDS = {
    "id", "project_id", "kind", "status", "phase",
    "progress_current", "progress_total", "progress_message",
    "error", "created_at", "updated_at", "requested_by_user_id",
    "requester_name_snapshot", "partial_output", "metrics",
}


class RouteDataService:
    def __init__(
        self,
        data: DataProvider,
        *,
        minigame_loader: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.data = data
        self.minigame_loader = minigame_loader

    @staticmethod
    def member_job_view(job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in job.items()
            if key in _MEMBER_JOB_FIELDS
        }

    def list_projects(
        self,
        *,
        admin: bool,
        user_id: str,
    ) -> list[dict[str, Any]]:
        return self.data.projects.list_projects(
            admin=admin,
            user_id=user_id,
        )

    def story_settings(
        self,
        project_id: str,
        *,
        include_ai_instructions: bool,
    ) -> dict[str, Any]:
        settings = dict(self.data.projects.story_settings(project_id))
        if not include_ai_instructions:
            settings.pop("ai_instructions", None)
        return settings

    def project_bundle(
        self,
        project_id: str,
        *,
        admin: bool,
        user_id: str,
    ) -> dict[str, Any] | None:
        project = self.data.projects.get(project_id)
        if not project:
            return None

        project = dict(project)
        project["bible_documents"] = self.data.projects.bible_documents(project_id)

        story_nodes = self.data.stories.nodes(project_id, trashed=False)
        visible_story_ids = {
            node["id"]
            for node in self.data.stories.path(project.get("active_node_id"))
        }
        if not admin:
            story_nodes = [
                node for node in story_nodes
                if node["id"] in visible_story_ids
            ]
        project["story_nodes"] = story_nodes
        project["trashed_story_nodes"] = (
            self.data.stories.nodes(project_id, trashed=True)
            if admin else []
        )

        suggestions = self.data.stories.suggestions(project_id)
        if not admin:
            suggestions = [
                item for item in suggestions
                if item["story_node_id"] in visible_story_ids
            ]
        project["suggestions"] = suggestions

        interventions = self.data.stories.npc_interventions(project_id)
        for item in interventions:
            raw = item.pop("cited_fact_ids_json", "[]")
            item["cited_fact_ids"] = json.loads(raw or "[]")
        if not admin:
            interventions = [
                item for item in interventions
                if item["story_node_id"] in visible_story_ids
            ]
        project["npc_interventions"] = interventions

        appearances = self.data.stories.scene_appearances(project_id)
        if not admin:
            appearances = [
                item for item in appearances
                if item["story_node_id"] in visible_story_ids
            ]
        project["scene_appearances"] = appearances

        project["story_settings"] = self.story_settings(
            project_id,
            include_ai_instructions=admin,
        )
        project["permissions"] = {
            "admin": admin,
            "edit_bible": True,
            "submit_story": True,
            "edit_story": admin,
            "manage_context": admin,
        }

        active_jobs = self.data.jobs.active_for_project(project_id)
        for position, active_job in enumerate(active_jobs, start=1):
            payload = json.loads(active_job.pop("payload_json") or "{}")
            pending = payload.get("pending_action") or {}
            active_job["queue_position"] = position
            active_job["action_type"] = pending.get("action") or payload.get("action")
            active_job["input_preview"] = str(
                pending.get("content") or payload.get("guidance") or ""
            )[:500]
            active_job["can_cancel"] = (
                admin
                or active_job.get("requested_by_user_id") == user_id
            )
        project["active_jobs"] = active_jobs
        return project

    def list_jobs(
        self,
        *,
        admin: bool,
        assigned_project_ids: list[str],
        requested_project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if admin:
            return self.data.jobs.list(
                project_ids=[requested_project_id] if requested_project_id else None,
                limit=None if requested_project_id else 100,
            )

        if not assigned_project_ids:
            return []

        if (
            requested_project_id
            and requested_project_id not in assigned_project_ids
        ):
            raise PermissionError("Story is not assigned to this account")

        selected = (
            [requested_project_id]
            if requested_project_id
            else assigned_project_ids
        )
        return [
            self.member_job_view(job)
            for job in self.data.jobs.list(
                project_ids=selected,
                limit=100,
            )
        ]

    def get_job(
        self,
        job_id: str,
        *,
        admin: bool,
    ) -> dict[str, Any] | None:
        job = self.data.jobs.get(job_id)
        if not job:
            return None
        return job if admin else self.member_job_view(job)
