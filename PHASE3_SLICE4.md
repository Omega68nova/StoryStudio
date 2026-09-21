# Phase 3 — Slice 4: WorldRepository

This slice extracts WorldEngine storage without changing world semantics.

## WorldEngine still owns

- mutation normalization
- mutation -> event semantics
- projection application
- branch visibility
- previews
- validation
- route/path logic
- transaction composition
- lore-card derivation
- commit ordering decisions

## WorldRepository now owns

- projection cache reads/writes/invalidation
- committed transaction reads
- ordered event reads
- resolved-minigame persistence lookup used by commit
- atomic storage of an already-composed world transaction:
  - new world entity metadata rows
  - assistant story node
  - NPC interventions / scene appearances
  - world transaction row
  - world event rows
  - weather proposal materialization
  - world entity metadata updates
  - lore-card versions/search rows
  - project active head/update timestamp
  - minigame committed state
  - projection-cache invalidation

The repository does not decide which events to create or what they mean.

## Apply

Copy/merge:

    backend/app/data/worldRepository.py

Then run from the StoryStudio repository root:

    python apply_phase3_slice4_world_repository.py

The patcher updates:
- `backend/app/data/dataProvider.py`
- `backend/app/services/world.py`

and creates `.phase4-backup` copies.

## Validation

From `backend/`:

    python -m pytest tests/test_phase3_slice4.py
    python -m compileall app

Then run the full backend suite:

    python -m pytest

Important application smoke tests:
1. normal story generation
2. stop story generation midway and preserve partial prose
3. create/update/move world entities
4. change branches / undo / redo
5. approve a planning stage that publishes world changes
6. reload the application and confirm identical world projection
7. generate a story after a minigame result

## Deliberately deferred

WorldEngine still directly reads several *other domains*, such as:
- stats/abilities
- outfits
- environment settings
- story ancestry/project head

Those are validation/context dependencies, not world event-store persistence.
They should migrate to their respective typed repositories rather than be
absorbed into WorldRepository.

After this slice, Phase 3 cleanup/audit can remove remaining transitional
`Database` facade usage before Phase 4 BatchGeneration begins.
