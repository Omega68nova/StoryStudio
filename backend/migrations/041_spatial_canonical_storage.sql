-- Canonical/materialized spatial storage for the active project branch.
-- World events remain the branch/revision history. These tables provide a normalized,
-- rebuildable database representation for the map editor and spatial runtime.

CREATE TABLE spatial_project_state (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    root_location_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
    source_head_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
    source_transaction_id TEXT REFERENCES world_transactions(id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE spatial_locations (
    location_id TEXT PRIMARY KEY REFERENCES world_entities(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_location_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
    topology TEXT NOT NULL DEFAULT 'closed' CHECK(topology IN ('open','closed')),
    occupancy TEXT NOT NULL DEFAULT 'direct_allowed' CHECK(occupancy IN ('direct_allowed','child_required')),
    boundary_access TEXT NOT NULL DEFAULT 'free' CHECK(boundary_access IN ('free','connection_required')),
    spatial_kind TEXT NOT NULL DEFAULT 'spot' CHECK(spatial_kind IN ('spot','area')),
    exposure TEXT NOT NULL DEFAULT 'outdoor' CHECK(exposure IN ('indoor','outdoor','isolated')),
    x REAL,
    y REAL,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    random_encounter INTEGER NOT NULL DEFAULT 0 CHECK(random_encounter IN (0,1)),
    minutes_per_unit REAL NOT NULL DEFAULT 1 CHECK(minutes_per_unit >= 0),
    base_visibility_units REAL,
    encounter_rate REAL NOT NULL DEFAULT 0 CHECK(encounter_rate >= 0),
    requires_map_review INTEGER NOT NULL DEFAULT 0 CHECK(requires_map_review IN (0,1)),
    footprint_kind TEXT CHECK(footprint_kind IN ('point','polyline','polygon')),
    local_bounds_kind TEXT CHECK(local_bounds_kind IN ('point','polyline','polygon')),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_spatial_locations_project_parent
    ON spatial_locations(project_id, parent_location_id);

CREATE TABLE spatial_location_vertices (
    location_id TEXT NOT NULL REFERENCES spatial_locations(location_id) ON DELETE CASCADE,
    geometry_role TEXT NOT NULL CHECK(geometry_role IN ('footprint','local_bounds')),
    position INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    PRIMARY KEY(location_id, geometry_role, position)
);

CREATE TABLE spatial_anchors_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    coordinate_space_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('landmark','entrance','exit','waypoint','encounter')),
    x REAL,
    y REAL,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    requires_map_review INTEGER NOT NULL DEFAULT 0 CHECK(requires_map_review IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_spatial_anchors_location ON spatial_anchors_current(project_id, location_id);
CREATE INDEX idx_spatial_anchors_space ON spatial_anchors_current(project_id, coordinate_space_id);

CREATE TABLE spatial_barriers_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    geometry_kind TEXT CHECK(geometry_kind IN ('point','polyline','polygon')),
    blocked_modes_json TEXT NOT NULL DEFAULT '["walk"]',
    requirements_json TEXT,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    requires_map_review INTEGER NOT NULL DEFAULT 0 CHECK(requires_map_review IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_spatial_barriers_location ON spatial_barriers_current(project_id, location_id);

CREATE TABLE spatial_barrier_vertices (
    barrier_id TEXT NOT NULL REFERENCES spatial_barriers_current(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    PRIMARY KEY(barrier_id, position)
);

CREATE TABLE spatial_connections_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('route','door','portal')),
    source_anchor_id TEXT NOT NULL REFERENCES spatial_anchors_current(id) ON DELETE CASCADE,
    target_anchor_id TEXT NOT NULL REFERENCES spatial_anchors_current(id) ON DELETE CASCADE,
    travel_minutes INTEGER NOT NULL DEFAULT 0 CHECK(travel_minutes >= 0),
    modes_json TEXT NOT NULL DEFAULT '["walk"]',
    bidirectional INTEGER NOT NULL DEFAULT 1 CHECK(bidirectional IN (0,1)),
    requirements_json TEXT,
    lock_json TEXT,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_spatial_connections_project ON spatial_connections_current(project_id);
CREATE INDEX idx_spatial_connections_source ON spatial_connections_current(source_anchor_id);
CREATE INDEX idx_spatial_connections_target ON spatial_connections_current(target_anchor_id);

CREATE TABLE spatial_encounter_rules_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    location_id TEXT REFERENCES world_entities(id) ON DELETE CASCADE,
    connection_id TEXT REFERENCES spatial_connections_current(id) ON DELETE CASCADE,
    probability REAL NOT NULL DEFAULT 0 CHECK(probability >= 0 AND probability <= 1),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
    discovered INTEGER NOT NULL DEFAULT 1 CHECK(discovered IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL,
    CHECK((location_id IS NULL) <> (connection_id IS NULL))
);
CREATE INDEX idx_spatial_encounters_project ON spatial_encounter_rules_current(project_id);

CREATE TABLE spatial_encounter_candidates (
    rule_id TEXT NOT NULL REFERENCES spatial_encounter_rules_current(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    PRIMARY KEY(rule_id, position)
);

CREATE TABLE spatial_itineraries_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    destination_location_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
    destination_anchor_id TEXT REFERENCES spatial_anchors_current(id) ON DELETE SET NULL,
    destination_x REAL,
    destination_y REAL,
    mode TEXT NOT NULL DEFAULT 'walk',
    current_segment INTEGER NOT NULL DEFAULT 0 CHECK(current_segment >= 0),
    remaining_minutes REAL NOT NULL DEFAULT 0 CHECK(remaining_minutes >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','cancelled')),
    interruption_json TEXT,
    traversal_seed TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_spatial_itineraries_character ON spatial_itineraries_current(project_id, character_id);

CREATE TABLE spatial_itinerary_segments (
    itinerary_id TEXT NOT NULL REFERENCES spatial_itineraries_current(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('geometric','connection')),
    source_location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    target_location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
    minutes REAL NOT NULL CHECK(minutes >= 0),
    connection_id TEXT REFERENCES spatial_connections_current(id) ON DELETE SET NULL,
    PRIMARY KEY(itinerary_id, position)
);

CREATE TABLE spatial_itinerary_segment_points (
    itinerary_id TEXT NOT NULL,
    segment_position INTEGER NOT NULL,
    point_position INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    PRIMARY KEY(itinerary_id, segment_position, point_position),
    FOREIGN KEY(itinerary_id, segment_position)
        REFERENCES spatial_itinerary_segments(itinerary_id, position) ON DELETE CASCADE
);
