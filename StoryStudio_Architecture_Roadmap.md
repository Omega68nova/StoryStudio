# StoryStudio Architecture Refactor — Current State and Roadmap
# BASE IDEA
Right now everything is bunched up in large interconnected systems; not only is this dangerous but unmantenible in the long run.
The first phase of fixing this should be diving responsabilities among multiple smaller managers and function files that 

aiGenerator-manager: mainly what the current scheduler's primary function; switching between the text(lamma.cpp) and image (confiui) generation models as needed.
generateImage: image generator function (generic, requires positive, negative, width, height and a boolean makeTransparent); requires aiGenerator-manager
generateText: text completion and conversation llama.ccp functions; requires aiGenerator-manager
Image manager: hosts all distinct image types:
        Portraits are 512x512, 
              must use the transparentOutput output
              required preffix(changeable in config): "portrait, anime style, full color, clean lineart, soft shading,   looking at viewer,  simple background, white background,"
        full body images 2048 x 784, for tall characters, 1552 x 784 for children, a character can be any height in between. 
              must use the transparentOutput output
              required preffix(changeable in config):"full body, standing, anime style, full color, clean lineart, soft shading,   looking at viewer,  simple background, white background,"
        background images are 1920 x 1080, 
              must use the normal output
        icons are 512 x 512 and require the prompt to include  in the beginning since the image ai is very viased for character generation and that preffix counters it.
              "(((no humans))),simple background, white background,"
              must use the transparentOutput output
