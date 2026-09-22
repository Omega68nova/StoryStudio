# Phase 4 — Slice 3: Review, regeneration, and commit

This slice adds the lifecycle that separates:

    generated -> approved -> committed

Those states are intentionally distinct.

## Added

### Review metadata
`generation_plan_tasks` now stores:

- approved timestamp
- committed timestamp
- review note
- commit metadata

### Revision history
`generation_task_revisions` preserves the previous generation whenever a task
is rejected/regenerated or its definition is revised.

Regenerating a task:

- archives the previous result
- increments its revision
- clears approval/commit metadata
- invalidates only downstream descendants

### Approval
`BatchGenerationManager` now supports:

- `approve_task`
- `approve_many`
- `reject_task`
- `regenerate_task`
- revision history

Approving can unlock dependencies requiring `approved`.

### Commit boundary
`BatchTaskCommitter` is the explicit publication contract.

A task can become `committed` only after:

1. it is approved
2. a committer adapter succeeds

This slice includes `NoopBatchCommitter` only for tests or explicit
non-domain artifacts. StoryStudio canonical domain state is **not**
automatically modified by it.

The next slice supplies real StoryStudio commit adapters.

### Plan aggregation
Plan status is recalculated from task states:

- running while jobs are queued/running
- awaiting_review when generated/approved output needs action
- ready when a generation frontier is available
- failed when a task failed
- completed only when every task is committed

## Apply

Extract this package over Slice 2 + Hotfix 1.

Migration 029 is applied through normal `Database.initialize()`.

No additional patcher is required because this slice replaces the Phase 4
repository/manager files directly.

## Test

From backend:

    python -m pytest tests/test_phase4_generation_plan.py tests/test_phase4_batch_execution.py tests/test_phase4_review_commit.py -v
    python -m compileall app
    python -m pytest -q

## Next

Slice 4 will add StoryStudio-specific commit adapters and the first bridge from
Planning v2 resources into GenerationPlan:

- canonical world/entity publication
- runtime/environment/config publication
- media/image publication handoff
- planning-to-generation-plan adapter
