from __future__ import annotations

from pathlib import Path
import shutil
import sys

REPOSITORY = Path("backend/app/data/batchGenerationRepository.py")


def main() -> int:
    if not REPOSITORY.is_file():
        print(
            "Run this from the StoryStudio repository root after "
            "Phase 4 Slice 2.",
            file=sys.stderr,
        )
        return 2

    text = REPOSITORY.read_text(encoding="utf-8")
    if "    def set_task_status(" in text:
        print("BatchGenerationRepository.set_task_status already present.")
        return 0

    marker = "    def bind_job("
    position = text.find(marker)
    if position < 0:
        raise RuntimeError(
            "Could not locate BatchGenerationRepository.bind_job(). "
            "The file does not match Phase 4 Slice 2."
        )

    method = '''    def set_task_status(
        self,
        plan_id: str,
        task_key: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE generation_plan_tasks SET "
            "status=?,result_json=COALESCE(?,result_json),error=?,"
            "active_job_id=NULL,updated_at=? "
            "WHERE plan_id=? AND task_key=?",
            (
                status,
                json.dumps(result) if result is not None else None,
                error,
                utc_now(),
                plan_id,
                task_key,
            ),
        )

'''
    updated = text[:position] + method + text[position:]

    backup = REPOSITORY.with_suffix(
        REPOSITORY.suffix + ".phase4-slice2-hotfix1-backup"
    )
    if not backup.exists():
        shutil.copy2(REPOSITORY, backup)
    REPOSITORY.write_text(updated, encoding="utf-8")
    print(f"Updated {REPOSITORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
