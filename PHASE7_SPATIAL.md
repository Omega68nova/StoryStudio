# Phase 7 Spatial Map Handoff

## Canonical boundary

Locations remain branch-projected world entities. Their state now owns
topology, occupancy, boundary access, spatial kind, scale, visibility,
encounter rate, footprint, and local bounds. Characters store their deepest
occupied location and optional local coordinates; ancestors are inferred.

Anchors, barriers, typed connections, encounter rules, and itineraries are
branch-aware projection collections produced only from world events. The
repository mirrors every mutable spatial event into append-only revisions and
normalizes geometry vertices. Database rows and raw polygons are not AI DTOs.

Shapely owns geometry validity, containment, intersection, and distance.
`SpatialService` owns open/closed path resolution, barrier and requirement
checks, deterministic exploration/encounters, partial travel, discovery, and
compact blocked reasons. `WorldEngine` remains the transaction, branch, and
validation authority.

## Compatibility boundary

- A sole legacy top-level location is read as an implicit root.
- `POST /api/projects/{project_id}/spatial/migrate` persists that root or
  creates a closed, child-required synthetic `World` root for multiple
  top-level locations.
- Migration retains legacy route IDs and creates center anchors plus typed
  route connections. Legacy random-encounter locations become candidates with
  probability zero.
- `findRoute`, `moveCharacter`, `getLocationMap`, the environment map API, and
  `setRelationship(relation="route")` remain operational adapters.
- Legacy route writes should be removed only after every project has a
  canonical root and planning/import no longer emits `routes`.
- Environment, time, weather, ambient loops, music, and one-shot noises remain
  operational in rootless projects.

## AI and planning contract

The storyteller reads semantic local maps, travel options/previews, status,
and reviewed presets. It writes root/location records, anchors, barriers,
connections, discovery changes, primitive geometry edits, and the four travel
actions. Persistent IDs remain canonical; aliases are prompt-only. Geometry
is omitted from compact player/storyteller map output and may remain a
review-required draft.

Planning stages 2 and 3 now describe preset-backed locations, anchors, and
typed connections. Existing saved `routes` are still accepted as a
compatibility import shape but are no longer present in the compact generation
schema.

## Authoring surface

The project configuration workspace now includes a Location Map tab with root
creation/adoption, breadcrumbs, nested layers, touch-safe pan/zoom, placement
tools, barrier drawing, route/door/portal creation, inspection, and structural
warnings. The existing Environment editor remains responsible for weather,
time, backgrounds, ambient loops, and the detailed location form.

## Follow-up boundaries

- Connect travel lock interruptions to standalone minigame sessions and commit
  persistent versus one-pass authorization from verified minigame results.
- Expand the map inspector from its current semantic/raw preview into focused
  forms for requirements, encounter weights, lock configuration, discovery,
  and point-level editing.
- Add the travel simulation/reachable-area overlay and administrative/player
  visibility switch to the map workspace.
- Elevation, 3D navigation, true occlusion, sight cones, and advanced
  line-of-sight remain intentionally deferred.

Tests and builds were not run during this slice, per the project workflow.
