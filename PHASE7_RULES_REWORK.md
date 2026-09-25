# Phase 7 canonical rules handoff

This slice replaces legacy inline ability JSON and anonymous entity-local
effects with canonical project rules.

## Ownership boundary

- `RulesRepository` owns normalized stat, effect/formula, ability,
  requirement, cost, action, trigger, bullet-hell-link, and migration-warning
  persistence. It also enforces rule-reference, owner-compatibility, formula,
  timing-override, and complete stat-bound graph invariants for every caller,
  including planning and cloning.
- `RulesRuntime` resolves requirements, targets, costs, formulas, stacking,
  clocks, passive cascades, and dependent stat clamps into deterministic world
  events.
- `RuleEventProjector` owns rule-specific projection and mutation-event shapes.
- `WorldEngine` remains responsible for branch reconstruction, transaction
  ordering, cross-system validation, and atomic commit.

This boundary is deliberate: rule behavior must not migrate back into
`world.py`, and repositories must not become public DTOs.

## Canonical contract

- Stats use immutable `stat_key` identity and declare all compatible owner
  kinds. Dynamic min/max references are validated as an acyclic dependency
  graph and bound changes persist derived clamp events.
- Effects use immutable `effect_key` identity, modify one target stat, and use
  bounded expression trees over actor/source/target stats. Immediate, delayed,
  periodic, and indefinite schedules use story-minute, target-action, or
  world-action clocks.
- Abilities use immutable `ability_key` identity. Character and item ownership,
  typed requirements/costs/actions, passive triggers, timed attacks, and
  bullet-hell links are normalized. Item abilities require the selected held or
  equipped item to actually own the ability.
- Active instances live at projection level and retain canonical participants,
  clock progress, schedule, stacks, and snapshot inputs. Every firing records
  resolved inputs and magnitude for deterministic replay.
- Story-minute effects advance for every committed time-producing mutation,
  including travel and ability actions. Passive requirements and unaffordable
  passive costs filter that trigger rather than invalidating the action that
  caused it.

## Migration boundary

Migration `042_canonical_rules.sql` follows the imported spatial migration 041.
The initializer recognizes databases that briefly used the unfinished
`041_canonical_rules` name and does not replay the rule rewrite.

Legacy stat operations become distinct reusable effects named from their
ability and action position. Non-stat operations become typed actions.
Marker-only statuses and active temporary legacy effects are discarded with
project-visible warnings. Permanent stat-change events remain intact and
projection caches are invalidated.

No legacy rule endpoints or inline JSON write adapters remain. Planning and
deep cloning publish/copy stats, then effects, then abilities.

## Validation

Source tests were updated and canonical-rule coverage was added for normalized
round trips, formula evaluation, repository-level references, indirect bound
cycles, transitive clamps, item ownership, stacking, passive filtering,
periodic ticks, non-explicit time advancement, expiry, and invalid timing. Per
project instruction, tests and builds were not run during this slice.
