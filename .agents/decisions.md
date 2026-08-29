# Decision Log

Use this file for lightweight architecture decisions. Add newest entries at the top.

## 2026-08-29 - Conditional Database Sync Backup

Decision:

- Add a conditional DB sync mode that applies one user-entered `WHERE` fragment to each selected source table.
- Match affected target rows by primary key, then allow insert-only, backup plus delete/insert, or backup plus upsert handling for duplicate keys.
- Write affected target rows to typed DBeaver-style CSV files under `db_sync_backups/<timestamp>_<table-or-multi-table>/` before deleting or overwriting them.

Reason:

- Users need to sync a focused business subset without truncating whole tables or requiring an external CSV export/import loop.
- Backing up affected target rows gives a local audit trail before destructive duplicate-key handling.

Consequence:

- Conditional sync requires matching primary-key metadata.
- The `WHERE` fragment is intentionally limited to one statement fragment; semicolons and SQL comments are rejected.

## 2026-08-13 - SQL Source Data Matched-Key Trace

Decision:

- Expand SQL Workspace Source Data from simple `alias.*` rewrites to a strict matched-primary-key trace for base tables that have metadata and primary keys.
- For each safely wrappable base-table source occurrence, rewrite the original SELECT into a `SELECT DISTINCT alias.pk...` trace query, then fetch full rows from the base table by joining back on those matched keys.
- For statements with CTE syntax that cannot be nested as a derived table on SQL Server, use exact `alias.*` projection instead of the key-wrapper form.
- Allow logical CTE/reference source projection when the result columns can be inferred from the database cursor description.
- Keep base-table lineage through CTE/derived projection, grouped queries, HAVING, QUALIFY, LIMIT/OFFSET, and set operations unsupported until exact lineage rules exist.

Reason:

- Matched-key tracing preserves the original WHERE/JOIN/EXISTS predicates while avoiding false rows from whole-table fallback.
- Fetching full rows by primary key gives stable Source Data, CSV export, negative-record lookup, and inline update snapshots.

Consequence:

- Complex predicates inside supported top-level SELECT statements can now produce exact base-table source records.
- Source Data remains strict: unsupported scopes still render diagnostics instead of approximate records.

## 2026-08-12 - Database SQL Workspace

Decision:

- Remove the independent SQL menu entry from the web UI and expose SQL tooling as the `SQL Workspace` tab inside Database.
- Use a common Database 1/Database 2 connection area: Database 1 serves CSV, SQL Workspace, and sync source; Database 2 serves sync target.
- Add `autocompare_tool/sql_database_workspace.py` for SQL execution, write-mode tokens, result spool, source lineage diagnostics, export, and optimistic update.
- Keep `sql_tools.py` parser-only and keep database adapter behavior in `database_io.py`.
- Use strict source lineage: unsupported SQL structures show diagnostics instead of approximating source rows from whole tables.

Reason:

- SQL analysis becomes much more useful when paired with live metadata and source data, but execution and update need stronger safety boundaries than the formatter/analyzer.
- A common Database connection area avoids duplicated credentials and makes it clear which database is source or target.
- Strict lineage prevents misleading test data when CTEs, aggregates, derived sources, or correlated logic cannot be rewritten without changing semantics.

Consequence:

- DDL/DML execution requires a temporary Write mode token tied to the Database 1 fingerprint.
- Query result/source grids use temporary workspace spool and page loading instead of loading full result sets into browser memory.
- Inline update is available only for base tables with primary keys and uses full-row conflict detection.
- Future lineage support should add exact rewrites first, then expose data; never add best-effort whole-table fallback.

## 2026-08-07 - Primary-Key Streaming Delta Sync

Decision:

- Keep append and truncate sync modes for compatibility, but make primary-key incremental sync the default in the web UI.
- Stream both tables in primary-key order and write only source-only inserts, changed-row updates, and optional target-only deletes.
- Use bounded batches plus separate target read/write connections; keep target mutations atomic per table.
- Reject incremental sync when PK metadata is missing/mismatched, a record limit is supplied, or canonical PK order is incompatible.

Why:

- Large tables with small differences should not be truncated, fully rewritten, or loaded into application memory.
- Without CDC/change metadata, a full read comparison is still required, but database writes and transaction-log volume can remain proportional to the actual delta.

## 2026-07-28 - Multi-Database CSV Import Export

Decision:

- Add `autocompare_tool/database_io.py` as the new multi-database adapter layer.
- Rename the GUI database page from SQL Server-specific wording to a generic database page.
- Support SQL Server, MySQL, PostgreSQL, and Oracle adapters first.
- Add CSV normalize, import, and export actions behind a successful connection check.
- Keep identity preservation as an explicit import checkbox.

Reason:

- CSV-to-DB behavior now needs database-specific metadata and SQL dialect handling.
- Identity, computed/generated, and rowversion-style columns have different constraints per database.
- Keeping SQL construction out of the GUI gives the project a cleaner path for future databases.

