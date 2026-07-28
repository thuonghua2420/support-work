# Project Conventions

## Coding Style

- Use Python 3.10+ type hints.
- Prefer `pathlib.Path` for filesystem paths.
- Keep dataclasses for simple workflow result objects.
- Keep GUI orchestration separate from workflow logic.
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

- GUI worker logs should be readable by non-developers.
- Include relative CSV paths when processing many files.
- Distinguish skipped files from errors.
