CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE bible_documents (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE story_nodes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES story_nodes(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'complete',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_story_nodes_project ON story_nodes(project_id);
CREATE INDEX idx_story_nodes_parent ON story_nodes(parent_id);

CREATE TABLE branch_summaries (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  leaf_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  through_node_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE image_suggestions (
  id TEXT PRIMARY KEY,
  story_node_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  negative_prompt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'suggested',
  image_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE workflow_presets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  graph_json TEXT NOT NULL,
  mappings_json TEXT NOT NULL,
  validation_status TEXT NOT NULL DEFAULT 'unvalidated',
  validation_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE generation_jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('story', 'image')),
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_generation_jobs_status ON generation_jobs(status, created_at);

CREATE TABLE runtime_settings (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  llama_executable TEXT NOT NULL DEFAULT '',
  storyteller_model_path TEXT NOT NULL DEFAULT '',
  storyteller_model_id TEXT NOT NULL DEFAULT '',
  llama_url TEXT NOT NULL DEFAULT 'http://127.0.0.1:8080',
  llama_extra_args_json TEXT NOT NULL DEFAULT '[]',
  comfy_command_json TEXT NOT NULL DEFAULT '[]',
  comfy_workdir TEXT NOT NULL DEFAULT '',
  comfy_url TEXT NOT NULL DEFAULT 'http://127.0.0.1:8188',
  context_tokens INTEGER NOT NULL DEFAULT 8192,
  updated_at TEXT NOT NULL
);

