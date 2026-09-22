# Phase 4 Slice 6 — Hotfix 2

Fixes the Hotfix 1 deletion guard.

The consolidation architecture test intentionally mentions
`planningJobHandler.py`, so that file is excluded from dependency scanning.

`test_planning_job_handler.py` only tests JSON/truncation helpers and is migrated
to `test_planning_generation_core.py`, importing those helpers from
`planningGenerationCore`.

Apply from repository root:

    python apply_phase4_slice6_hotfix2.py

Then:

    cd backend
    python -m compileall app
    python -m pytest tests/test_phase4_execution_consolidation.py -v
    python -m pytest tests/test_planning_generation_core.py -v
    python -m pytest -q
