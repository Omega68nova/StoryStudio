from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import decode_json_fields, new_id, utc_now


class WorkflowRepository(BaseRepository):
    def get(self, workflow_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM workflow_presets WHERE id=?",
            (workflow_id,),
        )
        return decode_json_fields(
            row,
            "graph_json",
            "mappings_json",
            "source_graph_json",
        )

    def exists(self, workflow_id: str) -> bool:
        return bool(self.db.fetch_one(
            "SELECT id FROM workflow_presets WHERE id=?",
            (workflow_id,),
        ))

    def list(self, *, admin: bool) -> list[dict[str, Any]]:
        if not admin:
            return self.db.fetch_all(
                "SELECT id,name,validation_status,validation_error,"
                "created_at,updated_at FROM workflow_presets "
                "ORDER BY updated_at DESC"
            )
        rows = self.db.fetch_all(
            "SELECT id,name,graph_json,mappings_json,source_graph_json,"
            "validation_status,validation_error,source_format,created_at,updated_at "
            "FROM workflow_presets ORDER BY updated_at DESC"
        )
        return [
            decode_json_fields(
                row,
                "graph_json",
                "mappings_json",
                "source_graph_json",
            ) or {}
            for row in rows
        ]

    def create(
        self,
        *,
        name: str,
        graph: dict[str, Any],
        mappings_json: str,
        source_graph: dict[str, Any],
        source_format: str,
        validation_status: str,
        validation_error: str | None,
    ) -> dict[str, Any]:
        workflow_id, now = new_id(), utc_now()
        self.db.execute(
            "INSERT INTO workflow_presets"
            "(id,name,graph_json,mappings_json,validation_status,"
            "validation_error,source_graph_json,source_format,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                workflow_id, name, json.dumps(graph), mappings_json,
                validation_status, validation_error, json.dumps(source_graph),
                source_format, now, now,
            ),
        )
        return self.get(workflow_id) or {}

    def update(
        self,
        workflow_id: str,
        *,
        name: str,
        graph: dict[str, Any],
        mappings_json: str,
        source_graph: dict[str, Any],
        source_format: str,
        validation_status: str,
        validation_error: str | None = None,
    ) -> dict[str, Any]:
        self.db.execute(
            "UPDATE workflow_presets SET name=?,graph_json=?,mappings_json=?,"
            "validation_status=?,validation_error=?,source_graph_json=?,"
            "source_format=?,updated_at=? WHERE id=?",
            (
                name, json.dumps(graph), mappings_json, validation_status,
                validation_error, json.dumps(source_graph), source_format,
                utc_now(), workflow_id,
            ),
        )
        return self.get(workflow_id) or {}

    def set_validation(
        self,
        workflow_id: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        self.db.execute(
            "UPDATE workflow_presets "
            "SET validation_status=?,validation_error=?,updated_at=? WHERE id=?",
            (status, error, utc_now(), workflow_id),
        )

    def active_job(self, workflow_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT id FROM generation_jobs "
            "WHERE status IN ('queued','running','switching') "
            "AND json_extract(payload_json,'$.preset_id')=? LIMIT 1",
            (workflow_id,),
        )

    def historical_job_count(self, workflow_id: str) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) n FROM generation_jobs "
            "WHERE json_extract(payload_json,'$.preset_id')=?",
            (workflow_id,),
        ) or {"n": 0}
        return int(row["n"])

    def delete(self, workflow_id: str) -> None:
        self.db.execute(
            "DELETE FROM workflow_presets WHERE id=?",
            (workflow_id,),
        )