Consequence:

- DB writes are now part of the product surface and must keep explicit confirmation in the GUI.
- Future database support should extend `database_io.py` adapters and focused tests.
- `db_roundtrip.py` remains as legacy SQL Server normalize behavior but new GUI behavior should use `database_io.py`.

## 2026-07-28 - File Utilities Menu

Decision:

- Add a left-menu `File Utilities` page for simple bulk filesystem tasks.
- Implement logic in `autocompare_tool/file_utilities.py`.
- Keep delete confirmations in `gui.py`.

Reason:

- Users need operational cleanup tools near compare workflows without mixing this logic into compare modules.

Consequence:

- Future utility tasks should be added to `file_utilities.py` first, then exposed through the file utilities page.
- Destructive tasks must continue to require explicit GUI confirmation.

## 2026-07-28 - Ad-Hoc CSV Folder Compare

Decision:

- Add a separate left-menu page for comparing two user-selected CSV folders.
- Add `autocompare_tool/folder_compare.py` as the workflow wrapper.
- Reuse `excel_writer.write_compare_workbook_with_fixmes` with `include_left_only_files=True`.

Reason:

- Users need a direct folder-to-folder compare that is not tied to `UT*` root structure.
- Reusing the existing Excel writer keeps FIXME output and compare semantics consistent.

Consequence:

- The folder compare output workbook path is user-selected, with a default file name in `autocompare_config.ini`.
- Future improvements to compare semantics should generally happen in `compare.py` or `excel_writer.py` so both compare flows benefit.

## 2026-07-28 - Left-Side Main Menu

Decision:

- Replace the single stacked GUI surface with a left-side `Main Menu`.
- Keep Compare, Copy UT Files, and SQL Server as separate pages.

Reason:

- The tool now has enough features that separate work areas are easier to manage than one long screen.

Consequence:

- New GUI features should usually be added as a page or a section within the relevant page instead of adding another global frame.

## 2026-07-28 - Configurable Compare Workflows And FIXME Review

Decision:

- Add `autocompare_config.ini` for folder names, output workbook names, Excel headers, and default compare checkbox state.
- Add a third compare workflow for HTC after vs HTM after.
- Add GUI review table for generated `FIXME` mismatch entries.
- Persist note combobox values in `fixme_notes.json`.

Reason:

- The compare workflow needs to grow without hard-coded path and output names spread across modules.
- Users need a structured way to turn `FIXME` markers into meaningful review notes.

Consequence:

- `processor.py` now takes selected workflow keys.
- `excel_writer.py` returns detailed mismatch metadata in addition to writing workbooks.
- Future compare workflows should be added through config/workflow objects instead of branching in GUI code.

## 2026-07-28 - Establish Agent Documentation

Decision:

- Add root `AGENTS.md`.
- Add `.agents` project-memory docs for context, architecture, conventions, roadmap, and decisions.

Reason:

- The project is expected to grow, and future agents need stable orientation before changing behavior.

Consequence:

- Behavior changes should update docs together with code.

## 2026-07-28 - SQL CSV Normalize Scans Selected Folder

Decision:

- SQL CSV normalize scans all `*.csv` files recursively under the selected folder.
- Missing DB tables are skipped instead of treated as workflow errors.

Reason:

- Users may select arbitrary folders and need the tool to process every matching CSV it can safely map.

Consequence:

- Users should choose the normalize root carefully because CSV files are rewritten in place.
- Future dry-run support would reduce risk.

## 2026-08-05 - Local Web UI Replaces Default Tkinter Startup

Decision:

- Make a local HTML/CSS/JavaScript interface the default UI.
- Serve it from a dependency-free Python `ThreadingHTTPServer` on `127.0.0.1:8765` by default.
- Keep Tkinter available through `--desktop` as a temporary fallback.
- Run one long-lived background job at a time and poll incremental logs from the browser.

Reason:

- A browser layout is easier to organize, resize, and extend than the growing stacked desktop surface.
- Reusing the Python process preserves local filesystem access and all existing compare/DB workflow modules.
- Avoiding a frontend build system and new web framework keeps Windows startup simple and offline-friendly.

Alternatives:

- Flask/FastAPI would provide routing helpers but add another runtime dependency.
- Electron/Tauri would provide desktop packaging but add a separate application toolchain.
- Upload-based browser inputs cannot preserve the absolute local paths required by the current workflows.

Consequence:

- `run.bat [port]` starts the local server and opens the browser.
- The server supplies a local filesystem picker because standard browser file inputs do not expose absolute paths.
- Server binding must stay loopback by default; exposing it to a network grants access to powerful local file and DB workflows.
- Destructive actions require confirmation in both the browser payload and backend dispatch.

## ADR Template

```text
## YYYY-MM-DD - Title

Decision:

- What changed.

Reason:

- Why this option was chosen.

Alternatives:

- Other choices considered.

Consequence:

- Follow-up work, risk, or constraints introduced.
```
