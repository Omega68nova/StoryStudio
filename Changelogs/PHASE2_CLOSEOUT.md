# StoryStudio Phase 2 — Final Integrated Closeout

This is the consolidated Phase 1 + Phase 2 generation architecture.

It is intended to replace the earlier separate starter ZIPs as the reference
tree for the next migration step.

## Included architecture

```text
GenerationScheduler
    queue / cancellation / generic job lifecycle
    |
    +-- AIGeneratorManager
    |     llama.cpp / ComfyUI runtime ownership
    |
    +-- StoryJobHandler
    |     job adapter + minigame-session persistence
    |     |
    |     +-- StoryManager
    |     |     turn interpretation / planning / memory candidates
    |     |     |
    |     |     +-- ContextBuilder
    |     |           compact model context
    |     |           |
    |     |           +-- EnvironmentManager
    |     |                 +-- SoundManager
    |     |                 +-- MusicManager
    |     |
    |     +-- StoryStreamService
    |     |     live token stream / inline envelopes / repair loop
    |     |
    |     +-- StoryInlineActions
    |     |     world-domain validation
    |     |
    |     +-- StoryFinalizer
    |           commit / review / encounter media / background jobs / memory
    |
    +-- ImageJobHandler
    |     workflow resolution + persistence
    |     |
    |     +-- generate_image
    |     +-- ImageManager
    |
    +-- PlanningJobHandler
          current Planning v2 behavior
```

## Consolidation corrections

### 1. Workflow-native image dimensions are preserved

The generic `ImageGenerationRequest` now uses:

```python
width: int | None = None
height: int | None = None
```

Existing image jobs that omit dimensions therefore preserve the dimensions
already encoded in their ComfyUI workflow instead of being silently forced to
512x512.

Typed `ImageManager` requests still explicitly provide:

```text
portrait:   512 x 512
full body:  784 x 1552..2048
background: 1920 x 1080
icon:       512 x 512
```

### 2. Transparency is opt-in during migration

Existing `portrait` / `full_body` DB asset kinds do not automatically imply a
transparent workflow output in `ImageJobHandler`.

Why: the current production workflow schema exposes only `image_output`.
Automatically inferring transparency from the media kind would break existing
workflows that do not have a second transparent terminal node.

New callers should explicitly provide:

```text
make_transparent = true
transparent_output_node_id = ...
```

until WorkflowMappings receives a first-class transparent-output mapping.

### 3. Runtime transitions are visible again

`AIGeneratorManager` now reports model ownership transitions back through the
scheduler state callback, restoring events such as:

```text
loading_storyteller
switching_to_image
restoring_storyteller
```

without putting GPU-transition implementation back into GenerationScheduler.

### 4. Current `main.py` compatibility is preserved

The live API currently accesses domain services through properties such as:

```python
scheduler.world
scheduler.planning
scheduler.minigames
```

The final Phase 2 scheduler keeps these as explicitly transitional facades.

They are **not** part of the long-term scheduler responsibility.

Phase 3 should inject `WorldEngine`, `PlanningService`, `MinigameService`, etc.
directly into routes/services and then remove these scheduler compatibility
attributes.

### 5. Default handlers are registered automatically

For drop-in migration:

```python
scheduler = GenerationScheduler(db, events, supervisor)
```

installs:

```text
story    -> StoryJobHandler
image    -> ImageJobHandler
planning -> PlanningJobHandler
```

Callers may still pass an explicit handler mapping for tests/customization.

### 6. Correct environment-manager spelling

New code uses:

```text
environmentManager.py
```

A deprecated compatibility shim is included at:

```text
enviromentManager.py
```

for any stale imports.

## Phase 2 boundaries now achieved

### Scheduler

No story generation implementation.
No planning generation implementation.
No image workflow execution implementation.

It dispatches jobs.

### StoryManager

No JobExecutionContext.
No EventHub.
No raw token loop.
No final story persistence.

It prepares a story turn.

### StoryStreamService

No scheduler.
No world model.
No minigame DB persistence.
No finalization.

It provides the live validated prose stream.

### EnvironmentManager

Owns resolved runtime scene state and delegates sound/music responsibilities.

### SoundManager

Owns ambient sound discovery and resolution.

### MusicManager

Keeps three existing concepts separate:

```text
project policy
canonical story theme
shared multiplayer playback
```

## Deliberately not changed in Phase 2

The database model remains intact.

`WorldEngine` remains temporal/event-sourced.

Persistent IDs remain strings.

Planning v2 remains the active planning implementation.

Authoring CRUD in `main.py` remains mostly where it is.

`DataProvider` / repository conversion is deferred to Phase 3.

Batch-generation dependency planning is deferred to Phase 4.

## Validation performed on this package

- Every generated Python file is parsed with Python's AST parser.
- Generated-to-generated `app.*` imports were checked.
- The consolidated interfaces were reconciled against current `master` for:
  - `Database` job update methods
  - `LlamaClient`
  - `ComfyClient`
  - `ProcessSupervisor`
  - `NpcDirector`
  - `MinigameService`
  - `PlanningService`
  - current scheduler runtime semantics

This is still not a substitute for running StoryStudio's full test suite and a
real llama.cpp + ComfyUI integration test after applying the overlay to a repo
branch.

## Recommended migration before Phase 3

Apply this overlay on a branch, then run:

```text
backend unit tests
startup / scheduler warm-up
direct story generation
low planning story generation
smart planning story generation
inline world mutation
minigame pause + resume
user stop during streaming
review-required mutation
image suggestion generation
portrait/full-body existing workflows
background generation
planning stage generation / append / repair
music theme change
ambient scene resolution
```

Once those pass, Phase 2 can be treated as complete and Phase 3 can begin with
the DataProvider/repository boundary.
