# Phase 4 — Slice 1: GenerationPlan foundation

This slice introduces the generic definition layer for BatchGeneration while
leaving Planning v2 fully operational.

## Added

### `generation_plans`
A project-scoped generation plan with optional source metadata and settings.

### `generation_plan_tasks`
Each task has:

- stable `task_key`
- `generator_kind`: text / image / deterministic
- `target_kind` and optional `target_key`
- prompt/settings JSON
- independent lifecycle status
- revision number
- result/error storage

### `generation_task_dependencies`
Explicit dependency edges with a required state:

- `generated`
- `approved`
- `committed`

This means, for example, an image can require an approved character while a
character-detail generation may need only a generated foundation.

## Domain behavior

`batchGeneration.py` provides:

- typed definitions
- duplicate/missing dependency validation
- self-dependency validation
- cycle detection
- deterministic topological layers
- dependency-state readiness
- descendant calculation

## Manager behavior

`BatchGenerationManager` currently supports:

- create plan
- get/list plans
- resolve ready tasks
- revise one task
- invalidate only downstream descendants after a revision

It deliberately does **not** enqueue generation jobs yet. That comes in Slice 2
so the new definition model can land independently of the existing Planning v2
execution system.

## Apply

Copy/extract this overlay into StoryStudio, then from repository root:

    python apply_phase4_slice1.py

The new migration is applied by the normal `Database.initialize()` path.

## Test

From `backend`:

    python -m pytest tests/test_phase4_generation_plan.py -v
    python -m compileall app

Then run the full suite:

    python -m pytest -q

Planning v2 should behave exactly as before.

## Next slice

Phase 4 Slice 2 will add execution:

- one generic `batch_generation` job handler
- individual task generation
- mass generation of currently-ready tasks
- dependency-aware progression
- cancellation/failure state
- text/image generator delegation without embedding domain-specific prompts in
  the scheduler
