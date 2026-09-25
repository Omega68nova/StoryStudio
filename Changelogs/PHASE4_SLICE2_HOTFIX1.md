# Phase 4 Slice 2 — Hotfix 1

Fixes the four failures reported after Slice 2.

## Fixes

1. Restores `BatchGenerationRepository.set_task_status()`, which Slice 2
   accidentally dropped when replacing the Slice 1 repository.

2. Adds migration `028_batch_generation_job_kind.sql`, expanding
   `generation_jobs.kind` to allow `batch_generation`.

The migration preserves the full current generation_jobs schema/data and keeps
existing child foreign-key targets pointing at `generation_jobs`.

## Apply

Extract over the repository and run from repo root:

    python apply_phase4_slice2_hotfix1.py

Then from `backend`:

    python -m pytest tests/test_phase4_generation_plan.py tests/test_phase4_batch_execution.py -v
    python -m pytest -q

`Database.initialize()` applies migration 028 automatically.
