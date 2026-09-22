# Phase 4 Slice 6 — Hotfix 4

Hotfix 3 still failed because it attempted to repair an already-malformed
multiline import incrementally.

Hotfix 4 instead rewrites only the import preamble before `class FakeLlama:`.
It removes:

- `planningJobHandler` imports
- dangling `_looks_like_token_truncation,`
- dangling `_planning_json_error,`
- orphan closing parenthesis from that deleted import
- duplicate `planningGenerationCore` imports

Then it inserts exactly one canonical import:

    from app.services.planningGenerationCore import PlanningGenerationCore, _looks_like_token_truncation, _planning_json_error

The entire test body is left untouched.

Apply from repository root:

    python apply_phase4_slice6_hotfix4.py

Then:

    cd backend
    python -m pytest tests/test_scheduler.py -q
    python -m pytest tests/test_phase4_execution_consolidation.py -v
    python -m pytest -q
