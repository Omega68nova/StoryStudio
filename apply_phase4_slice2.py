from __future__ import annotations

from pathlib import Path
import shutil
import sys

SCHEDULER = Path("backend/app/services/scheduler.py")
IMAGE_HANDLER = Path("backend/app/handlers/imageJobHandler.py")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase4-slice2-backup")
    if not target.exists():
        shutil.copy2(path, target)


def patch_scheduler() -> None:
    text = SCHEDULER.read_text(encoding="utf-8")
    original = text

    import_marker = "            from app.handlers.storyJobHandler import StoryJobHandler\n"
    import_line = "            from app.handlers.batchGenerationJobHandler import BatchGenerationJobHandler\n"
    if import_line not in text:
        if import_marker not in text:
            raise RuntimeError("Scheduler handler import marker not found")
        text = text.replace(import_marker, import_marker + import_line, 1)

    registration_marker = '                "planning": PlanningJobHandler(),\n'
    registration_line = '                "batch_generation": BatchGenerationJobHandler(),\n'
    if registration_line not in text:
        if registration_marker not in text:
            raise RuntimeError("Scheduler handler registration marker not found")
        text = text.replace(registration_marker, registration_marker + registration_line, 1)

    if text != original:
        backup(SCHEDULER)
        SCHEDULER.write_text(text, encoding="utf-8")
        print(f"Updated {SCHEDULER}")


def patch_image_handler() -> None:
    text = IMAGE_HANDLER.read_text(encoding="utf-8")
    original = text

    success_marker = """        self._commit_domain_records(\n            context,\n            paths,\n        )\n\n        result = {\n"""
    if "self._finish_batch_task(\n            context,\n            \"generated\"" not in text:
        if success_marker not in text:
            raise RuntimeError("Image success marker not found")
        text = text.replace(
            success_marker,
            """        self._commit_domain_records(\n            context,\n            paths,\n        )\n        self._finish_batch_task(\n            context,\n            \"generated\",\n            result={\"image_paths\": paths},\n        )\n\n        result = {\n""",
            1,
        )

    cancel_marker = """        self._finish_targets(\n            context,\n            \"cancelled\",\n            error=\"Image generation was cancelled\",\n        )\n"""
    if "self._finish_batch_task(\n            context,\n            \"cancelled\"" not in text:
        if cancel_marker not in text:
            raise RuntimeError("Image cancel marker not found")
        text = text.replace(
            cancel_marker,
            cancel_marker + """        self._finish_batch_task(\n            context,\n            \"cancelled\",\n            error=\"Image generation was cancelled\",\n        )\n""",
            1,
        )

    fail_marker = """        self._finish_targets(\n            context,\n            \"failed\",\n            error=message,\n        )\n"""
    if "self._finish_batch_task(\n            context,\n            \"failed\"" not in text:
        if fail_marker not in text:
            raise RuntimeError("Image failure marker not found")
        text = text.replace(
            fail_marker,
            fail_marker + """        self._finish_batch_task(\n            context,\n            \"failed\",\n            error=message,\n        )\n""",
            1,
        )

    if "    def _finish_batch_task(" not in text:
        helper = """    def _finish_batch_task(\n        self,\n        context: JobExecutionContext,\n        status: str,\n        *,\n        result: dict[str, Any] | None = None,\n        error: str | None = None,\n    ) -> None:\n        plan_id = context.payload.get(\"batch_generation_plan_id\")\n        task_key = context.payload.get(\"batch_generation_task_key\")\n        if not plan_id or not task_key:\n            return\n        from app.data.dataProvider import DataProvider\n        DataProvider(context.db).batch_generation.finish_task(\n            str(plan_id),\n            str(task_key),\n            context.job_id,\n            status=status,\n            result=result,\n            error=error,\n        )\n\n"""
        marker = "    async def _job_phase(\n"
        if marker not in text:
            raise RuntimeError("Image helper insertion marker not found")
        text = text.replace(marker, helper + marker, 1)

    if text != original:
        backup(IMAGE_HANDLER)
        IMAGE_HANDLER.write_text(text, encoding="utf-8")
        print(f"Updated {IMAGE_HANDLER}")


def main() -> int:
    if not SCHEDULER.is_file() or not IMAGE_HANDLER.is_file():
        print("Run from the StoryStudio repo root after Phase 4 Slice 1.", file=sys.stderr)
        return 2
    patch_scheduler()
    patch_image_handler()
    print("Phase 4 Slice 2 integration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
