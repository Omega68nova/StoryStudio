from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class ReviewRepository(BaseRepository):
    def create_pending(
        self,
        *,
        job_id: str,
        story_node_id: str | None,
        phase: str,
        mutations: list[dict[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        review_id, now = new_id(), utc_now()
        self.db.execute(
            "INSERT INTO pending_reviews"
            "(id,job_id,story_node_id,phase,status,mutations_json,reason,"
            "created_at,updated_at) VALUES(?,?,?,?, 'pending',?,?,?,?)",
            (
                review_id, job_id, story_node_id, phase,
                json.dumps(mutations), reason, now, now,
            ),
        )
        return {
            "id": review_id,
            "job_id": job_id,
            "story_node_id": story_node_id,
            "phase": phase,
            "status": "pending",
            "mutations": mutations,
            "reason": reason,
        }
