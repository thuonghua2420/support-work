# Project Conventions

## Coding Style

- Use Python 3.10+ type hints.
- Prefer `pathlib.Path` for filesystem paths.
- Keep dataclasses for simple workflow result objects.
- Keep web/Tkinter orchestration separate from workflow logic.
- Prefer explicit, small helper functions over large GUI callbacks.
- Add comments only for non-obvious behavior.

## File Editing

- Preserve existing Japanese folder names and generated workbook names.
- Be careful with console encoding; some existing docs show mojibake.
- Do not rewrite sample binary outputs unless required.
- Do not remove tracked `__pycache__` or generated artifacts unless cleanup is explicitly requested.

## CSV Rules

## Configuration Rules

- Folder names, compare output names, Excel headers, and default compare checkbox states live in `autocompare_config.ini`.
- Load config through `app_config.py`.
- Keep comments in `autocompare_config.ini` clear because users may edit it directly.
- Keep `constants.py` as a backward-compatible import surface only.
- When a compare workflow is unchecked, retain its existing workbook output. Overwrite only selected outputs; never clear the compare folder.

### Compare CSV

- Use `csv_table.py`.
- Supported encodings: `utf-8-sig`, `utf-8`, `cp932`.
- Preserve DBeaver-style NULL versus empty string in compare inputs: unquoted blank data cell is `NULL`, quoted empty string is `""`.
- Compare workbooks display `NULL` values as literal `NULL`; empty strings remain visually blank.
- Workbook preview exposes a separate record-count filter only when a record pair is present on one CSV side but missing on the other. That filter hides the unmatched before/after column pairs plus rows whose only FIXME entries belong to those pairs, and bulk note controls must target only the remaining visible differences.
- Pair records by the first CSV column when key values line up. If before/after files have the same record count but the first-column key sequence or key header differs, compare rows by top-down record order because leading identity or timestamp columns may legitimately differ.
- Compare must never automatically filter/delete records, CSV files or before folders, including equal-table cleanup. Keep equal sheets. After HTC/HTM row counts must never change.
- Copy Input to both before folders only when `copy_input` is enabled and at least one before-after workflow is selected. Copy overwrites matching filenames without clearing or pruning. Otherwise compare existing folders; after-after needs no Input/before folders.
- Optional `sort_by_key` uses `[update_compare_keys]` for ascending text ordering of all composite-key columns and explicit key pairing. `csv_order.py` validates both sides per table, preserves raw record contents/encoding and writes reordered CSVs atomically. Missing/unsafe keys skip sorting with a log. No CSV ordering or mutation occurs when disabled. Input is never sorted.
- HTM/HTC before-after workbooks compare tables present in before, including before-only CSVs; after-only CSVs must not create before-after sheets.
- Compare key extraction is managed from Database > Trích xuất key and reads primary-key metadata for all tables in the selected connected DB/schema. Extraction rewrites `[update_compare_keys]` with the DB keys it can read; use remove key to clear the section.

### DBeaver CSV

- Use `dbeaver_csv.py`.
- Preserve `NULL` versus empty string.
- Write with CRLF line endings.
- Existing normalize writer quotes all non-null data cells.
- Typed DB export writer leaves numeric cells unquoted and quotes string cells.
- SQL Workspace database grids display `None` as `[NULL]`; empty strings remain visually blank.
- Keep headers unquoted unless quoting is required by CSV syntax.

## DB CSV Rules

- Use `database_io.py` for multi-database connection, metadata, normalize, import, and export workflows.
- Supported built-in adapters: SQL Server, MySQL, PostgreSQL, Oracle.
- Do not build SQL in `gui.py`; keep dialect behavior inside adapters.
- Use `sql_database_workspace.py` for live SQL execution/source data/export/update; keep `sql_tools.py` parser-only and web assets as render/orchestration only.
- Use `sql_excel_loader.py` for reading numbered SQL lists from Excel sheets; the web layer should only pass file path, sheet name, and dialect.
- Real DB writes must be triggered only from an explicit user action and confirmation.
- SQL Workspace classifies each execution before it starts: read-only SQL runs directly, while CUD/DDL and unparsed raw SQL request confirmation and receive a short-lived server token for that execution without exposing a persistent write-mode toggle.
- Normalize scans all CSV files recursively under the selected folder.
- Import scans only CSV files directly inside the selected folder; nested folders are ignored.
- The web CSV import page can scan direct CSV files and pass selected table names to `import_csv_folder`; import-all must keep the same behavior as an empty selection.
- After at least one scanned CSV table is selected, Ctrl+A in the table picker selects every scanned table; the copy-all action writes all scanned table names to the clipboard one per line.
- Map table name from CSV file stem.
- Skip missing tables; do not mark them as errors.
- CSV headers must map to DB columns; unknown CSV columns are errors.
- Reorder output columns by DB column order.
- Normalize CSV values based on DB type:
  - `datetime`, `datetime2`, `smalldatetime` -> `yyyy-MM-dd HH:mm:ss.fff`.
  - `datetimeoffset` -> `yyyy-MM-dd HH:mm:ss.fff +/-HH:MM`.
  - `time` -> `HH:mm:ss.fff`.
  - `decimal`, `numeric`, `money`, `smallmoney` -> four decimal places.
