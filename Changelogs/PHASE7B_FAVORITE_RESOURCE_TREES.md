# Phase 7B Slice 2 — Dependency-aware favorites

This slice turns the Global Library foundation into a resource-level workflow
available from the canonical editors.

## Favorite workflow

Compatible resources now expose a Favorite control:

- characters,
- locations,
- items,
- factions,
- lore systems,
- facts,
- plot beats,
- outfits,
- stats,
- effects,
- abilities.

Weather, time phases, runtime relationships, and other records that are not
Global Library resource kinds intentionally do not expose the control.

Clicking Favorite asks the backend for a branch-aware dependency preview and
opens one shared selection dialog. The parent is always included. Dependencies
may be individually included or omitted, and nested children cannot be kept
without their selected parent.

The preview is recursive and may include, where applicable:

- character outfits,
- home/faction/owned or inventory items,
- equipment,
- location children,
- current-location context as an opt-in dependency,
- stat definitions,
- stat min/max dependencies,
- abilities,
- effects used by abilities,
- effect target/formula stats,
- requirement/cost/passive-trigger references,
- movement destinations and fact references.

Shared dependencies are displayed once in the picker but all applicable direct
edges are reconstructed in the persisted library graph.

## Original / latest / both

Event-backed world entities compare their initial branch-visible
`entity.created` snapshot with the active branch projection.

When those differ, Favorite offers:

- **Original version**
- **Latest version on this branch**
- **Both as separate revisions**

Selecting Both publishes the original snapshot followed by the current branch
snapshot, leaving the latest snapshot as the resource's current revision.
Changed dependencies receive the same per-dependency choice.

Transient top-level current stat values are not copied into entity snapshots.
Canonical stat definitions are separate dependencies. This keeps reusable
resource state distinct from temporary gameplay values.

Stats, effects, abilities, and outfits currently expose their latest canonical
definition only because those stores do not yet retain their own historical
definition timeline. They can still be dependencies and independent library
resources.

## Branch integrity

If the UI does not explicitly supply a story node, Favorite defaults to the
project's active story node. Published revisions therefore retain active-branch
provenance rather than silently becoming branch-agnostic.

Library resources remain immutable reusable snapshots. Favoriting never turns
a story entity into a live shared row and does not automatically synchronize
future story changes.

## UI surfaces

The shared Favorite control is used by:

- CharacterStudio resource rows,
- selected outfits in CharacterEditorForm,
- WorldStudio general entity rows,
- EnvironmentStudio location rows,
- RulesStudio stat/effect/ability cards.

The dependency/version dialog is shared by all of these surfaces.

## Tests

Coverage includes:

- changed entity original/latest/both publication,
- transitive item -> ability -> effect -> stat dependency discovery,
- shared dependency edge preservation,
- rejection of nested dependencies without their parent,
- active-branch provenance on published revisions.

No global media storage changes are included in this slice. Content-addressed
media, image-library reuse, lightbox/download, and icon media convergence remain
the following Phase 7B work.
