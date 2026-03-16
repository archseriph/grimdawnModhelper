# Grim Dawn Mod Helper — Scanner

This scanner is part of the Mod Creator + Mod Checker toolset for Grim Dawn.
It indexes mod folders into a local SQLite database, records file metadata and
file hashes, stores scan runs, and keeps a basic file history so the UI or
checker can detect missing / changed / conflicting files.

This README and the included `scan.py` provide an initial, minimal scanner
implementation and DB initialization. You mentioned you already added the DB
schema files — `scan.py` will also create the core tables if they are missing.

Goals
- Index mod files (path, size, mtime, sha256)
- Record scans and file history
- Provide a foundation for building parsing, asset extraction, and checkers
- Be easy to run locally and integrate with a UI or CLI

Requirements
- Python 3.8+
- No external packages required (uses stdlib sqlite3, hashlib, etc.)

Quick start
1. Put `scan.py` at the repository root (or wherever you like).
2. Run:
   - Full scan (compute hashes):
     python scan.py --mod-root /path/to/your/mod --db ./db/modhelper.db
   - Fast scan (skip hashing, rely on mtime/size):
     python scan.py --mod-root /path/to/your/mod --db ./db/modhelper.db --fast

Default DB location is `./db/modhelper.db`. If it does not exist, `scan.py`
will create it and create core tables.

What the scanner does
- Ensures core tables exist (schema_version, mods, files, file_history, scans,
  assets, references, issues).
- Creates or finds a `mods` entry for the scanned mod directory.
- Walks the mod root, recording for each file:
  - relative path inside the mod
  - file name and extension
  - size and mtime
  - sha256 (unless `--fast` is used)
- Upserts files into the `files` table, and if a file content change is
  detected (sha256 changed), writes an entry to `file_history`.
- Records a `scans` row with start/finish time, file counts, and changes_count.
- Optionally prints a summary.

Notes & next steps
- This script intentionally keeps parsing minimal. It includes a small helper
  to extract references to other `.dbr` files (simple regex). Proper parsing of
  Grim Dawn file formats should be added later to populate `assets` and
  `references` more accurately.
- Add unit tests and sample mod fixtures (small sample mod directories) to
  validate scanner behavior.
- Next improvements:
  - Add proper parsers for `.dbr`, `.gfx`, localization files, etc.
  - Implement checker rules (MISSING_REFERENCE, DUPLICATE_ID, etc.) that
    populate the `issues` table.
  - Add a small local API server / UI that reads from this DB for the user
    interface (Electron, Tauri, or native UI).

If you want, I can:
- Commit these files to a new branch and open a PR.
- Extend the scanner to parse `.dbr` files and populate `assets`/`references`.
- Create sample fixtures and simple unit tests.

Tell me which you prefer and which branch to target and I’ll prepare a PR.
