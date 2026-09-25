# Phase 3 — Slice 3B: Planning control persistence

This slice moves planning-control persistence behind `PlanningRepository`.

## Repository now owns
- planning session creation / lookup
- stage lookup and dependency reads
- stage generation queue transitions
- stage revisions
- generated/invalid draft persistence
- queued -> generating -> ready/cancelled/failed transitions
- reopen / skip / revalidate / reset state
- planning image-plan CRUD and queue state
- approval-claim primitives
- revision history / cleanup

## Refactored callers
- `PlanningService`
- `PlanningJobHandler`
- planning routes in `main.py`

## Deliberately still in the planning/domain layer
Approved planning publishes into canonical domains:
- WorldEngine transactions/events
- weather definitions/transitions
- stats/abilities
- outfits
- runtime/minigame/music/ambient configuration

Those are not "planning persistence"; they belong to their respective domain
repositories. Keeping them out of `PlanningRepository` prevents it becoming
another database god-object.

`approve_stage()` therefore still coordinates the canonical publish
transaction. Slice 4 will introduce WorldRepository storage without moving
WorldEngine's normalization/preview/commit semantics.

## Apply

Copy/merge `backend/app/data/planningRepository.py`, then from repo root:

    python apply_phase3b_planning_control.py

The patcher creates backups beside:
- `backend/app/services/planning.py`
- `backend/app/handlers/planningJobHandler.py`
- `backend/app/main.py`

## Validate

From `backend/`:

    python -m pytest tests/test_phase3_slice3a.py tests/test_phase3_slice3a_integration.py tests/test_phase3_slice3b.py
    python -m compileall app

Then exercise:
1. create/open a planning workshop
2. generate a stage
3. cancel a planning generation
4. regenerate it
5. save/edit a draft
6. approve / reopen / skip a stage
7. view revision history
8. edit/delete/generate planning image plans

Normal story/image generation should remain unchanged.
