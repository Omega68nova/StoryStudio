# Phase 7 consistency audit and convergence plan

This document records the current StoryStudio storage/runtime/UI architecture after
the canonical world, spatial, rules, Global Library, and Map V2 work, and defines
the convergence work that should happen before Phase 8.

The goal is not to replace working systems for aesthetic reasons. It is to make
one subsystem authoritative for each concept, remove duplicated authoring paths,
and make rules/media semantics match the intended gameplay model.

---

# 1. Guiding decisions

The convergence work should follow five rules.

1. **One canonical owner for each concept.**
   Multiple views may display the same data, but only one editor/workflow should
   be the primary authoring surface.

2. **Branch runtime state and project definitions remain separate.**
   Story/world mutations remain branch-aware world events. Rules, reusable
   templates, weather definitions, workflows, and other authoring definitions
   remain project/global configuration unless they explicitly represent story
   state.

3. **Materialized tables are read models, not a second source of truth.**
   Spatial current-state tables may continue to exist for efficient map queries,
   but authored location state continues to come from canonical world events.

4. **Reusable gameplay behavior should be declarative.**
   Stats describe values and reactions; effects describe reusable consequences;
   abilities describe activation, requirements, costs, targeting, and which
   effect is produced.

5. **Media files are global assets referenced by resources.**
   A character, outfit, location, story image, item, rule, or library resource
   should reference a shared media object rather than owning a copied file.

---

# 2. Current canonical storage map

## 2.1 World entities and branch state

Current world identity is stored in `world_entities`:

- stable ID
- project ID
- entity kind
- canonical name
- aliases
- tags
- creation metadata

Mutable entity state is not a mutable JSON row. It is reconstructed from
append-only `world_transactions` + `world_events` into a branch projection.

This is the correct architectural direction and should remain.

The projection currently carries:

- typed entity state,
- current stat values,
- relationships,
- active effects,
- spatial objects,
- elapsed/display time,
- transaction history.

### Keep

- WorldEngine as the branch-aware source of runtime truth.
- Event-driven entity changes.
- Projection cache as a rebuildable optimization.
- Separate normalized identity row in `world_entities`.

### Avoid

- Adding new mutable per-entity state tables that bypass WorldEngine.
- Letting the Global Library become a live source for story state.
- Making spatial materialization authoritative.

---

## 2.2 Locations

A location currently touches three major systems.

### A. World projection / LocationState

Canonical location state already contains both descriptive and spatial fields:

- description
- image generation description
- image tags
- parent location
- exposure
- x/y
- topology
- occupancy
- boundary access
- spot/area kind
- priority layer
- minutes per unit
- visibility radius
- footprint
- local bounds
- encounter rate
- enabled / hidden / discovered
- random encounter
- important / planning tier
- archived / visibility

This is the real branch-aware location object.

### B. Spatial materialization

`spatial_locations`, vertices, anchors, barriers, connections, encounters, and
itineraries are rebuilt from the branch projection.

These tables are valuable because they support:

- map-local queries,
- geometry,
- route/path behavior,
- route endpoint bindings,
- encounter geometry,
- itinerary materialization,
- visibility/discovery reads.

They should remain normalized read models.

### C. Environment definitions

Project-global environment data is stored separately:

- environment behavior settings,
- weather definitions/transitions,
- time phases,
- ambient sound catalog/assignments,
- noise catalog,
- background condition links.

Those definitions are not location identity/state and should remain separate
project configuration.

### Current interface duplication

Locations are currently exposed through all of:

1. **EnvironmentStudio**
   - full descriptive location editor
   - background generation/upload
   - ambient assignments
   - hierarchy
   - simplified map
   - some spatial fields

2. **LocationMapStudio / Map V2**
   - geometry
   - hierarchy
   - areas/spots
   - routes/doors/portals
   - barriers
   - route locks
   - priority layers
   - spatial contents
   - map placement

3. **WorldStudio**
   - locations appear among general entities
   - the generic entity editor intentionally refuses to save location state and
     redirects detailed editing to Environment.

4. **Player map dialog**
   - a separate simplified `LocationMap` exported by EnvironmentStudio.

