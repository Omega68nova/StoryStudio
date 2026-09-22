# Phase 4 — Slice 7: GenerationPlan API/UI consolidation

This slice removes the temporary Slice 6 planning-generation HTTP aliases and
makes GenerationPlan a first-class API surface.

## Backend

Adds `GenerationPlanApiService` and API routes for:

- list plans for a project
- get a plan with task/dependency state
- generate one task
- generate all currently-ready tasks
- replace/edit a generated result
- approve a generic task
- reject/regenerate a task
- read task revision history
- import/use a Planning-derived plan
- Planning-derived generation, preflight and approve/commit through the same
  GenerationPlan control plane
- random story direction through a GenerationPlan task

The old PlanningStudio generation aliases are removed:

- `/projects/{project_id}/planning/random-direction`
- `/planning/{session_id}/stages/{stage_number}/generate`
- `/planning/{session_id}/stages/{stage_number}/preflight`
- `/planning/{session_id}/stages/{stage_number}/approve`

## Authorization

The new routes are added to project-member authorization resolution. Both
Planning-session-backed routes and normal plan-id routes resolve back to their
project before access is granted.

## Frontend

PlanningStudio now calls `/generation-plans/...` for:

- random direction
- generate/regenerate
- section generation
- preflight
- approve + canonical commit

The legacy Planning draft PUT remains temporarily because Slice 8 is the
persistence-model migration. Planning v2 no longer owns generation execution.

## Apply

Extract over the current Slice 6 + hotfixes tree, then from repository root:

    python apply_phase4_slice7.py

Backend validation:

    cd backend
    python -m compileall app
    python -m pytest tests/test_phase4_generation_plan_api.py -v
    python -m pytest -q

Frontend validation:

    cd ../frontend
    npm run build

## Next

Slice 8 will migrate editable Planning state itself into GenerationPlan task
state/settings and begin deleting the parallel planning session/stage control
persistence and service methods.
