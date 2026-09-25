from __future__ import annotations

import json
from typing import Any, Iterable

from app.data.baseRepository import BaseRepository
from app.database import decode_json_fields, utc_now


class JobRepository(BaseRepository):
    JSON_FIELDS = ("payload_json", "result_json", "metrics_json")

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM generation_jobs WHERE id=?",
            (job_id,),
        )
        return decode_json_fields(row, *self.JSON_FIELDS)

    def create(
        self,
        project_id: str,
        kind: str,
        payload: dict[str, Any],
        requested_by_user_id: str | None = None,
        requester_name_snapshot: str | None = None,
    ) -> dict[str, Any]:
        return self.db.create_job(
            project_id,
            kind,
            payload,
            requested_by_user_id,
            requester_name_snapshot,
        )

    def list(
        self,
        *,
        project_ids: list[str] | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        if project_ids:
            placeholders = ",".join("?" for _ in project_ids)
            limit_sql = f" LIMIT {int(limit)}" if limit else ""
            rows = self.db.fetch_all(
                f"SELECT * FROM generation_jobs "
                f"WHERE project_id IN ({placeholders}) "
                f"ORDER BY created_at DESC{limit_sql}",
                tuple(project_ids),
            )
        else:
            limit_sql = f" LIMIT {int(limit)}" if limit else ""
            rows = self.db.fetch_all(
                "SELECT * FROM generation_jobs "
                f"ORDER BY created_at DESC{limit_sql}"
            )
        return [
            decode_json_fields(row, *self.JSON_FIELDS) or {}
            for row in rows
        ]

    def active_for_project(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT id,kind,status,phase,progress_current,progress_total,"
            "progress_message,created_at,updated_at,"
            "requester_name_snapshot,requested_by_user_id,partial_output,"
            "payload_json FROM generation_jobs "
            "WHERE project_id=? AND status IN "
            "('queued','running','switching','awaiting_review','awaiting_minigame') "
            "ORDER BY created_at",
            (project_id,),
        )

    def project_id_for_job(self, job_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT project_id FROM generation_jobs WHERE id=?",
            (job_id,),
        )
        return str(row["project_id"]) if row else None

    def update_payload(
        self,
        job_id: str,
        payload: dict[str, Any],
        status: str = "queued",
    ) -> None:
        self.db.execute(
            "UPDATE generation_jobs SET payload_json=?,status=?,"
            "error=NULL,updated_at=? WHERE id=?",
            (json.dumps(payload), status, utc_now(), job_id),
        )

    def clear_terminal(
        self,
        statuses: Iterable[str],
        *,
        project_id: str | None = None,
    ) -> int:
        status_list = list(statuses)
        if not status_list:
            return 0
        placeholders = ",".join("?" for _ in status_list)
        params: list[Any] = list(status_list)
        clause = ""
        if project_id:
            clause = " AND project_id=?"
            params.append(project_id)

        count = int(
            (
                self.db.fetch_one(
                    f"SELECT COUNT(*) n FROM generation_jobs "
                    f"WHERE status IN ({placeholders}){clause}",
                    tuple(params),
                )
                or {"n": 0}
            )["n"]
        )
        self.db.execute(
            f"DELETE FROM generation_jobs "
            f"WHERE status IN ({placeholders}){clause}",
            tuple(params),
        )
        return count

    def latest_story_job_for_node(
        self,
        story_node_id: str,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT payload_json,result_json FROM generation_jobs "
            "WHERE kind='story' "
            "AND json_extract(result_json,'$.story_node_id')=? "
            "ORDER BY created_at DESC LIMIT 1",
            (story_node_id,),
        )
