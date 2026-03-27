#!/usr/bin/env python3
"""
scan.py - Extended Grim Dawn mod scanner with basic asset extraction and checks

Usage:
    python scan.py --mod-root /path/to/mod --db ./db/modhelper.db [--fast] [--identifier my_mod] [--no-check]

What it does:
- Ensures core DB tables exist (creates simple schema if missing).
- Creates or finds a mod record for the provided folder.
- Walks the mod root and indexes files (relative_path, size, mtime, sha256).
- Upserts files into `files` table and writes `file_history` when content changes.
- Extracts references from text/data files and stores them in `references`.
- Populates a simple `assets` row per data file (.dbr, txt, lua, xml, ini).
- Runs basic checks and writes findings into `issues`:
    - MISSING_REFERENCE: a referenced .dbr target wasn't found in recorded files
    - DUPLICATE_ID: same asset_identifier appears multiple times
    - ORPHANED_ASSET: an asset that has no inbound references
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
import re
from typing import Optional, Tuple, List

ISO_NOW = lambda: datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# --- DB connection and schema (same as before) ---


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript(
        """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS mods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  identifier TEXT UNIQUE,
  author TEXT,
  version TEXT,
  description TEXT,
  root_path TEXT NOT NULL,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mod_id INTEGER REFERENCES mods(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  file_name TEXT NOT NULL,
  extension TEXT,
  size INTEGER,
  mtime INTEGER,
  sha256 TEXT,
  file_type TEXT,
  status TEXT,
  last_scanned_at TEXT,
  UNIQUE(mod_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_files_mod_path ON files(mod_id, relative_path);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  asset_type TEXT,
  asset_name TEXT,
  asset_identifier TEXT,
  metadata JSON,
  UNIQUE(file_id, asset_name)
);

CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(asset_name);
CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(asset_type);

CREATE TABLE IF NOT EXISTS references (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  target_relative_path TEXT,
  relation_type TEXT,
  info JSON
);

CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mod_id INTEGER REFERENCES mods(id),
  started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  files_count INTEGER,
  changes_count INTEGER,
  details JSON
);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS asset_tags (
  asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
  tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY(asset_id, tag_id)
);

CREATE TABLE IF NOT EXISTS file_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  sha256 TEXT,
  mtime INTEGER,
  changed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  note TEXT
);

