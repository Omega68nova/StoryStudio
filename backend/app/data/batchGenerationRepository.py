from __future__ import annotations

import json
from typing import Any

from app.database import new_id, utc_now
from app.services.batchGeneration import GenerationPlanDefinition


class BatchGenerationRepository:
    def __init__(self, db: Any) -> None:
        self.db = db

    @staticmethod
    def _decode_task(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["prompt"] = json.loads(item.pop("prompt_json") or "{}")
        item["settings"] = json.loads(item.pop("settings_json") or "{}")
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        item["commit_metadata"] = (
            json.loads(item.pop("commit_metadata_json"))
            if item.get("commit_metadata_json")
            else None
        )
        return item

    @staticmethod
    def _decode_plan(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["settings"] = json.loads(item.pop("settings_json") or "{}")
        return item

    def create_plan(self, project_id: str, definition: GenerationPlanDefinition) -> str:
        definition.validate()
        plan_id, now = new_id(), utc_now()
        task_ids = {task.key: new_id() for task in definition.tasks}
        with self.db._lock, self.db.connect() as c:
            c.execute(
                "INSERT INTO generation_plans"
                "(id,project_id,name,status,source_kind,source_id,settings_json,created_at,updated_at) "
                "VALUES(?,?,?,'ready',?,?,?,?,?)",
                (plan_id, project_id, definition.name.strip(), definition.source_kind,
                 definition.source_id, json.dumps(definition.settings), now, now),
            )
            for task in definition.tasks:
                c.execute(
                    "INSERT INTO generation_plan_tasks"
                    "(id,plan_id,task_key,label,generator_kind,target_kind,target_key,prompt_json,"
                    "settings_json,status,revision,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (task_ids[task.key], plan_id, task.key, task.label, task.generator_kind,
                     task.target_kind, task.target_key, json.dumps(task.prompt),
                     json.dumps(task.settings), "ready" if not task.dependencies else "blocked",
                     now, now),
                )
            for task in definition.tasks:
                for dep in task.dependencies:
                    c.execute(
                        "INSERT INTO generation_task_dependencies"
                        "(task_id,depends_on_task_id,required_state) VALUES(?,?,?)",
                        (task_ids[task.key], task_ids[dep.task_key], dep.required_state),
                    )
        return plan_id

    def plan(self, plan_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT * FROM generation_plans WHERE id=?", (plan_id,))
        return self._decode_plan(row) if row else None

    def plans_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return [self._decode_plan(row) for row in self.db.fetch_all(
            "SELECT * FROM generation_plans WHERE project_id=? ORDER BY updated_at DESC",
            (project_id,),
        )]

    def tasks(self, plan_id: str) -> list[dict[str, Any]]:
        return [self._decode_task(row) for row in self.db.fetch_all(
            "SELECT * FROM generation_plan_tasks WHERE plan_id=? ORDER BY created_at,task_key",
            (plan_id,),
        )]

    def task(self, plan_id: str, task_key: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM generation_plan_tasks WHERE plan_id=? AND task_key=?",
            (plan_id, task_key),
        )
        return self._decode_task(row) if row else None

    def dependency_map(self, plan_id: str) -> dict[str, list[dict[str, str]]]:
        rows = self.db.fetch_all(
            "SELECT child.task_key task_key,parent.task_key dependency_key,d.required_state "
            "FROM generation_task_dependencies d "
            "JOIN generation_plan_tasks child ON child.id=d.task_id "
            "JOIN generation_plan_tasks parent ON parent.id=d.depends_on_task_id "
            "WHERE child.plan_id=? ORDER BY child.task_key,parent.task_key",
            (plan_id,),
        )
        result: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            result.setdefault(row["task_key"], []).append({
                "task_key": row["dependency_key"],
                "required_state": row["required_state"],
            })
        return result

    def revisions(self, plan_id: str, task_key: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT r.* FROM generation_task_revisions r "
            "JOIN generation_plan_tasks t ON t.id=r.task_id "
            "WHERE t.plan_id=? AND t.task_key=? ORDER BY r.revision DESC",
            (plan_id, task_key),
        )
        decoded = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
            item["prompt"] = json.loads(item.pop("prompt_json") or "{}")
            item["settings"] = json.loads(item.pop("settings_json") or "{}")
            decoded.append(item)
        return decoded

    def _archive_current(self, c: Any, task: dict[str, Any], reason: str) -> None:
        c.execute(
            "INSERT OR IGNORE INTO generation_task_revisions"
            "(id,task_id,revision,status,result_json,prompt_json,settings_json,review_note,reason,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                new_id(), task["id"], task["revision"], task["status"],
                task.get("result_json"), task["prompt_json"], task["settings_json"],
                task.get("review_note") or "", reason, utc_now(),
            ),
        )

    def reset_for_regeneration(
        self,
        plan_id: str,
        task_key: str,
        *,
        stale_descendant_keys: list[str],
        reason: str,
        prompt: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as c:
            task = c.execute(
                "SELECT * FROM generation_plan_tasks WHERE plan_id=? AND task_key=?",
                (plan_id, task_key),
            ).fetchone()
            if not task:
                raise KeyError(task_key)
            task = dict(task)
            if task["status"] in {"queued", "running"}:
                raise ValueError("Cancel the active task before regenerating it")
            self._archive_current(c, task, reason)
            c.execute(
                "UPDATE generation_plan_tasks SET "
                "prompt_json=?,settings_json=?,revision=revision+1,status='ready',"
                "result_json=NULL,error=NULL,active_job_id=NULL,approved_at=NULL,"
                "committed_at=NULL,review_note='',commit_metadata_json=NULL,updated_at=? "
                "WHERE id=?",
                (
                    json.dumps(prompt if prompt is not None else json.loads(task["prompt_json"])),
                    json.dumps(settings if settings is not None else json.loads(task["settings_json"])),
                    now, task["id"],
                ),
            )
            for descendant in stale_descendant_keys:
                c.execute(
                    "UPDATE generation_plan_tasks SET status='stale',result_json=NULL,error=NULL,"
                    "active_job_id=NULL,approved_at=NULL,committed_at=NULL,review_note='',"
                    "commit_metadata_json=NULL,updated_at=? "
                    "WHERE plan_id=? AND task_key=? AND status NOT IN ('queued','running')",
                    (now, plan_id, descendant),
                )

    def set_task_status(self, plan_id: str, task_key: str, status: str, *,
                        result: dict[str, Any] | None = None,
                        error: str | None = None) -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET status=?,result_json=COALESCE(?,result_json),"
            "error=?,active_job_id=NULL,updated_at=? WHERE plan_id=? AND task_key=?",
            (status, json.dumps(result) if result is not None else None,
             error, utc_now(), plan_id, task_key),
        )

    def bind_job(self, plan_id: str, task_key: str, job_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET active_job_id=?,status=?,error=NULL,updated_at=? "
            "WHERE plan_id=? AND task_key=?",
            (job_id, status, utc_now(), plan_id, task_key),
        )

    def finish_task(self, plan_id: str, task_key: str, job_id: str | None, *,
                    status: str, result: dict[str, Any] | None = None,
                    error: str | None = None) -> None:
        sql = ("UPDATE generation_plan_tasks SET status=?,result_json=COALESCE(?,result_json),"
               "error=?,active_job_id=NULL,updated_at=? WHERE plan_id=? AND task_key=?")
        params: tuple[Any, ...] = (
            status, json.dumps(result) if result is not None else None,
            error, utc_now(), plan_id, task_key,
        )
        if job_id is not None:
            sql += " AND (active_job_id=? OR active_job_id IS NULL)"
            params += (job_id,)
        self.db.execute(sql, params)

    def approve_task(self, plan_id: str, task_key: str, note: str = "") -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET status='approved',approved_at=?,review_note=?,"
            "error=NULL,updated_at=? WHERE plan_id=? AND task_key=? AND status='generated'",
            (utc_now(), note, utc_now(), plan_id, task_key),
        )

    def commit_task(self, plan_id: str, task_key: str, metadata: dict[str, Any]) -> None:
        now = utc_now()
        self.db.execute(
            "UPDATE generation_plan_tasks SET status='committed',committed_at=?,"
            "commit_metadata_json=?,updated_at=? WHERE plan_id=? AND task_key=? "
            "AND status='approved'",
            (now, json.dumps(metadata), now, plan_id, task_key),
        )

    def mark_ready(self, plan_id: str, task_keys: list[str]) -> None:
        if not task_keys:
            return
        now = utc_now()
        with self.db._lock, self.db.connect() as c:
            for key in task_keys:
                c.execute(
                    "UPDATE generation_plan_tasks SET status='ready',updated_at=? "
                    "WHERE plan_id=? AND task_key=? AND status IN ('pending','blocked','stale') "
                    "AND active_job_id IS NULL",
                    (now, plan_id, key),
                )

    def mark_blocked(self, plan_id: str, task_keys: list[str]) -> None:
        if not task_keys:
            return
        now = utc_now()
        with self.db._lock, self.db.connect() as c:
            for key in task_keys:
                c.execute(
                    "UPDATE generation_plan_tasks SET status='blocked',updated_at=? "
                    "WHERE plan_id=? AND task_key=? AND status='ready' AND active_job_id IS NULL",
                    (now, plan_id, key),
                )

    def plan_by_source(
        self,
        source_kind: str,
        source_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM generation_plans "
            "WHERE source_kind=? AND source_id=? "
            "ORDER BY updated_at DESC LIMIT 1",
            (source_kind, source_id),
        )
        return self._decode_plan(row) if row else None

    def set_task_source(
        self,
        plan_id: str,
        task_key: str,
        source_kind: str,
        source_id: str,
    ) -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET "
            "source_kind=?,source_id=?,updated_at=? "
            "WHERE plan_id=? AND task_key=?",
            (
                source_kind,
                source_id,
                utc_now(),
                plan_id,
                task_key,
            ),
        )

    def import_task_state(
        self,
        plan_id: str,
        task_key: str,
        *,
        status: str,
        result: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        now = utc_now()
        approved_at = now if status in {"approved", "committed"} else None
        committed_at = now if status == "committed" else None
        self.db.execute(
            "UPDATE generation_plan_tasks SET "
            "status=?,result_json=?,error=NULL,active_job_id=NULL,"
            "approved_at=?,committed_at=?,review_note='',"
            "commit_metadata_json=?,updated_at=? "
            "WHERE plan_id=? AND task_key=?",
            (
                status,
                json.dumps(result) if result is not None else None,
                approved_at,
                committed_at,
                json.dumps(metadata) if metadata is not None else None,
                now,
                plan_id,
                task_key,
            ),
        )

    def configure_task(
        self,
        plan_id: str,
        task_key: str,
        *,
        prompt: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        current = self.db.fetch_one(
            "SELECT status,active_job_id FROM generation_plan_tasks "
            "WHERE plan_id=? AND task_key=?",
            (plan_id, task_key),
        )
        if not current:
            raise KeyError(task_key)
        if current.get("active_job_id") or current["status"] in {"queued", "running"}:
            raise ValueError("Cancel the active task before reconfiguring it")
        self.db.execute(
            "UPDATE generation_plan_tasks SET prompt_json=?,settings_json=?,"
            "updated_at=? WHERE plan_id=? AND task_key=?",
            (
                json.dumps(prompt),
                json.dumps(settings),
                utc_now(),
                plan_id,
                task_key,
            ),
        )

    def replace_generated_result(
        self,
        plan_id: str,
        task_key: str,
        result: dict[str, Any],
    ) -> None:
        now = utc_now()
        current = self.db.fetch_one(
            "SELECT status,active_job_id FROM generation_plan_tasks "
            "WHERE plan_id=? AND task_key=?",
            (plan_id, task_key),
        )
        if not current:
            raise KeyError(task_key)
        if current.get("active_job_id") or current["status"] in {"queued", "running"}:
            raise ValueError(
                "Wait for or cancel active generation before editing its result"
            )
        self.db.execute(
            "UPDATE generation_plan_tasks SET "
            "status='generated',result_json=?,error=NULL,active_job_id=NULL,"
            "approved_at=NULL,committed_at=NULL,review_note='',"
            "commit_metadata_json=NULL,updated_at=? "
            "WHERE plan_id=? AND task_key=?",
            (
                json.dumps(result),
                now,
                plan_id,
                task_key,
            ),
        )

    def update_plan_status(self, plan_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE generation_plans SET status=?,updated_at=? WHERE id=?",
            (status, utc_now(), plan_id),
        )

    def create_task(self, plan_id: str, task: dict[str, Any]) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as c:
            c.execute(
                "INSERT INTO generation_plan_tasks(id,plan_id,task_key,label,generator_kind,target_kind,target_key,prompt_json,settings_json,status,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'ready',1,?,?)",
                (new_id(), plan_id, task["task_key"], task["label"], task["generator_kind"], task["target_kind"], task.get("target_key"), json.dumps(task.get("prompt") or {}), json.dumps(task.get("settings") or {}), now, now),
            )
            c.execute("UPDATE generation_plans SET updated_at=? WHERE id=?", (now, plan_id))

    def update_task_definition(self, plan_id: str, task_key: str, task: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET label=?,generator_kind=?,target_kind=?,target_key=?,prompt_json=?,settings_json=?,updated_at=? WHERE plan_id=? AND task_key=?",
            (task["label"], task["generator_kind"], task["target_kind"], task.get("target_key"), json.dumps(task.get("prompt") or {}), json.dumps(task.get("settings") or {}), utc_now(), plan_id, task_key),
        )
        self.db.execute("UPDATE generation_plans SET updated_at=? WHERE id=?", (utc_now(), plan_id))

    def delete_task(self, plan_id: str, task_key: str) -> None:
        self.db.execute("DELETE FROM generation_plan_tasks WHERE plan_id=? AND task_key=?", (plan_id, task_key))
        self.db.execute("UPDATE generation_plans SET updated_at=? WHERE id=?", (utc_now(), plan_id))

    def replace_dependencies(self, plan_id: str, task_key: str, dependencies: list[dict[str, str]]) -> None:
        now = utc_now()
        with self.db._lock, self.db.connect() as c:
            task = c.execute("SELECT id FROM generation_plan_tasks WHERE plan_id=? AND task_key=?", (plan_id, task_key)).fetchone()
            if not task: raise KeyError(task_key)
            c.execute("DELETE FROM generation_task_dependencies WHERE task_id=?", (task["id"],))
            for dependency in dependencies:
                parent = c.execute("SELECT id FROM generation_plan_tasks WHERE plan_id=? AND task_key=?", (plan_id, dependency["task_key"])).fetchone()
                if not parent: raise KeyError(dependency["task_key"])
                c.execute("INSERT INTO generation_task_dependencies(task_id,depends_on_task_id,required_state) VALUES(?,?,?)", (task["id"], parent["id"], dependency["required_state"]))
            dependency_state = "blocked" if dependencies else "ready"
            c.execute("UPDATE generation_plan_tasks SET status=CASE WHEN status IN ('ready','blocked','pending') THEN ? ELSE status END,updated_at=? WHERE id=?", (dependency_state, now, task["id"]))
            c.execute("UPDATE generation_plans SET updated_at=? WHERE id=?", (now, plan_id))

    def mark_stale(self, plan_id: str, task_keys: list[str]) -> None:
        for task_key in task_keys:
            self.db.execute(
                "UPDATE generation_plan_tasks SET status='stale',active_job_id=NULL,updated_at=? WHERE plan_id=? AND task_key=? AND status IN ('generated','approved','committed')",
                (utc_now(), plan_id, task_key),
            )
