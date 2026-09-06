# Architecture

## High-Level Shape

The primary application is a local HTTP web interface over small workflow modules. The legacy Tkinter interface remains available through `--desktop` during migration.

```text
run.bat
  -> python -m autocompare_tool
    -> web_app.py -> web/index.html + web/app.css + web/app.js
      -> app_config.py      -> autocompare_config.ini
      -> processor.py       -> excel_writer.py -> compare.py -> csv_table.py
      -> compare_workbook_view.py -> generated compare .xlsx
      -> folder_compare.py  -> excel_writer.py -> compare.py -> csv_table.py
      -> excel_image_formatter.py -> Microsoft Excel Desktop COM
      -> excel_format_presets.py -> excel_format_presets.json
      -> sql_tools.py       -> SQLGlot parser/AST
      -> sql_excel_loader.py -> read numbered SQL blocks from Excel sheets
      -> sql_database_workspace.py -> database_io.py -> dbeaver_csv.py
      -> file_utilities.py
      -> fixme_notes.py     -> fixme_notes.json
      -> fixme_replacements.py
      -> database_io.py     -> dbeaver_csv.py
      -> db_roundtrip.py    -> dbeaver_csv.py
      -> copy_ut.py         -> copy_ut_files.py
```

Long-running web actions use a single in-process background job. The browser polls job state and incremental logs, matching the desktop application's one-worker-at-a-time behavior.

### `autocompare_tool/web_app.py`

Owns:

- Local `ThreadingHTTPServer` startup, static asset delivery, and JSON endpoints.
- Background job lifecycle, incremental logs, and JSON result summaries.
- Cooperative cancellation for long-running web jobs; database workflows receive a cancel checker and roll back/close connections at safe checkpoints.
- Web request validation, destructive-action confirmation enforcement, and mapping request payloads into existing workflow calls.
- Server-side local path browsing for directory/file selection.
- In-memory FIXME review state for the latest compare run.
- In-memory compare workbook references for the browser preview; sheet data is loaded only from generated compare workbooks, not arbitrary browser-supplied paths.

Rules:

- Bind to `127.0.0.1` by default because the app can access local files and databases.
- Accept mutation API bodies only as `application/json`.
- Keep business rules in the existing non-UI workflow modules.
- Require an explicit `confirmed: true` payload for delete, DB import/export, and DB synchronization actions.
- Require explicit confirmation for Excel image formatting because copied results can be overwritten and overwrite mode mutates source workbooks.

### `autocompare_tool/web/`

Owns:

- Responsive HTML layout and page navigation.
- Client-side form state, confirmation dialogs, FIXME/note rendering, per-column FIXME filters, bulk note assignment, database connection forms, and table selection.
- Polling background job state and rendering logs/toasts.
- Browser `localStorage` cache for the latest non-sensitive user inputs, selected sync tables, checkbox/radio choices, and non-sensitive database connection history. Generated outputs and picker internals are intentionally excluded.
- Database connection history is also persisted server-side in the ignored root file `database_connection_history.json`, including passwords, so users can reconnect after restarting the local server. Passwords are never sent back to the browser in bootstrap/job payloads; when a saved connection is selected, the browser submits public fields and the server fills the matching password from persistent history before auto-testing the connection.

The web client has no build step or external CDN dependency.

## Module Responsibilities

### `autocompare_tool/gui.py`

Owns:

- Legacy Tkinter layout used only with `--desktop`.
- Left-side Main Menu page navigation.
- User input validation.
- Worker thread startup.
- Worker-to-UI log queue.
- Compare workflow checkboxes.
- FIXME review table and note management UI.
- Ad-hoc two-folder CSV compare page.
- File utilities page and destructive-action confirmations.
- Database page for connection inputs and CSV import/export action orchestration.

Avoid adding new behavior here unless the desktop fallback must remain in parity. New UI work should target `web_app.py` and `autocompare_tool/web/`.

Avoid:

- CSV transformation rules.
- DB metadata interpretation.
- Excel layout rules beyond invoking workflow functions.

### `autocompare_tool/processor.py`

Owns:

