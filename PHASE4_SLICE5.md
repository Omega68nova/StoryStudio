# Phase 4 Slice 5 — Planning execution handoff

Planning-derived GenerationPlan tasks now route through the existing structured
Planning v2 generation machinery instead of generic chat generation.

Reused:
- PlanningService.stage_for_generation
- stage_prompt
- world inventory
- PlanningJobHandler raw JSON autocomplete
- context budgeting
- JSON parsing/default normalization
- empty-output retry
- PlanningService.validate_draft

Generation writes only to the Phase 4 task result.
Canonical Planning v2 state changes only later during approve/commit.

Invalid structured output is preserved on the task result as raw text plus a
validation error.

Apply from repo root:

    python apply_phase4_slice5.py

Then from backend:

    python -m compileall app
    python -m pytest -q
