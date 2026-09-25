from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import utc_now


class LifecycleRepository(BaseRepository):
    """Persistence for destructive/admin data lifecycle operations."""

    def jobs(
        self,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if project_id:
            return self.db.fetch_all(
                "SELECT id,project_id,kind,status,phase,created_at "
                "FROM generation_jobs WHERE project_id=?",
                (project_id,),
            )
        return self.db.fetch_all(
            "SELECT id,project_id,kind,status,phase,created_at "
            "FROM generation_jobs"
        )

    def referenced_paths(self) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT image_path path FROM image_suggestions "
            "WHERE image_path IS NOT NULL "
            "UNION ALL "
            "SELECT file_path path FROM entity_media_assets "
            "WHERE file_path IS NOT NULL "
            "UNION ALL "
            "SELECT file_path path FROM music_tracks "
            "WHERE file_path IS NOT NULL"
        )
        return [row["path"] for row in rows if row.get("path")]

    def path_reference_rows(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT 'image_suggestions' source_table,id,image_path path "
            "FROM image_suggestions WHERE image_path IS NOT NULL "
            "UNION ALL "
            "SELECT 'entity_media_assets' source_table,id,file_path path "
            "FROM entity_media_assets WHERE file_path IS NOT NULL "
            "UNION ALL "
            "SELECT 'music_tracks' source_table,id,file_path path "
            "FROM music_tracks WHERE file_path IS NOT NULL"
        )

    def clear_file_failure(self, path: str) -> None:
        self.db.execute(
            "DELETE FROM managed_file_failures WHERE path=?",
            (path,),
        )

    def record_file_failure(self, path: str, error: str) -> None:
        self.db.execute(
            "INSERT INTO managed_file_failures(path,error,last_attempt_at) "
            "VALUES(?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "error=excluded.error,last_attempt_at=excluded.last_attempt_at",
            (path, error, utc_now()),
        )

    def dangling_search_rows(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT rowid,entity_id,version_id FROM lore_card_search "
            "WHERE version_id NOT IN (SELECT id FROM lore_card_versions)"
        )

    def delete_search_rows(self, rowids: list[int]) -> None:
        if not rowids:
            return
        with self.db._lock, self.db.connect() as connection:
            connection.executemany(
                "DELETE FROM lore_card_search WHERE rowid=?",
                [(rowid,) for rowid in rowids],
            )

    def table_count(self, table: str) -> int:
        # Callers pass only an internal fixed allowlist.
        return int(
            (
                self.db.fetch_one(
                    f"SELECT COUNT(*) n FROM {table}"
                )
                or {"n": 0}
            )["n"]
        )

    def trashed_story_count(self) -> int:
        return int(
            (
                self.db.fetch_one(
                    "SELECT COUNT(*) n FROM story_nodes WHERE trashed=1"
                )
                or {"n": 0}
            )["n"]
        )

    def dangling_search_count(self) -> int:
        return int(
            (
                self.db.fetch_one(
                    "SELECT COUNT(*) n FROM lore_card_search "
                    "WHERE version_id NOT IN "
                    "(SELECT id FROM lore_card_versions)"
                )
                or {"n": 0}
            )["n"]
        )

    def file_failures(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM managed_file_failures "
            "ORDER BY last_attempt_at DESC"
        )

    def project_paths(self, project_id: str) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT s.image_path path FROM image_suggestions s "
            "JOIN story_nodes n ON n.id=s.story_node_id "
            "WHERE n.project_id=? AND s.image_path IS NOT NULL "
            "UNION ALL "
            "SELECT file_path path FROM entity_media_assets "
            "WHERE project_id=? AND file_path IS NOT NULL",
            (project_id, project_id),
        )
        return [row["path"] for row in rows]

    def project_ids(self) -> list[str]:
        return [
            row["id"]
            for row in self.db.fetch_all("SELECT id FROM projects")
        ]

    def purge_project(self, project_id: str) -> None:
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "DELETE FROM lore_card_search WHERE project_id=?",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM projects WHERE id=?",
                (project_id,),
            )

    def clear_story_content(self) -> None:
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM lore_card_search")
            connection.execute("DELETE FROM projects")

    def factory_reset(self) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM lore_card_search")
            connection.execute("DELETE FROM projects")
            connection.execute("DELETE FROM workflow_presets")
            connection.execute("DELETE FROM music_tracks")
            connection.execute("DELETE FROM music_themes")
            connection.execute(
                "DELETE FROM bullethell_attacks WHERE built_in=0"
            )
            connection.execute(
                "DELETE FROM bullethell_modes WHERE built_in=0"
            )
            connection.execute(
                "DELETE FROM bullethell_skills WHERE built_in=0"
            )
            connection.execute("DELETE FROM managed_file_failures")
            connection.execute(
                "UPDATE runtime_settings SET "
                "llama_executable='',storyteller_model_path='',"
                "storyteller_model_id='',"
                "llama_url='http://127.0.0.1:8080',"
                "llama_extra_args_json='[]',"
                "comfy_command_json='[]',comfy_workdir='',"
                "comfy_url='http://127.0.0.1:8188',"
                "context_tokens=8192,planning_context_tokens=8192,"
                "memory_provider='builtin',updated_at=? WHERE id=1",
                (now,),
            )
