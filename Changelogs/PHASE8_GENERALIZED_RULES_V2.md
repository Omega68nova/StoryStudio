# Phase 8 — Generalized Rules V2

Branch: `phase8-generalized-rules-v2`

## Why this branch exists

The current canonical rules runtime on `master` is the correct baseline for the
next rules-system iteration.

The older `finish-stats-effects-abilities` PR contains useful regression tests
and historical fixes, but its runtime assumptions are more character/item
specific and it is based on a substantially older repository state.

Current `master` already has the stronger foundation:

- canonical project-local stat/effect/ability keys;
- stat definitions compatible with multiple owner kinds;
- stats stored on world entities and relationships;
- typed recursive requirements;
- typed formulas;
- effect application resolved independently for each target;
- multi-target ability action selectors;
- dynamic stat bounds;
- active effect timing/stacking;
- branch-safe rule events.

The remaining problem is that requirement, cost and formula references are still
expressed through several separate, partly hard-coded concepts such as
`actor`, `source` and `target`.

Phase 8 replaces those parallel concepts with one generalized object-selection
and value-expression framework.

## Intended model

### Stat-bearing objects

Stats are not character attributes. They are typed project-level properties that
may be compatible with any supported stat-bearing object kind.

The runtime must resolve a stat owner through a canonical object reference rather
than assuming a character.

At minimum this includes:

- character;
- item;
- location;
- faction;
- lore system;
- fact;
- plot beat;
- relationship.

The Phase 8 design should be extensible to additional canonical database objects
such as abilities, effects, weather/environment resources, outfits and Spatial
V3 objects without adding a new evaluator for every subsystem.

A stat definition still declares which owner kinds are valid. An object receives
the stat's default value when it has no explicit stored override.

### Object selectors

Requirements, costs and formulas should select objects through one shared
selector vocabulary.

Initial selector families:

- actor;
- source;
- primary target;
- each resolved target;
- current location;
- ability definition;
- explicit object reference;
- relationship object;
- party/allies/enemies/faction members;
- other context-provided named sources.

Selectors return zero, one or many canonical object references depending on the
operation.

Any multi-target effect is evaluated separately for every selected target. The
formula's `target` reference therefore means the target currently being
processed, not a shared aggregate target.

### Value expressions

A shared typed value-expression tree should replace formula-only stat references.

A value expression can produce at least:

- numeric constant;
- stat value from a selected object;
- arithmetic operations;
- min/max;
- negation.

Later extensions may expose safe non-stat values without changing the expression
tree's execution model.

A stat-value node contains:

- object selector;
- stat key.

This permits expressions such as:

- source item.attack + actor.strength;
- target.armor;
- current location.magic_intensity;
- ability.power;
- explicit weather.temperature;
- target.max_hp * 0.2.

The evaluator validates that the selected object's kind is compatible with the
referenced stat definition.

### Conditions / requirements

Requirements use the same selector and value infrastructure.

Boolean condition nodes should support:

- and / or / not;
- numeric/string comparisons between value expressions;
- object existence;
- tag membership;
- item possession;
- ability possession;
- relationship checks;
- location checks;
- time/weather checks.

The existing requirement tree remains migratable into this form.

A condition must be usable by:

- abilities;
- Spatial V3 traversal alternatives;
- Spatial V3 encounter policies/candidates;
- future item interactions;
- scripted world rules;
- UI availability checks.

This eliminates the current duplication between map requirements and ability
requirements.

### Ability costs

Costs should no longer imply "subtract a stat from the actor".

A cost specifies:

- owner selector;
- resource kind;
- resource/stat identifier;
- value expression for the amount;
- operation/consumption behavior where applicable.

Examples:

- actor.mana -= 10;
- source_item.durability -= 1;
- current_location.magic -= 5;
- consume one explicit inventory item;
- target.stamina -= actor.strength * 0.1.

All costs are normalized before commit and remain atomic.

### Effects

An effect remains a reusable project-level definition identified by
`effect_key`.

An effect specifies:

- target selector supplied by the ability/action context;
- target stat;
- operation;
- magnitude ValueExpression;
- timing/clock;
- snapshot/live evaluation;
- stacking behavior.

Runtime execution receives an evaluation context containing canonical object
references. For every resolved target:

1. bind `target` to that one target;
2. resolve all other selectors independently;
3. evaluate the magnitude;
4. validate target-stat compatibility;
5. clamp/round using that target's stat definition/bounds;
6. emit a deterministic event.

Timed live effects preserve enough source/context identity to re-resolve their
value expression later.

### Abilities

Abilities remain compositions rather than inline effect blobs.

An ability contains:

- owner compatibility;
- invocation target semantics;
- requirement condition tree;
- ordered costs;
- ordered actions.

An apply-effect action references an `effect_key` and supplies the target
selector/context.

The same ability can therefore be owned by a character, item or future supported
owner without introducing a separate ability execution system.

## Differences from current master

Current master is already closer to this model than the rejected rules PR.

It already has:

- broad stat owner compatibility;
- generic entity/relationship stat adjustment;
- per-target effect normalization;
- multi-target selectors;
- actor/source/target formula participants;
- typed requirement trees.

Still hard-coded today:

