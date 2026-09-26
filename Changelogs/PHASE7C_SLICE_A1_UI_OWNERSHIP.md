# Phase 7C Slice A1 — UI ownership convergence

This is the first implementation pass of Slice A from the Phase 7 consistency
audit. It deliberately changes interface ownership before removing any backend
compatibility endpoints.

## Implemented

### Environment & Map is now the primary location workspace

The configuration navigation now names Map V2 **Environment & Map**.

The previous Environment tab is renamed **Environment settings** and explicitly
described as transitional for location controls. It remains available while
weather/time/audio and the remaining location-only controls are moved into Map
V2.

WorldStudio no longer exposes locations through its generic entity editor.
Locations are still canonical branch-aware WorldEngine entities; this is only an
authoring ownership change.

### Map V2 location inspector parity

The selected-location sidebar now owns more of the descriptive/environment
surface that previously required EnvironmentStudio:

- name,
- description,
- image-generation description,
- tags,
- image tags,
- parent,
- spot/area representation,
- topology,
- occupancy,
- boundary access,
- exposure,
- travel scale,
- visibility,
- encounter rate,
- area priority,
- enabled/discovered/hidden/random-encounter state,
- backgrounds,
- Global Library favorite action.

Background authoring now exposes all stored weather/time variants rather than
silently showing only the first row.

Map V2 also now exposes the first project-level Environment settings directly:
environment enablement, AI location creation, AI weather proposals, automatic
backgrounds, initial weather, background workflow, and perception stat. New backgrounds can be generated or
uploaded for:

- any weather / any time,
- a specific weather,
- a specific time phase,
- a weather + time combination.

Existing variants can be selected and regenerated independently.

This uses the existing canonical environment/media endpoints, so no duplicate
storage model is introduced.

### Character viewport polish

The character editor no longer derives its height from a raw `82vh` value.
It now reserves room for application/configuration chrome using dynamic viewport
units, preventing the small outer-page vertical overflow seen when the full-body
rail fills the editor.

Internal character panes remain the scrolling surfaces.

## Intentionally not removed yet

EnvironmentStudio still contains its old location list/form and simplified map.
Removing those now would temporarily remove features that have not yet moved to
Map V2, particularly:

- conditional ambient sound-set editing,
- project weather/time management,
- ambient/noise catalog management,
- project environment behavior/workflow settings.

Those controls are now explicitly transitional rather than co-equal location
authoring surfaces.

## Next Slice A work

A2 should continue moving into Environment & Map:

1. weather definitions/transitions;
2. time-cycle definitions/order;
3. location conditional ambient sets;
4. ambient/noise catalogs;
5. any remaining background controls not represented in Map V2.

After parity:

- delete the EnvironmentStudio location list/form and simplified admin map;
- remove the separate Environment settings top-level tab if all project
  environment controls fit cleanly into Environment & Map;
- retain only the player-facing map where needed;
- begin Slice B endpoint consolidation.

No database migration is required by A1.
