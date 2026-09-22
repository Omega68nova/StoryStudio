# Phase 4 — Slice 6: Execution Consolidation

This is the first deliberately destructive Phase 4 slice.

## Architectural result

There is now one execution job for planning-style generation:

    batch_generation

`PlanningJobHandler` is removed from runtime ownership and, when no remaining
Python imports reference it, deleted from the repository.

Structured planning generation is split into reusable modules:

- `PlanningGenerationCore`
  - raw JSON autocomplete
  - truncation detection/continuation
  - cache-free empty-output retry
  - random creative-direction generation
- `PlanningBatchTaskExecutor`
  - Planning-stage prompt/context construction
  - section/append generation
  - repair generation
  - validation and normalization
- `BatchGenerationJobHandler`
  - the scheduler execution owner
- `BatchGenerationApiService`
  - temporary HTTP compatibility orchestration for the current PlanningStudio

The old PlanningStudio URLs remain for this slice, but they are now only API
aliases. They do not create legacy `planning` jobs.

## Preserved behavior

The consolidation retains:

- random-direction generation
- high planning-context runtime selection
- raw structured JSON continuation
- malformed-output repair
- incremental/section generation
- generation-plan result overlay into the existing PlanningStudio view
- stage 8 deterministic image-plan preparation
- the existing approval/commit canonical publication boundary

The old `planning` value remains in the historical generation_jobs CHECK for
now so existing job history is readable. No application code should create a
new job of that kind.

## Automation

The automate flag propagates through GenerationPlan task prompts. After a
generated task is successfully approved and committed, the next dependency
frontier is configured and queued through BatchGeneration. If validation or
commit requires human review, automation pauses rather than using the old
planning handler as a fallback.

## Apply

Extract this package over Phase 4 Slice 5.

From the StoryStudio repository root:

    python apply_phase4_slice6.py

The patcher creates `.phase4-slice6-backup` files before modifying/deleting
legacy files.

## Validate

From `backend`:

    python -m compileall app
    python -m pytest tests/test_phase4_execution_consolidation.py -v
    python -m pytest -q

Also verify that this file is gone after the patch:

    app/handlers/planningJobHandler.py

If the patcher reports that the handler was retained, it will print every
remaining Python file that still imports/references it. Those references should
be migrated rather than keeping the handler as a fallback.

## Next slice

Slice 7 will migrate the API/UI model itself:

- first-class `/generation-plans` endpoints
- PlanningStudio -> Batch Generation UI
- direct review/approve/reject/regenerate/commit controls
- dependency-frontier visualization
- remove old planning-generation HTTP aliases once the frontend consumes the
  GenerationPlan API directly

After that, the one-time persistence migration can absorb the remaining useful
Planning v2 data and let us delete the parallel planning control tables/services.
