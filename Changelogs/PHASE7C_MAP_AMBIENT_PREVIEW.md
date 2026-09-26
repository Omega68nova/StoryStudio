# Phase 7C — Map ambience preview follow-up

This follow-up extends the Environment & Map ownership work with a live
weather/time ambience audition workflow.

## Toolbar preview controls

Environment & Map now has three preview controls on the right side of the map
toolbar:

- Weather
- Time of day
- Toggle sound

Weather defaults to the project's enabled initial weather. Time defaults to the
first enabled phase. These selectors are preview-only and do not mutate the
story's current scene environment.

The sound toggle requires a selected location. When enabled it plays the
ambience that resolves for that location under the selected weather/time.

## Same ambience sources as runtime

The map loads the existing
`GET /api/projects/{project_id}/environment/ambient` payload. It uses the same:

- indexed ambient variants and sound URLs,
- weather-owned assignments,
- time-owned assignments,
- location-owned assignments,
- exposure selectors,
- tag selectors,
- weather/time conditions,
- enabled/available variant filtering.

The map preview additionally treats the action selector as `standing`, matching
the normal idle scene case.

The normal story AmbientPlayer is faded out while the map preview is enabled so
the author does not hear the live story ambience and editor preview mixed
together.

## Live unsaved location ambience

The selected-location inspector now contains its location ambient sound sets.

Changes are draft-local until **Save ambience** is pressed. In particular:

- adding a sound,
- removing a sound,
- adding/removing a conditional set,
- changing exposure/tag selector,
- changing weather condition,
- changing time condition

all recompute the playing preview immediately.

No temporary assignment is written to the database for previewing.

This intentionally differs from the old edit/save cycle: audio authoring is now
auditionable before persistence.

Map/world refreshes do not discard the current location ambience draft.
Switching to another location loads that location's saved assignment sets.

## Saving

**Save ambience** uses the existing canonical replacement endpoint:

`PUT /api/projects/{project_id}/environment/ambient/assignments/location/{location_id}`

The preview therefore needs no new persistence API and does not create another
ambient model.

**Reset ambience** restores the saved assignment state for the selected
location.

## Next

Weather/time definition editing and the ambient/noise catalogs still need to
move into Environment & Map before the old Environment settings workspace can
be removed.
