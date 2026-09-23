from __future__ import annotations

from typing import Any, Iterable

from app.data.dataProvider import DataProvider
from app.services.batchCommit import BatchTaskCommitter
from app.services.batchGeneration import (
    GenerationDependency,
    GenerationPlanDefinition,
    GenerationPlanError,
    GenerationTaskDefinition,
    descendant_keys,
    ready_task_keys,
)


class BatchGenerationManager:
    def __init__(self, db: Any, *, data_provider: DataProvider | None = None) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.batch_generation

    def create_plan(self, project_id: str, definition: GenerationPlanDefinition) -> dict[str, Any]:
        return self.get_plan(self.repo.create_plan(project_id, definition))

    def _aggregate_status(self, tasks: list[dict[str, Any]], ready: list[str]) -> str:
        states = {str(task["status"]) for task in tasks}
        if tasks and all(task["status"] == "committed" for task in tasks):
            return "completed"
        if states & {"queued", "running"}:
            return "running"
        if states & {"failed"}:
            return "failed"
        if states & {"generated", "approved"}:
            return "awaiting_review"
        if ready:
            return "ready"
        if tasks and all(task["status"] == "cancelled" for task in tasks):
            return "cancelled"
        return "ready"

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self.repo.plan(plan_id)
        if not plan:
            raise GenerationPlanError("Generation plan not found")

        tasks = self.repo.tasks(plan_id)
        dependencies = self.repo.dependency_map(plan_id)
        ready = ready_task_keys(tasks, dependencies)
        self.repo.mark_ready(plan_id, ready)
        ready_set = set(ready)
        self.repo.mark_blocked(plan_id, [
            task["task_key"] for task in tasks
            if task["status"] == "ready"
            and task["task_key"] not in ready_set
            and not task.get("active_job_id")
        ])

        tasks = self.repo.tasks(plan_id)
        ready = ready_task_keys(tasks, dependencies)
        aggregate = self._aggregate_status(tasks, ready)
        if plan["status"] != aggregate:
            self.repo.update_plan_status(plan_id, aggregate)
            plan["status"] = aggregate

        plan["tasks"] = [
            {**task, "dependencies": dependencies.get(task["task_key"], [])}
            for task in tasks
        ]
        plan["ready_task_keys"] = ready
        return plan

    def list_plans(self, project_id: str) -> list[dict[str, Any]]:
        return self.repo.plans_for_project(project_id)

    def _validate_edit(self, plan_id: str, *, replacement: tuple[str, dict[str, Any]] | None = None,
                       addition: dict[str, Any] | None = None, removed: str | None = None,
                       dependencies: tuple[str, list[dict[str, str]]] | None = None) -> None:
        plan = self.get_plan(plan_id)
        definitions: list[GenerationTaskDefinition] = []
        for row in plan["tasks"]:
            if row["task_key"] == removed: continue
            value = replacement[1] if replacement and replacement[0] == row["task_key"] else row
            deps = dependencies[1] if dependencies and dependencies[0] == row["task_key"] else row.get("dependencies", [])
            definitions.append(GenerationTaskDefinition(
                key=row["task_key"], label=value.get("label", ""), generator_kind=value["generator_kind"],
                target_kind=value["target_kind"], target_key=value.get("target_key"), prompt=value.get("prompt") or {}, settings=value.get("settings") or {},
                dependencies=[GenerationDependency(item["task_key"], item.get("required_state", "generated")) for item in deps],
            ))
        if addition:
            definitions.append(GenerationTaskDefinition(
                key=addition["task_key"], label=addition.get("label", ""), generator_kind=addition["generator_kind"],
                target_kind=addition["target_kind"], target_key=addition.get("target_key"), prompt=addition.get("prompt") or {}, settings=addition.get("settings") or {},
                dependencies=[GenerationDependency(item["task_key"], item.get("required_state", "generated")) for item in addition.get("dependencies", [])],
            ))
        GenerationPlanDefinition(name=plan["name"], tasks=definitions).validate()

    def create_task(self, plan_id: str, task: dict[str, Any]) -> dict[str, Any]:
        self._validate_edit(plan_id, addition=task)
        self.repo.create_task(plan_id, task)
        self.repo.replace_dependencies(plan_id, task["task_key"], task.get("dependencies", []))
        return self.get_plan(plan_id)

    def update_task(self, plan_id: str, task_key: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.repo.task(plan_id, task_key)
        if not current: raise GenerationPlanError(f"Generation task not found: {task_key}")
        if current.get("active_job_id") or current["status"] in {"queued", "running"}: raise GenerationPlanError("Cancel the active task before editing it")
        value = {**current, **patch}
        self._validate_edit(plan_id, replacement=(task_key, value))
        self.repo.update_task_definition(plan_id, task_key, value)
        plan = self.get_plan(plan_id)
        deps = {item["task_key"]: item["dependencies"] for item in plan["tasks"]}
        self.repo.mark_stale(plan_id, [task_key, *descendant_keys(task_key, deps)])
        return self.get_plan(plan_id)

    def replace_dependencies(self, plan_id: str, task_key: str, dependencies: list[dict[str, str]]) -> dict[str, Any]:
        self._validate_edit(plan_id, dependencies=(task_key, dependencies))
        self.repo.replace_dependencies(plan_id, task_key, dependencies)
        plan = self.get_plan(plan_id)
        deps = {item["task_key"]: item["dependencies"] for item in plan["tasks"]}
        self.repo.mark_stale(plan_id, [task_key, *descendant_keys(task_key, deps)])
        return self.get_plan(plan_id)

    def delete_task(self, plan_id: str, task_key: str) -> dict[str, Any]:
        current = self.repo.task(plan_id, task_key)
        if not current: raise GenerationPlanError(f"Generation task not found: {task_key}")
        if current.get("active_job_id") or current["status"] in {"queued", "running"}: raise GenerationPlanError("Cancel the active task before deleting it")
        self._validate_edit(plan_id, removed=task_key)
        self.repo.delete_task(plan_id, task_key)
        return self.get_plan(plan_id)

    def queue_task(self, plan_id: str, task_key: str, *,
                   requested_by_user_id: str | None = None,
                   requester_name_snapshot: str | None = None) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        task = next((t for t in plan["tasks"] if t["task_key"] == task_key), None)
        if not task:
            raise GenerationPlanError(f"Generation task not found: {task_key}")
        if task_key not in set(plan["ready_task_keys"]):
            raise GenerationPlanError(f"Generation task is not ready: {task_key}")
        if task.get("active_job_id"):
            raise GenerationPlanError(f"Generation task already has an active job: {task_key}")
        job = self.data.jobs.create(
            plan["project_id"], "batch_generation",
            {"plan_id": plan_id, "task_key": task_key},
            requested_by_user_id, requester_name_snapshot,
        )
        self.repo.bind_job(plan_id, task_key, job["id"], "queued")
        self.repo.update_plan_status(plan_id, "running")
        return job

    def queue_ready(self, plan_id: str, *,
                    requested_by_user_id: str | None = None,
                    requester_name_snapshot: str | None = None) -> list[dict[str, Any]]:
        plan = self.get_plan(plan_id)
        return [
            self.queue_task(
                plan_id, key,
                requested_by_user_id=requested_by_user_id,
                requester_name_snapshot=requester_name_snapshot,
            )
            for key in plan["ready_task_keys"]
        ]

    def regenerate_task(self, plan_id: str, task_key: str, *,
                        prompt: dict[str, Any] | None = None,
                        settings: dict[str, Any] | None = None,
                        reason: str = "regenerated") -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        by_key = {task["task_key"]: task for task in plan["tasks"]}
        task = by_key.get(task_key)
        if not task:
            raise GenerationPlanError(f"Generation task not found: {task_key}")
        deps = {item["task_key"]: item["dependencies"] for item in plan["tasks"]}
        self.repo.reset_for_regeneration(
            plan_id,
            task_key,
            stale_descendant_keys=descendant_keys(task_key, deps),
            reason=reason,
            prompt=prompt,
            settings=settings,
        )
        return self.get_plan(plan_id)

    def revise_task(self, plan_id: str, task_key: str, *,
                    prompt: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        return self.regenerate_task(
            plan_id, task_key, prompt=prompt, settings=settings, reason="definition revised"
        )

    def approve_task(self, plan_id: str, task_key: str, note: str = "") -> dict[str, Any]:
        task = self.repo.task(plan_id, task_key)
        if not task:
            raise GenerationPlanError(f"Generation task not found: {task_key}")
        if task["status"] != "generated":
            raise GenerationPlanError("Only generated tasks can be approved")
        self.repo.approve_task(plan_id, task_key, note)
        return self.get_plan(plan_id)

    def approve_many(self, plan_id: str, task_keys: Iterable[str], note: str = "") -> dict[str, Any]:
        for key in task_keys:
            task = self.repo.task(plan_id, key)
            if not task or task["status"] != "generated":
                raise GenerationPlanError(f"Task is not generated and reviewable: {key}")
        for key in task_keys:
            self.repo.approve_task(plan_id, key, note)
        return self.get_plan(plan_id)

    def reject_task(self, plan_id: str, task_key: str, note: str = "") -> dict[str, Any]:
        task = self.repo.task(plan_id, task_key)
        if not task:
            raise GenerationPlanError(f"Generation task not found: {task_key}")
        if task["status"] not in {"generated", "approved"}:
            raise GenerationPlanError("Only generated/approved tasks can be rejected")
        return self.regenerate_task(
            plan_id,
            task_key,
            reason=f"rejected: {note}".strip(),
        )

    def commit_task(
        self,
        plan_id: str,
        task_key: str,
        committer: BatchTaskCommitter,
    ) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        task = next((t for t in plan["tasks"] if t["task_key"] == task_key), None)
        if not task:
            raise GenerationPlanError(f"Generation task not found: {task_key}")
        if task["status"] != "approved":
            raise GenerationPlanError("Only approved tasks can be committed")
        result = committer.commit(plan=plan, task=task)
        self.repo.commit_task(plan_id, task_key, result.metadata)
        return self.get_plan(plan_id)

    def revisions(self, plan_id: str, task_key: str) -> list[dict[str, Any]]:
        return self.repo.revisions(plan_id, task_key)
