# Spatial V3 — Navigation Spaces and Layered Map Features

This document supersedes the current conceptual spatial model for future Map V3
work. It is deliberately implemented in parallel with the current Map V2 schema
so migration can be incremental and branch-safe.

The core change is simple:

> **Locations are semantic places. Navigation spaces describe where movement
> happens. Map features describe geometry and traversal inside those spaces.**

This removes the need for a growing matrix of location flags such as
spot/area, open/closed, occupancy mode, boundary access, local bounds, and
special-case obstacle behavior.

---

# 1. Why the current spatial model is being replaced

The existing system makes a Location simultaneously represent:

- a semantic place,
- its geometry in a parent map,
- whether it has an interior map,
- whether actors can occupy it directly,
- whether its boundary is freely crossable,
- whether it is a point or area,
- encounter behavior,
- travel behavior.

Those are different concepts.

A city district is a semantic place and a region, but usually has no separate
interior map.

A building is a semantic place and a footprint in its parent map, and may own
another map containing rooms/corridors.

A city wall blocks crossing but the city interior remains navigable.

A road is a thick navigable surface, not a graph edge.

A portal is a transition that may ignore geometry entirely.

Trying to encode all of those as variations of Location creates too many
dependent booleans and special cases.

---

# 2. Core concepts

## Location

A semantic world entity.

Examples:

- Eias-Bústaðr
- Market District
- Inn
- Inn Lobby
- Forest
- Shrine

A Location can exist without owning a map.

A Location can be represented by one or more map features in a parent
NavigationSpace.

A Location can optionally own a NavigationSpace.

---

## NavigationSpace

One interactable movement map.

Examples:

- world/regional map,
- city map,
- dungeon floor,
- house interior,
- cave system.

Fields:

- stable ID,
- project,
- optional owner location,
- navigation mode,
- base travel multiplier,
- optional bounds,
- revision/provenance.

Navigation mode is only:

### free

The base map is navigable unless features restrict it.

Typical uses:

- world maps,
- cities,
- forests,
- wilderness.

Unassigned space remains valid traversable space.

### routed

The base map is non-navigable. Occupancy is limited to authored traversable
features such as rooms and corridors.

Typical uses:

- building interiors,
- point-and-click maps,
- tightly routed dungeons.

This means a building interior does not need a separate "child required"
occupancy flag. If its NavigationSpace is routed, the actor must be on a room,
corridor, or other traversable feature.

---

# 3. Map feature primitives

A NavigationSpace contains features.

The initial V3 feature set is intentionally small.

## Surface

Polygon or MultiPolygon.

Represents an area the actor may be inside.

Examples:

- ocean,
- river,
- forest,
- city footprint,
- city district,
- room,
- building footprint,
- swamp,
- bridge deck.

A Surface may reference a semantic Location.

Surfaces may overlap. Point queries return **all matching surfaces**.

This is intentional.

An actor standing on a road inside the Market District inside the city is
simultaneously inside:

- city,
- district,
- road/travel surface.

No single "winning area" owns the coordinate.

Surface properties may influence:

- movement,
- encounters,
- ambience,
- environment tags.

---

## Corridor

LineString or MultiLineString + width.

Represents a width-bearing traversable strip authored from a centerline.

Examples:

- road,
- alley,
- hallway,
- footpath.

The editor/runtime derives its polygon from the centerline and width.

This makes branching roads much easier to author than hand-editing a large
polygon around every street.

Corridors can modify movement cost and encounter behavior just like surfaces.

---

## Barrier

LineString or MultiLineString.

Represents blocked or conditional **crossing**, not blocked interior area.

Examples:

- city wall,
- fence,
- cliff edge,
- hedge,
- security boundary.

A wall around a city does not make the city polygon itself blocked.

Instead:

- city = Surface,
- city wall = Barrier,
- gates = Connectors.

Barriers use a TraversalPolicy.

Examples:

- completely blocked,
- fly over,
- climb with equipment,
- pass after a stat/ability requirement.

---

## Connector

Explicit transition between two points/spaces.

Examples:

- door,
- gate,
- stairs,
- ladder,
- bridge transition,
- climb point,
- portal.

Connectors may have:

- source space + point,
- target space + point,
- requirements,
- travel multiplier,
- fixed travel time,
- directionality.

Portals intentionally do not require their endpoints to have a geometric
relationship.

