from pathlib import Path
import shutil
import sys

REPLACEMENTS = {
    'planning': [
        ('once', 'from app.database import Database, new_id, utc_now\n', 'from app.database import Database, new_id, utc_now\nfrom app.data.dataProvider import DataProvider\n', 'planning import'),
        ('once', 'class PlanningService:\n    def __init__(self, db: Database, world: WorldEngine) -> None:\n        self.db, self.world = db, world\n', 'class PlanningService:\n    def __init__(\n        self,\n        db: Database,\n        world: WorldEngine,\n        *,\n        data_provider: DataProvider | None = None,\n    ) -> None:\n        self.db = db\n        self.world = world\n        self.data = data_provider or DataProvider(db)\n        self.repo = self.data.planning\n', 'planning ctor'),
        ('between', '    def create_session(self, project_id: str, settings: dict[str, Any]) -> dict[str, Any]:\n', '\n    def get_session(self, session_id: str) -> dict[str, Any]:\n', '    def create_session(self, project_id: str, settings: dict[str, Any]) -> dict[str, Any]:\n        active = self.repo.active_session(project_id)\n        if active:\n            return self.get_session(active["id"])\n        session_id = self.repo.create_session(\n            project_id,\n            normalized_settings(settings),\n            PLANNING_STAGES,\n        )\n        return self.get_session(session_id)\n', 'create_session'),
        ('between', '    def get_session(self, session_id: str) -> dict[str, Any]:\n', '\n    def world_inventory(', '    def get_session(self, session_id: str) -> dict[str, Any]:\n        session = self.repo.session(session_id)\n        if not session:\n            raise WorldValidationError("Planning session not found")\n        session["settings"] = json.loads(session.pop("settings_json"))\n        session["schema_version"] = int(session.get("schema_version") or 2)\n        session["recovery_warnings"] = json.loads(\n            session.pop("recovery_warnings_json", "[]") or "[]"\n        )\n        stages = self.repo.stages(session_id)\n        for stage in stages:\n            stage["draft"] = json.loads(stage["draft_json"]) if stage["draft_json"] else None\n            stage["approved"] = json.loads(stage["approved_json"]) if stage["approved_json"] else None\n            stage["dependency_snapshot"] = json.loads(stage.get("dependency_snapshot_json") or "{}")\n            stage["published_domains"] = json.loads(stage.get("published_domains_json") or "{}")\n            stage["conflicts"] = self.repo.conflicts_for_stage(stage["id"])\n            stage["operation"] = None\n            if stage.get("active_job_id"):\n                job = self.db.get_job(stage["active_job_id"])\n                if job:\n                    stage["operation"] = {\n                        key: job.get(key)\n                        for key in (\n                            "id", "status", "phase", "progress_message",\n                            "progress_current", "progress_total", "error",\n                            "created_at", "updated_at",\n                        )\n                    }\n        session["stages"] = stages\n        session["image_plans"] = self.repo.image_plans(session_id)\n        return session\n', 'get_session'),
        ('between', '    def conflicts_for_stage(self, stage_id: str) -> list[dict[str, Any]]:\n', '\n    def preflight(', '    def conflicts_for_stage(self, stage_id: str) -> list[dict[str, Any]]:\n        return self.repo.conflicts_for_stage(stage_id)\n', 'conflicts'),
        ('between', '    def stage_for_generation(self, session_id: str, stage_number: int) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:\n', '\n    def save_draft(', '    def stage_for_generation(\n        self,\n        session_id: str,\n        stage_number: int,\n    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:\n        session_raw = self.repo.session(session_id)\n        stage = self.repo.stage(session_id, stage_number)\n        if not session_raw or not stage:\n            raise WorldValidationError("Planning stage not found")\n        if session_raw["status"] != "active":\n            raise WorldValidationError("Planning session is not active")\n        if self.repo.has_unapproved_prior(session_id, stage_number):\n            raise WorldValidationError("Approve earlier planning stages first")\n        stage["description"] = next(\n            item[2] for item in PLANNING_STAGES if item[0] == stage_number\n        )\n        approved = self.repo.prior_stages(\n            session_id,\n            stage_number,\n            statuses=("approved", "skipped", "stale"),\n        )\n        return session_raw, stage, approved\n', 'stage_for_generation'),
        ('between', '    def save_draft(self, stage_id: str, draft: dict[str, Any]) -> dict[str, Any]:\n', '\n    @staticmethod\n    def validate_draft', '    def save_draft(self, stage_id: str, draft: dict[str, Any]) -> dict[str, Any]:\n        stage = self.repo.stage_with_settings(stage_id)\n        if not stage:\n            raise WorldValidationError("Planning stage not found")\n        validate_stage(\n            int(stage["stage_number"]),\n            draft,\n            json.loads(stage["settings_json"]),\n        )\n        return self.repo.save_draft(stage_id, draft)\n\n    def save_generated_draft(\n        self,\n        stage_id: str,\n        job_id: str,\n        draft: dict[str, Any],\n    ) -> bool:\n        stage = self.repo.stage_with_settings(stage_id)\n        if not stage:\n            raise WorldValidationError("Planning stage not found")\n        validate_stage(\n            int(stage["stage_number"]),\n            draft,\n            json.loads(stage["settings_json"]),\n        )\n        return self.repo.save_generated_draft(stage_id, job_id, draft)\n\n    def save_invalid_generated_draft(\n        self,\n        stage_id: str,\n        job_id: str,\n        raw: str,\n        error: str,\n    ) -> bool:\n        return self.repo.save_invalid_generated_draft(\n            stage_id,\n            job_id,\n            raw,\n            error,\n        )\n', 'draft persistence'),
        ('between', '    def reopen_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n', '\n    def skip_stage(', '    def reopen_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n        session = self.repo.session(session_id)\n        stage = self.repo.stage(session_id, stage_number)\n        if not session or not stage:\n            raise WorldValidationError("Planning stage not found")\n        if stage["status"] in {"queued", "generating"}:\n            raise WorldValidationError(\n                "Cancel active planning generation before reopening a stage"\n            )\n        self.repo.reopen_stage(\n            session_id=session_id,\n            stage_id=stage["id"],\n            stage_number=stage_number,\n            default_draft=empty_draft(stage_number),\n        )\n        return self.get_session(session_id)\n', 'reopen'),
        ('between', '    def skip_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n', '\n    def dependency_impact(', '    def skip_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n        _session, stage, approved = self.stage_for_generation(\n            session_id,\n            stage_number,\n        )\n        if stage["status"] in {"queued", "generating"}:\n            raise WorldValidationError(\n                "Cancel active generation before skipping this stage"\n            )\n        draft = empty_draft(stage_number)\n        self.repo.skip_stage(\n            session_id=session_id,\n            stage_id=stage["id"],\n            stage_number=stage_number,\n            draft=draft,\n            revision_hash=stable_hash(draft),\n            dependencies=dependency_snapshot(approved, stage_number),\n            domains=published_domains(stage_number, draft),\n            stage_count=len(PLANNING_STAGES),\n        )\n        return self.get_session(session_id)\n', 'skip'),
        ('between', '    def dependency_impact(self, session_id: str, stage_number: int) -> dict[str, Any]:\n', '\n    def revalidate_stage(', '    def dependency_impact(self, session_id: str, stage_number: int) -> dict[str, Any]:\n        affected: list[dict[str, Any]] = []\n        dirty = set(STAGE_PUBLISHES[stage_number])\n        for later in self.repo.later_stages(session_id, stage_number):\n            later_number = int(later["stage_number"])\n            if STAGE_CONSUMES[later_number] & dirty:\n                affected.append({\n                    "stage_number": later["stage_number"],\n                    "kind": later["kind"],\n                    "status": later["status"],\n                })\n                dirty.update(STAGE_PUBLISHES[later_number])\n        return {\n            "stage_number": stage_number,\n            "changed_domains": sorted(STAGE_PUBLISHES[stage_number]),\n            "affected_stages": affected,\n        }\n', 'dependency'),
        ('between', '    def revalidate_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n', '\n    def prepare_image_stage(', '    def revalidate_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:\n        stage = self.repo.stage(session_id, stage_number)\n        if not stage or stage["status"] != "stale":\n            raise WorldValidationError("Only stale stages can be revalidated")\n        current = dependency_snapshot(\n            self.repo.prior_stages(session_id, stage_number),\n            stage_number,\n        )\n        approved = json.loads(stage.get("approved_json") or "{}")\n        validate_stage(stage_number, approved)\n        self.repo.revalidate_stage(stage["id"], current)\n        return self.get_session(session_id)\n', 'revalidate'),
    ],
    'handler': [
        ('once', 'from app.database import new_id, utc_now\n', 'from app.database import new_id, utc_now\nfrom app.data.dataProvider import DataProvider\n', 'handler import'),
        ('once', '        planning = PlanningService(context.db, world)\n', '        data = DataProvider(context.db)\n        planning = PlanningService(\n            context.db,\n            world,\n            data_provider=data,\n        )\n        planning_repo = data.planning\n', 'handler setup'),
        ('once', '        context.db.execute(\n            "UPDATE planning_stages "\n            "SET status=\'generating\', updated_at=? "\n            "WHERE id=? AND active_job_id=?",\n            (\n                utc_now(),\n                stage["id"],\n                context.job_id,\n            ),\n        )\n', '        if not planning_repo.mark_generating(\n            stage["id"],\n            context.job_id,\n        ):\n            context.db.update_job(\n                context.job_id,\n                "cancelled",\n                error="Superseded planning revision",\n            )\n            return\n', 'mark generating'),
        ('once', '        current = context.db.fetch_one(\n            "SELECT active_job_id FROM planning_stages WHERE id=?",\n            (stage["id"],),\n        )\n        if (\n            not current\n            or current["active_job_id"] != context.job_id\n        ):\n', '        if planning_repo.active_job_id(stage["id"]) != context.job_id:\n', 'active job check'),
    ],
    'main': [
        ('between', '@app.get("/api/projects/{project_id}/planning")\n', '\n\n@app.post("/api/planning/{session_id}/stages/{stage_number}/preflight")\n', '@app.get("/api/projects/{project_id}/planning")\nasync def get_planning_session(project_id: str) -> dict[str, Any] | None:\n    require_project(project_id)\n    session_id = data.planning.latest_session_id(project_id)\n    return scheduler.planning.get_session(session_id) if session_id else None\n', 'get planning session'),
        ('once', '    now, revision_id = utc_now(), new_id()\n    db.execute(\n        "INSERT INTO planning_stage_revisions(id, stage_id, job_id, prompt, status, created_at, updated_at) VALUES (?, ?, ?, ?, \'queued\', ?, ?)",\n        (revision_id, stage["id"], job["id"], human_prompt, now, now),\n    )\n    db.execute(\n        "UPDATE planning_stages SET human_prompt = ?, status = \'queued\', active_job_id = ?, updated_at = ? WHERE id = ?",\n        (human_prompt, job["id"], now, stage["id"]),\n    )\n', '    data.planning.queue_stage_generation(\n        stage_id=stage["id"],\n        job_id=job["id"],\n        prompt=human_prompt,\n    )\n', 'queue generation'),
        ('between', '@app.get("/api/planning/{session_id}/revisions")\n', '\n\n@app.patch("/api/planning/image-plans/{plan_id}")\n', '@app.get("/api/planning/{session_id}/revisions")\nasync def planning_revision_history(session_id: str) -> list[dict[str, Any]]:\n    if not data.planning.session_exists(session_id):\n        raise HTTPException(404, "Planning session not found")\n    return data.planning.revision_history(session_id)\n', 'revision history'),
        ('between', '@app.patch("/api/planning/image-plans/{plan_id}")\n', '\n\n@app.delete("/api/planning/image-plans/{plan_id}", status_code=204)\n', '@app.patch("/api/planning/image-plans/{plan_id}")\nasync def update_planning_image_plan(\n    plan_id: str,\n    request: PlanningImagePlanUpdate,\n) -> dict[str, Any]:\n    plan = data.planning.image_plan(plan_id)\n    if not plan:\n        raise HTTPException(404, "Planning image not found")\n    if plan["status"] == "queued":\n        raise HTTPException(409, "Wait for or cancel the active image job")\n    workflow = (\n        data.workflows.get(request.workflow_preset_id)\n        if request.workflow_preset_id\n        else None\n    )\n    status = (\n        "ready"\n        if workflow and workflow["validation_status"] == "valid"\n        else "draft"\n    )\n    revision = hashlib.sha256(\n        json.dumps(\n            request.model_dump(),\n            sort_keys=True,\n            separators=(",", ":"),\n        ).encode()\n    ).hexdigest()\n    return data.planning.update_image_plan(\n        plan_id,\n        prompt=request.prompt,\n        negative_prompt=request.negative_prompt,\n        workflow_preset_id=request.workflow_preset_id,\n        width=request.width,\n        height=request.height,\n        prompt_revision=revision,\n        status=status,\n    )\n', 'image update'),
        ('between', '@app.delete("/api/planning/image-plans/{plan_id}", status_code=204)\n', '\n\nasync def _queue_planning_image', '@app.delete("/api/planning/image-plans/{plan_id}", status_code=204)\nasync def delete_planning_image_plan(plan_id: str) -> None:\n    plan = data.planning.image_plan(plan_id)\n    if not plan:\n        raise HTTPException(404, "Planning image not found")\n    if plan["status"] == "queued":\n        raise HTTPException(409, "Wait for or cancel the active image job")\n    data.planning.delete_image_plan(plan_id)\n', 'image delete'),
        ('once', '    plan = db.fetch_one("SELECT * FROM planning_image_plans WHERE id=?", (plan_id,))\n', '    plan = data.planning.image_plan(plan_id)\n', 'image queue lookup'),
        ('once', '    db.execute("UPDATE planning_image_plans SET status=\'queued\',media_asset_id=?,generation_job_id=?,error=NULL,updated_at=? WHERE id=?", (asset_id, job["id"], now, plan_id))\n', '    data.planning.mark_image_plan_queued(plan_id, media_asset_id=asset_id, generation_job_id=job["id"])\n', 'image queued'),
        ('between', '@app.post("/api/planning/{session_id}/images/generate", status_code=202)\n', '\n\n@app.post("/api/planning/{session_id}/stages/{stage_number}/reset")\n', '@app.post("/api/planning/{session_id}/images/generate", status_code=202)\nasync def generate_planning_images(\n    session_id: str,\n    request: PlanningImageGenerateBatch,\n) -> dict[str, Any]:\n    if not data.planning.session_exists(session_id):\n        raise HTTPException(404, "Planning session not found")\n    ids = request.plan_ids or data.planning.ready_image_plan_ids(session_id)\n    known = data.planning.image_plan_ids(session_id)\n    if not set(ids) <= known:\n        raise HTTPException(\n            422,\n            "Image selection contains a plan from another workshop",\n        )\n    jobs: list[dict[str, Any]] = []\n    failures: list[dict[str, Any]] = []\n    for plan_id in dict.fromkeys(ids):\n        try:\n            jobs.append(await _queue_planning_image(plan_id))\n        except HTTPException as exc:\n            failures.append({"plan_id": plan_id, "error": str(exc.detail)})\n    return {"jobs": jobs, "failures": failures}\n', 'image batch'),
        ('once', '    db.execute("DELETE FROM planning_approval_claims WHERE stage_id=?", (stage["id"],))\n    db.execute("UPDATE planning_stages SET status=\'pending\',draft_json=NULL,raw_draft_text=NULL,validation_error=NULL,active_job_id=NULL,updated_at=? WHERE id=?", (utc_now(), stage["id"]))\n', '    data.planning.reset_stage(stage["id"])\n', 'reset stage'),
        ('between', '@app.delete("/api/planning/{session_id}/revisions")\n', '\n\n@app.get("/api/projects/{project_id}/reviews")\n', '@app.delete("/api/planning/{session_id}/revisions")\nasync def clear_planning_revisions(session_id: str) -> dict[str, int]:\n    session = data.planning.session(session_id)\n    if not session:\n        raise HTTPException(404, "Planning session not found")\n    try:\n        lifecycle.require_idle(session["project_id"])\n    except LifecycleConflict as exc:\n        raise HTTPException(\n            409,\n            {"message": str(exc), "recovery_actions": exc.actions},\n        ) from exc\n    return {"removed": data.planning.clear_revisions(session_id)}\n', 'clear revisions'),
    ],
}