This is too many conceptual homes for one resource.

---

# 3. Location convergence

## Decision: Map V2 becomes the master location workspace

The existing Environment and Location Map configuration tabs should converge
into one **Environment & Map** workspace backed by LocationMapStudio.

The map is the correct master because hierarchy, containment, geometry, routes,
barriers, and spatial dependencies are structurally part of a location and are
hard to represent correctly in a detached list/form.

The map sidebar should expand instead of keeping a second location editor.

## 3.1 Proposed Map V2 sidebar

When a location is selected, the right sidebar should contain sections/tabs:

### Identity

- name
- aliases
- description
- tags
- archived/visibility as applicable
- favorite to Global Library

### Spatial

- parent
- spot/area
- geometry
- local bounds
- topology
- occupancy
- boundary access
- priority layer
- minutes per unit
- visibility radius
- discovered/hidden/enabled
- random encounter
- encounter rate

### Environment

- indoor/outdoor/isolated
- weather/time-specific behavior as applicable
- environment-specific settings tied to that location

### Backgrounds

- current/default background
- weather-conditioned backgrounds
- time-conditioned backgrounds
- upload
- generate
- choose from Global Media Library
- full-screen view/download

### Audio

- location ambient sets
- weather/time selectors
- previews

### Encounters / access

- encounter rules
- routes/doors/portals touching this location
- barriers
- locks/requirements
- relevant travel metadata

### History / advanced

- branch history
- raw/diagnostic view only where still useful

## 3.2 Project-level environment controls

Map V2 should also have a map-level mode or drawer for:

- environment enabled
- AI location creation
- AI weather proposals
- automatic background generation
- background workflow
- perception stat
- weather catalog and transitions
- time cycle
- ambient catalog
- noise catalog

These are not fields on a location, but they belong in the same environment
workspace.

## 3.3 UI removals after convergence

After parity is achieved:

- remove the separate **Environment** top-level configuration tab;
- rename **Location Map** to **Environment & Map**;
- remove the EnvironmentStudio location list/form and simplified admin map;
- remove locations from the editable WorldStudio general-entity list;
- if WorldStudio surfaces a location reference, provide **Open in Environment &
  Map** instead of a second editor;
- keep the player-facing compact map only if useful, but make it consume the
  same canonical spatial read endpoint and shared map primitives.

## 3.4 Backend cleanup

The backend currently has both location-oriented environment endpoints and
spatial placement endpoints. They both eventually write through WorldEngine,
which is good, but they duplicate validation and payload concepts.

Converge toward:

- one typed location create/update command;
- one location geometry/placement command for high-frequency geometry edits;
- one branch-aware location service used by Map V2;
- spatial repository synchronization after successful world commits;
- environment endpoints only for project environment definitions, not location
  CRUD.

The spatial current tables remain materialized projections and are never edited
directly.

---

# 4. Character system audit

The character system is already the closest subsystem to the desired end state.

## Current strengths

CharacterState already cleanly separates:

- identity/description
- appearance/image prompt
- personality/goals/secrets
- runtime position
- inventory/equipment
- abilities
- factions/knowledge/party
- active outfit
- gameplay/minigame data

Outfits are normalized resources and media may be outfit-specific.

The editor already provides:

- portrait
- full body
- stats
- active effects
- wardrobe
- equipment
- abilities
- relationships
- context
- history

## Required changes

Only UI/media convergence should happen here unless a concrete runtime problem
appears.

### Layout fix

The desktop character editor currently uses:

`height: min(82vh, 920px)`

inside a page that also has application chrome/padding. On some viewport sizes
the resulting editor is slightly taller than the usable content area, producing
the small approximately 10px page scroll described during testing.

Replace the hard relative-height assumption with a layout based on the actual
available stage height, for example:

- configuration content uses `min-height: 0`;
- character editor uses `height: 100%` or
  `calc(100dvh - measured app/config headers)`;
- only the center/rail panes scroll;
- the outer page should not acquire a second scrollbar.

Do not redesign the character data model as part of this pass.

---

# 5. Rules: current storage versus intended semantics

The current canonical rule storage is normalized and substantially better than
the pre-Phase-7 JSON model, but the semantic boundaries are still not the
desired final model.