A door from a city map to a building interior is just a Connector between two
NavigationSpaces.

---

## Spot

Point feature.

Examples:

- fountain,
- chest,
- sign,
- interaction point,
- landmark,
- NPC anchor.

A Spot may reference a semantic Location or another world entity later.

---

# 4. Geometry

Spatial V3 uses a GeoJSON-like geometry contract.

Supported now:

- Point
- LineString
- MultiLineString
- Polygon
- MultiPolygon

Polygon rings support holes.

MultiPolygon supports disconnected shapes belonging to one logical feature.

Examples this enables:

- district with an excluded central plaza,
- forest in multiple disconnected patches,
- river islands,
- building footprints with courtyards,
- complex city walls,
- multipart regional zones.

The editor should never require users to type GeoJSON directly.

---

# 5. Layering

Layering is primarily an editor/render concept, not semantic containment.

Default presentation groups:

1. topology
2. regions
3. roads
4. places
5. barriers
6. connections

A city map could therefore render:

### topology

- ocean
- river
- base terrain
- city wall

### regions

- market district
- residential district
- forest difficulty regions

### roads

- roads
- alleys
- bridges

### places

- buildings
- landmarks
- spots

The same coordinate may belong to many features across these layers.

Layer visibility can be toggled independently.

Each layer also has a label mode:

- hidden
- important
- all

This replaces the current always-visible large opaque location labels.

Future UI should render labels more like conventional maps:

- transparent/floating text,
- optional subtle outline/shadow,
- zoom-sensitive visibility,
- buildings/spots hidden until appropriate zoom.

---

# 6. Traversal policy

Traversal is attached to spatial features, not encoded as a Location type.

A TraversalPolicy contains:

- default allowed or blocked,
- default travel multiplier,
- zero or more alternative traversal options.

Example: ordinary forest

    default_allowed = true
    travel_multiplier = 1.8

Example: road

    default_allowed = true
    travel_multiplier = 0.65

Example: city wall

    default_allowed = false

Example: climbable cliff

    default_allowed = false

    option Fly:
      requirement: actor has ability Fly
      multiplier: 1.0

    option Climb:
      requirement: actor has climbing gear
      multiplier: 3.0

Requirements are intentionally stored as opaque versioned payloads during the
Spatial V3 foundation.

Spatial V3 must not permanently adopt the current limited stat-vs-literal
RequirementExpression because Phase 7C Requirements V2 will introduce shared
actor/source/target ValueExpressions.

---

# 7. Movement resolution

The old "one area wins by priority" model should not survive.

Instead:

1. find all enabled surfaces/corridors containing the actor/segment;
2. collect applicable movement modifiers;
3. find barriers intersected by movement;
4. find connector overrides where relevant;
5. evaluate available traversal policies;
6. combine semantic memberships separately from movement rules.

Movement priority exists only to resolve conflicting movement modifiers in the
same family.

It does not remove semantic membership.

Example:

At one coordinate:

- City surface
- Market District surface
- Main Road corridor
- River surface
- Bridge corridor

The actor remains semantically inside City and Market District.

The travel resolver may choose Bridge/Main Road movement behavior over River
walking restrictions because the crossing feature is more specific.

The precise combination algorithm should be implemented and tested in the
runtime slice rather than inferred from render order.

---

# 8. Buildings and interiors

On the parent map:

    Tavern
      semantic Location
      building footprint Surface
      owns NavigationSpace: Tavern Interior

The exterior building footprint may be non-traversable from the surrounding
map.

Entry occurs through a Door Connector:

    city point -> Tavern Lobby point

Inside:

    NavigationSpace mode = routed

Features:

- Lobby surface
- Kitchen surface
- Bedroom surfaces
- Hallway corridor
- interior barriers/walls where needed
- doors/connectors

Because routed maps have no navigable unassigned background, the actor cannot
be "inside the Tavern but outside every room/path".

That behavior follows from the NavigationSpace mode instead of an occupancy
special case.

---

# 9. Regional/city maps

For a free map:

    navigation_mode = free

The map itself supplies default traversability.

Features override or modify it:

- forest -> slower movement + forest encounters
- road -> faster movement
- river/ocean -> block walking
- city district -> different ambience/encounters
- city wall -> blocks crossing
- gate -> connector through wall

Unassigned map space remains valid.

