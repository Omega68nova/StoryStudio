from pathlib import Path
import shutil
import sys

HANDLER = Path("backend/app/handlers/batchGenerationJobHandler.py")

def main():
    if not HANDLER.is_file():
        print("Run from StoryStudio repo root after Slice 4.", file=sys.stderr)
        return 2

    text = HANDLER.read_text(encoding="utf-8")
    original = text

    imp = (
        "from app.services.planningBatchTaskExecutor import "
        "PlanningBatchTaskExecutor\n"
    )
    marker = "from app.services.runtimes import RuntimeFailure\n"
    if imp not in text:
        text = text.replace(marker, marker + imp, 1)

    needle = (
        "        messages = prompt.get(\"messages\")\n"
    )
    branch = '''        if bool(settings.get("planning_bridge")):
            result = await PlanningBatchTaskExecutor().generate(
                context,
                task,
            )
            if result.get("invalid_structured_output"):
                repo.finish_task(
                    plan_id,
                    task["task_key"],
                    context.job_id,
                    status="failed",
                    result=result,
                    error=str(result.get("validation_error") or "Invalid structured planning output"),
                )
                context.db.update_job(
                    context.job_id,
                    "failed",
                    result={
                        "plan_id": plan_id,
                        "task_key": task["task_key"],
                        "result": result,
                    },
                    error=str(result.get("validation_error") or "Invalid structured planning output"),
                )
                return

            repo.finish_task(
                plan_id,
                task["task_key"],
                context.job_id,
                status="generated",
                result=result,
            )
            context.db.update_job(
                context.job_id,
                "completed",
                result={
                    "plan_id": plan_id,
                    "task_key": task["task_key"],
                    "result": result,
                },
            )
            return

'''
    if branch not in text:
        if needle not in text:
            raise RuntimeError("Could not locate _run_text message marker")
        text = text.replace(needle, branch + needle, 1)

    if text != original:
        backup = HANDLER.with_suffix(
            HANDLER.suffix + ".phase4-slice5-backup"
        )
        if not backup.exists():
            shutil.copy2(HANDLER, backup)
        HANDLER.write_text(text, encoding="utf-8")
        print(f"Updated {HANDLER}")

    print("Phase 4 Slice 5 applied.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
