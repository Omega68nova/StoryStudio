# Phase 5A — Slice 1: Typed world foundations

This slice introduces opt-in typed domain views over StoryStudio's existing
world and configuration records. It deliberately leaves persistence, event
payloads, projection dictionaries, HTTP contracts, and generation behavior
unchanged.

## Added

- `app.domain.world` defines canonical identity and typed character, location,
  weather, stat, ability, requirement, and action-effect models.
- `app.domain.adapters` converts current projection dictionaries and database
  record shapes to and from those models.
- `WorldEngine.typed_entity(...)` provides a branch-aware typed read without
  changing `WorldEngine.projection(...)`.

All models retain unknown fields. Adapters use `exclude_unset` when converting
back, so reading sparse historical data does not inject default fields. JSON
columns are parsed at the adapter boundary and re-emitted in their existing
database shape.

## Compatibility boundary

- No migration is included.
- Existing callers continue to receive dictionaries.
- Cross-reference and business-rule validation remains in `WorldEngine`.
- AI aliases are not identity and are not resolved by this slice.
- Ambient audio and music remain separate systems.

## Tests supplied

`backend/tests/test_phase5_typed_world.py` covers round trips, extension data,
canonical references, malformed JSON, branch-aware reads, model validation,
and projection immutability.

The tests and build are intentionally left for the repository owner to run.

## Follow-on

Phase 5A Slice 2 adopts these typed views incrementally in environment
resolution and world context composition. Relationship targeting, requirement
evaluation, and effect execution remain reserved for Phase 5B.
