# Phase 4 Slice 8 — Hotfix 1

This is a test-contract update, not a runtime fix.

Slice 8 intentionally stopped synchronizing GenerationPlan commit state back
into `planning_stages.status`.

The old test still expected:

    planning_stages.status == "approved"

That is no longer the ownership model.

The corrected test verifies:

- the GenerationPlan task becomes `committed`
- canonical publication still updates the story premise
- the legacy planning stage remains `ready`
- no duplicate legacy lifecycle synchronization occurs

Apply from repository root:

    python apply_phase4_slice8_hotfix1.py

Then:

    cd backend
    python -m pytest tests/test_phase4_planning_bridge.py -v
    python -m pytest -q