- If a value cannot be parsed/formatted, preserve the original value.
- Import skips computed/generated/rowversion columns because DBs own those values.
- Import identity values only when the user selects the keep-identity option and the adapter/database supports it.
- Import existing-row mode defaults to append for backward compatibility.
- Delete-matching import uses every primary-key column, including composite keys; do not guess a key when table metadata has no primary key.
- Delete-matching import requires all primary-key columns to be present and insertable. Identity primary keys therefore require keep-identity mode.
- Reject `NULL` primary keys and duplicate keys inside the same CSV before issuing delete statements.
- Truncate-table import truncates only the table mapped to each CSV and requires explicit UI plus backend confirmation.
- Incremental DB sync requires matching primary-key definitions and uses the complete composite key.
- Conditional DB sync applies one user-entered WHERE fragment to each selected source table, then matches target rows by primary key.
- Conditional sync rejects semicolons and SQL comments in the WHERE fragment; do not allow stacked statements.
- Conditional sync duplicate handling can be plain insert, backup plus delete/insert, or backup plus upsert.
- When conditional sync deletes or overwrites target rows with duplicate keys, backup the affected target rows under `db_sync_backups` before modifying them.
- Stream source and target rows with bounded `fetchmany()` batches; never materialize a full table for incremental sync.
- Use a separate target read connection so target writes cannot invalidate the streaming read cursor.
- Apply incremental insert/update/delete batches in one target transaction per table and roll back the table on comparison or DML errors.
- Disable record limits for exact incremental sync because a partial source scan cannot safely identify target-only rows.
- Validate canonical PK ordering while streaming and fail on incompatible datatype/collation ordering.
- Export `NULL` as an unquoted blank cell, empty strings as `""`, string columns quoted, and numeric columns unquoted.

## Excel Rules

- Compare workbooks are generated with `openpyxl`.
- Sheet names must be sanitized and unique.
- Diff cells are styled in `excel_writer.py`; compare workbook color codes are read from `[excel_compare_style]` in `autocompare_config.ini`.
- Keep `diff_font_color` and `a1_font_color` separate: mismatch cells use `diff_font_color` and bold text, while A1 and final-column `FIXME` cells are not bold.
- Metadata columns skipped by compare are listed in `compare.py`.
- `excel_writer.py` should return mismatch metadata whenever processor/GUI needs review data.
- If multiple mismatch rows point to one final-column `FIXME` cell, applying notes joins unique selected notes with line breaks but keeps wrap text disabled.
- Applying FIXME notes uses every assigned entry in the current compare result across all cases, workbooks, and sheets; the active preview sheet only controls visibility.

## Testing Rules

- Prefer unit tests for mapping, parsing, formatting, and workbook behavior.
- Add fake connections/cursors for DB metadata tests.
- Only add real SQL Server integration tests behind an explicit opt-in.
- Keep tests runnable with:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

## Logging Rules

- Web job and legacy GUI worker logs should be readable by non-developers.
- Include relative CSV paths when processing many files.
- Distinguish skipped files from errors.
- Keep the web activity log history across tasks; add start/end timestamps, elapsed time, and a separator line after each task.
- Do not redirect local dev/smoke web-server stdout or stderr to `*-server-*.log`, `*.err.log`, or `*.out.log` in the repo root. Use `DEVNULL` for detached helper servers, or place temporary diagnostics under ignored `.tmp` and clean them up.

## Web UI Rules

- Keep the server dependency-free beyond the project's existing Python dependencies; static assets require no build step.
- Bind to loopback by default and document the risk before exposing the server to a network.
- Keep one background mutation job active at a time.
- Require both a visible browser confirmation and backend `confirmed: true` validation for destructive file and DB actions.
- Never return database passwords in bootstrap, job status, logs, or result payloads.
- Never persist database passwords in the browser input cache or browser history cache.
- Persist database passwords only in the local server-side `database_connection_history.json` file, which must remain ignored by git.
- When a saved DB connection is selected, auto-test the connection and let the server reuse the matching password from persistent history.
- Long-running DB actions should accept a cooperative cancel checker, check it between batches/files/tables, and roll back active write transactions before surfacing cancellation.
- Use the server-side filesystem picker for absolute local paths; browsers cannot provide those paths through standard upload controls.
- Keep Case, File compare, and Sheet selectors together above the workbook grid. Normal workbook preview expands to the full sheet height; maximize uses the full viewport and confines scrolling to the grid.
