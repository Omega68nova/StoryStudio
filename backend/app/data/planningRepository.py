from __future__ import annotations

import json
from typing import Any, Iterable

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class PlanningRepository(BaseRepository):
    """Persistence boundary for planning-control state.

    This repository owns planning sessions, stages, revisions, conflicts,
    approval claims and image-plan lifecycle. It intentionally does NOT own
    canonical world/weather/stats/etc publishing.
    """

    # ------------------------------------------------------------------
    # Sessions / stages
    # ------------------------------------------------------------------

    def active_session(self, project_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM planning_sessions "
            "WHERE project_id=? AND status='active' "
            "ORDER BY created_at DESC",
            (project_id,),
        )

    def latest_session_id(self, project_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT id FROM planning_sessions "
            "WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        )
        return str(row["id"]) if row else None

    def session(self, session_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM planning_sessions WHERE id=?",
            (session_id,),
        )

    def session_exists(self, session_id: str) -> bool:
        return bool(self.db.fetch_one(
            "SELECT id FROM planning_sessions WHERE id=?",
            (session_id,),
        ))

    def create_session(
        self,
        project_id: str,
        settings: dict[str, Any],
        stage_definitions: Iterable[tuple[int, str, str]],
    ) -> str:
        session_id, now = new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO planning_sessions"
                "(id,project_id,status,settings_json,current_stage,"
                "created_at,updated_at) "
                "VALUES(?,?,'active',?,1,?,?)",
                (session_id, project_id, json.dumps(settings), now, now),
            )
            for number, kind, _description in stage_definitions:
                connection.execute(
                    "INSERT INTO planning_stages"
                    "(id,session_id,stage_number,kind,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,'pending',?,?)",
                    (new_id(), session_id, number, kind, now, now),
                )
        return session_id

    def stages(self, session_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM planning_stages "
            "WHERE session_id=? ORDER BY stage_number",
            (session_id,),
        )

    def stage(
        self,
        session_id: str,
        stage_number: int,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM planning_stages "
            "WHERE session_id=? AND stage_number=?",
            (session_id, stage_number),
        )

    def stage_by_id(self, stage_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM planning_stages WHERE id=?",
            (stage_id,),
        )

    def stage_with_settings(self, stage_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT s.*,p.settings_json "
            "FROM planning_stages s "
            "JOIN planning_sessions p ON p.id=s.session_id "
            "WHERE s.id=?",
            (stage_id,),
        )

    def prior_stages(
        self,
        session_id: str,
        stage_number: int,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            return self.db.fetch_all(
                "SELECT * FROM planning_stages "
                "WHERE session_id=? AND stage_number<? "
                f"AND status IN ({placeholders}) "
                "ORDER BY stage_number",
                (session_id, stage_number, *statuses),
            )
        return self.db.fetch_all(
            "SELECT * FROM planning_stages "
            "WHERE session_id=? AND stage_number<? ORDER BY stage_number",
            (session_id, stage_number),
        )

    def later_stages(
        self,
        session_id: str,
        stage_number: int,
    ) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM planning_stages "
            "WHERE session_id=? AND stage_number>? ORDER BY stage_number",
            (session_id, stage_number),
        )

    def has_unapproved_prior(
        self,
        session_id: str,
        stage_number: int,
    ) -> bool:
        return bool(self.db.fetch_one(
            "SELECT id FROM planning_stages "
            "WHERE session_id=? AND stage_number<? "
            "AND status NOT IN ('approved','skipped') LIMIT 1",
            (session_id, stage_number),
        ))

    # ------------------------------------------------------------------
    # Planning operation lifecycle
    # ------------------------------------------------------------------

    def queue_stage_generation(
        self,
        *,
        stage_id: str,
        job_id: str,
        prompt: str,
    ) -> str:
        revision_id, now = new_id(), utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO planning_stage_revisions"
                "(id,stage_id,job_id,prompt,status,created_at,updated_at) "
                "VALUES(?,?,?,?,'queued',?,?)",
                (revision_id, stage_id, job_id, prompt, now, now),
            )
            connection.execute(
                "UPDATE planning_stages "
                "SET human_prompt=?,status='queued',active_job_id=?,updated_at=? "
                "WHERE id=?",
                (prompt, job_id, now, stage_id),
            )
        return revision_id

    def mark_generating(self, stage_id: str, job_id: str) -> bool:
        with self.db._lock, self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE planning_stages "
                "SET status='generating',updated_at=? "
                "WHERE id=? AND active_job_id=?",
                (utc_now(), stage_id, job_id),
            )
            return cursor.rowcount == 1

    def active_job_id(self, stage_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT active_job_id FROM planning_stages WHERE id=?",
            (stage_id,),
        )
        if not row or not row.get("active_job_id"):
            return None
        return str(row["active_job_id"])

    def finish_generation(
        self,
        *,
        session_id: str,
        stage_number: int,
        job_id: str,
        status: str,
    ) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "UPDATE planning_stages "
                "SET status=?,active_job_id=NULL,updated_at=? "
                "WHERE session_id=? AND stage_number=? AND active_job_id=?",
                (status, now, session_id, stage_number, job_id),
            )
            connection.execute(
                "UPDATE planning_stage_revisions "
                "SET status=?,updated_at=? WHERE job_id=?",
                (status, now, job_id),
            )

    # ------------------------------------------------------------------
    # Draft lifecycle
    # ------------------------------------------------------------------

    def save_draft(
        self,
        stage_id: str,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        self.db.execute(
            "UPDATE planning_stages "
            "SET draft_json=?,raw_draft_text=NULL,validation_error=NULL,"
            "status='ready',updated_at=? WHERE id=?",
            (json.dumps(draft), utc_now(), stage_id),
        )
        return self.stage_by_id(stage_id) or {}

    def save_generated_draft(
        self,
        stage_id: str,
        job_id: str,
        draft: dict[str, Any],
    ) -> bool:
        now = utc_now()
        encoded = json.dumps(draft)
        with self.db._lock, self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE planning_stages "
                "SET draft_json=?,raw_draft_text=NULL,validation_error=NULL,"
                "status='ready',active_job_id=NULL,updated_at=? "
                "WHERE id=? AND active_job_id=?",
                (encoded, now, stage_id, job_id),
            )
            if cursor.rowcount != 1:
                connection.execute(
                    "UPDATE planning_stage_revisions "
                    "SET draft_json=?,status='superseded',updated_at=? "
                    "WHERE job_id=?",
                    (encoded, now, job_id),
                )
                return False
            connection.execute(
                "UPDATE planning_stage_revisions "
                "SET draft_json=?,status='ready',updated_at=? WHERE job_id=?",
                (encoded, now, job_id),
            )
        return True

    def save_invalid_generated_draft(
        self,
        stage_id: str,
        job_id: str,
        raw: str,
        error: str,
    ) -> bool:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE planning_stages "
                "SET draft_json=NULL,raw_draft_text=?,validation_error=?,"
                "status='ready',active_job_id=NULL,updated_at=? "
                "WHERE id=? AND active_job_id=?",
                (raw, error, now, stage_id, job_id),
            )
            connection.execute(
                "UPDATE planning_stage_revisions "
                "SET raw_output=?,validation_error=?,status='invalid',updated_at=? "
                "WHERE job_id=?",
                (raw, error, now, job_id),
            )
        return cursor.rowcount == 1

    def reopen_stage(
        self,
        *,
        session_id: str,
        stage_id: str,
        stage_number: int,
        default_draft: dict[str, Any],
    ) -> None:
        stage = self.stage_by_id(stage_id) or {}
        source = (
            stage.get("approved_json")
            or stage.get("draft_json")
            or json.dumps(default_draft)
        )
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "UPDATE planning_stages "
                "SET status='ready',draft_json=?,raw_draft_text=NULL,"
                "validation_error=NULL,replaces_revision_hash=approved_revision_hash,"
                "active_job_id=NULL,updated_at=? WHERE id=?",
                (source, now, stage_id),
            )
            connection.execute(
                "DELETE FROM planning_approval_claims WHERE stage_id=?",
                (stage_id,),
            )
            connection.execute(
                "UPDATE planning_sessions "
                "SET status='active',current_stage=?,updated_at=? WHERE id=?",
                (stage_number, now, session_id),
            )

    def skip_stage(
        self,
        *,
        session_id: str,
        stage_id: str,
        stage_number: int,
        draft: dict[str, Any],
        revision_hash: str,
        dependencies: dict[str, str],
        domains: dict[str, str],
        stage_count: int,
    ) -> None:
        now = utc_now()
        next_number = stage_number + 1
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "UPDATE planning_stages SET "
                "status='skipped',draft_json=?,approved_json=?,"
                "approved_revision_hash=?,dependency_snapshot_json=?,"
                "published_domains_json=?,active_job_id=NULL,updated_at=? "
                "WHERE id=?",
                (
                    json.dumps(draft),
                    json.dumps(draft),
                    revision_hash,
                    json.dumps(dependencies),
                    json.dumps(domains),
                    now,
                    stage_id,
                ),
            )
            connection.execute(
                "UPDATE planning_sessions SET current_stage=?,status=?,updated_at=? "
                "WHERE id=?",
                (
                    min(next_number, stage_count),
                    "completed" if next_number > stage_count else "active",
                    now,
                    session_id,
                ),
            )

    def revalidate_stage(
        self,
        stage_id: str,
        dependency_snapshot: dict[str, str],
    ) -> None:
        self.db.execute(
            "UPDATE planning_stages "
            "SET status='approved',dependency_snapshot_json=?,updated_at=? "
            "WHERE id=?",
            (json.dumps(dependency_snapshot), utc_now(), stage_id),
        )

    def reset_stage(self, stage_id: str) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "DELETE FROM planning_approval_claims WHERE stage_id=?",
                (stage_id,),
            )
            connection.execute(
                "UPDATE planning_stages SET "
                "status='pending',draft_json=NULL,raw_draft_text=NULL,"
                "validation_error=NULL,active_job_id=NULL,updated_at=? "
                "WHERE id=?",
                (now, stage_id),
            )

    # ------------------------------------------------------------------
    # Conflicts / claims
    # ------------------------------------------------------------------

    def conflicts_for_stage(self, stage_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT * FROM planning_conflicts "
            "WHERE stage_id=? ORDER BY entity_key",
            (stage_id,),
        )
        for row in rows:
            row["proposed"] = json.loads(row.pop("proposed_json"))
            row["candidates"] = json.loads(row.pop("candidates_json"))
            row["resolution"] = (
                json.loads(row.pop("resolution_json"))
                if row.get("resolution_json")
                else None
            )
        return rows

    def clear_conflicts(self, stage_id: str) -> None:
        self.db.execute(
            "DELETE FROM planning_conflicts WHERE stage_id=?",
            (stage_id,),
        )

    def claim_approval(self, stage_id: str, revision_hash: str) -> None:
        self.db.execute(
            "INSERT INTO planning_approval_claims"
            "(stage_id,revision_hash,created_at) VALUES(?,?,?)",
            (stage_id, revision_hash, utc_now()),
        )

    def release_approval_claim(self, stage_id: str) -> None:
        self.db.execute(
            "DELETE FROM planning_approval_claims WHERE stage_id=?",
            (stage_id,),
        )

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------

    def revision_history(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT r.*,s.stage_number,s.kind "
            "FROM planning_stage_revisions r "
            "JOIN planning_stages s ON s.id=r.stage_id "
            "WHERE s.session_id=? ORDER BY r.created_at DESC",
            (session_id,),
        )
        for row in rows:
            row["draft"] = (
                json.loads(row.pop("draft_json"))
                if row.get("draft_json")
                else None
            )
        return rows

    def clear_revisions(self, session_id: str) -> int:
        count = int(
            (
                self.db.fetch_one(
                    "SELECT COUNT(*) n FROM planning_stage_revisions "
                    "WHERE stage_id IN "
                    "(SELECT id FROM planning_stages WHERE session_id=?)",
                    (session_id,),
                )
                or {"n": 0}
            )["n"]
        )
        self.db.execute(
            "DELETE FROM planning_stage_revisions "
            "WHERE stage_id IN "
            "(SELECT id FROM planning_stages WHERE session_id=?)",
            (session_id,),
        )
        return count

    # ------------------------------------------------------------------
    # Image plans
    # ------------------------------------------------------------------

    def image_plans(self, session_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM planning_image_plans "
            "WHERE session_id=? ORDER BY kind,resource_key",
            (session_id,),
        )

    def image_plan(self, plan_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM planning_image_plans WHERE id=?",
            (plan_id,),
        )

    def image_plan_ids(self, session_id: str) -> set[str]:
        return {
            row["id"]
            for row in self.db.fetch_all(
                "SELECT id FROM planning_image_plans WHERE session_id=?",
                (session_id,),
            )
        }

    def ready_image_plan_ids(self, session_id: str) -> list[str]:
        return [
            row["id"]
            for row in self.db.fetch_all(
                "SELECT id FROM planning_image_plans "
                "WHERE session_id=? AND status='ready'",
                (session_id,),
            )
        ]

    def update_image_plan(
        self,
        plan_id: str,
        *,
        prompt: str,
        negative_prompt: str,
        workflow_preset_id: str | None,
        width: int | None,
        height: int | None,
        prompt_revision: str,
        status: str,
    ) -> dict[str, Any]:
        self.db.execute(
            "UPDATE planning_image_plans SET "
            "prompt=?,negative_prompt=?,workflow_preset_id=?,width=?,height=?,"
            "prompt_revision=?,status=?,generation_job_id=NULL,error=NULL,"
            "updated_at=? WHERE id=?",
            (
                prompt,
                negative_prompt,
                workflow_preset_id,
                width,
                height,
                prompt_revision,
                status,
                utc_now(),
                plan_id,
            ),
        )
        return self.image_plan(plan_id) or {}

    def delete_image_plan(self, plan_id: str) -> None:
        self.db.execute(
            "DELETE FROM planning_image_plans WHERE id=?",
            (plan_id,),
        )

    def mark_image_plan_queued(
        self,
        plan_id: str,
        *,
        media_asset_id: str,
        generation_job_id: str,
    ) -> None:
        self.db.execute(
            "UPDATE planning_image_plans "
            "SET status='queued',media_asset_id=?,generation_job_id=?,"
            "error=NULL,updated_at=? WHERE id=?",
            (
                media_asset_id,
                generation_job_id,
                utc_now(),
                plan_id,
            ),
        )