Sound manager: allows querying current song, theme and story enviroment sounds.
Enviroment manager: solves enviroment like time of day, weather, action, and selected them to query the sound manager.
dataProvider: provides db access, allows fitered queries with dependencies and dependants optionally.
Story manager: Solves enviroment, preset characters, general context and past messages and has functions for continuing with completion and starndard system responses. (current system has a bug that crashes on multiple bot responses in a row)
batchgenmanager:  stores settings and instructions to generate different objects (structure, param shape (appeareance and imegeGenInfo must be a list of tags in text format similar to gelbooru tags, don't include outfit details in main body or the other way around) and has functions to generate them all in mass or individually (generate un character with requeriments, generate 1 character with already existing values, generate 3 characters...)
Orchestrator system: orchestrates all systems together into a semi-seamless system while not shouldering the full load.

- Re-Organizacion of interface and behaviour:
    - Preplanning -> Batch generation; no stages, all can be still run in order, but all are open at all times and more items can be generated for any. Foundation is the only replacing one.
       - GenerationManager: 

- Ai/Human context should include:
   - Main context
   - Relevant facts and plot beats
   - Party composition (who is in the team's group, any follower counts except enemies)
   - Time of day and weather
   - Location: (Description)
   - Available Locations including parent location sublocations and all siblings that are accessible
   - Current action: (Fighting, Running, Walking, Relaxing), -ing verb
   - Characters in location, appeareance (including outfit) and personality including secrets to themselves.
   - Current music theme.
   - Functions to query, edit or create any character, outfit, location, routes, relationships, factions, items, lore systems, facts and plot beats, create images, change music theme, and add sound effects temporarily.
  In the most compressed way possible that the ai can understand.
- Talking about them; we need to formalize preplanning, characters, world, enviroment, rules, minigames, bullethell and workflows into an actual proper data system:
   Instead of being in so many options, make them in a single "World configuration" button that accesses a far more simplistic and utilitarian interface with multiple tables.
DB storage refactor to get ride of broken systems and improve ai compatibility
Target types: self, choice, all, allies, enemies, random.
Object types: (all have a id (NUMERIC id since uuids confuse ai, or alterantively compound keys of source story and internal name (key: {story:"Story3", id:"attack"})), name and identity and description, genDescription, and icon)
   Location: ParentLocation (default NULL = root), coords, RandomEncounter, exposurelevel.
   Weather: transmissionWeather
   Time: Duration (ingame), layer.
   Ambience :[locations], [weathers], [times], backgroundImage(can be null), [soundEffects], overrideSoundEffects=false, defaultMusic
   Character: aliases, pronouns, personality, goals, character secrets, secrets from character, appeareance, isPlayerControlled, autonomyLevel (none, low, medium, high)
   Outfit: (nothing else)
   Stat: Max, Min, normal. Max and Min can be either a number or another stat (Eg id:"hp", "name":"Health", min=0, maxStat="maxhp" (references stat.maxhp) (max=100 but Stats overrida raw max and minStat=null), effect
   Requeriment:Stat, min(number) (can be null), max(number) (can be null)
   Ability: [requeriments], isPasive, effect
   Item: [requeriments], isConsumable, [effects]
   ActionEffect: actionText, sound.
   Enemy:
   Faction:
Relationship types:
   ItemOwner: item, char, ammount
   AbilityOwner: char, ability.
   EffectInflicted: char, effect, durationLeft.
   Path: startLocation, endLocation, distance, roughnessMultiplier
   RelationShipStat: feelerChar, feltChar, stat, count.
   CharStat: char, stat.
   CharOutfit: char, outfit. charImage(can be null),
   CharWearing: char, outfit.
   ObjLocation: Character/Item, Location
   CharHome: Character, Location 
   QueryRequeriment: targettype, targetid, sourcetype, sourceid, selectquery.
   CustomRelationship: type1, id1, type2, id2, [requeriments], name, description, 
   Effect:
     - Stat1
     - Stat2
     - Ability (optional)
     - TargetType
     - Duration (time) = 0 (-1 = infinite)
     - Tick (time) = 0 (0 = once, 1 once per action of character including context
 Ability to deepClone as required to other stories (character with optionaly: stats, abilities, items, outfits, characters with relationship, home), (location with characters, sublocations, items and factions), (items with their stats, abilities and requeriments), (enemy with stat and abilities), outfits.
 Tree visibility of dependencies
 Ability to create object, relationships and dependants with a single prompt (location, character, item, stat, ability, effect, outift, enemy, faction); should create the object and dependants recursively. (starting by dependants), give a final object, and once aproved commit all in order.
  -Tries to create ability: ability needs effect (select or create) that needs stat (select or create) that needs maxStat that is anther stat...
  -Tries to create character: outfit, faction, relationship with other characters...

## 1. Purpose

This document captures the architecture we have built so far, the structure we are converging on, and the remaining work needed to finish the refactor.

The central architectural decision is:

> **GenerationPlan / BatchGeneration is the single workflow owner for generation, review, approval, regeneration, and commit.**

Planning is no longer a separate workflow engine. It is now a specialized use of GenerationPlan.

The governing implementation rule for this roadmap is:

> **This is primarily a behavior-preserving extraction refactor.** Existing
> responsibilities should be moved out of large files into small, named
> modules with clearer ownership and test boundaries. New product behavior is
> secondary and must be identified explicitly rather than being folded into
> an extraction.

Unless a slice says otherwise, its compatibility target is the behavior that
existed before the extraction: persistence, events, API payloads, runtime
semantics, and user-visible workflows remain unchanged. A new module or type
does not by itself authorize redesigning the feature it contains.

---

## 2. Target architecture

The intended high-level structure is:

```text
UI / API
   |
   v
GenerationPlan
   |
   v
BatchGenerationManager
   |
   +------------------+-------------------+
   |                  |                   |
   v                  v                   v
Generate            Review              Commit
   |                  |                   |
   v                  v                   v
Task generators    revisions /       Domain committers
   |               approval
   |
   +--> Text
   +--> Image
   +--> Deterministic
   +--> Planning-specific executor
   |
   v
AI / runtime managers
```

The key ownership rules are:

- GenerationPlan owns task lifecycle.
- BatchGeneration owns execution.
- Domain services own validation and publication.
- AI/runtime managers own model/runtime concerns.
- ImageManager should own semantic image generation concerns.
- World/domain services own persistent world state.
- No parallel Planning-specific persistence/state machine should exist.

---

## 3. What has been completed

## Phase 3 — DataProvider / repository architecture

Phase 3 established repository boundaries and moved persistence responsibilities out of managers and services where appropriate.

Completed work included:

- DataProvider facade
- project repository
- story repository
- job repository
- workflow repository
- media repository
- review repository
- environment repository
- music repository
- sound repository
- world repository
- runtime repository
- repository boundary tests

The important result is that managers generally do not own raw persistence.

---

## Phase 4 — GenerationPlan / BatchGeneration

Phase 4 is now complete.

### Slice 1 — GenerationPlan foundations

Added:

- `GenerationPlanDefinition`
- `GenerationTaskDefinition`
- `GenerationDependency`
- task validation
- dependency validation
- cycle detection
- topological layers
- readiness calculation
- descendant calculation
- persistent generation plans/tasks/dependencies

GenerationPlan tasks support states including:

```text
pending
blocked
ready
queued
running
generated
approved
committed
failed
cancelled
stale
```

Dependency requirements can target:

```text
generated
approved
committed
```

This gives us a real DAG rather than a fixed stage counter.

---

### Slice 2 — Execution

GenerationPlan execution was connected to the scheduler.

The active job type is:

```text
batch_generation
```

`BatchGenerationJobHandler` handles:

- text tasks
- deterministic tasks
- image delegation
- planning-specific structured generation

Planning no longer has its own job handler.

---

### Slice 3 — Review / approval / commit

Generation tasks gained:

- revisions
- approval
- rejection
- regeneration
- commit
- commit metadata

This separates:

```text
generated
approved
committed
```

That separation is important because generation output can be reviewed before it modifies the canonical world.

---

### Slice 4 — Planning migration bridge

Planning sessions were initially imported into GenerationPlan through a temporary bridge.

The bridge existed only to move ownership safely.

It was not intended to remain part of the final architecture.

---

### Slice 5 / 6 — Planning execution consolidation

Planning generation was moved onto the same BatchGeneration execution path.

Reusable structured generation behavior was extracted into:

- `PlanningGenerationCore`
- `PlanningBatchTaskExecutor`

`PlanningGenerationCore` contains reusable structured-generation mechanisms such as:

- raw llama completion
- JSON continuation
- truncated-output recovery
- retrying empty output without prompt cache
- random creative-direction generation

`PlanningBatchTaskExecutor` handles planning-specific prompt/context/validation behavior.

The old PlanningJobHandler was removed.

---

### Slice 7 — GenerationPlan API

GenerationPlan became a first-class API surface.

The frontend planning workflow now talks through GenerationPlan-backed APIs for:

- task generation
- result editing
- approval
- rejection
- revisions
- commit
- preflight
- generate-ready

---

### Slice 8 — GenerationPlan becomes editable/review state owner

Editable planning drafts stopped being owned by `planning_stages`.

Generation task results became the authoritative editable state.

Previous-stage context is now built from committed GenerationPlan task results.

This removed continuous state synchronization between Planning v2 and GenerationPlan.

---

### Slice 9 — Provenance ownership

Canonical resource/image provenance was moved away from planning-session ownership.

GenerationPlan now owns:

- resource-key provenance
- planning image records
- publication identity

This removed the hidden requirement that canonical resources remain attached to a planning session.

---

### Slice 10 — Legacy Planning v2 removal

This was the destructive consolidation pass.

Migration `033_remove_legacy_planning.sql`:

- imports untouched historical planning sessions into GenerationPlan
- preserves historical transaction receipts
- normalizes planning tasks to `planning_workspace`
- recreates task dependencies
- migrates resource provenance
- migrates image-plan ownership
- removes the last planning-session FK from inactive world transactions

It then drops the old workflow tables:

```text
planning_sessions
planning_stages
planning_stage_revisions
planning_conflicts
planning_approval_claims
planning_entity_keys
planning_resource_keys
planning_image_plans
```

The runtime bridge was also removed.

`PlanningGenerationBridge` no longer exists.

The old planning restart repair logic was removed.

---

## 4. Current planning architecture

Planning is now built on top of GenerationPlan.

### PlanningWorkspaceService

`PlanningWorkspaceService` is a compatibility/workspace layer over GenerationPlan.

It:

- creates an eight-task planning GenerationPlan
- exposes a temporary PlanningSession-like UI shape
- maps GenerationPlan task states to planning-stage UI states
- queues planning tasks
- skips/reopens/revalidates tasks
- exposes task revisions
- manages planning image-plan records

Important:

> The `session.id` exposed to the current PlanningStudio UI is actually a GenerationPlan ID.

This is temporary compatibility vocabulary, not a second persistence model.

---

### PlanningPlanContext

Builds planning prompt context directly from GenerationPlan.

Previous committed tasks are used as prior-stage context.

There is no planning-stage table lookup.

---

### PlanningBatchTaskExecutor

Executes planning text tasks through BatchGeneration.

It uses:

- GenerationPlan task prompt/settings
- PlanningPlanContext
- PlanningGenerationCore
- planning schema/validation helpers

---

### PlanningService

PlanningService is no longer a workflow owner.

Its role is now semantic/domain behavior:

- planning validation
- world inventory
- conflict preflight
- canonical publication
- resource provenance
- image-plan preparation

This is much closer to the desired architecture.

---

### PlanningTaskCommitter

`PlanningTaskCommitter` publishes an approved planning GenerationPlan task into canonical project/world state.

Flow:

```text
GenerationPlan task
      |
      v
approved
      |
      v
PlanningTaskCommitter
      |
      +--> preflight
      +--> conflict resolution
      +--> PlanningService.publish()
      |
      v
canonical world/config state
```

---

## 5. Current GenerationPlan model

GenerationPlan is now the central workflow primitive.

Each task contains:

- task key
- label
- generator kind
- target kind
- target key
- prompt data
- settings
- dependencies
- status
- revision number
- generated result
- active job
- review data
- commit metadata

The DAG supports non-linear plans.

Example:

```text
Foundation
   |
   +--> Locations
   |
   +--> Rules
   |
   +--> Characters
           |
           +--> Character details
           +--> Portraits
```

The current planning workspace is still sequential, but the underlying architecture is not limited to sequential stages.

---

## 6. Current execution architecture

```text
GenerationPlan
      |
      v
BatchGenerationManager
      |
      v
generation_jobs(kind=batch_generation)
      |
      v
BatchGenerationJobHandler
      |
      +--> text
      +--> deterministic
      +--> image
      +--> PlanningBatchTaskExecutor
```

This gives us one generation scheduler path.

That was one of the main goals of Phase 4.

---

## 7. Current canonical publication path

For planning:

```text
GenerationPlan task
      |
      v
generated
      |
      v
review / edit
      |
      v
approved
      |
      v
PlanningTaskCommitter
      |
      v
PlanningService.publish()
      |
      +--> WorldEngine
      +--> weather
      +--> stats
      +--> abilities
      +--> outfits
      +--> routines
      +--> ambient assignments
      +--> music config
      +--> story defaults
      |
      v
committed
```

The canonical world remains separate from generation drafts.

That is intentional.

---

## 8. Current provenance model

Planning resource aliases/keys are now owned by GenerationPlan.

Current tables include:

```text
generation_resource_keys
generation_image_plans
```

These replace the old planning-session-owned equivalents.

Historical session IDs may still be retained as inert migration/audit metadata, but runtime ownership is GenerationPlan.

---

## 9. Current test baseline

The post-Phase-4 test consolidation removed tests that existed only to preserve deleted architecture.

Tests were kept/reworked around current contracts:

- GenerationPlan DAG behavior
- execution
- review/approval/commit
- regeneration
- revisions
- structured JSON continuation
- canonical publication
- world validation
- planning semantic validation
- image generation
- authorization
- repository boundaries
- scheduler behavior

Old tests for the deleted Planning v2 state machine were removed or rewritten.

---

# 10. Planning specialization after wire cleanup

## PlanningStudio vocabulary

The planning API and frontend now present:

```text
plan
task
current_task
dependencies
```

The fixed workshop is a GenerationPlan specialization, not a second workflow
engine. Historical database columns and internal planning algorithms may still
use stage terminology where it specifically describes the eight-task template.

---

## Eight-stage planning layout

The current planning workspace still constructs the traditional eight planning tasks.

The dependency editor can now represent and validate arbitrary DAG edges. The
default workshop template remains eight tasks because that ordering is useful
product configuration, not an engine limitation.

---

## Planning naming

Files such as:

```text
planning.py
planning_v2.py
PlanningWorkspaceService
PlanningBatchTaskExecutor
```

still carry historical naming.

Some of that is useful because planning remains a real domain.

But `planning_v2.py` in particular should eventually be renamed/split because “v2” no longer describes a live migration layer.

---

# 11. Important hardening still worth doing

These are not required to say Phase 4 is complete, but they are valuable before the system grows much larger.

## Commit idempotency

There is still a failure window conceptually:

```text
domain publication succeeds
        |
        X process crashes
        |
task not marked committed
```

The long-term solution should be an idempotent commit receipt.

Example:

```text
task commit key
      |
      v
domain publication
      |
      v
commit receipt
      |
      v
task marked committed
```

Retrying the operation should never duplicate publication.

---

## approve_many transaction semantics

`approve_many()` validates all tasks first and then approves them one by one.

It is not a single atomic transaction.

We should explicitly choose:

- all-or-nothing transaction
- or best-effort with per-task results

and encode that behavior deliberately.

---

## richer plan lifecycle

Useful GenerationPlan lifecycle operations could include:

```text
cancel plan
cancel subtree
archive plan
supersede plan
clone plan
```

These become useful once GenerationPlan is used for more than planning.

---

## result replacement revision behavior

Manual result replacement should have a clearly defined revision policy.

The invariant should probably be:

> Any user-visible replacement of a generated result creates recoverable revision history.

That prevents manual edits from silently overwriting history.

---

# 12. Phase 5 — typed world/domain model

Phase 5 establishes the typed domain and compatibility boundaries described
below. The expression, effect, target, alias, clone, and one-shot-noise
extensions in this section are implemented as described in the completion
handoff.

Today much of the world system still uses:

```text
dict[str, Any]
JSON state
generic entity kinds
string-based relationships
```

This is flexible, but too weak as the system grows.

The target is explicit domain types.

Suggested core types:

```text
Location
Weather
Time
Ambience
Character
Outfit
Stat
Requirement
Ability
Item
ActionEffect
Enemy
Faction
```

Supporting structures:

```text
RequirementExpression
EffectOperation
TargetResolver
Relationship
ClonePolicy
DomainReference
AI alias mapping
```

---

## Typed persistent identity

Persistent IDs should remain stable.

AI-facing aliases can be human-friendly, but they must resolve to persistent canonical IDs.

Example:

```text
AI key: "old_town"
        |
        v
DomainReference
        |
        v
UUID: 8f6...
```

AI should never directly decide database identity.

---

## Requirement expression tree

Requirements should move away from ad-hoc JSON blobs toward a typed expression tree.

Example:

```text
AND
├── stat("strength") >= 10
└── OR
    ├── has_item("key")
    └── faction_reputation("guild") >= 50
```

Possible node types:

```text
And
Or
Not
Compare
HasItem
HasTag
RelationshipCheck
LocationCheck
TimeCheck
WeatherCheck
```

---

## Effect operations

Actions/abilities should use typed effects.

Example:

```text
EffectOperation(
    target=Actor,
    operation=Subtract,
    stat="stamina",
    amount=10,
)
```

Potential operations:

```text
Set
Add
Subtract
Multiply
Move
Create
Remove
ApplyStatus
RevealKnowledge
ChangeRelationship
AdvanceTime
```

---

## Target resolver

Abilities/effects should not embed arbitrary target logic.

A TargetResolver should resolve semantic targets such as:

```text
actor
target
party
location
nearby_enemies
faction_members
relationship_target
```

into concrete domain IDs.

---

# 13. AI architecture we want

The AI should operate through structured context and tools rather than direct persistence.

Target AI context:

```text
Main context
Facts / plot beats
Party members
Time
Weather
Location
Recent actions
Characters
Appearance
Personality
Secrets
Music theme
Available tools
```

AI tools should perform controlled domain actions such as:

```text
search world
create/update entity
move character
advance time
change weather
create relationship
generate image
generate music
play/generate SFX
```

Critical invariant:

> AI never writes directly to the database.

It should request domain operations through services/managers.

---

# 14. Image architecture we want

The long-term image architecture should separate semantic intent from ComfyUI graph topology.

Desired flow:

```text
Generation task
      |
      v
ImageManager
      |
      +--> semantic image kind
      +--> prompt
      +--> negative prompt
      +--> width / height
      +--> transparency
      +--> style/profile
      |
      v
aiGenerator-manager
      |
      v
ComfyUI runtime/workflow
```

ImageManager should understand:

```text
character portrait
full body
location
item
background
transparent asset
```

It should not need to understand the exact ComfyUI graph structure.

---

# 15. Runtime/model architecture we want

The target runtime manager is the common AI execution layer.

Conceptually:

```text
aiGenerator-manager
      |
      +--> generateText(...)
      |       |
      |       +--> llama.cpp runtime
      |
      +--> generateImage(...)
              |
              +--> ComfyUI runtime
```

Responsibilities:

- runtime startup/shutdown
- model switching
- context size
- VRAM/resource management
- backend health
- retry/recovery
- common generation API

Domain services should not know runtime implementation details.

---

# 16. Other domain managers

The intended modular services remain:

```text
ImageManager
SoundManager
EnvironmentManager
MusicManager
StoryManager
BatchGenerationManager
WorldEngine / domain layer
```

Each manager should own semantic behavior for its domain, while repositories own persistence.

---

# 17. Phase 5 implementation order and completion boundaries

## Phase 5A — typed world foundations

Introduce typed domain models without immediately rewriting every caller.

Start with:

```text
DomainId / DomainReference
Location
Character
Weather
Stat
Ability
RequirementExpression
ActionEffect
```

Build conversion layers to/from existing JSON state.

---

## Phase 5B — typed relationships and targeting

Add:

```text
Relationship
TargetResolver
RequirementEvaluator
EffectExecutor
```

Move world mutation validation onto typed operations.

**Completed:** relationship views, recursive requirement expressions,
semantic/group target expansion, deterministic target persistence, ability
cost/effect calculation, expanded non-stat effects, and direct stat adjustment
now use typed domain operations.

---

## Phase 5C — AI tool/domain boundary

Define explicit AI-facing tools that call domain services.

Remove remaining places where AI prompt/execution code knows storage-level details.

**Completed compatibility scope:** storyteller planning uses one
`AIWorldToolService` for tool metadata, policy filtering, compact context,
read execution, and staged write normalization. The planner no longer queries
the database directly. Ephemeral AI keys and unique aliases are resolved to
canonical persistent IDs at this boundary.

---

## Phase 5D — semantic media generation

Finish ImageManager abstraction.

Then apply the same model to:

```text
music
ambient audio
sound effects
```

**Completed:** image jobs execute through `ImageManager`,
which owns both semantic image requests and a deletion-target adapter for
legacy generic requests. Music, ambient loops, and one-shot noises retain
separate semantic managers. No audio generation was introduced: noises and
ambient speed variants both use stored files.

---

## Phase 5E — PlanningStudio / GenerationPlan UI cleanup

Replace compatibility vocabulary.

Move from:

```text
planning session
stage number
current stage
```

toward:

```text
GenerationPlan
task
dependency
task state
```

Allow arbitrary DAG display and editing.

**Completed:** fixed planning entries are presented as
GenerationPlan tasks, task metadata/default result construction lives outside
the monolithic component, stage-centric user-facing and wire labels are
removed, and the plan owner validates arbitrary task/dependency edits. The
editor exposes dependency graph changes and rejects cycles.

---

# 18. Final desired structure

A clean end-state would look approximately like:

```text
Frontend
   |
   v
API
   |
   +--> StoryManager
   +--> BatchGenerationManager
   +--> ImageManager
   +--> MusicManager
   +--> SoundManager
   +--> EnvironmentManager
   |
   v
Domain services
   |
   +--> Character
   +--> Location
   +--> Weather
   +--> Ability
   +--> Requirement
   +--> Effect
   +--> Relationship
   |
   v
Repositories / DataProvider
   |
   v
Database
```

Retrieval is a derived view of canonical storage, not another persistence
owner:

```text
Repositories / DataProvider
      |
      +--> canonical branch-aware records
      |
      +--> RetrievalProjection --> disposable search/vector index
                                      |
                                      v
                                 ContextBuilder
```

AI sits beside the domain layer:

```text
AI tools
   |
   v
Domain services
```

not:

```text
AI
 |
 v
Database
```

Generation infrastructure sits beside both:

```text
GenerationPlan
      |
      v
BatchGeneration
      |
      v
AI runtime managers
```

---

# 19. Architectural invariants going forward

These are the rules worth protecting with tests.

1. **One generation workflow owner**
   - GenerationPlan owns generation lifecycle.

2. **No parallel planning state machine**
   - Planning is a GenerationPlan specialization.

3. **No AI direct database writes**
   - AI uses domain tools/services.

4. **Repositories own persistence**
   - Managers/services should not casually accumulate raw SQL.

5. **Domain publication is explicit**
   - Generated content does not become canonical until commit.

6. **Persistent IDs remain stable**
   - AI-friendly aliases must not replace canonical identity.

7. **Compatibility layers must have deletion targets**
   - Temporary adapters must not become permanent architecture.

8. **Semantic managers hide runtime topology**
   - Image/music/sound domain code should not know backend graph internals.

9. **Tests protect current contracts**
   - Do not retain tests solely to preserve deleted implementation.

10. **Extraction is the default kind of change**
   - Move existing responsibilities into focused modules before redesigning
     them.
   - Call out the smaller set of intentional feature changes separately.
   - Preserve external behavior and compatibility unless a slice explicitly
     changes the contract.

11. **Retrieval is never canonical storage**
   - Search documents, embeddings, and graph indexes must be rebuildable from
     repository-owned records.
   - Retrieved state is reloaded from the active branch before use.

12. **Retrieval preserves branch and visibility boundaries**
   - A memory from another branch, an undiscovered location, or a secret the
     current narrator cannot know must not enter storyteller context.

---

# 20. Phase 7 — canonical storage refactor

Phase 3 established repository ownership, but it deliberately did not finish
the underlying storage redesign described in the base idea. Phase 7 will
normalize the remaining JSON-heavy and compatibility-era persistence behind
those repository boundaries.

This phase must preserve stable persistent identity, world event/projection
semantics, branch history, and existing API contracts while migrations are in
progress. The typed Phase 5 domain models define the target records; storage
rows must not become the public domain API.

Expected implementation slices:

1. Inventory canonical records, duplicated state, JSON columns, compatibility
   tables, and current migration/read paths.
2. Define normalized repository records for world entities, relationships,
   rules, revisions, and branch-aware events while retaining lossless plugin
   data.
3. Normalize story turns, branch ancestry, summaries, and their references to
   world transactions.
4. Migrate incrementally with dual-read or explicit adapters where required;
   each compatibility path must have a deletion target.
5. Remove superseded persistence paths only after migrated data and branch
   replay behavior are verified.

The storage refactor should expose stable version/revision markers so derived
systems can update incrementally. It must not add embeddings or make a
retrieval database authoritative.

---

# 21. Phase 7B — reusability, branch integrity, and global library

Phase 7B is a prerequisite for the remaining Phase 7 polish and for Phase 8.
Phase 8 will create and retrieve far more resources; reusable snapshots,
provenance, dependency trees, and shared media must exist before AI generation
starts producing them at scale.

The governing rule is:

> **Branches own runtime truth. The Global Library owns immutable reusable
> revisions.**

A library resource must never be the same mutable row as an entity, rule, or
runtime state inside a story. Saving from a story publishes an immutable
snapshot revision with provenance. Importing creates or updates project-local
canonical records and records which library revision they came from. Library
revisions never silently synchronize into existing stories.

Expected implementation slices:

## Phase 7B-A — revisioned global resource foundation

- Add first-class global resources with stable library IDs and typed resource
  kinds.
- Store immutable numbered revisions containing versioned snapshots.
- Record optional source project, story node/branch, source kind, and source
  key for every published revision.
- Allow resources to form dependency trees/bundles through explicit child
  edges instead of embedding unrelated records into one opaque JSON blob.
- Track project imports separately so usage counts and provenance remain
  queryable without making the library authoritative over story state.
- Add marked/unmarked resources, searchable tags, and a Global Library
  workspace directly below Stories.
- Keep import/update/compare explicit; no automatic synchronization.

## Phase 7B-B — stat packs and rule bundles

- Replace hardcoded story-creation stat presets with reusable `stat_pack`
  resources.
- A stat pack captures canonical definitions and their dependency ordering,
  not transient per-character values.
- Support saving selected or complete stat sets from a story as a new library
  resource or a new revision.
- Import stat packs with explicit conflict policy and project-local copies.
- Extend the same resource-tree mechanism to effects, abilities, and mixed
  rule packs, resolving immutable keys and dependencies explicitly.

## Phase 7B-C — entity/resource trees

**In progress:** compatible resource editors now expose dependency-aware
Favorite actions. Character/location/item/faction/lore/fact/plot-beat
snapshots can publish their initial branch state, latest active-branch state,
or both as immutable revisions. Stats, effects, abilities, and outfits can
also be favorited and participate in dependency trees; rule/outfit historical
version selection remains pending a dedicated canonical revision history.

- Save initial state and explicitly player-approved important updates for
  characters, items, locations, factions, lore systems, outfits, and related
  resources.
- Allow tree publication such as character -> outfits, home, items, stats,
  abilities/effects, relationships, and dependent rule definitions.
- Provide dependency preview and selective include/exclude when publishing or
  importing a tree.
- Preserve exact source branch/story-node provenance for every published
  revision so alternate branches can intentionally produce separate library
  revisions.

## Phase 7B-D — global shared media

- Move image file identity to a content-addressed global media layer so one
  physical file can serve many story/resource references.
- Use SHA-256 (or equivalent content hash) for deduplication; references, not
  copied files, attach media to characters, outfits, items, rules, locations,
  and story illustrations.
- Preserve semantic image kinds even when dimensions match:
  `icon`, `portrait`, `full_body`, `background`, and `story_image`.
- Preserve generation metadata (prompt, negative prompt, seed, workflow,
  model/checkpoint, dimensions, transparency, source resource/outfit) and
  searchable tags such as character name and appearance/location concepts.
- Generated metadata is descriptive/searchable data, never canonical world
  state.
- Expose reference count, referenced story count, and zero-reference state in
  the library. Zero-reference assets remain until explicitly cleaned up.

## Phase 7B-E — shared media input/viewer

- Every image input uses one reusable picker surface: generate, upload, choose
  from library, view full screen, download, and remove reference.
- Item/ability/effect icons use the canonical transparent 512x512 icon profile
  but may explicitly use an emoji alternative.
- Portraits and icons remain semantically distinct despite sharing 512x512
  transparent dimensions.
- Story illustrations, portraits, full bodies, backgrounds, and icons all use
  one full-screen media viewer with original-file download.
- Library media defaults to a thumbnail grid with optional table view and
  filters for marked/all, kind, tags, referenced/unreferenced, and generation
  source.

## Phase 7B-F — compare, update, cleanup, and hardening

- Compare a story-local resource with the library revision it originated from.
- Explicitly update/re-import from a newer revision with dependency/conflict
  preview.
- Publish a new library revision from an important player-decided branch state
  without automatically exporting transient simulation values.
- Add orphan/unreferenced media cleanup with confirmation and marked-resource
  protection.
- Test branch isolation, provenance, import determinism, dependency cycles,
  media deduplication/reference counts, and revision immutability.

Phase 7B must be substantially complete before Phase 8 resource generation or
RAG indexing treats global-library resources as reusable context.

---

# 22. Phase 8 — branch-aware context retrieval (RAG)

Phase 8 adds retrieval-augmented context after the canonical storage model is
stable. Its purpose is to reduce prompt size for mature stories without
replacing deterministic scene state or repository-owned persistence.

The storyteller context is divided into two classes:

- **Always included:** current scene, POV character, present characters,
  environment, current stats/effects, immediate rules, and recent turns.
- **Retrieved when relevant:** distant entities, older events and dialogue,
  facts, lore, previous locations, dormant plot threads, and branch summaries.

Retrieved documents contain canonical source references and indexing metadata,
not authoritative copies of mutable state. Before a result is included,
StoryStudio must verify that it belongs to the active project and branch,
passes narrator/character visibility rules, and still resolves through the
repositories. Current entity state is then rehydrated from the active branch.

Expected implementation slices:

## Phase 8A — retrieval contracts and source projection

- Preserve the existing `MemoryProvider` boundary where useful, but separate
  source projection, indexing, candidate retrieval, and canonical rehydration.
- Define versioned chunks for story turns, summaries, lore/entity cards, and
  world events.
- Include project, source record, branch ancestry, visibility, involved
  entities, location, and story/world time metadata.
- Treat the existing Cognee integration as an optional compatibility adapter,
  not the final storage architecture.

## Phase 8B — built-in hybrid retrieval

- Combine exact ID/name/alias matches, lexical/FTS search, relationship graph
  distance, recency, plot relevance, and semantic similarity.
- Return bounded candidate references with ranking evidence.
- Deduplicate historical mentions against the canonical current entity card.

## Phase 8C — incremental and rebuildable indexing

- Update derived indexes after committed world transactions and completed
  story turns.
- Handle revisions, deletion/tombstones, archive state, and branch changes.
- Retain a full-project rebuild command for recovery and provider changes.

## Phase 8D — ContextBuilder adoption

- Use the user request, scene intent, resolved aliases, and active plan as the
  retrieval query.
- Apply explicit configurable token ceilings to mandatory world state,
  retrieved memory, recent transcript, instructions, and response space.
- Support both direct and planned story generation rather than limiting
  retrieval to planning paths.
- Fall back safely to canonical compact context when the optional retrieval
  provider is unavailable.

## Phase 8E — inspection and evaluation

- Show which memories were selected, why they ranked, their token cost, and
  why candidates were filtered.
- Test branch isolation, secret/knowledge visibility, stale-state
  rehydration, deterministic fallback, and index rebuilding.
- Measure context reduction and story recall on representative long-running
  projects before changing default budgets.

---

# 23. Current roadmap status

```text
Phase 3 — DataProvider / repositories
    COMPLETE

Phase 4 — GenerationPlan / BatchGeneration
    COMPLETE

Post-Phase-4 test consolidation
    COMPLETE

Phase 5 — Typed world/domain model
    COMPLETE

Phase 6 — UI/world configuration cleanup
    IN PROGRESS — Slice 2 complete

Phase 7 — Canonical storage refactor
    IN PROGRESS — typed entities, spatial storage, and canonical rules complete

Phase 7B — Reusability / branch integrity / Global Library
    IN PROGRESS — revisioned foundation, stat packs, and dependency-aware favorites implemented

Phase 7C — Consistency convergence
    PLANNED — unify location authoring, rules semantics, and media ownership before Phase 8

Phase 8 — Branch-aware context retrieval (RAG)
    FUTURE — depends on Phase 7 canonical records and Phase 7B reusable-resource/media foundations
```

Phase 5A established lossless typed identity, entity, weather, rule,
requirement, and effect models. Phase 5B moved evaluation and execution into
typed domain operations and now includes recursive expressions, semantic
target sets, and expanded effects. Phase 5C provides the AI tool gateway and
ephemeral alias resolution. Phase 5D keeps image, music, ambient loops, and
stored one-shot noises behind distinct managers. Phase 5E makes task
dependencies editable and removes the obsolete stage vocabulary from the
planning wire contract. Deep world-subgraph cloning is available through its
own service and API.

The most important architectural achievement so far is that StoryStudio now has a single generation workflow model.

Phase 6 Slice 1 consolidates the project-scoped configuration editors behind
one World configuration workspace without changing their APIs or internal
behavior. The next slices can extract the remaining large editor
implementations, unify repeated resource-table/editor infrastructure, and
retire compatibility UI only after its replacement is complete.

Phase 6 Slice 2 extracts the ComfyUI workflow preset editor from `App.tsx`.
The World configuration workspace now owns that focused module directly;
workflow import, mapping, validation, persistence, and deletion contracts are
unchanged. Further slices should continue extracting coherent application and
settings responsibilities before introducing shared editor abstractions.

The current built-in/Cognee memory provider is an early retrieval scaffold.
It may continue to operate during the refactor, but Phase 8 must rebuild its
inputs around Phase 7 repository records rather than cementing current tables
or JSON payloads into the retrieval architecture.

## Phase 7 spatial-map slice status

The branch-aware spatial-map foundation is implemented. It formalizes a world
root, independent open/closed topology and direct/child-required occupancy,
typed anchors, barriers, routes, doors, portals, encounter rules, locks, and
resumable travel itineraries. Spatial mutations remain `WorldEngine` events
and are additionally recorded as append-only repository revisions with
normalized geometry vertices.

Legacy route relationships and environment map APIs remain adapters.
`POST /spatial/migrate` promotes existing maps to canonical roots, anchors,
connections, and zero-probability encounter rules. Planning stages 2 and 3 now
generate location presets, anchors, and typed connections; legacy `routes`
remain an import-only compatibility shape.

The Location Map configuration tab owns root adoption/creation, nested layer
navigation, pan/zoom/touch interaction, location and anchor placement, barrier
drawing, typed connection creation, object inspection, and structural
warnings. Future editor refinements should remain in that focused module
instead of returning map responsibilities to `App.tsx`.

Phase 7's typed entity contract slice replaces generic projection parsing for
factions, items, lore systems, facts, and plot beats with explicit permissive
domain states. Their projection adapters remain lossless, preserve extension
fields and sparse historical shapes, and expose canonical references without
changing persistence or HTTP payloads. Item gameplay semantics, relationship
definitions, media slots, storage normalization, and planner adoption remain
separate later slices.

## Phase 7 consistency-convergence status

A repository-wide audit is recorded in
`Changelogs/PHASE7_CONSISTENCY_AUDIT_PLAN.md`.

The audit establishes three remaining structural convergence goals before
Phase 8:

1. **Location authoring converges on Map V2.** The current Environment,
   Location Map, and World surfaces expose overlapping location concepts.
   Map V2 should become the single Environment & Map authoring workspace,
   with descriptive location fields, backgrounds, ambient assignments,
   weather/time controls, encounters, and spatial behavior brought into the
   map/sidebar rather than maintained as separate location editors.

2. **Rules move from normalized storage to final gameplay semantics.**
   Stats must support true unbounded values and explicit effect reactions.
   Requirement comparisons must use actor/source/target numeric expressions,
   including target-side stats and item targets. Abilities become activation
   contracts pointing to reusable result effects; Effects become reusable
   ordered gameplay macros/statuses instead of only one-stat operations.

3. **Media becomes globally referenced rather than owner-local.** Existing
   image generation profiles remain valid, but entity media, location
   backgrounds, story images, and rule icons need one hash-addressed media
   identity/reference model, shared picker, lightbox/download, generation
   metadata, tags, and reference counts.

Character storage is considered structurally sound; its remaining work in this
convergence pass is UI sizing/polish and adoption of the shared media system.

The detailed migration order and regression gate are in the audit document.
No Phase 8 retrieval/generation contract should depend on the duplicated
location editors, current stat-vs-literal requirement shape, single-stat
EffectDefinition shape, or per-owner image file storage.

## Phase 7 canonical-rules slice status

Stats, reusable effects, and abilities now use immutable project-local keys
and normalized repository tables. Stat definitions declare compatible owner
kinds and support transitive stat-derived bounds. Global effects own their
target stat, bounded expression tree, timing clock, evaluation mode, and
stacking policy. Abilities reference those effects and keep movement, noise,
knowledge, relationship, time, creation, and removal as separate typed
actions.

Runtime rule behavior is extracted from `WorldEngine` into `RulesRuntime` and
`RuleEventProjector`. `WorldEngine` remains the branch-aware coordinator: it
orders mutations, validates the complete projection, and commits transactions,
but it no longer evaluates formulas, resolves ability costs, advances active
effects, performs passive cascades, or owns rule-specific projection shapes.
Canonical repository validation is shared by HTTP editing, planning
publication, and deep cloning, while dependency-aware publication preserves
dynamic stat bounds and cross-ability references.

The Rules screen uses structured stat, formula, effect, requirement, cost,
action, trigger, and minigame editors. Legacy inline requirement/cost/effect
JSON columns are removed by migration 042. Marker-only statuses and temporary
legacy instances are intentionally discarded with visible migration warnings;
permanent `stat.changed` history is retained.
