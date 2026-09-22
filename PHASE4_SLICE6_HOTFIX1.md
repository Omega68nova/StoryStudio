# Phase 4 Slice 6 — Hotfix 1

Fixes the two consolidation-test failures:

- `planningJobHandler.py` was retained by an over-conservative deletion guard.
- That retained file still contained the old automation code that created
  legacy `"planning"` jobs.

## What this hotfix does

1. Removes any remaining test imports of `PlanningJobHandler`.
2. Redirects helper imports to `planningGenerationCore`.
3. Removes any stale scheduler registration/import.
4. Scans `backend/app` and `backend/tests` for remaining handler references.
5. Deletes `backend/app/handlers/planningJobHandler.py`.
6. AST-scans the application to ensure nothing creates a legacy
   `"planning"` job anymore.

If an unexpected reference remains, the script stops and prints the exact file
instead of deleting code blindly.

## Apply

From the StoryStudio repository root:

    python apply_phase4_slice6_hotfix1.py

Then:

    cd backend
    python -m compileall app
    python -m pytest tests/test_phase4_execution_consolidation.py -v
    python -m pytest -q

Expected consolidation test result:

    3 passed
