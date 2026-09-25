-- Phase 7B: revisioned global reusable resources and project import provenance.
CREATE TABLE library_resources (
  id TEXT PRIMARY KEY,
  resource_kind TEXT NOT NULL CHECK(resource_kind IN (
    'bundle','character','location','item','outfit','faction','lore_system',
    'fact','plot_beat','stat','stat_pack','effect','ability','rule_pack'
  )),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  marked INTEGER NOT NULL DEFAULT 0 CHECK(marked IN (0,1)),
  current_revision_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_library_resources_kind_name ON library_resources(resource_kind,name);
CREATE INDEX idx_library_resources_marked ON library_resources(marked,resource_kind,name);

CREATE TABLE library_resource_revisions (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES library_resources(id) ON DELETE CASCADE,
  revision_number INTEGER NOT NULL CHECK(revision_number > 0),
  snapshot_json TEXT NOT NULL,
  source_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  source_story_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  source_kind TEXT,
  source_key TEXT,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(resource_id, revision_number)
);
CREATE INDEX idx_library_revisions_resource ON library_resource_revisions(resource_id,revision_number DESC);
CREATE INDEX idx_library_revisions_source_project ON library_resource_revisions(source_project_id);

CREATE TABLE library_resource_children (
  parent_resource_id TEXT NOT NULL REFERENCES library_resources(id) ON DELETE CASCADE,
  child_resource_id TEXT NOT NULL REFERENCES library_resources(id) ON DELETE CASCADE,
  relation_kind TEXT NOT NULL DEFAULT 'contains',
  position INTEGER NOT NULL DEFAULT 0,
  required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY(parent_resource_id,child_resource_id,relation_kind),
  CHECK(parent_resource_id <> child_resource_id)
);
CREATE INDEX idx_library_children_child ON library_resource_children(child_resource_id);

CREATE TABLE library_resource_tags (
  resource_id TEXT NOT NULL REFERENCES library_resources(id) ON DELETE CASCADE,
  tag TEXT NOT NULL COLLATE NOCASE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(resource_id,tag)
);

CREATE TABLE library_project_imports (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES library_resources(id) ON DELETE RESTRICT,
  revision_id TEXT NOT NULL REFERENCES library_resource_revisions(id) ON DELETE RESTRICT,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  target_kind TEXT NOT NULL,
  target_key TEXT,
  source_story_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_library_imports_project ON library_project_imports(project_id,created_at);
CREATE INDEX idx_library_imports_resource ON library_project_imports(resource_id,project_id);

CREATE TRIGGER library_revision_belongs_to_resource_insert
BEFORE INSERT ON library_resource_revisions
WHEN EXISTS (
  SELECT 1 FROM library_resource_revisions r
  WHERE r.id=NEW.id AND r.resource_id<>NEW.resource_id
)
BEGIN SELECT RAISE(ABORT,'library revision resource mismatch'); END;
