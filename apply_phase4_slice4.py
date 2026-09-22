from __future__ import annotations

from pathlib import Path
import shutil
import sys

REPOSITORY = Path("backend/app/data/batchGenerationRepository.py")


def main() -> int:
    if not REPOSITORY.is_file():
        print(
            "Run from the StoryStudio repository root after Phase 4 Slice 3.",
            file=sys.stderr,
        )
        return 2

    text = REPOSITORY.read_text(encoding="utf-8")
    if "    def plan_by_source(" in text:
        print("Planning bridge repository methods already installed.")
        return 0

    marker = "    def update_plan_status("
    pos = text.find(marker)
    if pos < 0:
        raise RuntimeError(
            "Could not locate BatchGenerationRepository.update_plan_status()."
        )

    methods = """    def plan_by_source(
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

"""
    updated = text[:pos] + methods + text[pos:]

    backup = REPOSITORY.with_suffix(
        REPOSITORY.suffix + ".phase4-slice4-backup"
    )
    if not backup.exists():
        shutil.copy2(REPOSITORY, backup)
    REPOSITORY.write_text(updated, encoding="utf-8")
    print(f"Updated {REPOSITORY}")
    print("Phase 4 Slice 4 integration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
