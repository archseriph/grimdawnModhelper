-- Basic schema for a local SQLite DB to support a Grim Dawn mod helper UI

PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE mods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  identifier TEXT UNIQUE, -- e.g., mod folder or unique id
  author TEXT,
  version TEXT,
  description TEXT,
  root_path TEXT NOT NULL, -- local path to mod root
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mod_id INTEGER REFERENCES mods(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL, -- path within mod root
  file_name TEXT NOT NULL,
  extension TEXT,
  size INTEGER,
  mtime INTEGER, -- epoch seconds
  sha256 TEXT, -- content hash to detect changed files even if mtime differs
  file_type TEXT, -- e.g., 'asset', 'dat', 'lua', 'txt', 'gfx', 'localization'
  status TEXT, -- e.g., 'present', 'missing', 'conflict'
  last_scanned_at TEXT,
  UNIQUE(mod_id, relative_path)
);

CREATE INDEX idx_files_mod_path ON files(mod_id, relative_path);
CREATE INDEX idx_files_sha256 ON files(sha256);

CREATE TABLE assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  asset_type TEXT, -- e.g., 'item', 'skill', 'npc', 'texture'
  asset_name TEXT, -- game/internal name
  asset_identifier TEXT, -- unique id if available
  metadata JSON, -- optional free-form metadata for UI
  UNIQUE(file_id, asset_name)
);

CREATE INDEX idx_assets_name ON assets(asset_name);
CREATE INDEX idx_assets_type ON assets(asset_type);

CREATE TABLE references (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
  target_asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
  relation_type TEXT, -- e.g., 'uses', 'spawn', 'requires'
  info JSON
);

CREATE TABLE scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mod_id INTEGER REFERENCES mods(id),
  started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  files_count INTEGER,
  changes_count INTEGER,
  details JSON
);

CREATE TABLE tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE
);

CREATE TABLE asset_tags (
  asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
  tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY(asset_id, tag_id)
);

-- Optional: keep history of file states for undo/audit
CREATE TABLE file_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  sha256 TEXT,
  mtime INTEGER,
  changed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  note TEXT
);
