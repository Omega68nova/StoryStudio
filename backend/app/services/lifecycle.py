from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.database import Database, utc_now


ACTIVE_JOB_STATUSES = {"queued", "running", "switching", "awaiting_review", "awaiting_minigame"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "interrupted", "rejected"}


class LifecycleConflict(ValueError):
    def __init__(self, message: str, actions: list[str] | None = None) -> None:
        super().__init__(message)
        self.actions = actions or []


class DataLifecycle:
    def __init__(self, db: Database) -> None:
        self.db = db

    def active_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        where, params = (" WHERE project_id=?", (project_id,)) if project_id else ("", ())
        rows = self.db.fetch_all(f"SELECT id, project_id, kind, status, phase, created_at FROM generation_jobs{where}", params)
        return [row for row in rows if row["status"] in ACTIVE_JOB_STATUSES]

    def require_idle(self, project_id: str | None = None) -> None:
        jobs = self.active_jobs(project_id)
        if jobs:
            raise LifecycleConflict("Cancel or finish affected generation jobs first", ["cancel_jobs", "retry_after_completion"])

    def referenced_paths(self) -> set[str]:
        result: set[str] = set()
        for table, column in (("image_suggestions", "image_path"), ("entity_media_assets", "file_path"), ("music_tracks", "file_path")):
            result.update(row[column] for row in self.db.fetch_all(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL") if row[column])
        return {self._normalize_relative(path) for path in result}

    def path_references(self, value: str) -> list[dict[str, str]]:
        normalized = self._normalize_relative(value)
        references: list[dict[str, str]] = []
        for table, column in (("image_suggestions", "image_path"), ("entity_media_assets", "file_path"), ("music_tracks", "file_path")):
            for row in self.db.fetch_all(f"SELECT id,{column} path FROM {table} WHERE {column} IS NOT NULL"):
                if self._normalize_relative(row["path"]) == normalized:
                    references.append({"table": table, "id": row["id"]})
        return references

    def _normalize_relative(self, value: str) -> str:
        return str(Path(value)).replace("\\", "/").lstrip("/")

    def _managed_path(self, relative: str) -> Path | None:
        path = (self.db.data_dir / self._normalize_relative(relative)).resolve()
        roots = (self.db.images_dir.resolve(), self.db.music_dir.resolve())
        return path if any(path == root or root in path.parents for root in roots) else None

    def release_paths(self, candidates: Iterable[str]) -> list[dict[str, str]]:
        referenced = self.referenced_paths()
        failures: list[dict[str, str]] = []
        for relative in {self._normalize_relative(item) for item in candidates if item} - referenced:
            path = self._managed_path(relative)
            if not path or not path.is_file():
                continue
            try:
                path.unlink()
                self.db.execute("DELETE FROM managed_file_failures WHERE path=?", (relative,))
            except OSError as exc:
                failures.append({"path": relative, "error": str(exc)})
                self.db.execute(
                    "INSERT INTO managed_file_failures(path,error,last_attempt_at) VALUES(?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET error=excluded.error,last_attempt_at=excluded.last_attempt_at",
                    (relative, str(exc), utc_now()),
                )
        return failures

    def orphan_paths(self) -> list[str]:
        referenced = self.referenced_paths()
        found: set[str] = set()
        for root in (self.db.images_dir, self.db.music_dir):
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.is_file():
                        found.add(str(path.relative_to(self.db.data_dir)).replace("\\", "/"))
        return sorted(found - referenced)

    def garbage_collect(self) -> dict[str, Any]:
        orphans = self.orphan_paths()
        failures = self.release_paths(orphans)
        dangling = self.db.fetch_all(
            "SELECT rowid, entity_id, version_id FROM lore_card_search WHERE version_id NOT IN (SELECT id FROM lore_card_versions)"
        )
        if dangling:
            with self.db._lock, self.db.connect() as connection:
                connection.executemany("DELETE FROM lore_card_search WHERE rowid=?", [(row["rowid"],) for row in dangling])
        return {"files_removed": len(orphans) - len(failures), "fts_rows_removed": len(dangling), "failures": failures}

    def summary(self) -> dict[str, Any]:
        tables = (
            "projects", "bible_documents", "story_nodes", "story_node_revisions", "image_suggestions", "generation_jobs", "planning_sessions",
            "planning_stages", "planning_stage_revisions", "world_entities", "world_transactions", "world_events", "lore_card_versions",
            "entity_outfits", "entity_media_assets", "scene_appearances", "stat_definitions", "ability_definitions",
            "workflow_presets", "music_themes", "music_tracks",
            "project_minigame_configs", "minigame_sessions",
            "bullethell_skills", "bullethell_modes", "bullethell_attacks",
        )
        counts = {table: int((self.db.fetch_one(f"SELECT COUNT(*) n FROM {table}") or {"n": 0})["n"]) for table in tables}
        disk = 0
        for root in (self.db.images_dir, self.db.music_dir):
            if root.is_dir():
                disk += sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        fts_orphans = int((self.db.fetch_one(
            "SELECT COUNT(*) n FROM lore_card_search WHERE version_id NOT IN (SELECT id FROM lore_card_versions)"
        ) or {"n": 0})["n"])
        return {
            "counts": counts,
            "managed_disk_bytes": disk,
            "active_jobs": self.active_jobs(),
            "trashed_story_nodes": int((self.db.fetch_one("SELECT COUNT(*) n FROM story_nodes WHERE trashed=1") or {"n": 0})["n"]),
            "orphan_files": self.orphan_paths(),
            "dangling_fts_rows": fts_orphans,
            "file_failures": self.db.fetch_all("SELECT * FROM managed_file_failures ORDER BY last_attempt_at DESC"),
        }

    def project_paths(self, project_id: str) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT s.image_path path FROM image_suggestions s JOIN story_nodes n ON n.id=s.story_node_id WHERE n.project_id=? AND s.image_path IS NOT NULL "
            "UNION ALL SELECT file_path path FROM entity_media_assets WHERE project_id=? AND file_path IS NOT NULL",
            (project_id, project_id),
        )
        return [row["path"] for row in rows]

    def purge_project(self, project_id: str) -> dict[str, Any]:
        self.require_idle(project_id)
        paths = self.project_paths(project_id)
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM lore_card_search WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return {"project_id": project_id, "file_failures": self.release_paths(paths)}

    def clear_all_story_content(self) -> dict[str, Any]:
        self.require_idle()
        project_ids = [row["id"] for row in self.db.fetch_all("SELECT id FROM projects")]
        paths = [path for project_id in project_ids for path in self.project_paths(project_id)]
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM lore_card_search")
            connection.execute("DELETE FROM projects")
        return {"projects_removed": len(project_ids), "file_failures": self.release_paths(paths)}

    def factory_reset(self) -> dict[str, Any]:
        self.require_idle()
        paths = list(self.referenced_paths())
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM lore_card_search")
            connection.execute("DELETE FROM projects")
            connection.execute("DELETE FROM workflow_presets")
            connection.execute("DELETE FROM music_tracks")
            connection.execute("DELETE FROM music_themes")
            connection.execute("DELETE FROM bullethell_attacks WHERE built_in=0")
            connection.execute("DELETE FROM bullethell_modes WHERE built_in=0")
            connection.execute("DELETE FROM bullethell_skills WHERE built_in=0")
            connection.execute("DELETE FROM managed_file_failures")
            connection.execute(
                "UPDATE runtime_settings SET llama_executable='',storyteller_model_path='',storyteller_model_id='',"
                "llama_url='http://127.0.0.1:8080',llama_extra_args_json='[]',comfy_command_json='[]',"
                "comfy_workdir='',comfy_url='http://127.0.0.1:8188',context_tokens=8192,memory_provider='builtin',updated_at=? WHERE id=1",
                (now,),
            )
        result = self.release_paths(paths)
        result.extend(self.release_paths(self.orphan_paths()))
        return {"file_failures": result}
