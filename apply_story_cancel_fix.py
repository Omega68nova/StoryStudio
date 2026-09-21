from __future__ import annotations

from pathlib import Path
import shutil
import sys

TARGET = Path("backend/app/handlers/storyJobHandler.py")
BACKUP = TARGET.with_suffix(".py.cancel-fix-backup")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match in {TARGET}, found {count}. No changes were written."
        )
    return text.replace(old, new, 1)

def main() -> int:
    if not TARGET.is_file():
        print(f"Could not find {TARGET}. Run this script from the StoryStudio repo root.", file=sys.stderr)
        return 2

    original = TARGET.read_text(encoding="utf-8")
    updated = original

    updated = replace_once(
        updated,
        """            stopped_content = (
                self._complete_sentences(
                    stream_result.content
                )
            )
            if not stopped_content:
                raise asyncio.CancelledError
""",
        """            # Preserve the prose already streamed to the user.
            stopped_content = stream_result.content.strip()
            if not stopped_content:
                raise asyncio.CancelledError
""",
        "partial prose preservation",
    )

    updated = replace_once(
        updated,
        """        self._discard_materialized_input(
            context
        )
""",
        """        # Do not discard the materialized user turn here.
        #
        # scheduler.cancel() invokes this hook immediately after setting the
        # cancel event, while run() is still unwinding the text stream. The
        # running coroutine owns the decision about whether partial prose can
        # be committed. Deleting the user node here races with
        # commit_stopped_story(), whose assistant node references it as parent,
        # producing SQLite "FOREIGN KEY constraint failed".
""",
        "cancel race removal",
    )

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)

    TARGET.write_text(updated, encoding="utf-8")
    print(f"Updated {TARGET}")
    print(f"Backup:  {BACKUP}")
    print("Recommended validation:")
    print("  cd backend")
    print("  python -m compileall app")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