- Root validation for compare workflow.
- `UT*` test case discovery.
- Before-folder refresh.
- Selected compare workflow execution.
- Compare workbook generation summary and FIXME item aggregation.

Important functions:

- `process_root`
- `discover_test_cases`
- `_refresh_before_folders`

### `autocompare_tool/folder_compare.py`

Owns:

- Validation for two user-selected CSV folders.
- Ad-hoc compare workbook generation outside the `UT*` root workflow.
- Passing `include_left_only_files=True` and `recursive=True` for the one-workbook mode so all CSV files under both selected folders are represented.
- Direct-folder CSV pair preview for per-file export.
- Per-file compare export, where each user-adjusted pair is written to its own workbook.

### `autocompare_tool/file_utilities.py`

Owns:

- Bulk rename/delete/move helpers for files and folders.
- Excel sheet rename by contained text.
- Empty-folder detection and deletion.

Rules:

- Scan below the selected folder, not the selected folder itself.
- Sort deepest paths first before renaming/deleting folders.
- Avoid overwrites by generating unique target names.
- Keep destructive confirmation in GUI, not in this module.

### `autocompare_tool/compare.py`

Owns:

- CSV row pairing.
- Column union.
- Metadata-column skipping.

Matching rule:

- Use the first CSV column as key.
- Duplicate keys are disambiguated by occurrence order.
- Rows present only in before are appended after after-driven rows.

### `autocompare_tool/excel_writer.py`

Owns:

- Workbook and sheet creation.
- Sheet-name sanitization.
- Cell values, diff styling, freeze panes, and column widths.
- Detailed mismatch metadata used by the GUI FIXME review table.

Keep:

- Compare workbook text labels in `[excel_headers]` and style colors in `[excel_compare_style]` of `autocompare_config.ini`.

### `autocompare_tool/compare_workbook_view.py`

Owns:

- Building the Case/workbook/sheet index for the latest generated compare output.
- Reading compare workbook sheets with `openpyxl` and serializing cell values, compare colors, row heights, column widths, and FIXME cell mappings for the web preview. It also scans current compare workbooks for remaining exact `FIXME` markers after note application. Font and size stay controlled by the web UI.

Rules:

- Read only workbook references stored by `web_app.py` after compare workflows.
- Keep preview data close to the real workbook output so browser colors and mapped/unmapped columns match the exported Excel file.

### `autocompare_tool/excel_image_formatter.py`

Owns:

- Recursive discovery of `.xlsx`, `.xls`, `.xlsb`, and `.xlsm` workbooks.
- Safe-copy output under `Formatted` or explicit in-place overwrite mode.
- One hidden Microsoft Excel COM session per batch.
- Simple `.xlsx` workbooks without OOXML drawing/media/control parts are formatted with `openpyxl` before Excel COM is started.
- Native image layout based on the bundled VBA sample: classify pictures into six regions from their original `TopLeftCell` (old/new system × Input/Steps/Output), preserve paste order via z-order, resize to configured widths, stack each column region independently with a configured pixel gap, and grow or shrink empty row space at section boundaries.
- Workbook-wide font/font-size formatting, row exclusions, A1 selection, scroll reset, and first-sheet activation.

Rules:

- Use Excel Desktop automation rather than `openpyxl` so images, VBA projects, and form buttons remain intact.
- Skip temporary `~$` workbooks, the output tree, and history/sample sheets excluded by configured markers.
- Apply general font/view formatting to every worksheet; special-sheet exclusions affect only the image layout step.
- Treat a plain exclusion as an exact, case-insensitive value anywhere in a row; treat `(Text, A1)` as a value check at one explicit cell.
- Retry transient Excel COM busy errors, including `Call was rejected by callee`, before marking a workbook as failed.
- Keep row markers, old/new column boundaries, image anchors/sizes/gaps, borders, and optional header/background settings in `[excel_image_format]` of `autocompare_config.ini`.

### `autocompare_tool/excel_format_presets.py`

Owns:

- Parsing and validating font-size exclusion rules.
- Loading, updating, and deleting user-named Excel format presets.
- JSON persistence in the ignored root-level `excel_format_presets.json` file.

Rules:

