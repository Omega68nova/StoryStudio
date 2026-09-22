# Phase 4 — Slice 4: Planning v2 bridge

This is the first Phase 4 slice that takes over real StoryStudio planning work.

## What it does

`PlanningGenerationBridge` imports an existing Planning v2 session into a
GenerationPlan without deleting or mutating the legacy workshop.

Mapping:

- approved Planning v2 stage -> committed GenerationPlan task
- existing editable draft -> generated GenerationPlan task
- untouched stage -> ready/blocked according to Phase 4 dependencies

Each imported task keeps a source link to the original planning stage.

Import is idempotent: importing the same planning session again returns/syncs
the same generation plan.

## Canonical commits

`PlanningStageCommitter` does not duplicate publication logic.

It delegates to the existing `PlanningService`:

1. validates the generated draft
2. runs canonical-world preflight
3. requires conflict resolutions where necessary
4. calls the existing atomic `approve_stage()`
5. preserves its world/config/resource-key transaction behavior
6. records the resulting transaction metadata on the Phase 4 task

Stage 7 also preserves Planning v2's image-stage preparation behavior.

This means Phase 4 `committed` now corresponds to an actual existing
StoryStudio publication boundary.

## Migration

Migration 030 adds source metadata to GenerationPlan tasks:

- source_kind
- source_id

## Apply

Extract over Phase 4 Slice 3, then from repo root:

    python apply_phase4_slice4.py

From backend:

    python -m pytest tests/test_phase4_generation_plan.py tests/test_phase4_batch_execution.py tests/test_phase4_review_commit.py tests/test_phase4_planning_bridge.py -v
    python -m compileall app
    python -m pytest -q

## Scope

This bridge is deliberately one-way/additive. Planning v2 remains available as
a fallback while Phase 4 proves equivalent behavior.

The next slice will make Planning-derived GenerationPlan tasks executable with
the existing stage prompt/validation machinery, so new planning generation can
run through BatchGeneration instead of merely importing existing drafts.
