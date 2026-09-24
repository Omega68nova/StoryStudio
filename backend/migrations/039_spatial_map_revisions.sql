CREATE TABLE spatial_objects (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_kind TEXT NOT NULL CHECK(object_kind IN ('root','anchor','barrier','connection','encounter','itinerary')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, object_kind, id)
);

CREATE TABLE spatial_object_revisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES world_transactions(id) ON DELETE CASCADE,
    event_ordinal INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id, object_kind, object_id)
        REFERENCES spatial_objects(project_id, object_kind, id)
);

CREATE INDEX idx_spatial_revisions_object
    ON spatial_object_revisions(project_id, object_kind, object_id, created_at);

CREATE TABLE map_geometry_vertices (
    revision_id TEXT NOT NULL REFERENCES spatial_object_revisions(id) ON DELETE CASCADE,
    geometry_role TEXT NOT NULL,
    position INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    PRIMARY KEY(revision_id, geometry_role, position)
);

CREATE TRIGGER spatial_revisions_no_update
BEFORE UPDATE ON spatial_object_revisions
BEGIN
    SELECT RAISE(ABORT, 'spatial object revisions are append-only');
END;
