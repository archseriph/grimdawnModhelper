# Grim Dawn Mod Helper — Scanner & Basic Checker

This scanner is part of the Mod Creator + Mod Checker toolset for Grim Dawn.
It indexes mod folders into a local SQLite database, records file metadata and
file hashes, stores scan runs, and runs a set of basic checks that populate an
`issues` table for the UI/CLI to display.

This package includes:
- scan.py — extended Python scanner that indexes files, extracts assets/references (heuristic), and runs basic checks.
- (You mentioned you already added DB schema files; the scanner will also create core tables if missing.)

Goals
- Index Grim Dawn mod files (path, size, mtime, sha256)
- Populate a derived assets table (heuristic extraction)
- Detect references between files and identify missing references
- Detect duplicate asset identifiers and orphaned assets
- Provide a DB-backed foundation for a UI and further checks

Requirements
- Python 3.8+
- No external packages required (uses stdlib sqlite3, hashlib, etc.)

Suggested branch name for these files: feature/scanner-checker

Quick start
1. Place `scan.py` at the repository root (or in a tools/ directory).
2. Run (example):
   - Full scan (computes hashes and runs checks):
     python scan.py --mod-root /path/to/your/mod --db ./db/modhelper.db
   - Fast scan (skip hashing; rely on mtime+size):
     python scan.py --mod-root /path/to/your/mod --db ./db/modhelper.db --fast
   - Skip checks:
     python scan.py --mod-root /path/to/your/mod --db ./db/modhelper.db --no-check

Default DB location is `./db/modhelper.db`. If it does not exist, `scan.py`
creates it and the core tables.

What the scanner currently does
- Ensures core tables exist (schema_version, mods, files, file_history, scans, assets, references, issues).
- Creates or updates a `mods` row for the scanned mod directory.
- Walks the mod root and records:
  - relative path, file name, extension
  - size, mtime, sha256 (unless --fast)
  - file_type (heuristic from extension)
- Upserts files into the `files` table and writes to `file_history` if content changes are detected.
- Extracts `.dbr`-like references from text/data files and stores them in `references`.
- Populates the `assets` table heuristically for data files (.dbr, .txt, .lua, .xml, .ini).
- Runs basic checks and writes `issues` entries:
  - MISSING_REFERENCE (severity: error)
  - DUPLICATE_ID (severity: warning)
  - ORPHANED_ASSET (severity: info)

Where to look in the DB
- mods: registered mod roots
- files: indexed files for each mod
- assets: heuristically-detected assets from data files
- references: recorded references found in text data
- scans: scan runs and metadata
- file_history: changed-file history
- issues: detected findings for later UI display or export

Limitations & next steps
- Parsing is heuristic-based. Proper Grim Dawn parsers for .dbr, localization, and gfx formats will drastically improve accuracy.
- Reference resolution uses exact or suffix matching; a more robust resolver should be added.
- Checker rules are basic. Add rules for localization, format versions, and conflict resolution.
- Add unit tests and sample fixture mods for CI.
- Add an API or UI (Electron/Tauri/C#/.NET/PySide) that reads from this DB and provides the secondary Checker window you described.

If you want, I can:
- Create small sample fixtures demonstrating missing references and duplicates.
- Add unit tests and a simple report export (JSON/HTML).
- Open a PR on branch `feature/scanner-checker` with these files and fixtures.

Please tell me if you want me to also create the PR for that branch, include sample fixtures, or make any changes to file placement.
