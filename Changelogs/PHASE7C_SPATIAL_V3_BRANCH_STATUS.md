# Spatial V3 experimental branch status

Branch: `phase7c-spatial-v3-foundation`

This branch is intentionally kept separate from `master`. It is a parallel
implementation used to prove that Spatial V3 is materially simpler and more
capable than the current location/spatial model before any replacement is
merged.

## Implemented foundation

### Navigation spaces

A semantic Location may own a NavigationSpace.

Navigation spaces explicitly choose:

- `free`: unassigned space is navigable unless features block/modify it;
- `routed`: unassigned space is void and only authored traversable geometry
  is occupiable.

This replaces overloading Location topology/occupancy with map mechanics.

### Map features

The new feature vocabulary is:

- Surface
- Corridor
- Barrier
- Connector
- Spot

Surface geometry accepts Polygon and MultiPolygon, including holes.

Corridors are LineString/MultiLineString centerlines plus width. They are
therefore real width-bearing roads, alleys and hallways rather than zero-width
route edges.

Barriers block crossing rather than blocking the interior they surround.

Connectors represent doors, gates, stairs, ladders, bridges, climb points and
portals. Portal endpoints may live in unrelated navigation spaces.

Spots are point-like interactions/landmarks.

### Layered membership

Point resolution returns every containing Surface/Corridor. There is no longer
one winning semantic area.

A coordinate can therefore simultaneously be:

- inside a city,
- inside a district,
- on a road,
- inside another environmental region.

Movement policy is resolved separately. The highest `movement_priority`
surface/corridor supplies the local movement policy, so a road can override a
slow/blocked terrain movement rule without removing semantic membership in the
terrain/city/district.

### Geometry

The V3 canonical geometry is GeoJSON-shaped and supports:

- Point
- LineString
- MultiLineString
- Polygon with holes
- MultiPolygon with holes

The legacy two-point pseudo-polygon is not canonical V3 geometry. Legacy
degenerate objects are flagged for review during migration.

### Traversal policies

Traversal is attached to map features rather than semantic Locations.

A policy may:

- allow normal traversal;
- block traversal;
- provide conditional alternatives with requirements;
- alter travel multiplier;
- provide fixed traversal time.

Requirement payloads remain intentionally versioned/opaque until the shared
Requirements V2 / ValueExpression work lands. Spatial V3 does not encode a new
map-only requirement language.

## Random encounters

Random encounters are first-class navigation policies, not a
`Location.random_encounter` flag.

An encounter policy targets either:

- the NavigationSpace base zone; or
- any MapFeature.

This supports different encounter behavior for:

- open/unassigned terrain,
- cities,
- districts,
- forests,
- roads/corridors,
- connectors/transitions,
- any other feature.

Policies compose with:

- `augment`: add encounter rate/candidates;
- `replace`: replace lower-priority contributors;
- `disabled`: suppress lower-priority encounters.

Two trigger kinds currently exist:

### Distance

Defined as expected encounters per 100 map units.

The probability of at least one encounter over distance `d` is resolved as a
Poisson process:

`1 - exp(-(rate_per_100_units / 100) * d)`

This makes encounter chance scale consistently with actual movement distance.

### Transition

A single probability roll when traversing a feature/connector.

This exists both because it is useful for gates/doors/routes and because it
preserves the old encounter-rule semantics losslessly.

Legacy `encounter_rate + random_encounter children` is also preserved during
migration as an explicit transition policy and flagged for later review. It can
then be converted to a distance-based policy in the V3 editor.

Encounter conditions are reserved for the shared Requirements V2 evaluator.

## Parallel persistence

Migrations 047-049 add only new Spatial V3 tables.

The old `spatial_*` tables and current Map V2 runtime remain untouched.

Spatial V3 canonical state now lives in branch-aware WorldEngine events and the
active WorldEngine projection. The V3 SQL tables are explicitly rebuildable
query/materialization state and may be cleared/rebuilt from the active branch.

## Legacy migration adapter

The branch now contains a deterministic legacy -> V3 adapter.

Current conversions:

- old map-owning locations -> NavigationSpaces;
- old open/closed topology -> free/routed mode;
- area footprints -> Surface features;
- spots -> Spot features;
- barriers -> Barrier features;
- doors/portals/routes -> Connector features;
- old requirements -> versioned traversal alternatives;
- old encounter rules -> V3 transition encounter policies;
- old map-level encounter fallback -> V3 transition encounter policy;
- default editor/render layers -> V3 layers.

Legacy routes are intentionally migrated as generic Connectors and flagged for
review because the old model has no physical width. A road should be explicitly
converted to a V3 Corridor after migration.

Experimental comparison endpoints:

