# Phase 5B — Slice 1: Typed operation extraction

This slice moves the ability-operation responsibilities that were embedded in
`WorldEngine._normalize_ability(...)` into focused typed domain services. It
is intentionally an extraction refactor, not a redesign of ability gameplay.

## Extracted responsibilities

- `TargetResolver` resolves the existing self, character, relationship, and
  per-effect actor/target rules.
- `RequirementEvaluator` evaluates the existing required tags and
  `min_stats` vocabulary.
- `EffectExecutor` calculates existing stat costs and effects, including
  bounds, integer rounding, sequential working values, and turn/minute
  expiration metadata.
- `Relationship` and its projection adapters provide the typed relationship
  view needed by those services.

`WorldEngine` still owns orchestration. It loads the current branch
projection and database definitions, enforces provenance, delegates the
extracted calculations, translates domain errors to `WorldValidationError`,
and returns the same normalized mutation arguments.

## Compatibility boundary

- No migration or database schema change is included.
- No HTTP, event, mutation, or projection shape is changed.
- Ability costs and effects are calculated but not persisted by the domain
  services; the existing event/commit path remains authoritative.
- Existing target types and effect operations are unchanged.
- Unknown extension and plugin fields remain accepted by typed models.
- Legacy unknown effect target labels still resolve to the primary target,
  and unknown duration labels still produce immediate effects, matching the
  prior runtime behavior.
- Cross-entity loading and branch selection remain `WorldEngine`
  responsibilities.

## Tests supplied

The new Phase 5 typed-operations tests cover relationship round trips,
normalized ability payload compatibility, requirement failures, self-target
validation, and relationship effect routing. Existing expansion tests remain
the regression coverage for temporary effects, costs, player provenance, and
invalid effect operations.

The tests and build are intentionally left for the repository owner to run.

## Subsequent slices

The remaining Phase 5 work continued the same extraction-first approach for
direct stat adjustment, the AI tool gateway, image-manager execution, and the
planning task UI boundary. See `PHASE5_COMPLETION.md` for the final
compatibility boundary and explicitly deferred product features.