---

## 5.1 Stats today

Current `Stat` / `stat_definitions` provides:

- stable `stat_key`
- label/description
- compatible owner kinds
- default value
- mandatory numeric minimum and maximum
- optional minimum-stat key
- optional maximum-stat key
- integer/continuous display behavior
- visibility/presentation/icon metadata

Runtime values live on world entities/relationships and are changed through
world events.

### What is correct

- stable keys
- reusable definitions
- owner compatibility
- per-entity values in branch projection
- bounds referencing other stats
- recalculation/clamping when dependent bounds change

### What is inconsistent with the intended model

A stat is intended to be a **bounded or unbounded gameplay variable**.

Today every stat has finite `minimum` and `maximum` values. Even when dynamic
bound references are used, static numeric fallbacks still exist. Truly
unbounded variables are impossible.

A stat also currently has no first-class way to declare meaningful reactions
such as:

- HP <= 0 -> death effect
- sanity <= 20 -> panic status
- reputation >= 100 -> promotion effect

Passive abilities can approximate some of this, but that is an indirect authoring
model and the current requirement system cannot express all needed comparisons.

## Target stat model

A stat definition should describe:

- key/name/description
- compatible owner kinds
- default value
- integer/continuous
- visibility/presentation
- **optional** lower bound
- **optional** upper bound

Each bound should support:

- no bound;
- fixed numeric bound;
- another compatible stat;
- later, if needed, a numeric expression.

Recommended normalized representation:

- `minimum_kind = none | constant | stat`
- `minimum_value`
- `minimum_stat_key`
- same for maximum.

Alternatively nullable minimum/maximum plus optional stat refs can be retained,
but the invariant must clearly represent "no bound".

## Stat reactions

Do not put arbitrary side-effect code directly inside the stat definition.

Add explicit reusable reaction records, conceptually:

- owner stat key
- trigger: changed / increased / decreased / crosses threshold
- comparison expression
- effect key
- priority / enabled

Example:

`hp <= 0 -> effect: death`

This keeps stats declarative while still allowing stats to cause gameplay
consequences.

Reactions should run through the same bounded cascade/event limits already used
for passive effects.

---

# 6. Requirements: the largest rules mismatch

## Current implementation

RequirementExpression currently supports boolean nodes and leaves such as:

- and/or/not
- compare
- has item
- has tag
- relationship
- location
- time
- weather
- has ability

A compare node stores:

- participant: actor or target
- one stat key
- comparison operator
- literal value

Runtime therefore evaluates expressions such as:

`actor.strength >= 10`

The UI exposes exactly this model.

## Missing intended behavior

The desired requirement can compare expressions involving multiple
participants, for example:

`actor.intelligence * 10 > target.tech_level`

The current model cannot express that.

It also assumes compare targets are character/relationship-like. Item targets
are not a first-class ability target even though items may own abilities and
the intended mechanics include comparisons against item stats.

## Target requirement model

Use one shared numeric expression language for both effect formulas and numeric
requirement operands.

Introduce a canonical `ValueExpression`:

- constant
- participant stat
- add
- subtract
- multiply
- divide
- min
- max
- negate

Participants:

- actor
- source
- target

Then a comparison requirement becomes:

- left expression
- operator
- right expression

Example:

`multiply(stat(actor,intelligence), constant(10)) > stat(target,tech_level)`

Keep nonnumeric requirement leaves:

- has item
- has tag
- relationship
- location
- time
- weather
- has ability

These leaves should also use explicit participant selectors where meaningful.

## Compatibility validation

The editor and repository must validate that referenced stats can exist on the
selected participant kind.

Do not list every stat in every dropdown.

---

# 7. Ability semantics

## Current model

An ability currently contains:

- active/passive kind
- character/item owner compatibility
- target type
- requirement tree
- costs
- ordered actions
- passive triggers
- minigame configuration
- icon

Ordered actions can:

- apply an effect
- move
- create
- remove
- reveal knowledge
- change relationship
- advance time
- play noise

## Current problems

