from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class StoryRepository(BaseRepository):
    def node(self, node_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM story_nodes WHERE id=?",
            (node_id,),
        )

    def nodes(
        self,
        project_id: str,
        *,
        trashed: bool = False,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM story_nodes "
            "WHERE project_id=? AND trashed=? ORDER BY created_at",
            (project_id, int(trashed)),
        )

    def path(self, leaf_id: str | None) -> list[dict[str, Any]]:
        if not leaf_id:
            return []
        return self.db.story_path(leaf_id)

    def branch_summary_for_path(
        self,
        project_id: str,
        node_ids: set[str],
    ) -> dict[str, Any] | None:
        if not node_ids:
            return None
        rows = self.db.fetch_all(
            "SELECT * FROM branch_summaries "
            "WHERE project_id=? "
            "ORDER BY created_at DESC",
            (project_id,),
        )
        return next(
            (
                row
                for row in rows
                if row["through_node_id"] in node_ids
            ),
            None,
        )

    def inherited_view(self, node_id: str | None) -> dict[str, Any] | None:
        if not node_id:
            return None
        return self.db.fetch_one(
            "SELECT pov_character_id,narration_mode "
            "FROM story_nodes WHERE id=?",
            (node_id,),
        )

    def create_node(
        self,
        project_id: str,
        parent_id: str | None,
        role: str,
        content: str,
        *,
        status: str = "complete",
        pov_character_id: str | None = None,
        narration_mode: str = "third_limited",
        action_kind: str = "story",
        author_user_id: str | None = None,
        author_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        return self.db.create_story_node(
            project_id,
            parent_id,
            role,
            content,
            status,
            pov_character_id,
            narration_mode,
            action_kind,
            author_user_id,
            author_name_snapshot,
        )

    def create_revision(
        self,
        node_id: str,
        content: str,
    ) -> tuple[dict[str, Any] | None, str]:
        node = self.node(node_id)
        if not node:
            return None, ""
        revision_id = new_id()
        now = utc_now()
        self.db.execute(
            "INSERT INTO story_node_revisions"
            "(id,story_node_id,previous_content,content,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                revision_id,
                node_id,
                node["content"],
                content,
                now,
            ),
        )
        self.db.execute(
            "UPDATE story_nodes SET content=? WHERE id=?",
            (content, node_id),
        )
        return self.node(node_id), revision_id

    def revisions(self, node_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM story_node_revisions "
            "WHERE story_node_id=? ORDER BY created_at DESC",
            (node_id,),
        )

    def revision(self, revision_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM story_node_revisions WHERE id=?",
            (revision_id,),
        )

    def subtree_ids(self, node_id: str) -> list[str]:
        return [
            row["id"]
            for row in self.db.fetch_all(
                "WITH RECURSIVE subtree(id) AS ("
                "SELECT ? UNION ALL "
                "SELECT n.id FROM story_nodes n "
                "JOIN subtree s ON n.parent_id=s.id"
                ") SELECT id FROM subtree",
                (node_id,),
            )
        ]

    def set_trashed(
        self,
        node_ids: list[str],
        trashed: bool,
    ) -> None:
        for node_id in node_ids:
            self.db.execute(
                "UPDATE story_nodes SET trashed=? WHERE id=?",
                (int(trashed), node_id),
            )

    def children(
        self,
        project_id: str,
        parent_id: str | None,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM story_nodes "
            "WHERE project_id=? AND parent_id IS ? "
            "AND status!='rejected' AND trashed=0 "
            "ORDER BY created_at DESC",
            (project_id, parent_id),
        )

    def suggestions(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT s.*,j.id image_job_id,j.status image_job_status,"
            "j.phase image_job_phase,"
            "j.progress_current image_progress_current,"
            "j.progress_total image_progress_total,"
            "j.progress_message image_progress_message "
            "FROM image_suggestions s "
            "JOIN story_nodes n ON n.id=s.story_node_id "
            "LEFT JOIN generation_jobs j ON j.id=("
            "SELECT gj.id FROM generation_jobs gj "
            "WHERE json_extract(gj.payload_json,'$.suggestion_id')=s.id "
            "ORDER BY gj.created_at DESC LIMIT 1"
            ") WHERE n.project_id=? AND n.trashed=0 "
            "ORDER BY s.created_at",
            (project_id,),
        )

    def npc_interventions(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT i.* FROM npc_interventions i "
            "JOIN story_nodes n ON n.id=i.story_node_id "
            "WHERE n.project_id=? AND n.trashed=0 "
            "ORDER BY i.created_at",
            (project_id,),
        )

    def scene_appearances(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT a.* FROM scene_appearances a "
            "JOIN story_nodes n ON n.id=a.story_node_id "
            "WHERE n.project_id=? AND n.trashed=0 "
            "ORDER BY a.created_at",
            (project_id,),
        )

    def purge_impact(self, node_id: str) -> dict[str, int]:
        ids = self.subtree_ids(node_id)
        if not ids:
            return {"nodes": 0, "suggestions": 0, "revisions": 0}
        placeholders = ",".join("?" for _ in ids)
        suggestions = int(
            (
                self.db.fetch_one(
                    f"SELECT COUNT(*) n FROM image_suggestions "
                    f"WHERE story_node_id IN ({placeholders})",
                    tuple(ids),
                )
                or {"n": 0}
            )["n"]
        )
        revisions = int(
            (
                self.db.fetch_one(
                    f"SELECT COUNT(*) n FROM story_node_revisions "
                    f"WHERE story_node_id IN ({placeholders})",
                    tuple(ids),
                )
                or {"n": 0}
            )["n"]
        )
        return {
            "nodes": len(ids),
            "suggestions": suggestions,
            "revisions": revisions,
        }

    def clear_revisions(self, node_id: str) -> int:
        count = int(
            (
                self.db.fetch_one(
                    "SELECT COUNT(*) n FROM story_node_revisions "
                    "WHERE story_node_id=?",
                    (node_id,),
                )
                or {"n": 0}
            )["n"]
        )
        self.db.execute(
            "DELETE FROM story_node_revisions WHERE story_node_id=?",
            (node_id,),
        )
        return count
