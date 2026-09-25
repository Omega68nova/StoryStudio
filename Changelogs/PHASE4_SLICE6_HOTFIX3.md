# Phase 4 Slice 6 — Hotfix 3

Fixes the `IndentationError` in `backend/tests/test_scheduler.py`.

Hotfix 2 removed the multiline `planningJobHandler` import header but left its
indented continuation names behind. This hotfix rebuilds that import block and
uses `planningGenerationCore` directly.

Apply from repository root:

    python apply_phase4_slice6_hotfix3.py

Then:

    cd backend
    python -m pytest tests/test_scheduler.py -q
    python -m pytest tests/test_phase4_execution_consolidation.py -v
    python -m pytest -q

The patcher syntax-parses `test_scheduler.py` before it exits.