CREATE TABLE IF NOT EXISTS issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mod_id INTEGER REFERENCES mods(id) ON DELETE CASCADE,
  file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
  asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  severity TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  details JSON NULL,
  resolved INTEGER DEFAULT 0
);
"""
    )
    conn.commit()


# --- mod handling ---


def get_or_create_mod(conn: sqlite3.Connection, identifier: str, name: str, root_path: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM mods WHERE identifier = ?", (identifier,))
    r = cur.fetchone()
    if r:
        mod_id = r["id"]
        cur.execute("UPDATE mods SET name = ?, root_path = ?, updated_at = ? WHERE id = ?",
                    (name, root_path, ISO_NOW(), mod_id))
    else:
        cur.execute(
            "INSERT INTO mods (name, identifier, root_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, identifier, root_path, ISO_NOW(), ISO_NOW()),
        )
        mod_id = cur.lastrowid
    conn.commit()
    return mod_id


# --- low-level file operations ---


def compute_sha256(file_path: str, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _file_record(conn: sqlite3.Connection, mod_id: int, relative_path: str) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE mod_id = ? AND relative_path = ?", (mod_id, relative_path))
    return cur.fetchone()


def upsert_file(conn: sqlite3.Connection, mod_id: int, rel_path: str, size: int, mtime: int, sha256: Optional[str],
                file_type: Optional[str]):
    cur = conn.cursor()
    now = ISO_NOW()
    file_name = os.path.basename(rel_path)
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    existing = _file_record(conn, mod_id, rel_path)
    if existing:
        file_id = existing["id"]
        prev_sha = existing["sha256"]
        changed = False
        if sha256 and prev_sha and prev_sha != sha256:
            changed = True
        elif sha256 and not prev_sha:
            changed = True
        cur.execute(
            """UPDATE files SET file_name = ?, extension = ?, size = ?, mtime = ?, sha256 = ?, file_type = ?, last_scanned_at = ?
               WHERE id = ?""",
            (file_name, ext, size, mtime, sha256, file_type, now, file_id),
        )
        if changed:
            cur.execute(
                "INSERT INTO file_history (file_id, sha256, mtime, changed_at, note) VALUES (?, ?, ?, ?, ?)",
                (file_id, sha256, mtime, now, "content changed"),
            )
    else:
        cur.execute(
            """INSERT INTO files (mod_id, relative_path, file_name, extension, size, mtime, sha256, file_type, status, last_scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'present', ?)""",
            (mod_id, rel_path, file_name, ext, size, mtime, sha256, file_type, now),
        )
        file_id = cur.lastrowid
    conn.commit()
    return file_id


# --- reference extraction (existing simple regex) ---
DRB_REF_REGEX = re.compile(r"[\w\/\.-]+\.dbr", re.IGNORECASE)


def extract_references_from_text(content: str) -> list:
    return list(set(DRB_REF_REGEX.findall(content)))


def index_references_for_file(conn: sqlite3.Connection, source_file_id: int, rel_path_base: str, file_path: str) -> int:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except Exception:
        return 0
    refs = extract_references_from_text(text)
    if not refs:
        return 0
    cur = conn.cursor()
    inserted = 0
    for ref in refs:
        target_rel = ref.replace("\\", "/")
        cur.execute(
            "INSERT INTO references (source_file_id, target_relative_path, relation_type, info) VALUES (?, ?, ?, ?)",
            (source_file_id, target_rel, "references", json.dumps({"detected_in": rel_path_base})),
        )
        inserted += 1
    conn.commit()
    return inserted


# --- scans table helpers ---


def start_scan(conn: sqlite3.Connection, mod_id: int) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO scans (mod_id, started_at, files_count, changes_count, details) VALUES (?, ?, 0, 0, ?)",
                (mod_id, ISO_NOW(), json.dumps({}),))
    conn.commit()
    return cur.lastrowid


def finish_scan(conn: sqlite3.Connection, scan_id: int, files_count: int, changes_count: int, details: dict = None):
    cur = conn.cursor()
    cur.execute("UPDATE scans SET finished_at = ?, files_count = ?, changes_count = ?, details = ? WHERE id = ?",
                (ISO_NOW(), files_count, changes_count, json.dumps(details or {}), scan_id))
    conn.commit()


# --- asset extraction and upsert ---


ASSET_NAME_REGEX = re.compile(r'name\s*=\s*"([^"]+)"', re.IGNORECASE)


def detect_asset_type_from_path(rel_path: str) -> str:
    p = rel_path.lower()
    if "records/items" in p or "/items/" in p:
        return "item"
    if "records/skills" in p or "/skills/" in p:
        return "skill"
    if "records/creatures" in p or "/creatures/" in p:
        return "npc"
    if p.endswith(".gfx") or "/gfx/" in p:
        return "gfx"
    if p.endswith((".dds", ".png", ".jpg", ".tga")):
        return "texture"
    return "unknown"


def extract_asset_name_from_file(file_path: str) -> Optional[str]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read(4096)  # sample
    except Exception:
        return None
    m = ASSET_NAME_REGEX.search(text)
    if m:
        return m.group(1).strip()
    # fallback: try to find a token like "recordName = ..." or "id = ..."
    alt = re.search(r'(recordname|id|internalname)\s*=\s*"([^"]+)"', text, re.IGNORECASE)
    if alt:
        return alt.group(2).strip()
    return None


def populate_assets_for_mod(conn: sqlite3.Connection, mod_id: int, mod_root: Path) -> int:
    """
    For data files (heuristic: extension in set), insert or update assets.
    Returns number of assets upserted.
    """
    cur = conn.cursor()
    cur.execute("SELECT id, relative_path FROM files WHERE mod_id = ?", (mod_id,))
    entries = cur.fetchall()
    upserted = 0
    for row in entries:
        file_id = row["id"]
        rel = row["relative_path"]
        ext = os.path.splitext(rel)[1].lower().lstrip(".")
        if ext in ("dbr", "txt", "lua", "xml", "ini"):
            abs_path = (mod_root / rel).resolve()
            asset_name = extract_asset_name_from_file(str(abs_path)) or os.path.splitext(os.path.basename(rel))[0]
            asset_identifier = rel  # stable identifier for now
            asset_type = detect_asset_type_from_path(rel)
            # upsert asset by file_id + asset_name
            cur2 = conn.cursor()
            cur2.execute("SELECT id FROM assets WHERE file_id = ? AND asset_name = ?", (file_id, asset_name))
            ex = cur2.fetchone()
            metadata = {"source_hint": "heuristic-extract", "sample_path": rel}
            if ex:
                aid = ex["id"]
                cur2.execute(
                    "UPDATE assets SET asset_type = ?, asset_identifier = ?, metadata = ? WHERE id = ?",
                    (asset_type, asset_identifier, json.dumps(metadata), aid),
                )
            else:
                cur2.execute(
                    "INSERT INTO assets (file_id, asset_type, asset_name, asset_identifier, metadata) VALUES (?, ?, ?, ?, ?)",
                    (file_id, asset_type, asset_name, asset_identifier, json.dumps(metadata)),
                )
            upserted += 1
    conn.commit()
    return upserted


# --- Issue helpers and checkers ---


def insert_issue(conn: sqlite3.Connection, mod_id: int, file_id: Optional[int], asset_id: Optional[int],
                 severity: str, code: str, message: str, details: dict = None):
    """
    Insert an issue unless an unresolved identical one exists (same mod_id, file_id, code, message).
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM issues WHERE mod_id = ? AND file_id IS ? AND code = ? AND message = ? AND resolved = 0",
        (mod_id, file_id, code, message)
    )
    if cur.fetchone():
        return None
    cur.execute(
        "INSERT INTO issues (mod_id, file_id, asset_id, severity, code, message, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mod_id, file_id, asset_id, severity, code, message, json.dumps(details or {}))
    )
    conn.commit()
    return cur.lastrowid


