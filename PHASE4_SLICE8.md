# Phase 4 — Slice 8: Persistence Consolidation

This slice moves editable/review planning state fully onto GenerationPlan.

## What changes

GenerationPlan now owns:

- generated draft/result
- manual draft edits
- active generation job
- task status
- approval/review status
- revision history
- dependency readiness
- prior committed planning context

Planning v2 stage rows are no longer the source of truth for those concerns.

## Generation context

`PlanningBatchTaskExecutor` now uses `PlanningPlanContext`.

Prior planning context is built from earlier **committed GenerationPlan task
results**, not `planning_stages.approved_json`.

## One-time legacy import

`PlanningGenerationBridge` is now a one-time migration bridge.

After a planning session has been imported once, the plan is marked
`legacy_import_complete=1`. Future loads return the GenerationPlan directly and
do not sync legacy draft/status data back over newer task state.

Migration:

    031_generation_plan_persistence_owner.sql

adds that marker.

## Manual draft editing

PlanningStudio no longer saves editable drafts through:

    PUT /planning/{session_id}/stages/{stage_number}

It now saves directly to the GenerationPlan task result through:

    PUT /generation-plans/planning/{session_id}/tasks/{stage_number}/result

The legacy draft PUT route is removed.

## Canonical publication

`PlanningStageCommitter` still delegates to the proven canonical publisher, but
it now calls:

    approve_stage(..., sync_legacy_state=False)

Canonical world/config/resource-key publication still occurs, while these
legacy lifecycle writes are skipped:

- stage approved status
- stage draft/approved JSON synchronization
- downstream legacy stale-state propagation
- planning session current-stage/status advancement

The old behavior remains available only for legacy partial-batch paths that have
not yet been migrated.

## Why the old tables are not dropped yet

`planning_resource_keys` and `planning_image_plans` still use the Planning
session as a provenance/FK anchor. Dropping `planning_sessions` immediately
would cascade-delete useful canonical linkage metadata.

The next persistence slice can first move those keys/image-plan ownership onto
GenerationPlan/task IDs, then safely remove the parallel planning lifecycle
tables and most of PlanningRepository.

## Apply

Extract over Phase 4 Slice 7.

From the StoryStudio repository root:

    python apply_phase4_slice8.py

Then:

    cd backend
    python -m compileall app
    python -m pytest tests/test_phase4_persistence_consolidation.py -v
    python -m pytest -q

Frontend:

    cd ../frontend
    npm run build

## Expected architectural boundary

After this slice, normal planning generation/edit/review should not depend on:

- `planning_stages.draft_json`
- `planning_stages.active_job_id`
- `planning_stages.status`
- `planning_stages.approved_json`

for workflow state.

Those columns may still exist temporarily for old partial-batch/publication
compatibility, but GenerationPlan is now the runtime source of truth.