1. Ability requirements are less expressive than effect formulas.
2. Item targets are not a first-class target.
3. Costs are primarily actor-oriented and the UI filters stat costs to
   character-compatible stats.
4. Ability outcome behavior is split between reusable effects and inline typed
   actions.
5. This makes it unclear whether a reusable consequence belongs in an ability
   or an effect.
6. Sequential action execution has historically required special care to ensure
   later actions see prior mutations.

## Intended model

An ability is an **activation contract**, not the reusable consequence itself.

It should primarily define:

- who may own/use it;
- active/passive;
- target selection;
- requirements;
- costs;
- passive triggers;
- minigame/activation metadata;
- one reusable result effect/macro.

Conceptually:

`Ability -> requirements + costs + target policy + result_effect_key`

For complex abilities, the referenced effect is the reusable macro containing
the ordered consequences.

Add item as a proper target kind, and make target compatibility explicit.

---

# 8. Effects should become reusable gameplay macros

## Current effect model

An effect currently represents exactly one stat operation plus timing:

- target stat
- add/subtract/set/multiply
- numeric formula
- clock
- duration/tick
- snapshot/live
- stacking
- visibility

This is strong for statuses such as poison/regen, but too narrow for the final
meaning of "effect".

## Intended meaning

Statuses and ability results are both reusable effects.

Therefore the canonical Effect should become a reusable macro with:

- stable key/name/description/icon;
- timing/stacking semantics;
- ordered effect steps.

Effect steps should share the typed gameplay action vocabulary.

Minimum step set:

- modify stat using a ValueExpression;
- move;
- create entity;
- remove/archive entity;
- reveal knowledge;
- change relationship;
- advance time;
- play noise;
- potentially explicit state/lifecycle actions needed for mechanics such as
  death.

A duration-zero effect is an immediate ability result.

A finite/indefinite effect is a status.

Periodic status execution replays the effect's applicable periodic steps using
the configured clock.

## Avoid arbitrary nesting initially

Do not allow unrestricted effect -> effect recursion in the first migration.
If composition is required, either:

- flatten referenced child effects at validation time, or
- permit references only with an acyclic dependency graph and the existing
  recursion/event limits.

---

# 9. Suggested rules V3 normalized storage

Do not destroy the current canonical tables until migration tests exist.

Suggested destination:

## stat_definitions

Keep current identity/presentation/owner tables, but replace mandatory bound
semantics with explicit optional bounds.

## stat_reactions

- project_id
- stat_key
- position
- trigger kind
- comparison/value-expression tree
- effect_key
- enabled

## value_expression_nodes

Use one normalized expression representation shared by:

- effect stat modifications
- requirement left operand
- requirement right operand
- future dynamic numeric fields.

The existing `effect_formula_nodes` can be migrated into this form.

## ability_requirement_nodes

Keep boolean tree structure, but compare nodes reference left/right expression
roots instead of `stat_key + literal value`.

## effect_definitions

Own timing/stacking/visibility metadata.

## effect_steps

Ordered typed effect actions.

## ability_definitions

Own activation semantics and `result_effect_key`.

Costs/triggers/minigame associations remain normalized.

## Migration compatibility

Migrate each current ability action list into a generated/reused result Effect
macro.

For an existing ability:

- preserve current requirement/cost/target settings;
- create `{ability_key}_result` or deterministic collision-safe equivalent;
- copy ordered actions into effect steps;
- point ability at that effect.

Existing one-stat EffectDefinitions become one-step macro effects without
changing their behavior.

---

# 10. Image/media audit

## Current image storage

Images are fragmented across several concepts.

### Entity media

`entity_media_assets` stores:

- project ID
- entity ID
- optional outfit ID
- kind: portrait / full_body / location
- source
- file path
- MIME/name
- prompt / negative prompt
- featured state
- source story node

Files are stored under managed media directories.

### Location backgrounds

`location_backgrounds` references an `entity_media_assets` row and adds:

- weather condition
- time condition
- ordering

### Story-generated images

`image_suggestions` stores its own path/prompt/status against a story node.

### Rule icons

Stat/effect/ability icon fields are currently strings. The frontend accepts
emoji, semantic text, URL, or path.

### Image generation profiles

