# Phase 3 — DataProvider / Repository Refactor

## Phase 2 status

Phase 2 is now treated as working:
- AI runtime/model switching
- generic text/image generation
- semantic image profiles
- StoryManager + ContextBuilder
- StoryStreamService
- EnvironmentManager / SoundManager / MusicManager
- smaller scheduler + extracted handlers
- normal + transparent ComfyUI terminal outputs

## Phase 3 goal

Managers and domain services should stop owning SQL. `DataProvider` is a typed
repository facade, not a generic query helper.

### Slice 1 — included here
- add DataProvider
- add MusicRepository, SoundRepository, EnvironmentRepository
- migrate MusicManager, SoundManager and EnvironmentManager's direct lookups
- keep constructors backward compatible
- do not alter WorldEngine transaction/event semantics

### Slice 2
- migrate EnvironmentService CRUD SQL
- add MediaRepository and WorkflowRepository
- migrate StoryFinalizer review/media persistence

### Slice 3
- add ProjectRepository, StoryRepository, JobRepository, PlanningRepository
- move route persistence out of main.py
- main.py becomes HTTP validation + delegation

### Slice 4
- add WorldRepository for storage of world transactions/events/cache
- WorldEngine continues to own normalization, preview, branching and commits

### Slice 5
- remove transitional manager `.db` access
- repository integration/transaction tests
- audit for remaining raw SQL outside repositories/migrations

## Later phases

### Phase 4 — BatchGeneration / GenerationPlan
- generation definitions separate from execution
- dependency graph, topological order, approval, cycle detection
- mass + individual generation/regeneration
- appearance/image generation settings

### Phase 5 — typed world model
- typed objects and relationships
- Requirement expression tree
- Effect operations + TargetResolver
- DeepClone dependency policies
- AI-facing compact aliases while preserving persistent IDs
- preserve WorldEngine event/projection semantics

### Phase 6 — UI / World Configuration cleanup
- Preplanning -> Batch Generation
- remove unnecessary rigid stages
- consolidate world configuration entry point
- finalize characters/world/environment/rules/minigames/bullethell/workflows UI
- remove compatibility facades and legacy UI

## Validation

    python -m pytest backend/tests/test_phase3_data_provider.py
    python -m compileall backend/app

Then run the existing backend test suite.