def resolve_reference_target(conn: sqlite3.Connection, target_rel: str) -> List[sqlite3.Row]:
    """
    Try to find matching files for target_rel. We attempt exact match, then suffix match.
    Returns list of file rows.
    """
    cur = conn.cursor()
    # exact match first
    cur.execute("SELECT * FROM files WHERE relative_path = ?", (target_rel,))
    rows = cur.fetchall()
    if rows:
        return rows
    # suffix match (helpful if reference contains smaller path)
    cur.execute("SELECT * FROM files WHERE relative_path LIKE ?", ('%' + target_rel,))
    rows = cur.fetchall()
    return rows


def run_basic_checks(conn: sqlite3.Connection, mod_id: int):
    """
    Runs basic checks and writes issues:
    - MISSING_REFERENCE
    - DUPLICATE_ID
    - ORPHANED_ASSET
    """
    cur = conn.cursor()
    # MISSING_REFERENCE: for each reference where source is in this mod, try to resolve target to any file
    cur.execute(
        """SELECT r.id as rid, r.source_file_id as src, r.target_relative_path as target, f.mod_id as src_mod
           FROM references r
           JOIN files f ON f.id = r.source_file_id
           WHERE f.mod_id = ?""", (mod_id,)
    )
    refs = cur.fetchall()
    missing = 0
    for r in refs:
        target = r["target"]
        matches = resolve_reference_target(conn, target)
        if not matches:
            # source_file_id maps to a file; create a missing reference issue
            insert_issue(conn, mod_id, r["src"], None, "error", "MISSING_REFERENCE",
                         f"Reference to '{target}' not found", {"target": target})
            missing += 1

    # DUPLICATE_ID: assets with same asset_identifier across DB; report duplicates if count > 1
    cur.execute("SELECT asset_identifier, COUNT(*) as cnt FROM assets GROUP BY asset_identifier HAVING cnt > 1")
    duplicates = cur.fetchall()
    dup_count = 0
    for d in duplicates:
        identifier = d["asset_identifier"]
        # fetch all assets with this identifier
        cur2 = conn.cursor()
        cur2.execute("SELECT id, file_id FROM assets WHERE asset_identifier = ?", (identifier,))
        rows = cur2.fetchall()
        for a in rows:
            # find file's mod id for issue context
            cur3 = conn.cursor()
            cur3.execute("SELECT mod_id FROM files WHERE id = ?", (a["file_id"],))
            frow = cur3.fetchone()
            mid = frow["mod_id"] if frow else None
            insert_issue(conn, mid, a["file_id"], a["id"], "warning", "DUPLICATE_ID",
                         f"Asset identifier '{identifier}' appears in multiple locations",
                         {"asset_identifier": identifier})
            dup_count += 1

    # ORPHANED_ASSET: asset exists but is not referenced by any references row; mark as info for the asset's mod
    cur.execute("SELECT a.id as aid, a.file_id as fid, a.asset_identifier as ident FROM assets a")
    all_assets = cur.fetchall()
    orphan_count = 0
    for a in all_assets:
        cur.execute("SELECT COUNT(*) as c FROM references r WHERE r.target_relative_path LIKE ?", ('%' + (a["ident"] or ""),))
        c = cur.fetchone()["c"]
        # also check references pointing directly to the file path
        if c == 0:
            # Check inbound references referencing this file specifically by file relative_path
            cur.execute("SELECT relative_path, mod_id FROM files WHERE id = ?", (a["fid"],))
            frow = cur.fetchone()
            if not frow:
                continue
            rel = frow["relative_path"]
            cur.execute("SELECT COUNT(*) as c2 FROM references WHERE target_relative_path = ? OR target_relative_path LIKE ?", (rel, '%' + rel))
            c2 = cur.fetchone()["c2"]
            if c2 == 0:
                # orphan
                cur.execute("SELECT mod_id FROM files WHERE id = ?", (a["fid"],))
                mod_row = cur.fetchone()
                mid = mod_row["mod_id"] if mod_row else None
                insert_issue(conn, mid, a["fid"], a["aid"], "info", "ORPHANED_ASSET",
                             f"Asset '{a['ident']}' appears to have no inbound references", {"asset_identifier": a["ident"]})
                orphan_count += 1

    return {"missing_references": missing, "duplicate_issues": dup_count, "orphaned": orphan_count}


