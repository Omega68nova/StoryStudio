# Phase 5A — Slice 2: Typed read adoption

This slice adopts the Phase 5A typed models in the first read-only domain
paths while preserving all existing external dictionaries.

## Environment resolution

`EnvironmentService` now exposes typed scene character/location resolution and
a typed weather view. Both `EnvironmentService.scene(...)` and
`EnvironmentManager.resolve(...)` use those models for semantic field access,
then return the same scene payloads as before.

The scene-weather repository query is intentionally compact, so the typed view
receives its known project ID from the calling environment service rather than
adding that field to the public weather payload.

Ambient sound and music remain separate systems. Ambient resolution continues
to receive the existing projection, location, weather, and time dictionaries.

## Storyteller context

`WorldEngine.context_package(...)` now uses typed character state to resolve:

- the point-of-view character's current location;
- other characters present at that location;
- narrator-visible and character-visible secret channels.

The compact context packet remains a dictionary. Secret fields are still
removed from entity state and emitted only through `narrative_secrets` under
the existing narration rules.

## Compatibility boundary

- No migration or HTTP contract change is included.
- Projection reconstruction, event replay, and mutation execution remain on
  their existing dictionary paths.
- Typed reads do not write defaults back into projections.
- Unknown extension and plugin fields remain present in returned packets.

## Tests supplied

The Phase 5 test module now also covers environment payload compatibility,
typed weather/location resolution, compact context shape, secret filtering,
extension-field preservation, and read-only projection behavior.

The tests and build are intentionally left for the repository owner to run.

## Next phase

Phase 5A's planned foundations and initial read adoption are complete. Phase
5B Slice 1 extracts typed relationships, target resolution, requirement
evaluation, and effect calculation from the existing ability normalization
path. The extraction preserves the current mutation and event contracts.
