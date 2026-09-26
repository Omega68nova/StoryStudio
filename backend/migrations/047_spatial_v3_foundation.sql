-- Spatial V3 parallel foundation.
--
-- This migration is deliberately additive. Existing spatial_* tables and
-- WorldEngine events remain untouched while the V3 editor/runtime adapter is
-- built. These tables are a materialized current-state representation, not a
-- second branch history.
--
-- Core split:
--   Location        = semantic place
--   NavigationSpace = one interactable movement map owned by a location
--   MapFeature      = geometry/traversal/environment feature inside that map

CREATE TABLE navigation_spaces_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_location_id TEXT REFERENCES world_entities(id) ON DELETE CASCADE,
    navigation_mode TEXT NOT NULL CHECK(navigation_mode IN ('free','routed')),
    base_travel_multiplier REAL NOT NULL DEFAULT 1 CHECK(base_travel_multiplier > 0),
    bounds_geojson TEXT,
    source_head_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
    source_transaction_id TEXT REFERENCES world_transactions(id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, owner_location_id)
);
CREATE INDEX idx_navigation_spaces_project
    ON navigation_spaces_current(project_id);

CREATE TABLE map_features_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    navigation_space_id TEXT NOT NULL REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    semantic_location_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
    feature_kind TEXT NOT NULL CHECK(feature_kind IN ('surface','corridor','barrier','connector','spot')),
    name TEXT NOT NULL DEFAULT '',
    geometry_geojson TEXT NOT NULL,
    render_layer TEXT NOT NULL DEFAULT 'regions'
        CHECK(render_layer IN ('topology','regions','roads','places','barriers','connections')),
    render_order REAL NOT NULL DEFAULT 0,
    movement_priority REAL NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_map_features_space_layer
    ON map_features_current(navigation_space_id, render_layer, render_order);
CREATE INDEX idx_map_features_semantic_location
    ON map_features_current(project_id, semantic_location_id);

-- Surfaces represent regions the actor may be inside: terrain, districts,
-- rivers/oceans, building footprints, rooms, etc. Overlap is intentional:
-- point queries return all containing surfaces rather than one winning area.
CREATE TABLE map_surface_properties (
    feature_id TEXT PRIMARY KEY REFERENCES map_features_current(id) ON DELETE CASCADE,
    traversal_json TEXT NOT NULL DEFAULT '{"default_allowed":true,"travel_multiplier":1,"options":[]}',
    encounter_rate REAL NOT NULL DEFAULT 0 CHECK(encounter_rate >= 0),
    encounter_table_json TEXT NOT NULL DEFAULT '[]',
    ambience_tags_json TEXT NOT NULL DEFAULT '[]',
    environment_tags_json TEXT NOT NULL DEFAULT '[]'
);

-- Corridors are width-bearing roads/alleys/hallways authored as centerlines.
-- The runtime/editor derives the occupied polygon from centerline + width.
CREATE TABLE map_corridor_properties (
    feature_id TEXT PRIMARY KEY REFERENCES map_features_current(id) ON DELETE CASCADE,
    width REAL NOT NULL CHECK(width > 0),
    traversal_json TEXT NOT NULL DEFAULT '{"default_allowed":true,"travel_multiplier":1,"options":[]}',
    encounter_rate REAL NOT NULL DEFAULT 0 CHECK(encounter_rate >= 0),
    encounter_table_json TEXT NOT NULL DEFAULT '[]',
    ambience_tags_json TEXT NOT NULL DEFAULT '[]'
);

-- Barriers block crossing only; they do not make their enclosed interior
-- non-navigable. City walls, fences and cliff edges are barriers.
CREATE TABLE map_barrier_properties (
    feature_id TEXT PRIMARY KEY REFERENCES map_features_current(id) ON DELETE CASCADE,
    traversal_json TEXT NOT NULL DEFAULT '{"default_allowed":false,"travel_multiplier":1,"options":[]}'
);

-- Connectors are explicit transitions: doors, gates, stairs, bridges,
-- ladders, climb points and portals. Portals intentionally need no geometric
-- relationship between endpoints.
CREATE TABLE map_connector_properties (
    feature_id TEXT PRIMARY KEY REFERENCES map_features_current(id) ON DELETE CASCADE,
    connector_kind TEXT NOT NULL DEFAULT 'generic'
        CHECK(connector_kind IN ('generic','door','gate','stairs','ladder','bridge','climb','portal')),
    source_space_id TEXT NOT NULL REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    target_space_id TEXT NOT NULL REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    source_point_json TEXT NOT NULL,
    target_point_json TEXT NOT NULL,
    traversal_json TEXT NOT NULL DEFAULT '{"default_allowed":true,"travel_multiplier":1,"options":[]}',
    travel_minutes REAL,
    bidirectional INTEGER NOT NULL DEFAULT 1 CHECK(bidirectional IN (0,1))
);
CREATE INDEX idx_map_connectors_source_space
    ON map_connector_properties(source_space_id);
CREATE INDEX idx_map_connectors_target_space
    ON map_connector_properties(target_space_id);

CREATE TABLE map_spot_properties (
    feature_id TEXT PRIMARY KEY REFERENCES map_features_current(id) ON DELETE CASCADE,
    interaction_kind TEXT NOT NULL DEFAULT 'generic'
);

-- A location may own another navigation space. This explicit relation is kept
-- separate from parent-map geometry so a district can be a semantic region
-- without automatically becoming a nested map.
CREATE TABLE location_navigation_spaces_current (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    navigation_space_id TEXT NOT NULL REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    entrance_policy TEXT NOT NULL DEFAULT 'connectors'
        CHECK(entrance_policy IN ('connectors','open')),
    bounds_mode TEXT NOT NULL DEFAULT 'inherit_parent'
        CHECK(bounds_mode IN ('inherit_parent','independent')),
    PRIMARY KEY(project_id, location_id),
    UNIQUE(navigation_space_id)
);

-- Optional editor-defined layer visibility/ordering. Layers are presentation
-- groups only; they do not determine semantic containment.
CREATE TABLE navigation_space_layers_current (
    navigation_space_id TEXT NOT NULL REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    layer_key TEXT NOT NULL,
    label TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    visible INTEGER NOT NULL DEFAULT 1 CHECK(visible IN (0,1)),
    labels_mode TEXT NOT NULL DEFAULT 'important'
        CHECK(labels_mode IN ('hidden','important','all')),
    PRIMARY KEY(navigation_space_id, layer_key)
);
