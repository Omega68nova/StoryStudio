# Phase 7B Slice 1 — Global Library foundation

This slice starts the reusable-resource and branch-integrity work that must
precede Phase 8.

## Architectural rule

Branches remain the authority for runtime story state. The Global Library owns
immutable reusable revisions only.

Publishing from a story never moves the live entity/rule row into the library.
Importing never makes a story point at mutable global state. Every import
creates or updates project-local canonical records and records which library
revision was used.

## Added persistence

Migration `046_global_library.sql` adds:

- `library_resources`
- `library_resource_revisions`
- `library_resource_children`
- `library_resource_tags`
- `library_project_imports`

Resources have stable global IDs, typed resource kinds, marked state, tags,
and an explicit current revision. Revisions are immutable numbered snapshots
and may preserve source project, exact story node/branch, source kind/key, and
publication note.

Resource children are explicit dependency/tree edges rather than opaque nested
copies. Cycles are rejected. Project imports are recorded separately so
library usage can be counted without making library rows authoritative over a
story.

## First reusable resource: stat packs

`GlobalLibraryService` introduces first-class reusable stat packs.

A saved stat pack contains canonical stat definitions and dependency ordering,
not character runtime stat values. A pack may be published as a new resource
or as a new immutable revision of an existing pack.

Import validates:

- snapshot version/type,
- complete stat-bound dependency closure,
- indirect dependency cycles,
- owner compatibility of bound stats,
- explicit conflict policy.

Imported definitions receive the destination project ID and are saved through
`RulesRepository`; the library revision remains unchanged.

## UI

A Global Library workspace now appears directly below Stories.

The initial view supports:

- marked-only versus all entries,
- type filtering,
- name/description/tag search,
- revision count,
- child/dependency count,
- referenced-story count,
- import count,
- saving the current story's complete canonical stat set as a marked stat pack,
- applying a stat pack to the current story with explicit stop-on-conflict or
  keep-existing behavior.

New-story creation now selects marked reusable stat packs from the Global
Library instead of exposing the two hardcoded Adventure/Romance choices.
The legacy `stats_preset` request field remains temporarily supported for old
callers and is a deletion-target compatibility path.

## Deliberately deferred

This slice does not yet implement:

- character/item/location publication trees,
- effect/ability/rule-pack publication,
- compare/update UI,
- global content-addressed image storage,
- media reference counting,
- shared image picker/lightbox/download,
- zero-reference cleanup,
- automatic synchronization.

Those remain the next Phase 7B slices described in the architecture roadmap.

Tests were added for stat-pack round-trip/import, revision immutability,
resource trees, cycle rejection, and cross-project branch-provenance rejection.