- Persist only preset name, font name, font size, and normalized exclusion text.
- Keep preset matching case-insensitive and rule order stable.

### `autocompare_tool/sql_tools.py`

Owns:

- Multi-statement SQL parsing and pretty formatting through SQLGlot.
- Numbered SQL block formatting for Excel-loaded SQL lists.
- Dialect validation for the SQL Studio choices.
- AST/scope traversal for physical tables, CTE references, aliases, DML targets, conditions, CTEs, subqueries, projections, grouping, ordering, and limits.
- Parser-error translation into line/column messages suitable for the web UI.

Rules:

- Never execute submitted SQL or connect to a database from this module.
- Use AST nodes and SQLGlot scopes; do not identify tables or subqueries with regex.
- Keep every table occurrence, including repeated/self-join references, because aliases and scopes are semantically distinct.

### `autocompare_tool/sql_excel_loader.py`

Owns:

- Reading `.xlsx/.xlsm/.xltx/.xltm` sheets that store SQL lists.
- Detecting SQL numbers from column A.
- Joining SQL text from column B onward for every row from one SQL number to the next.
- Rendering raw numbered SQL blocks for the SQL editor.

### `autocompare_tool/sql_database_workspace.py`

Owns:

- Database SQL Workspace execution on Database 1.
- Read/write statement classification and temporary Write mode tokens.
- Result spool/workspace paging through bounded `fetchmany()` batches.
- Metadata-backed relation cards, source occurrence IDs, column usage colors, and join groups.
- Strict source lineage diagnostics for exact Source Data, CSV export, negative-record lookup, and optimistic inline update.
- Matched-primary-key source tracing for supported base tables: rewrite the original SELECT to `SELECT DISTINCT alias.pk...`, then fetch full source rows by joining those keys back to the base table.

Rules:

- Format/analyze remain parser-only; execution always goes through this module.
- Do not expose passwords in workspace responses, logs, bootstrap payloads, or job results.
- DDL/DML require a valid Write mode token tied to the current Database 1 fingerprint.
- Source Data must stay strict: unsupported lineage shows a diagnostic card and must not fall back to whole-table data.
- Base-table lineage through CTE/derived projection, grouped queries, HAVING, QUALIFY, LIMIT/OFFSET, and set operations must remain diagnostic-only until exact rewrite rules are implemented.
- Inline update is limited to base tables with primary keys and uses parameterized SQL plus full-row conflict checks.

### `autocompare_tool/csv_table.py`

Owns:

- Simple CSV reading for compare workflow.
- Rows as dictionaries keyed by header.
- Missing trailing values become empty strings.

### `autocompare_tool/dbeaver_csv.py`

Owns:

- DBeaver-compatible CSV parsing/writing.
- Distinction between `NULL` and empty string.

Semantics:

- Unquoted blank data cell -> `None`.
- Quoted blank data cell -> `""`.
- Written data strings are always quoted.
- Typed export can leave numeric values unquoted while still quoting string columns.
- Written `None` values are blank.

### `autocompare_tool/database_io.py`

Owns:

- Database adapter layer for SQL Server, MySQL, PostgreSQL, and Oracle.
- Connection validation and DB test query dispatch.
- Metadata lookup for table columns, identity columns, generated/computed columns, primary keys, and numeric scale.
- CSV normalize/import/export workflows for the GUI database page.
- Import rules for skipping computed/generated/rowversion columns, optionally preserving identity values, deleting rows by composite primary key, or truncating destination tables.
- Typed DBeaver-style CSV export.

Important functions:

- `test_database_connection`
- `normalize_csv_folder`
- `import_csv_folder`
- `export_csv_folder`

Rules:

- Adapter methods own SQL dialect differences.
- GUI must not build SQL statements directly.
- Real DB writes require explicit GUI confirmation before invoking this module.

### `autocompare_tool/db_roundtrip.py`

Owns:

- SQL Server connection setup.
- Metadata lookup from `sys.schemas`, `sys.tables`, `sys.columns`, `sys.types`.
- CSV-to-table matching by file stem.
- Recursive CSV scanning under the selected folder.
- Column reorder and datatype-based output formatting.

