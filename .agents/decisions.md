# Decision Log

Use this file for lightweight architecture decisions. Add newest entries at the top.

## 2026-11-20 - Multi-Database CSV Import/Export And Compact Connection Popup

Decision:

- Import/export can target several databases in one action (`connections` payload, ids `main`/`target`/`extra-1..8`). A CSV goes to every selected database that has the table; export writes one shared folder and skips later duplicates instead of overwriting.
- The connection popup became a connection list plus one editor with a 3-column field grid; a "Nhiều database" switch (default `[database] multi_database_default = false`) reveals selection checkboxes and extra connections. The selected databases are shown as chips beside the Import/Export controls and in the confirmation text.

Why:

- Projects with several databases forced the user to reconnect three times per task; the old two-card popup needed scrolling and had no room for more connections.

Consequences:

- Truncate/trigger options apply to every selected database, so confirmations list the databases. Extra connections live in the server session cache and the UI cache; removing one in the UI does not clear the server cache entry. Behaviour with the switch off is identical to before.

## 2026-11-20 - Import Respects Foreign Keys, Can Bypass Triggers, Reports Every Table

Decision:

- Import orders tables parents-first from FK metadata; truncate mode also clears dependent tables outside the CSV folder (children first, one transaction per database) because otherwise the database refuses to delete. Per-CSV commits are kept for inserts.
- Add an opt-in `disable_triggers` import option that temporarily disables enabled triggers on the written tables (SQL Server, PostgreSQL, Oracle) so an unrelated trigger target cannot fail the import. MySQL cannot do this.
- Import/export report succeeded / failed / skipped tables with reasons in the log and the result payload.

Why:

- Alphabetical CSV order and per-table `TRUNCATE` failed on databases with foreign keys; triggers that copy rows into stricter log tables made inserts fail for reasons unrelated to the imported table.

Consequences:

- Truncate is more destructive (extra tables emptied); the confirmation text and log say so. After a clear, a CSV that later fails to insert leaves its table empty.
- Trigger bypass needs ALTER privileges, skips trigger-generated rows, and Oracle's trigger DDL auto-commits. FK/trigger SQL is covered by mocks only; verify on a test database before production use.

## 2026-11-15 - Key Extraction Is Add-Only, Keys Editable In The UI

Decision:

- `extract_all_compare_keys` merges into `[update_compare_keys]` instead of rewriting it: new tables are added, identical keys are kept, conflicting keys keep the stored value and are reported in `skipped` and the log. The file is not written when nothing is added.
- Add `save_compare_key` + web action `compare_keys_save` and an inline editor in Database > Trích xuất key to add or change one table's key. "Xóa key" still clears everything; no per-table delete.

Why:

- One workspace can use several databases; extracting from the second must not erase the first one's keys or manual entries.
- With old keys preserved, an explicit way to change a key was needed.

Consequences:

- Saving through the editor or extraction rewrites only the `[update_compare_keys]` section; comment lines inside that section are not preserved.

## 2026-11-14 - CSV Compare Pairs Records By Configured Key

Decision:

- Reverse the 2026-10-07 "pair strictly by position" rule. `compare.py` matches records by the complete `[update_compare_keys]` key using an in-memory sort-merge (stable sort of `(key, index)` + two pointers) and classifies INSERT / DELETE / UPDATE / UNCHANGED.
- Apply to every writer caller: HTM/HTC before-after, HTC after vs HTM after, and folder compare.
- Missing/unusable keys fall back to positional pairing with a workbook warning instead of failing.
- Statuses are displayed only in the web preview; the Excel layout, labels and FIXME behaviour are unchanged.

Why:

- Positional pairing compared unrelated records after any insert/delete, even with `sort_by_key`, producing false differences.
- Streaming two-pointer merge on files would require sorted input (not guaranteed) and gives no memory benefit because CSVs and workbook sheets are already fully in memory and capped at 8190 pairs per sheet.

Consequences:

- Regenerated workbooks may order record pairs differently and can have more pairs (up to N+M) than before; the Excel column-limit check uses the real pair count.
- Tables whose primary key is regenerated on each run show DELETE + INSERT; this is accepted.

## 2026-11-04 - File Compare Rebuilt In The Style Of WinMerge

Decision:

- Split File Compare into a path-selection page, a full-height diff/merge workspace and a full-height folder grid, instead of one card holding inputs, options and the editor.
- Turn on the merge addon's copy buttons in both directions and add toolbar merge commands (current, current + next, all), undo/redo, find / go-to-line, keyboard shortcuts, a two-column location pane and per-pane save.
- Implement "ignore whitespace / case / blank lines" as chunk-level neutralisation rather than changing the diff algorithm.
- Keep folder comparison read-only; only open pairs from it.

Reason:

- The old layout spent most of the screen on inputs and had no way to merge differences, which is the main reason to compare text files.

Consequence:

- Ids from the previous layout (`tc-text-panel`, `tc-folder-panel`, `data-tc-tab`, `tc-folder-status`) no longer exist; `web_text_compare_smoke.cjs` was rewritten for the new ids.
- Ignored chunks stay in the aligned layout but are excluded from counts, navigation and merge.

## 2026-10-31 - Merge Compare CSV And Compare By Folder

Decision:

- Fold the separate "Compare theo folder" page into Compare CSV as a second mode, with the workbook preview as a third `Kết quả` tab.
- Make mode 1 self-explanatory: a read-only case scan and a folder-structure tree (with an edit button) replace the old full-width form and metric card.
- Keep all element ids used by scripts and smoke tests (`compare-form`, `folder-compare-form`, `compare-root`, `folder-*`) so behaviour and API payloads are unchanged.

Reason:

- Users could not tell the two features apart or what folder layout mode 1 required, and the old layout needed scrolling for a few inputs.

Consequence:

- `data-page="folder-compare"` no longer exists; the URL hash is aliased. Smoke tests that iterated that page now select `#tab-folder-compare-form`.

## 2026-10-31 - Compare Excel / PDF / Image Usability And Accuracy Pass

Decision:

- Excel compare also compares cached formula results when both files store them, labels type/whitespace-only differences, and can disable positional pairing of differently named sheets.
- Image compare ignores the hidden RGB of fully transparent pixels.
- Excel and PDF pages show their verdict and per-sheet / per-page detail inline instead of only printing an output path; the output path is auto-suggested and moved under advanced options.
- Image compare runs automatically when both images are present; paste goes to the first empty side.
- A small allowlisted `open-result` endpoint lets the page open produced files and reveal them in Explorer.

Reason:

- Users could not tell what a result meant without opening files, and several differences were invisible (`"5"` vs `5`, trailing spaces) or false (transparent pixels, formulas with equal text but different results).

Consequence:

- Whitespace-only differences in compare cells are now quoted (`Old:"a  b" # New:"a b"`).
- Positional sheet pairing stays the default for backward compatibility, but the result flags every positionally paired sheet.

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
