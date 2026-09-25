from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class LibraryRepository(BaseRepository):
    """Persistence boundary for revisioned reusable global resources."""

    def list_resources(
        self,
        *,
        resource_kind: str | None = None,
        marked_only: bool = False,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if resource_kind:
            clauses.append("r.resource_kind=?")
            params.append(resource_kind)
        if marked_only:
            clauses.append("r.marked=1")
        if search:
            clauses.append("(r.name LIKE ? OR r.description LIKE ? OR EXISTS (SELECT 1 FROM library_resource_tags t WHERE t.resource_id=r.id AND t.tag LIKE ?))")
            token = f"%{search}%"
            params.extend([token, token, token])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.db.fetch_all(
            f"""
            SELECT r.*,
              COALESCE((SELECT MAX(revision_number) FROM library_resource_revisions v WHERE v.resource_id=r.id),0) AS revision_count,
              (SELECT COUNT(*) FROM library_resource_children c WHERE c.parent_resource_id=r.id) AS child_count,
              (SELECT COUNT(DISTINCT i.project_id) FROM library_project_imports i WHERE i.resource_id=r.id) AS referenced_story_count,
              (SELECT COUNT(*) FROM library_project_imports i WHERE i.resource_id=r.id) AS import_count
            FROM library_resources r
            {where}
            ORDER BY r.marked DESC, r.resource_kind, r.name COLLATE NOCASE, r.id
            """,
            tuple(params),
        )

    def resource_for_source(
        self,
        *,
        source_project_id: str,
        source_kind: str,
        source_key: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            """
            SELECT r.id
            FROM library_resources r
            JOIN library_resource_revisions v ON v.resource_id=r.id
            WHERE v.source_project_id=? AND v.source_kind=? AND v.source_key=?
            ORDER BY v.created_at DESC
            LIMIT 1
            """,
            (source_project_id, source_kind, source_key),
        )
        return self.resource(row["id"]) if row else None

    def resource(self, resource_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            """
            SELECT r.*,
              COALESCE((SELECT MAX(revision_number) FROM library_resource_revisions v WHERE v.resource_id=r.id),0) AS revision_count,
              (SELECT COUNT(*) FROM library_resource_children c WHERE c.parent_resource_id=r.id) AS child_count,
              (SELECT COUNT(DISTINCT i.project_id) FROM library_project_imports i WHERE i.resource_id=r.id) AS referenced_story_count,
              (SELECT COUNT(*) FROM library_project_imports i WHERE i.resource_id=r.id) AS import_count
            FROM library_resources r WHERE r.id=?
            """,
            (resource_id,),
        )
        if not row:
            return None
        row["tags"] = [
            item["tag"]
            for item in self.db.fetch_all(
                "SELECT tag FROM library_resource_tags WHERE resource_id=? ORDER BY tag COLLATE NOCASE",
                (resource_id,),
            )
        ]
        row["children"] = self.db.fetch_all(
            """
            SELECT c.*, r.resource_kind, r.name, r.description, r.marked, r.current_revision_id
            FROM library_resource_children c
            JOIN library_resources r ON r.id=c.child_resource_id
            WHERE c.parent_resource_id=?
            ORDER BY c.position,r.name COLLATE NOCASE,r.id
            """,
            (resource_id,),
        )
        row["current_revision"] = (
            self.revision(row["current_revision_id"])
            if row.get("current_revision_id")
            else None
        )
        return row

    def create_resource(
        self,
        *,
        resource_kind: str,
        name: str,
        description: str = "",
        marked: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        resource_id, now = new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO library_resources(id,resource_kind,name,description,marked,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (resource_id, resource_kind, name.strip(), description.strip(), int(marked), now, now),
            )
            for tag in self._normalize_tags(tags or []):
                connection.execute(
                    "INSERT INTO library_resource_tags(resource_id,tag,created_at) VALUES(?,?,?)",
                    (resource_id, tag, now),
                )
        return self.resource(resource_id) or {}

    def update_resource(
        self,
        resource_id: str,
        *,
        name: str,
        description: str,
        marked: bool,
        tags: list[str],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            if not connection.execute("SELECT 1 FROM library_resources WHERE id=?", (resource_id,)).fetchone():
                raise ValueError("Library resource not found")
            connection.execute(
                "UPDATE library_resources SET name=?,description=?,marked=?,updated_at=? WHERE id=?",
                (name.strip(), description.strip(), int(marked), now, resource_id),
            )
            connection.execute("DELETE FROM library_resource_tags WHERE resource_id=?", (resource_id,))
            for tag in self._normalize_tags(tags):
                connection.execute(
                    "INSERT INTO library_resource_tags(resource_id,tag,created_at) VALUES(?,?,?)",
                    (resource_id, tag, now),
                )
        return self.resource(resource_id) or {}

    def revisions(self, resource_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT * FROM library_resource_revisions WHERE resource_id=? ORDER BY revision_number DESC",
            (resource_id,),
        )
        for row in rows:
            row["snapshot"] = json.loads(row.pop("snapshot_json"))
        return rows

    def revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT * FROM library_resource_revisions WHERE id=?", (revision_id,))
        if row:
            row["snapshot"] = json.loads(row.pop("snapshot_json"))
        return row

    def add_revision(
        self,
        resource_id: str,
        snapshot: dict[str, Any],
        *,
        source_project_id: str | None = None,
        source_story_node_id: str | None = None,
        source_kind: str | None = None,
        source_key: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        revision_id, now = new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            if not connection.execute("SELECT 1 FROM library_resources WHERE id=?", (resource_id,)).fetchone():
                raise ValueError("Library resource not found")
            if source_story_node_id:
                source_node = connection.execute(
                    "SELECT project_id FROM story_nodes WHERE id=?",
                    (source_story_node_id,),
                ).fetchone()
                if not source_node:
                    raise ValueError("Source story node not found")
                if source_project_id and source_node["project_id"] != source_project_id:
                    raise ValueError("Source story node does not belong to source project")
                source_project_id = source_project_id or source_node["project_id"]
            number = connection.execute(
                "SELECT COALESCE(MAX(revision_number),0)+1 AS n FROM library_resource_revisions WHERE resource_id=?",
                (resource_id,),
            ).fetchone()["n"]
            connection.execute(
                """
                INSERT INTO library_resource_revisions(
                  id,resource_id,revision_number,snapshot_json,source_project_id,
                  source_story_node_id,source_kind,source_key,note,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    revision_id, resource_id, number,
                    json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False),
                    source_project_id, source_story_node_id, source_kind, source_key,
                    note.strip(), now,
                ),
            )
            connection.execute(
                "UPDATE library_resources SET current_revision_id=?,updated_at=? WHERE id=?",
                (revision_id, now, resource_id),
            )
        return self.revision(revision_id) or {}

    def set_children(self, parent_resource_id: str, children: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM library_resource_children WHERE parent_resource_id=?", (parent_resource_id,))
            for position, child in enumerate(children):
                child_id = str(child["child_resource_id"])
                if child_id == parent_resource_id:
                    raise ValueError("A library resource cannot contain itself")
                if not connection.execute("SELECT 1 FROM library_resources WHERE id=?", (child_id,)).fetchone():
                    raise ValueError(f"Unknown child library resource: {child_id}")
                cycle = connection.execute(
                    """
                    WITH RECURSIVE descendants(id) AS (
                      SELECT child_resource_id
                      FROM library_resource_children
                      WHERE parent_resource_id=?
                      UNION
                      SELECT c.child_resource_id
                      FROM library_resource_children c
                      JOIN descendants d ON c.parent_resource_id=d.id
                    )
                    SELECT 1 FROM descendants WHERE id=? LIMIT 1
                    """,
                    (child_id, parent_resource_id),
                ).fetchone()
                if cycle:
                    raise ValueError("Library resource trees cannot contain cycles")
                connection.execute(
                    """
                    INSERT INTO library_resource_children(
                      parent_resource_id,child_resource_id,relation_kind,position,required,created_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        parent_resource_id, child_id,
                        str(child.get("relation_kind") or "contains"),
                        int(child.get("position", position)),
                        int(bool(child.get("required", True))),
                        now,
                    ),
                )

    def record_import(
        self,
        *,
        resource_id: str,
        revision_id: str,
        project_id: str,
        target_kind: str,
        target_key: str | None = None,
        source_story_node_id: str | None = None,
    ) -> dict[str, Any]:
        import_id, now = new_id(), utc_now()
        revision = self.db.fetch_one(
            "SELECT resource_id FROM library_resource_revisions WHERE id=?",
            (revision_id,),
        )
        if not revision or revision["resource_id"] != resource_id:
            raise ValueError("Imported revision does not belong to resource")
        if source_story_node_id:
            node = self.db.fetch_one(
                "SELECT project_id FROM story_nodes WHERE id=?",
                (source_story_node_id,),
            )
            if not node or node["project_id"] != project_id:
                raise ValueError("Import source story node does not belong to target project")
        self.db.execute(
            """
            INSERT INTO library_project_imports(
              id,resource_id,revision_id,project_id,target_kind,target_key,source_story_node_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (import_id, resource_id, revision_id, project_id, target_kind, target_key, source_story_node_id, now),
        )
        return self.db.fetch_one("SELECT * FROM library_project_imports WHERE id=?", (import_id,)) or {}

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            tag = str(raw).strip()
            key = tag.casefold()
            if not tag or key in seen:
                continue
            seen.add(key)
            result.append(tag)
        return result
