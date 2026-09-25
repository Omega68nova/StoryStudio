# Phase 5 completion — typed world and extracted domain ownership

> Historical handoff: the inline ability/effect storage described below was
> superseded by the Phase 7 canonical-rules slice. Current rules use normalized
> stat, effect, formula, ability, cost, action, and trigger records; see
> `PHASE7_RULES_REWORK.md`.

Phase 5 now includes the planned typed foundations, runtime adoption, and the
previously deferred semantic extensions. The central rule remains the base
idea of the refactor: domain behavior lives in focused modules while
`WorldEngine` remains the branch-aware validation and transaction facade.

## Typed requirements, targets, and effects

- Ability requirements support recursive `and`, `or`, and `not` expressions,
  stat comparisons, inventory/tag checks, relationship checks, and current
  location/time/weather predicates. Legacy `tags` and `min_stats` remain valid.
- Ability and effect targets include self, explicit choice, relationship,
  location, party/allies/enemies, faction members, everyone present, and a
  resolved random choice.
- Group selectors are expanded to canonical IDs during normalization. Replays
  never recalculate a random or semantic target.
- Effects support bounded add/subtract/set/multiply, movement, entity creation
  and archival, statuses, knowledge reveals, relationship changes, story-time
  advancement, and one-shot noises.
- Cross-entity validity and persistence still belong to `WorldEngine`; domain
  operations only resolve and normalize typed intent.

## AI identity boundary

`AIWorldToolService` gives every projected entity a compact, ephemeral
`ai_key`. Exact IDs, unique names, unique aliases, and AI keys are accepted at
the AI boundary and converted to canonical IDs before validation. Ambiguous
names and aliases are deliberately left unresolved and rejected normally.
Friendly names never become persistent identity.

## Deep cloning

`WorldCloneService` clones a selected world subgraph into a target project.
It can include contained locations, characters located within the selected
tree, recursively referenced entities, internal relationships, and missing
stat/ability definitions. Every cloned entity receives a fresh ID and nested
references are remapped. The world portion is normalized and committed as one
author transaction.

## Media and sound ownership

- Image jobs continue through `ImageManager`.
- Music remains a separate music/theme system.
- Ambient sound remains a looping environment system, including stored-file
  speed variants such as using a walking file at a faster playback rate.
- No audio generation feature was added.
- Noises are a third system: stored files under `public/sounds/noises`, played
  once on demand by story, ability, minigame, or manual callers. They have a
  separate catalog, availability state, playback rate/gain, client toggle, and
  client volume. Noise files are excluded from ambient indexing.

## GenerationPlan DAG and planning wire cleanup

- GenerationPlan tasks can be created, edited, deleted, and assigned arbitrary
  dependencies through the first-class task API.
- Every dependency edit is validated against missing tasks, self-dependencies,
  duplicates, and cycles before persistence.
- PlanningStudio exposes dependency editing and unlocks tasks from dependency
  state rather than numeric ordering.
- Planning HTTP/event payloads now use `tasks`, `task_number`, `task_key`,
  `current_task`, and `affected_tasks`. The old `stages`, `stage_number`,
  `current_stage`, `affected_stages`, and `/planning/.../stages/...` wire
  aliases were removed. Internal planning algorithms and historical database
  columns may retain stage terminology where it describes the fixed eight-task
  specialization; they are not public wire contracts.

## Persistence changes

- Migration 034 adds independent noise variants and per-user noise preferences.
- Migration 035 expands the persisted ability target vocabulary while retaining
  all existing ability rows and minigame profile JSON.

## Validation handoff

Tests were added or updated for recursive expressions, semantic target
expansion, AI alias canonicalization, editable DAG cycle rejection, the new
planning wire shape, deep clone remapping, and ambient/noise folder separation.
Per repository instructions, tests, compilation, frontend builds, and Git
operations were not run during implementation.