This avoids requiring a giant "open area" polygon just to fill empty map
space.

---

# 10. Encounters and ambience

Encounter and ambience behavior belongs primarily to spatial features and
NavigationSpaces, not to generic Location flags.

Surfaces/corridors may provide:

- encounter rate,
- encounter table,
- ambience tags/context,
- environment tags/context.

Multiple overlapping semantic regions may contribute context.

The final resolver will define precedence/merging rules, but data modeling no
longer assumes exactly one current area.

This supports:

- city encounters,
- district-specific encounters,
- road encounters,
- forest difficulty bands,
- interior room ambience.

---

# 11. Authoring presets

Presets are editor conveniences, never persistent object subclasses.

Suggested presets:

## Open region

Creates:

- Surface
- open traversal
- region render layer

## Forest

Creates:

- Surface
- slower travel multiplier
- outdoor environment tags
- encounters enabled

## Road

Creates:

- Corridor
- width
- faster travel multiplier
- roads layer

## River

Creates:

- Corridor or Surface
- walking blocked by default
- water tags

## Building

Creates:

- semantic Location
- parent-map building footprint Surface
- owned routed NavigationSpace
- inherited interior bounds by default
- door Connector workflow
- indoor environment defaults

## Walled settlement

Creates:

- semantic city Location
- city Surface
- owned free NavigationSpace
- Barrier following selected boundary
- gate Connector workflow

After creation every object is composed from normal V3 primitives.

No runtime code branches on "building preset" or "forest preset".

---

# 12. Parallel migration strategy

Spatial V3 is added beside the existing spatial system.

Do not delete current tables yet.

Migration order:

1. Add V3 domain contracts and parallel materialized tables.
2. Add conversion adapter from current map state into V3.
3. Add V3 read endpoint.
4. Add V3 editor rendering behind a feature flag/development route.
5. Add V3 authoring mutations through WorldEngine.
6. Add movement/membership resolver.
7. Migrate existing routes:
   - ordinary thick roads should become Corridors,
   - doors/portals become Connectors,
   - barriers become Barriers,
   - areas become Surfaces.
8. Migrate locations that actually own child maps into NavigationSpaces.
9. Verify branch replay/materialization parity.
10. Switch Environment & Map to V3.
11. Remove old spatial flags only after migrated projects replay correctly.

---

# 13. Current fields that become compatibility data

Long term, these LocationState fields should not remain authoritative spatial
semantics:

- spatial_kind
- topology
- occupancy
- boundary_access
- footprint
- local_bounds
- priority_layer
- random_encounter
- encounter_rate
- minutes_per_unit
- base_visibility_units

Their information migrates into:

- NavigationSpace,
- MapFeature,
- TraversalPolicy,
- encounter configuration,
- visibility/discovery state.

Location keeps semantic/environment data.

Compatibility readers may continue to synthesize the old fields during the
migration window.

---

# 14. Foundation implemented on this branch

This branch currently adds:

## Migration 047

Parallel tables:

- navigation_spaces_current
- map_features_current
- map_surface_properties
- map_corridor_properties
- map_barrier_properties
- map_connector_properties
- map_spot_properties
- location_navigation_spaces_current
- navigation_space_layers_current

These tables are explicitly current-state/materialized storage. Branch history
remains WorldEngine events.

## Domain models

backend/app/domain/spatial_v3.py defines:

- free/routed NavigationSpace
- GeoJSON geometry with holes and MultiPolygon support
- Surface / Corridor / Barrier / Connector / Spot
- TraversalPolicy and conditional options
- presentation layers/label modes
- nested location-space relation

## Tests

Initial domain tests cover:

- polygon holes,
- disconnected MultiPolygon regions,
- ring closure,
- corridor centerline + width,
- semantic surface references,
- blocked/conditional barriers,
- free/routed map modes,
- feature/geometry compatibility.

---

# 15. Next implementation slice

The next safe step on this branch should be a **read-only adapter and preview**:

1. convert current Map V2 projection into temporary V3 NavigationSpaces and
   features;
2. expose a V3 read endpoint;
3. render those V3 features in Environment & Map without changing authoring
   persistence;
4. validate city/road/barrier/building examples against real projects;
5. only then introduce V3 editing mutations.

That allows the new geometry/traversal model to be proven visually before old
spatial data is rewritten.
