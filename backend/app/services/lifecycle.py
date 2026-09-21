from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.database import Database
from app.data.dataProvider import DataProvider

ACTIVE_JOB_STATUSES = {"queued", "running", "switching", "awaiting_review", "awaiting_minigame"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "interrupted", "rejected"}


class LifecycleConflict(ValueError):
    def __init__(self, message: str, actions: list[str] | None = None) -> None:
        super().__init__(message)
        self.actions = actions or []


class DataLifecycle:
    def __init__(
        self,
        db: Database,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.lifecycle

    def active_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return [
            row for row in self.repo.jobs(project_id)
            if row["status"] in ACTIVE_JOB_STATUSES
        ]

    def require_idle(self, project_id: str | None = None) -> None:
        if self.active_jobs(project_id):
            raise LifecycleConflict(
                "Cancel or finish affected generation jobs first",
                ["cancel_jobs", "retry_after_completion"],
            )

    @staticmethod
    def _normalize_relative(value: str) -> str:
        return str(Path(value)).replace("\\", "/").lstrip("/")

    def referenced_paths(self) -> set[str]:
        return {
            self._normalize_relative(path)
            for path in self.repo.referenced_paths()
        }

    def path_references(self, value: str) -> list[dict[str, str]]:
        normalized = self._normalize_relative(value)
        return [
            {"table": row["source_table"], "id": row["id"]}
            for row in self.repo.path_reference_rows()
            if self._normalize_relative(row["path"]) == normalized
        ]

    def _managed_path(self, relative: str) -> Path | None:
        path = (self.db.data_dir / self._normalize_relative(relative)).resolve()
        roots = (self.db.images_dir.resolve(), self.db.music_dir.resolve())
        return path if any(path == root or root in path.parents for root in roots) else None

    def release_paths(self, candidates: Iterable[str]) -> list[dict[str, str]]:
        referenced = self.referenced_paths()
        failures: list[dict[str, str]] = []
        for relative in {
            self._normalize_relative(item)
            for item in candidates
            if item
        } - referenced:
            path = self._managed_path(relative)
            if not path or not path.is_file():
                continue
            try:
                path.unlink()
                self.repo.clear_file_failure(relative)
            except OSError as exc:
                failures.append({"path": relative, "error": str(exc)})
                self.repo.record_file_failure(relative, str(exc))
        return failures

    def orphan_paths(self) -> list[str]:
        referenced = self.referenced_paths()
        found: set[str] = set()
        for root in (self.db.images_dir, self.db.music_dir):
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.is_file():
                        found.add(
                            str(path.relative_to(self.db.data_dir))
                            .replace("\\", "/")
                        )
        return sorted(found - referenced)

    def garbage_collect(self) -> dict[str, Any]:
        orphans = self.orphan_paths()
        failures = self.release_paths(orphans)
        dangling = self.repo.dangling_search_rows()
        self.repo.delete_search_rows([int(row["rowid"]) for row in dangling])
        return {
            "files_removed": len(orphans) - len(failures),
            "fts_rows_removed": len(dangling),
            "failures": failures,
        }

    def summary(self) -> dict[str, Any]:
        tables = (
            "projects", "bible_documents", "story_nodes",
            "story_node_revisions", "image_suggestions", "generation_jobs",
            "planning_sessions", "planning_stages", "planning_stage_revisions",
            "world_entities", "world_transactions", "world_events",
            "lore_card_versions", "entity_outfits", "entity_media_assets",
            "scene_appearances", "stat_definitions", "ability_definitions",
            "workflow_presets", "music_themes", "music_tracks",
            "project_minigame_configs", "minigame_sessions",
            "bullethell_skills", "bullethell_modes", "bullethell_attacks",
        )
        counts = {table: self.repo.table_count(table) for table in tables}
        disk = 0
        for root in (self.db.images_dir, self.db.music_dir):
            if root.is_dir():
                disk += sum(
                    path.stat().st_size
                    for path in root.rglob("*")
                    if path.is_file()
                )
        return {
            "counts": counts,
            "managed_disk_bytes": disk,
            "active_jobs": self.active_jobs(),
            "trashed_story_nodes": self.repo.trashed_story_count(),
            "orphan_files": self.orphan_paths(),
            "dangling_fts_rows": self.repo.dangling_search_count(),
            "file_failures": self.repo.file_failures(),
        }

    def project_paths(self, project_id: str) -> list[str]:
        return self.repo.project_paths(project_id)

    def purge_project(self, project_id: str) -> dict[str, Any]:
        self.require_idle(project_id)
        paths = self.project_paths(project_id)
        self.repo.purge_project(project_id)
        return {
            "project_id": project_id,
            "file_failures": self.release_paths(paths),
        }

    def clear_all_story_content(self) -> dict[str, Any]:
        self.require_idle()
        project_ids = self.repo.project_ids()
        paths = [
            path
            for project_id in project_ids
            for path in self.project_paths(project_id)
        ]
        self.repo.clear_story_content()
        return {
            "projects_removed": len(project_ids),
            "file_failures": self.release_paths(paths),
        }

    def factory_reset(self) -> dict[str, Any]:
        self.require_idle()
        paths = list(self.referenced_paths())
        self.repo.factory_reset()
        result = self.release_paths(paths)
        result.extend(self.release_paths(self.orphan_paths()))
        return {"file_failures": result}
