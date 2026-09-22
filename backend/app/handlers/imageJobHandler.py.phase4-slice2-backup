from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database import utc_now
from app.functions.imageGen import (
    ImageGenerationRequest,
    ImageWorkflow,
    generate_image,
)
from app.schemas import WorkflowMappings
from app.services.job_handlers import BaseJobHandler, JobExecutionContext
from app.services.runtimes import RuntimeFailure
from app.services.workflow import validate_workflow


@dataclass(slots=True, frozen=True)
class ResolvedImageJob:
    workflow: ImageWorkflow
    request: ImageGenerationRequest
    preset_id: str
    media_kind: str | None


class ImageJobHandler(BaseJobHandler):
    """Runs StoryStudio `generation_jobs.kind == "image"` jobs.

    Responsibilities moved here from the legacy GenerationScheduler:
      * workflow preset lookup/validation status
      * payload -> generic ImageGenerationRequest conversion
      * progress publication
      * image persistence
      * image_suggestions updates
      * entity_media_assets updates
      * planning_image_plans updates
      * environment background-ready notification
      * image-domain cancellation/failure cleanup

    GPU/model ownership remains in AIGeneratorManager/generate_image().
    """

    async def run(self, context: JobExecutionContext) -> None:
        resolved = await self._resolve(context)

        context.db.update_job(context.job_id, "switching")
        await context.state(
            "switching_to_image",
            "Validated image job requires exclusive GPU ownership",
        )

        async def progress(update: dict[str, Any]) -> None:
            await context.state("generating_image", "Generating image")
            context.db.update_job_progress(
                context.job_id,
                "generating_image",
                "Generating image",
                update.get("value"),
                update.get("max"),
            )
            await context.events.publish(
                "job",
                {
                    "job_id": context.job_id,
                    "status": "running",
                    **update,
                },
            )

        outputs = await generate_image(
            context.ai,
            resolved.workflow,
            resolved.request,
            cancel_event=context.cancel_event,
            progress=progress,
            filename_prefix=f"StoryStudio_{context.job_id}",
        )

        await self._job_phase(
            context,
            "saving_image",
            "Saving generated image",
        )

        paths = self._persist_outputs(context, outputs)
        if not paths:
            raise RuntimeFailure(
                "Image generation finished without a persisted output"
            )

        self._commit_domain_records(
            context,
            paths,
        )

        result = {
            "image_paths": paths,
            "suggestion_id": context.payload.get("suggestion_id"),
            "media_asset_id": context.payload.get("media_asset_id"),
            "prompt_references": context.payload.get(
                "prompt_references",
                [],
            ),
        }

        context.db.update_job_progress(
            context.job_id,
            "completed",
            "Image ready",
            1,
            1,
        )
        context.db.update_job(
            context.job_id,
            "completed",
            result=result,
        )

        await context.events.publish(
            "image",
            {
                "job_id": context.job_id,
                **result,
            },
        )

        background_id = context.payload.get(
            "environment_background_id"
        )
        if background_id:
            await context.events.publish(
                "environment",
                {
                    "project_id": context.project_id,
                    "action": "background_ready",
                    "background_id": background_id,
                },
            )

        await context.events.publish(
            "job",
            {
                "job_id": context.job_id,
                "status": "completed",
                "result": result,
            },
        )

    async def cancel(self, context: JobExecutionContext) -> None:
        """Interrupt ComfyUI and move image-owned records to cancelled."""
        if context.ai.comfy is not None:
            try:
                await context.ai.interrupt_image()
            except Exception:
                # Cancellation cleanup should still update DB state if the
                # runtime is already gone.
                pass

        self._finish_targets(
            context,
            "cancelled",
            error="Image generation was cancelled",
        )

        latest = context.db.get_job(context.job_id) or context.job
        if latest.get("status") not in {
            "completed",
            "failed",
            "cancelled",
        }:
            context.db.update_job(
                context.job_id,
                "cancelled",
                error="Image generation was cancelled",
            )

        await context.events.publish(
            "image",
            {
                "job_id": context.job_id,
                "status": "cancelled",
            },
        )

    async def failed(
        self,
        context: JobExecutionContext,
        error: BaseException,
    ) -> None:
        message = str(error) or type(error).__name__

        self._finish_targets(
            context,
            "failed",
            error=message,
        )

        latest = context.db.get_job(context.job_id) or context.job
        if latest.get("status") not in {
            "completed",
            "failed",
            "cancelled",
        }:
            context.db.update_job(
                context.job_id,
                "failed",
                error=message,
            )

        await context.events.publish(
            "image",
            {
                "job_id": context.job_id,
                "status": "failed",
                "error": message,
            },
        )

    # ------------------------------------------------------------------
    # Resolution / validation
    # ------------------------------------------------------------------

    async def _resolve(
        self,
        context: JobExecutionContext,
    ) -> ResolvedImageJob:
        payload = context.payload
        preset_id = str(payload.get("preset_id") or "")
        if not preset_id:
            raise RuntimeFailure(
                "Image job has no workflow preset"
            )

        preset_raw = context.db.fetch_one(
            "SELECT * FROM workflow_presets WHERE id = ?",
            (preset_id,),
        )
        if not preset_raw:
            raise RuntimeFailure(
                "The selected workflow preset no longer exists"
            )

        graph = json.loads(preset_raw["graph_json"])
        mappings = WorkflowMappings.model_validate(
            json.loads(preset_raw["mappings_json"])
        )

        # Validate before requesting exclusive GPU ownership, matching the old
        # scheduler's fail-fast behavior.
        comfy = await context.ai.ensure_comfy_runtime()
        mapping_errors = validate_workflow(
            graph,
            mappings,
            await comfy.object_info(),
        )

        context.db.execute(
            "UPDATE workflow_presets "
            "SET validation_status = ?, validation_error = ?, updated_at = ? "
            "WHERE id = ?",
            (
                "invalid" if mapping_errors else "valid",
                "; ".join(mapping_errors) or None,
                utc_now(),
                preset_id,
            ),
        )

        if mapping_errors:
            raise RuntimeFailure(
                "Workflow validation failed: "
                + "; ".join(mapping_errors)
            )

        media_kind = self._media_kind(context)
        make_transparent = self._transparent_requested(
            context,
            media_kind,
            mappings,
        )

        workflow = ImageWorkflow(
            graph=graph,
            mappings=mappings,
        )

        values = dict(payload.get("values") or {})
        positive = str(
            values.pop(
                "prompt",
                values.pop("positive_prompt", ""),
            )
            or ""
        ).strip()
        if not positive:
            raise RuntimeFailure(
                "Image job has no positive prompt"
            )

        request = ImageGenerationRequest(
            positive_prompt=positive,
            negative_prompt=str(
                values.pop("negative_prompt", "") or ""
            ),
            width=self._optional_int(values.pop("width", None)),
            height=self._optional_int(values.pop("height", None)),
            make_transparent=make_transparent,
            seed=self._optional_int(values.pop("seed", None)),
            steps=self._optional_int(values.pop("steps", None)),
            guidance=self._optional_float(
                values.pop("guidance", None)
            ),
            checkpoint=self._optional_str(
                values.pop("checkpoint", None)
            ),
        )

        return ResolvedImageJob(
            workflow=workflow,
            request=request,
            preset_id=preset_id,
            media_kind=media_kind,
        )

    def _media_kind(
        self,
        context: JobExecutionContext,
    ) -> str | None:
        asset_id = context.payload.get("media_asset_id")
        if not asset_id:
            return None

        row = context.db.fetch_one(
            "SELECT kind FROM entity_media_assets WHERE id=?",
            (asset_id,),
        )
        return str(row["kind"]) if row and row.get("kind") else None

    @staticmethod
    def _transparent_requested(
        context: JobExecutionContext,
        media_kind: str | None,
        mappings: WorkflowMappings,
    ) -> bool:
        payload = context.payload

        # Explicit payload wins, enabling a gradual API migration.
        if "make_transparent" in payload:
            return bool(payload["make_transparent"])

        values = payload.get("values") or {}
        if "make_transparent" in values:
            return bool(values["make_transparent"])

        # Safe automatic behavior: typed character/icon media uses the
        # transparent path only when the selected workflow actually defines it.
        # Existing workflows without the mapping remain unchanged.
        return bool(
            mappings.transparent_image_output
            and media_kind in {"portrait", "full_body", "icon"}
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return None if value in (None, "") else int(value)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        return None if value in (None, "") else float(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_outputs(
        self,
        context: JobExecutionContext,
        outputs: list[tuple[bytes, str]],
    ) -> list[str]:
        project_dir = (
            context.db.images_dir / context.project_id
        )
        project_dir.mkdir(parents=True, exist_ok=True)

        paths: list[str] = []
        for index, (data, suffix) in enumerate(outputs):
            safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
            path = (
                project_dir
                / f"{context.job_id}-{index}{safe_suffix}"
            )
            path.write_bytes(data)
            paths.append(
                str(
                    path.relative_to(context.db.data_dir)
                ).replace("\\", "/")
            )

        return paths

    def _commit_domain_records(
        self,
        context: JobExecutionContext,
        paths: list[str],
    ) -> None:
        payload = context.payload
        first_path = paths[0]
        now = utc_now()

        suggestion_id = payload.get("suggestion_id")
        if suggestion_id:
            context.db.execute(
                "UPDATE image_suggestions "
                "SET status='generated', image_path=?, updated_at=? "
                "WHERE id=?",
                (
                    first_path,
                    now,
                    suggestion_id,
                ),
            )

        asset_id = payload.get("media_asset_id")
        if not asset_id:
            return

        context.db.execute(
            "UPDATE entity_media_assets "
            "SET source='generated', status='generated', "
            "file_path=?, mime_type=?, updated_at=? "
            "WHERE id=?",
            (
                first_path,
                self._mime_type(first_path),
                now,
                asset_id,
            ),
        )

        plan_id = payload.get("planning_image_plan_id")
        if not plan_id:
            plan = context.db.fetch_one(
                "SELECT id FROM planning_image_plans "
                "WHERE media_asset_id=? AND generation_job_id=?",
                (
                    asset_id,
                    context.job_id,
                ),
            )
            plan_id = plan.get("id") if plan else None

        if plan_id:
            context.db.execute(
                "UPDATE planning_image_plans "
                "SET status='generated', media_asset_id=?, "
                "error=NULL, updated_at=? WHERE id=?",
                (
                    asset_id,
                    now,
                    plan_id,
                ),
            )

    @staticmethod
    def _mime_type(path: str) -> str:
        suffix = Path(path).suffix.casefold()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "application/octet-stream")

    # ------------------------------------------------------------------
    # Cancellation / failure cleanup
    # ------------------------------------------------------------------

    def _finish_targets(
        self,
        context: JobExecutionContext,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        payload = context.payload
        now = utc_now()

        suggestion_id = payload.get("suggestion_id")
        if suggestion_id:
            context.db.execute(
                "UPDATE image_suggestions "
                "SET status=?, updated_at=? WHERE id=?",
                (
                    status,
                    now,
                    suggestion_id,
                ),
            )

        asset_id = payload.get("media_asset_id")
        if asset_id:
            context.db.execute(
                "UPDATE entity_media_assets "
                "SET status=?, updated_at=? WHERE id=?",
                (
                    status,
                    now,
                    asset_id,
                ),
            )

        plan_id = payload.get("planning_image_plan_id")
        if not plan_id and asset_id:
            plan = context.db.fetch_one(
                "SELECT id FROM planning_image_plans "
                "WHERE media_asset_id=? AND generation_job_id=?",
                (
                    asset_id,
                    context.job_id,
                ),
            )
            plan_id = plan.get("id") if plan else None

        if plan_id:
            context.db.execute(
                "UPDATE planning_image_plans "
                "SET status=?, error=?, updated_at=? "
                "WHERE id=?",
                (
                    status,
                    error,
                    now,
                    plan_id,
                ),
            )

    async def _job_phase(
        self,
        context: JobExecutionContext,
        phase: str,
        message: str,
    ) -> None:
        context.db.update_job_progress(
            context.job_id,
            phase,
            message,
        )
        await context.events.publish(
            "job",
            {
                "job_id": context.job_id,
                "status": "running",
                "stage": phase,
                "message": message,
            },
        )