- `FormulaParticipant` is limited to actor/source/target;
- active ability invocation assumes a character actor;
- ability ownership is restricted to character/item;
- stat ability costs are actor-only;
- item costs are inventory-specific;
- requirement stat comparisons special-case character/relationship/location;
- direct effect context uses fixed actor/source/target fields;
- active timed effects persist only actor/source/target identity;
- Spatial V3 requirements are intentionally opaque and cannot yet share the
  evaluator.

## Relationship to the old rules PR

Useful material to salvage from `finish-stats-effects-abilities`:

- `backend/tests/test_rules_rework.py`;
- the focused rules migration CI workflow;
- migration edge-case coverage;
- any individual bug fix that still reproduces on current master.

Do not rebase or merge that branch wholesale. Its implementation predates large
parts of current master and would reintroduce older assumptions.

## Implementation sequence

1. Introduce canonical RuleObjectRef / selector / evaluation-context models.
2. Introduce shared ValueExpression and ConditionExpression evaluators.
3. Adapt existing FormulaNode and RequirementExpression data without destructive
   migration.
4. Generalize stat lookup/access through canonical object refs.
5. Generalize ability costs.
6. Generalize effect source/value evaluation and persisted timed-effect context.
7. Adapt ability execution to the shared evaluator.
8. Wire Spatial V3 traversal and encounter requirements to ConditionExpression.
9. Port useful regression tests from the old rules PR and add cross-object tests.
10. Update Rules Studio editors for generic selectors/value expressions.
11. Only after compatibility tests pass, remove the old fixed-role evaluator
    paths.

## Required proof cases

Before this branch is considered complete, tests should demonstrate:

- an item stat affecting an effect applied to a character;
- a character stat and item stat both contributing to one formula;
- a location stat contributing to an effect;
- an ability-owned/configuration stat contributing to an effect once that owner
  kind is enabled;
- one multi-target ability producing different magnitudes for each target based
  on each target's stats;
- a requirement comparing arbitrary selected-object stats;
- a cost paid by an object other than the actor;
- atomic failure when any required cost cannot be paid;
- snapshot and live timed effects preserving the correct source context;
- Spatial V3 traversal requirements using the exact same condition evaluator;
- branch replay reproducing identical stat/effect results.


## Implementation status

### Shared evaluator foundation — implemented

The branch now contains `app.domain.rules_v2` with:

- `RuleObjectSelector` and extensible selector kinds;
- `RuleObjectSnapshot`;
- `RuleEvaluationContext`;
- recursive `ValueExpression`;
- recursive `ConditionExpression`;
- generic object resolution;
- value evaluation with stat-owner compatibility hooks;
- condition evaluation;
- legacy FormulaNode -> ValueExpression adapter;
- legacy RequirementExpression -> ConditionExpression adapter.

The old `FormulaEvaluator` and `RequirementEvaluator` now execute through
these adapters, preserving existing persisted definitions while moving runtime
semantics onto the shared engine.

`RulesRuntime.rule_context()` normalizes every world entity and relationship
to effective stat values, including defaults and dynamic bounds.
`RulesRuntime.evaluate_condition()` accepts both new Phase 8 condition payloads
and legacy requirement payloads. This is the integration boundary intended for
Spatial V3 and other subsystems.

### Salvaged from the old rules PR

- focused `test_rules_rework.py` regression suite;
- GitHub Actions backend/frontend rules workflow;
- shared stat dependency graph validator.

The old implementation itself has not been merged.


### Spatial V3 traversal conditions — implemented

The experimental Spatial V3 pathfinder now accepts a shared condition evaluator.

- default-blocked barriers/connectors can use authored TraversalOptions;
- option requirements are evaluated through Rules V2 when actor context is
  supplied;
- without actor/context, the previous conservative unresolved/blocked behavior
  remains unchanged;
- selected connector options are recorded in route steps;
- connector option fixed travel time and movement-option multipliers participate
  in route cost;
- the diagnostic path endpoint now accepts optional `actor_id` and evaluates
  traversal requirements against that branch projection.

This is the first cross-system consumer of the shared Phase 8 condition engine.


### Regressions salvaged from PR #13

The imported regression suite exposed four still-relevant defects on current
master. Phase 8 now ports only those fixes:

- active timed effects created by an ability start after the committing action;
- NOT requirement migration preserves the `not_child` edge;
- damage stat changes trigger both general `stat_changed` and `damage`
  passive hooks, restoring recursive-loop detection;
- legacy persisted ability ID/display-name references are rewritten to canonical
  `ability_key` values.

The focused CI now also runs Spatial V3 pathfinding tests because Phase 8 shares
its condition evaluator with conditional traversal.


### Generalized costs and effect value execution — runtime wired

Persisted Phase 8 value expressions now drive actual effect magnitude
calculation. Each target invocation builds a fresh rule context, so target-bound
values are evaluated independently. Current-location and explicit-object
selectors resolve against effective branch stats.

Ordered generalized stat costs are normalized after legacy stat costs against a
working projection, preventing mixed legacy/Phase-8 costs from double-spending
the same initial resource. The returned stat-change events remain part of the
same ability normalization/transaction.

Timed live effects persist the originating `ability_key` and re-evaluate
Phase 8 value expressions from current branch state when they fire.
