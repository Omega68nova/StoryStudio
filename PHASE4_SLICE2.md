# Phase 4 — Slice 2: GenerationPlan execution

This slice adds execution to the Slice 1 GenerationPlan model while keeping
Planning v2 intact.

## Execution model

One `batch_generation` generation job executes one plan task.

### Text tasks

- use `AIGeneratorManager.text_session()`
- accept either `prompt.messages` or `prompt.instruction`
- stream partial output into the normal generation job
- optionally parse JSON when `settings.parse_json=true`
- finish the plan task as `generated`

### Deterministic tasks

- resolve locally without model/runtime access
- useful for derived/default/static generation steps

### Image tasks

- do **not** duplicate ImageJobHandler or ComfyUI logic
- create a normal `image` generation job
- attach `batch_generation_plan_id` / `batch_generation_task_key`
- ImageJobHandler reports generated/cancelled/failed state back to the plan task

## Mass generation

`BatchGenerationManager.queue_ready()` queues only the current dependency
frontier. When those jobs finish, `get_plan()` recalculates readiness and the
next frontier becomes available.

This intentionally avoids recursively auto-running the whole DAG in Slice 2;
users/services can choose between individual generation and mass-generation of
the currently valid frontier.

## Task/job ownership

Migration 027 adds `generation_plan_tasks.active_job_id`.

This prevents duplicate execution and makes cancellation/failure ownership
explicit, including delegated image jobs.

## Apply

Extract over the existing Phase 4 Slice 1 tree, then from repo root:

    python apply_phase4_slice2.py

Migration 027 is picked up by normal `Database.initialize()`.

## Tests

From `backend`:

    python -m pytest tests/test_phase4_generation_plan.py tests/test_phase4_batch_execution.py -v
    python -m compileall app
    python -m pytest -q

## Next

Slice 3 should add the review/approval/commit layer:

- generated vs approved vs committed as explicit operations
- batch approve / batch commit
- task regeneration with descendant invalidation
- plan completion/status aggregation
- adapters that begin replacing fixed Planning v2 generation with GenerationPlan
  tasks without removing the legacy workshop UI yet