- `GET /api/projects/{project_id}/spatial-v3/migration-preview`
- `POST /api/projects/{project_id}/spatial-v3/materialize`
- `GET /api/projects/{project_id}/spatial-v3/spaces`
- `GET /api/projects/{project_id}/spatial-v3/spaces/{space_id}`
- `GET /api/projects/{project_id}/spatial-v3/spaces/{space_id}/resolve`
- transition encounter resolver endpoint

These are branch-only diagnostics and are not yet the production map API.

# What remains

## 1. Branch-owned canonical V3 events — implemented

Spatial V3 now participates in WorldEngine branch history through canonical
events for:

- navigation-space upsert/removal;
- feature upsert/removal (geometry is part of the feature payload);
- encounter-policy upsert/removal;
- layer updates;
- semantic Location <-> NavigationSpace binding/unbinding.

The WorldEngine projection owns canonical V3 state. The
`navigation_spaces_current` / `map_features_current` family is now treated
as a rebuildable query/materialization layer and is synchronized from the
active branch projection before V3 reads/resolution.

Legacy -> V3 materialization now commits a single author transaction containing
V3 events, then rebuilds the query tables from that branch projection. Existing
branch V3 spaces are removed first so stale child features/layers/bindings and
encounters cannot survive a re-migration.

Spatial V3 mutation tools are intentionally author-only for now: AI and
storyteller provenance is rejected until the V3 runtime/editor is stable.

## 2. Full movement/pathfinding runtime

Current V3 resolver can determine:

- layered membership at one coordinate;
- dominant local movement policy;
- conditional traversal alternatives.

Still needed:

- free-map path search around/through barriers;
- corridor cost integration;
- movement across regions with changing costs;
- requirements evaluation using the shared rules evaluator;
- connector traversal;
- routed-space graph/path traversal;
- portals across arbitrary spaces;
- travel-time integration along the complete path.

## 3. Full encounter integration into travel

Current V3 resolves encounter context and probabilities, but does not yet drive
the production travel itinerary.

Still needed:

- integrate path length per feature;
- split a route where encounter contributors change;
- stable seeded random roll/selection;
- pause/resume itinerary on encounter;
- condition evaluation via Requirements V2;
- preserve current retry stability guarantees.

## 4. V3 editor

Map V2 still edits the legacy spatial model.

A dedicated V3 mode/editor needs:

- layer visibility and label mode controls;
- Surface drawing;
- Polygon holes;
- MultiPolygon editing;
- Corridor centerline + width drawing;
- Barrier drawing;
- Connector creation;
- Spot placement;
- semantic Location linking;
- create/open nested NavigationSpace;
- FREE/ROUTED mode;
- encounter policy editor;
- traversal policy editor;
- authoring presets such as Road, River, Forest, Building, Room, Walled City.

Presets should create ordinary V3 primitives and never become permanent hard
coded location types.

## 5. Legacy migration review UI

The adapter already emits warnings.

The editor still needs a migration-review workflow for ambiguous objects:

- degenerate two-point areas;
- old zero-width routes that may be roads or abstract links;
- old area priority -> movement priority decisions;
- missing endpoint coordinates;
- old bounds that cannot become valid polygons;
- legacy encounter probability -> distance-rate conversion.

## 6. Semantic Location simplification

After V3 proves itself, remove map mechanics from LocationState:

- spatial_kind
- topology
- occupancy
- boundary_access
- footprint
- local_bounds
- priority_layer
- encounter_rate
- random_encounter
- most x/y placement semantics

Location should retain semantic/environment/story information. NavigationSpace
and MapFeature should own navigation geometry and traversal.

This removal must happen last, after branch replay and migration equivalence are
tested.

## 7. Environment integration

Environment/ambience should resolve from all active semantic/feature memberships
instead of assuming one winning area.

For example, a point may inherit:

- city ambience,
- district ambience,
- road modifiers,
- outdoor weather.

The current live Map ambience preview remains useful, but needs to consume V3
membership once the new editor is active.

The previously requested multi-select weather/time conditions for ambience are
also still outstanding and can be implemented independently while V3 is under
evaluation.

## 8. Production comparison gate

Do not merge V3 into master until side-by-side tests demonstrate:

- old projects migrate without losing reachable places;
- city + district + road simultaneous membership works;
- road-through-river and gate-through-wall cases work;
- free and routed maps both produce expected paths;
- building interiors require rooms/corridors/connectors rather than abstract
  building occupancy;
- portals work across arbitrary spaces;
- random encounters remain deterministic and branch-safe;
- MultiPolygon/hole geometry survives save/reload;
- V3 is measurably easier to author than the old flag-heavy model.

Only after this gate should old spatial tables/endpoints/UI be removed.
