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
- When a compare workflow is unchecked, remove its configured workbook output to avoid stale results.

### Compare CSV

- Use `csv_table.py`.
- Supported encodings: `utf-8-sig`, `utf-8`, `cp932`.
- Empty/missing values are compared as empty strings.

### DBeaver CSV

- Use `dbeaver_csv.py`.
- Preserve `NULL` versus empty string.
- Write with CRLF line endings.
- Existing normalize writer quotes all non-null data cells.
- Typed DB export writer leaves numeric cells unquoted and quotes string cells.
- Keep headers unquoted unless quoting is required by CSV syntax.

## DB CSV Rules

- Use `database_io.py` for multi-database connection, metadata, normalize, import, and export workflows.
- Supported built-in adapters: SQL Server, MySQL, PostgreSQL, Oracle.
- Do not build SQL in `gui.py`; keep dialect behavior inside adapters.
- Real DB writes must be triggered only from an explicit user action and confirmation.
- Scan all CSV files recursively under the selected folder.
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
- Stream source and target rows with bounded `fetchmany()` batches; never materialize a full table for incremental sync.
- Use a separate target read connection so target writes cannot invalidate the streaming read cursor.
- Apply incremental insert/update/delete batches in one target transaction per table and roll back the table on comparison or DML errors.
- Disable record limits for exact incremental sync because a partial source scan cannot safely identify target-only rows.
- Validate canonical PK ordering while streaming and fail on incompatible datatype/collation ordering.
- Export `NULL` as an unquoted blank cell, empty strings as `""`, string columns quoted, and numeric columns unquoted.

## Excel Rules

- Compare workbooks are generated with `openpyxl`.
- Sheet names must be sanitized and unique.
- Diff cells are styled in `excel_writer.py`.
- Metadata columns skipped by compare are listed in `compare.py`.
- `excel_writer.py` should return mismatch metadata whenever processor/GUI needs review data.
- If multiple mismatch rows point to one final-column `FIXME` cell, applying notes joins unique selected notes with line breaks.

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

## Web UI Rules

- Keep the server dependency-free beyond the project's existing Python dependencies; static assets require no build step.
- Bind to loopback by default and document the risk before exposing the server to a network.
- Keep one background mutation job active at a time.
- Require both a visible browser confirmation and backend `confirmed: true` validation for destructive file and DB actions.
- Never return database passwords in bootstrap, job status, logs, or result payloads.
- Use the server-side filesystem picker for absolute local paths; browsers cannot provide those paths through standard upload controls.