Non-goals until requested:

- New GUI behavior; use `database_io.py` for multi-database workflows.
- Schema migration.

### `autocompare_tool/app_config.py`

Owns:

- Loading `autocompare_config.ini`.
- Folder, workbook, Excel header, and compare workflow configuration.
- Default compare checkbox state.

### `autocompare_tool/fixme_notes.py`

Owns:

- Loading/saving user-defined note values and meanings.
- Runtime storage path: `fixme_notes.json`.

### `autocompare_tool/fixme_replacements.py`

Owns:

- Applying selected note text to generated workbook `FIXME` cells.
- Grouping multiple mismatch rows that point to the same workbook cell.
- Receiving many selected row notes in one call so the web UI can apply notes after filtering large FIXME sets.

### `copy_ut_files.py`

Owns:

- Legacy copy workflow and detailed CSV overwrite logging.

Current wrapper:

- `autocompare_tool/copy_ut.py` loads this module dynamically and exposes it to the GUI.

Future refactor path:

- Move legacy code into package modules when tests cover the copy workflow well enough.

## Data Flows

### Compare Flow

```text
Root folder
  -> discover UT* cases
  -> copy Input CSV to before folders
  -> prune before CSVs without matching after CSV
  -> run selected compare workflows
  -> read left/right CSV
  -> build row pairs and column list
  -> write Excel workbooks
  -> return mismatch items for GUI FIXME review
```

### Database CSV Flow

```text
Selected folder + connected database
  -> adapter validates DB settings and connects
  -> normalize scans CSV recursively; import scans only CSV files directly inside the selected folder
  -> read DBeaver CSV
  -> lookup table metadata by file stem
  -> skip if table missing
  -> validate CSV headers exist in table
  -> normalize: reorder to DB column order, format datetime/decimal values, rewrite CSV in place
  -> import: choose append/delete-matching-primary-keys/truncate-table mode
  -> validate PK columns and CSV key uniqueness when delete-matching mode is selected
  -> skip computed/generated/rowversion columns, apply identity option, clean existing data, insert rows
  -> export: select table rows, format values by metadata, write typed DBeaver CSV
```

### Database Delta Sync Flow

```text
Source table + target table
  -> validate matching DDL and primary-key columns
  -> open independent target read and write connections
  -> SELECT mapped columns from both sides ORDER BY the same logical primary key
  -> fetch rows in bounded batches and merge-compare canonical values
  -> buffer target-only deletes, changed-row updates, and source-only inserts
  -> execute parameterized DML batches inside one target transaction per table
  -> report source/target scans plus insert/update/delete/unchanged counts
```

Incremental sync never uses `fetchall()`. It validates that canonical primary-key order stays strictly increasing; incompatible PK datatypes/collations fail and roll back the table instead of risking an incorrect merge.

Conditional sync uses a user-entered `WHERE` fragment on each selected source table, fetches source rows in batches, looks up matching target rows by primary key, and can either insert only, backup plus delete/insert duplicate keys, or backup plus upsert duplicate keys. Backups are written as typed DBeaver-style CSV files under `db_sync_backups/<timestamp>_<table-or-multi-table>/` before target rows are deleted or overwritten.

### Folder Compare Flow

```text
Left CSV folder + right CSV folder + output workbook
  -> validate selected folders and output path
  -> run shared Excel writer with all recursive CSV files from both sides
  -> return mismatch items for GUI FIXME review
```

### File Utilities Flow

```text
Selected folder or Excel file
  -> validate path and user input
  -> run utility worker
  -> log per-item changes and summary
```

### SQL Studio Flow

```text
SQL text + selected dialect
  -> parse all statements into SQLGlot ASTs
  -> format each statement with pretty output and update the SQL editor in place
  -> traverse query scopes
  -> collect tables/aliases + conditions + CTE/subquery/projection/clause metadata
  -> return structured JSON for the web result panels
```

## Extension Points

- Add CLI subcommands for compare/copy/normalize once GUI behavior stabilizes.
- Add more database adapters by extending `database_io.py`.
- Move copy workflow into `autocompare_tool` after adding focused tests.
