from __future__ import annotations

from pathlib import Path
import shutil
import sys

TARGET = Path("backend/app/handlers/storyJobHandler.py")
BACKUP = TARGET.with_suffix(".py.cancel-fix-backup")


def main() -> int:
    if not TARGET.is_file():
        print(
            f"Could not find {TARGET}. Run this script from the StoryStudio repo root.",
            file=sys.stderr,
        )
        return 2

    original = TARGET.read_text(encoding="utf-8")
    updated = original

    # ------------------------------------------------------------------
    # 1) Preserve the actual text already streamed when Stop is pressed.
    # ------------------------------------------------------------------
    old_stop = """            stopped_content = (
                self._complete_sentences(
                    stream_result.content
                )
            )
            if not stopped_content:
                raise asyncio.CancelledError
"""
    new_stop = """            # Preserve exactly the prose already streamed to the user.
            stopped_content = stream_result.content.strip()
            if not stopped_content:
                raise asyncio.CancelledError
"""

    stop_count = updated.count(old_stop)
    if stop_count == 1:
        updated = updated.replace(old_stop, new_stop, 1)
    elif new_stop not in updated:
        raise RuntimeError(
            "Could not uniquely locate the stopped-content block. "
            "No changes were written."
        )

    # ------------------------------------------------------------------
    # 2) Remove destructive cleanup ONLY from async def cancel(...).
    #    Keep _discard_materialized_input() in failed(...).
    # ------------------------------------------------------------------
    cancel_start = updated.find(
        "    async def cancel(\n"
    )
    if cancel_start < 0:
        raise RuntimeError(
            "Could not find StoryJobHandler.cancel(). No changes were written."
        )

    failed_start = updated.find(
        "    async def failed(\n",
        cancel_start,
    )
    if failed_start < 0:
        raise RuntimeError(
            "Could not find StoryJobHandler.failed() after cancel(). "
            "No changes were written."
        )

    before_cancel = updated[:cancel_start]
    cancel_block = updated[cancel_start:failed_start]
    after_cancel = updated[failed_start:]

    cleanup = """        self._discard_materialized_input(
            context
        )
"""

    cleanup_count = cancel_block.count(cleanup)
    if cleanup_count == 1:
        cancel_block = cancel_block.replace(
            cleanup,
            """        # Do not delete the materialized user turn here.
        #
        # scheduler.cancel() calls this hook while run() may still be
        # unwinding the active text stream. The running coroutine decides
        # whether the already-streamed prose should be committed. Deleting
        # its parent here races with commit_stopped_story() and can cause
        # SQLite "FOREIGN KEY constraint failed".
""",
            1,
        )
    elif "Do not delete the materialized user turn here." not in cancel_block:
        raise RuntimeError(
            "Could not uniquely locate cancellation cleanup inside cancel(). "
            "No changes were written."
        )

    updated = before_cancel + cancel_block + after_cancel

    # Sanity check: failed() should still retain destructive cleanup.
    failed_block = updated[updated.find("    async def failed(\n"):]
    if cleanup not in failed_block:
        raise RuntimeError(
            "Safety check failed: failed() no longer contains "
            "_discard_materialized_input(). No changes were written."
        )

    if updated == original:
        print("The cancellation fix already appears to be applied.")
        return 0

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)

    TARGET.write_text(updated, encoding="utf-8")

    print(f"Updated: {TARGET}")
    print(f"Backup:  {BACKUP}")
    print()
    print("The fix now:")
    print("  - keeps the materialized user node during active cancellation")
    print("  - preserves all prose already streamed to the UI")
    print("  - still cleans up the user node on genuine generation failure")
    print()
    print("Validate with:")
    print("  cd backend")
    print("  python -m compileall app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