The image manager already has the correct semantic profiles:

- portrait: 512x512 transparent
- icon: 512x512 transparent
- full body: 784 wide x variable 1552-2048 transparent
- background: 1920x1080 opaque

### Existing helper

A SHA-256 content hash helper exists, but image persistence does not currently
use a global hash-indexed image table.

## Problem

The semantic image profiles are good, but storage/reference semantics are still
resource-local and duplicated.

---

# 11. Target global media architecture

This should remain the next major Phase 7B/7C data migration.

## media_blobs

One row per physical file:

- blob ID
- SHA-256 unique hash
- MIME
- width/height
- byte size
- managed path
- created time

One physical file for identical image bytes.

## media_assets

Semantic reusable media record:

- media asset ID
- blob ID
- semantic kind:
  - icon
  - portrait
  - full_body
  - background
  - story_image
- source: upload/generated/imported
- generation metadata
- prompt/negative prompt
- seed
- model/checkpoint
- workflow
- transparency
- created time
- marked/favorite state if media itself is library-visible

## media_tags

Normalized searchable tags.

Examples:

- character name
- outfit name
- city
- white hair
- night
- generated
- source model tags.

Generation metadata should be retained separately from tags.

## media_references

One asset may be referenced by many owners:

- project/entity
- outfit
- location background condition
- item
- ability
- effect
- stat
- story node
- Global Library resource/revision

Reference rows make these values queryable:

- reference count
- referenced story count
- zero-reference assets

## Icons

Item/stat/effect/ability icons should use an explicit icon source:

- media asset
- emoji
- none

Do not keep overloading one arbitrary string field forever.

## Shared UI

Every image slot should eventually use the same media surface:

- Generate
- Generate with custom prompt
- Upload
- Choose existing compatible media
- View full screen
- Download original
- Remove reference

The full-screen viewer should be shared by:

- story images
- portraits
- full bodies
- backgrounds
- icons

---

# 12. Interface ownership after convergence

| Concept | Primary editor | Secondary/read-only surfaces |
| --- | --- | --- |
| Character | CharacterStudio | story cast / references |
| Outfit | CharacterStudio wardrobe | Global Library |
| Location | Environment & Map (Map V2) | story map / entity links |
| Weather/time | Environment & Map project panel | story scene display |
| Routes/barriers/encounters | Environment & Map | story/player map |
| Faction/item/lore/fact/plot beat | WorldStudio | references |
| Relationship | WorldStudio | character relationship panel |
| Stat/effect/ability | RulesStudio | entity assignment displays |
| Media | shared Media Picker / Global Library | all resource editors |
| Reusable templates | Global Library | Favorite actions from editors |

A concept should not have two independent full editors.

---

# 13. What should not be changed

The audit does **not** recommend rewriting everything.

Keep:

- branch-aware WorldEngine/event model;
- world projection cache;
- normalized spatial materialization;
- Map V2 geometry/route work;
- CharacterState and most of CharacterStudio;
- normalized rule keys and repository separation;
- Global Library immutable revision model;
- image generation profiles;
- weather/time/ambient normalized project definitions;
- typed effect timing/stacking concepts;
- typed target resolution/event caps.

The main work is semantic convergence and removal of duplicated authoring
surfaces.

---

# 14. Proposed implementation sequence

## Slice A — audit guards and UI ownership

Low-risk convergence first.

1. Add architecture tests documenting canonical ownership.
2. Remove editable locations from WorldStudio; replace with "Open in
   Environment & Map".
3. Rename Location Map workspace to Environment & Map.
4. Move the EnvironmentStudio location form into Map V2 sidebar.
5. Move backgrounds and location ambient assignment controls into Map V2.
6. Move project environment/weather/time/audio panels into the same workspace.
7. Retire EnvironmentStudio location CRUD and its simplified admin map after
   parity.
8. Fix character editor viewport overflow.

No database migration should be required for most of Slice A.

## Slice B — unified location API

1. Introduce one typed location service/command path.
2. Make map/sidebar edits use it.
3. Keep specialized geometry placement command for drag performance.
4. Make spatial current tables explicitly rebuild-only.
5. Deprecate duplicate environment location CRUD endpoints.
6. Update player map to consume the same canonical spatial read model.