# --- main scan flow that ties things together ---


def scan_mod(root_path: str, db_path: str, identifier: Optional[str] = None, fast: bool = False, do_checks: bool = True):
    conn = connect_db(db_path)
    ensure_schema(conn)

    root = Path(root_path).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Mod root does not exist or is not a directory: {root}")

    identifier = identifier or root.name
    name = root.name
    mod_id = get_or_create_mod(conn, identifier, name, str(root))

    scan_id = start_scan(conn, mod_id)

    files_count = 0
    changes_count = 0
    inserted_refs_total = 0

    print(f"Scanning mod '{name}' (id={mod_id}) at {root}")
    start_time = time.time()

    # Walk and index
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            files_count += 1
            full = Path(dirpath) / fname
            try:
                stat = full.stat()
            except FileNotFoundError:
                continue
            rel = str(full.relative_to(root)).replace("\\", "/")
            size = stat.st_size
            mtime = int(stat.st_mtime)
            sha = None
            if not fast:
                try:
                    sha = compute_sha256(str(full))
                except Exception as e:
                    print(f"Warning: failed to hash {full}: {e}")
                    sha = None
            ext = full.suffix.lower().lstrip(".")
            if ext in ("dbr", "txt", "lua", "xml", "ini"):
                file_type = "data"
            elif ext in ("dds", "png", "jpg", "jpeg", "tga"):
                file_type = "texture"
            elif ext in ("gfx", "arc", "pak"):
                file_type = "archive"
            elif ext in ("wav", "mp3", "ogg"):
                file_type = "audio"
            else:
                file_type = "other"

            existing = _file_record(conn, mod_id, rel)
            prev_sha = existing["sha256"] if existing else None
            file_id = upsert_file(conn, mod_id, rel, size, mtime, sha, file_type)
            if sha and prev_sha and prev_sha != sha:
                changes_count += 1
            elif sha and not prev_sha:
                changes_count += 1

            if file_type == "data":
                inserted_refs = index_references_for_file(conn, file_id, rel, str(full))
                inserted_refs_total += inserted_refs

    duration = time.time() - start_time

    # populate assets (simple heuristics)
    assets_upserted = populate_assets_for_mod(conn, mod_id, root)

    # finish scan row with some details
    finish_scan(conn, scan_id, files_count, changes_count, {"duration_s": duration, "refs_detected": inserted_refs_total, "assets_upserted": assets_upserted})
    print(f"Scan completed in {duration:.1f}s: files={files_count}, changes_detected={changes_count}, refs_found={inserted_refs_total}, assets_upserted={assets_upserted}")

    # run checks
    check_results = {}
    if do_checks:
        check_results = run_basic_checks(conn, mod_id)
        print("Checks results:", check_results)
    conn.close()
    return {"files": files_count, "changes": changes_count, "refs": inserted_refs_total, "assets": assets_upserted, "checks": check_results}


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(description="Grim Dawn mod scanner - index a mod into SQLite DB and run basic checks")
    parser.add_argument("--mod-root", "-m", required=True, help="Path to the mod root folder to scan")
    parser.add_argument("--db", "-d", default="./db/modhelper.db", help="Path to SQLite DB file")
    parser.add_argument("--identifier", "-i", default=None, help="Optional mod identifier (defaults to folder name)")
    parser.add_argument("--fast", action="store_true", help="Fast mode: skip hashing (rely on mtime+size).")
    parser.add_argument("--no-check", action="store_true", help="Do not run checks after scanning.")
    args = parser.parse_args()

    db_dir = os.path.dirname(args.db)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    try:
        res = scan_mod(args.mod_root, args.db, args.identifier, args.fast, do_checks=not args.no_check)
        # print final summary
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"Error running scan: {e}")
        raise


if __name__ == "__main__":
    main()
