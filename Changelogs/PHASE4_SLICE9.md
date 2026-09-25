# Phase 4 — Slice 9 v3: Provenance Ownership

Use this package instead of the earlier Slice 9 attempts.

The patcher no longer tries to match individual SQL lines in
`planning_v2.py`. It uses Python AST function boundaries and replaces the
complete provenance-sensitive functions with their GenerationPlan-owned
implementations.

It also routes direct entity/relationship resource-key publication in
`PlanningService` through the same `record_resource()` helper.

Apply from repository root:

    python apply_phase4_slice9.py

Then:

    cd backend
    python -m compileall app
    python -m pytest tests/test_phase4_provenance_ownership.py -v

Per our agreement, legacy planning tests are not a gate until after Slice 10.