## Slice C — shared ValueExpression and requirements V2

1. Extract current effect FormulaNode into shared ValueExpression.
2. Add comparison requirement left/right expression trees.
3. Support actor/source/target stat operands.
4. Add item as an ability target.
5. Validate participant/stat owner compatibility.
6. Redesign RequirementEditor around expression operands instead of
   stat-vs-literal only.
7. Add regression tests for:
   - actor stat vs constant,
   - actor stat vs target stat,
   - `actor.intelligence * 10 > target.tech_level`,
   - item targets,
   - missing/incompatible participants.

## Slice D — stat bounds and reactions

1. Support no minimum and/or no maximum.
2. Migrate existing numeric bounds losslessly.
3. Add explicit stat reaction definitions.
4. Reactions reference effects, not arbitrary code.
5. Add threshold crossing semantics and cascade guards.
6. UI should make bounded/unbounded state obvious.

## Slice E — Effect macro / Ability activation split

1. Add effect steps.
2. Convert current one-stat effects to one-step macros.
3. Add result effect reference to abilities.
4. Migrate current ability ordered actions into generated result effects.
5. Preserve active/passive, requirements, costs, target policy, triggers, and
   minigame config on abilities.
6. Ensure each effect step sees the working projection produced by preceding
   steps.
7. Remove obsolete inline ability outcome actions after migration validation.

## Slice F — global media normalization

1. Add hash-addressed media blobs.
2. Add semantic media assets and references.
3. Migrate entity media, location backgrounds, and story images without copying
   duplicate bytes.
4. Add generation metadata/tags.
5. Add image-library reuse and zero-reference counts.
6. Add shared full-screen viewer/download.
7. Migrate item/stat/effect/ability icon inputs to media-or-emoji.
8. Keep current file paths readable during the migration window, then remove
   legacy ownership assumptions.

## Slice G — cleanup / Phase 8 readiness

1. Remove old Environment location editor.
2. Remove legacy location endpoints.
3. Remove old rule compatibility fields/tables once migrations are proven.
4. Remove arbitrary icon string compatibility.
5. Run branch replay / clone / Global Library round-trip tests.
6. Verify planning/generation writes only through canonical APIs.
7. Freeze the canonical object contracts before RAG and AI-interface V2 work.

---

# 15. Required regression matrix before Phase 8

## Locations

- create/edit/delete location from Map V2
- branch switch/replay
- parent changes
- area/spot geometry
- routes follow attachments
- backgrounds/weather/time conditions
- ambient sets
- encounter rules
- Global Library favorite original/latest/both
- spatial materialization rebuild equals projection

## Characters

- no outer-page micro-scroll at supported desktop sizes
- outfit/media switching
- stat/effect display
- branch history
- favorite dependencies

## Rules

- unbounded stat
- one-sided bound
- stat-derived bounds
- bound dependency cycles
- stat reactions
- actor/target/source expressions
- item targets
- ability requirements/costs
- ability result effect
- immediate/status/periodic effects
- stacking
- sequential effect steps
- rollback/cascade limits
- Global Library export/import

## Media

- identical image bytes stored once
- multiple owners reference one asset
- reference/story counts
- generated metadata retained
- choose existing image
- lightbox/download
- zero-reference asset remains until explicit cleanup
- branch deletion removes reference, not shared blob while still referenced

---

# 16. Phase 8 gate

Phase 8 should begin only after these contracts are stable:

- Map V2 is the single location authoring surface.
- Character UI is stable and no longer needs structural work.
- ValueExpression is shared by formulas and requirements.
- Abilities describe activation and point to reusable result effects.
- Effects are reusable gameplay macros/statuses.
- Stats can be truly unbounded and can trigger explicit effect reactions.
- Item targets and target-side requirements work.
- Global media references replace per-owner file duplication.
- Shared media picker/viewer exists.
- Global Library can snapshot/import the finalized resource graphs.

At that point RAG, AI interface V2, advanced resource generation, and advanced
gameplay can build on one coherent domain model instead of learning multiple
overlapping representations.