REPLACEMENTS["handler"].extend([
    (
        "once",
        """        now = utc_now()
        context.db.execute(
            "INSERT INTO planning_stage_revisions"
            "(id,stage_id,job_id,prompt,status,created_at,updated_at) "
            "VALUES(?,?,?,?, 'queued',?,?)",
            (
                new_id(),
                next_stage["id"],
                next_job["id"],
                shared_prompt,
                now,
                now,
            ),
        )
        context.db.execute(
            "UPDATE planning_stages "
            "SET human_prompt=?, status='queued', "
            "active_job_id=?, updated_at=? WHERE id=?",
            (
                shared_prompt,
                next_job["id"],
                now,
                next_stage["id"],
            ),
        )
""",
        """        planning.repo.queue_stage_generation(
            stage_id=next_stage["id"],
            job_id=next_job["id"],
            prompt=shared_prompt,
        )
""",
        "automation queue persistence",
    ),
    (
        "between",
        "    def _finish_planning_stage(\n",
        "\n    # ------------------------------------------------------------------\n    # Metrics",
        """    def _finish_planning_stage(
        self,
        context: JobExecutionContext,
        status: str,
    ) -> None:
        payload = context.payload
        session_id = payload.get("session_id")
        stage_number = payload.get("stage_number")
        if session_id is None or stage_number is None:
            return
        DataProvider(context.db).planning.finish_generation(
            session_id=str(session_id),
            stage_number=int(stage_number),
            job_id=context.job_id,
            status=status,
        )

""",
        "finish planning stage",
    ),
])

FILES = {
    "planning": Path("backend/app/services/planning.py"),
    "handler": Path("backend/app/handlers/planningJobHandler.py"),
    "main": Path("backend/app/main.py"),
}

def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

def between(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start] + replacement + text[end:]

def main():
    for path in FILES.values():
        if not path.is_file():
            print(f"Missing {path}; run from StoryStudio repo root.", file=sys.stderr)
            return 2
    for key, path in FILES.items():
        text = path.read_text(encoding="utf-8")
        original = text
        for item in REPLACEMENTS[key]:
            if item[0] == 'once':
                _, old, new, label = item
                if new not in text:
                    text = once(text, old, new, label)
            else:
                _, start, end, replacement, label = item
                if replacement not in text:
                    text = between(text, start, end, replacement, label)
        if text != original:
            backup = path.with_suffix(path.suffix + '.phase3b-backup')
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(text, encoding="utf-8")
            print(f"Updated {path}")
    print('Phase 3B planning-control integration applied.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
