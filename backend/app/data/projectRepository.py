from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import utc_now


class ProjectRepository(BaseRepository):
    def list_projects(
        self,
        *,
        admin: bool,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if admin:
            return self.db.fetch_all(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            )
        return self.db.fetch_all(
            "SELECT p.* FROM projects p "
            "JOIN user_project_access a ON a.project_id=p.id "
            "WHERE a.user_id=? ORDER BY p.updated_at DESC",
            (user_id,),
        )

    def get(self, project_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        )

    def update_title(self, project_id: str, title: str) -> dict[str, Any] | None:
        self.db.execute(
            "UPDATE projects SET title=?,updated_at=? WHERE id=?",
            (title, utc_now(), project_id),
        )
        return self.get(project_id)

    def set_active_node(
        self,
        project_id: str,
        node_id: str | None,
    ) -> None:
        self.db.execute(
            "UPDATE projects SET active_node_id=?,updated_at=? WHERE id=?",
            (node_id, utc_now(), project_id),
        )

    def bible_documents(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM bible_documents "
            "WHERE project_id=? ORDER BY position",
            (project_id,),
        )

    def bible_document(self, document_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM bible_documents WHERE id=?",
            (document_id,),
        )

    def update_bible_document(
        self,
        document_id: str,
        *,
        title: str,
        content: str,
    ) -> dict[str, Any] | None:
        self.db.execute(
            "UPDATE bible_documents "
            "SET title=?,content=?,updated_at=? WHERE id=?",
            (title, content, utc_now(), document_id),
        )
        return self.bible_document(document_id)

    def clear_bible(self, project_id: str) -> int:
        rows = self.db.fetch_all(
            "SELECT id FROM bible_documents WHERE project_id=?",
            (project_id,),
        )
        self.db.execute(
            "UPDATE bible_documents SET content='',updated_at=? "
            "WHERE project_id=?",
            (utc_now(), project_id),
        )
        return len(rows)

    def story_settings(self, project_id: str) -> dict[str, Any]:
        return self.db.fetch_one(
            "SELECT default_generation_mode,response_max_tokens,ai_instructions "
            "FROM project_story_settings WHERE project_id=?",
            (project_id,),
        ) or {
            "default_generation_mode": "low",
            "response_max_tokens": 300,
            "ai_instructions": "",
        }

    def update_story_settings(
        self,
        project_id: str,
        *,
        default_generation_mode: str,
        response_max_tokens: int,
        ai_instructions: str,
    ) -> dict[str, Any]:
        self.db.execute(
            "INSERT INTO project_story_settings"
            "(project_id,default_generation_mode,response_max_tokens,"
            "ai_instructions,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "default_generation_mode=excluded.default_generation_mode,"
            "response_max_tokens=excluded.response_max_tokens,"
            "ai_instructions=excluded.ai_instructions,"
            "updated_at=excluded.updated_at",
            (
                project_id,
                default_generation_mode,
                response_max_tokens,
                ai_instructions,
                utc_now(),
            ),
        )
        return self.story_settings(project_id)

    def delete_impact(self, project_id: str) -> dict[str, int]:
        queries = {
            "story_nodes": "SELECT COUNT(*) n FROM story_nodes WHERE project_id=?",
            "entities": "SELECT COUNT(*) n FROM world_entities WHERE project_id=?",
            "planning_sessions": "SELECT COUNT(*) n FROM planning_sessions WHERE project_id=?",
            "jobs": "SELECT COUNT(*) n FROM generation_jobs WHERE project_id=?",
            "media": "SELECT COUNT(*) n FROM entity_media_assets WHERE project_id=?",
            "minigame_sessions": "SELECT COUNT(*) n FROM minigame_sessions WHERE project_id=?",
        }
        return {
            name: int(
                (
                    self.db.fetch_one(query, (project_id,))
                    or {"n": 0}
                )["n"]
            )
            for name, query in queries.items()
        }

    def ensure_music_settings(self, project_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO project_music_settings(project_id) VALUES(?)",
            (project_id,),
        )

    def assigned_project_ids(self, user_id: str) -> list[str]:
        return [
            row["project_id"]
            for row in self.db.fetch_all(
                "SELECT project_id FROM user_project_access "
                "WHERE user_id=? ORDER BY project_id",
                (user_id,),
            )
        ]
