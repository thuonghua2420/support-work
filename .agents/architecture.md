# Architecture

## High-Level Shape

The application is a Tkinter GUI over small workflow modules.

```text
run.bat
  -> python -m autocompare_tool
    -> gui.py
      -> app_config.py      -> autocompare_config.ini
      -> processor.py       -> excel_writer.py -> compare.py -> csv_table.py
      -> folder_compare.py  -> excel_writer.py -> compare.py -> csv_table.py
      -> file_utilities.py
      -> fixme_notes.py     -> fixme_notes.json
      -> fixme_replacements.py
      -> database_io.py     -> dbeaver_csv.py
      -> db_roundtrip.py    -> dbeaver_csv.py
      -> copy_ut.py         -> copy_ut_files.py
```

## Module Responsibilities

### `autocompare_tool/gui.py`

Owns:

- Tkinter layout.
- Left-side Main Menu page navigation.
- User input validation.
- Worker thread startup.
- Worker-to-UI log queue.
- Compare workflow checkboxes.
- FIXME review table and note management UI.
- Ad-hoc two-folder CSV compare page.
- File utilities page and destructive-action confirmations.
- Database page for connection inputs and CSV import/export action orchestration.

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
- Passing `include_left_only_files=True` and `recursive=True` so all CSV files under both selected folders are represented.

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

- Styling constants near this module until there is a real theme/config need.

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
- Import rules for skipping computed/generated/rowversion columns and optionally preserving identity values.
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
  -> recursive CSV scan for normalize/import
  -> read DBeaver CSV
  -> lookup table metadata by file stem
  -> skip if table missing
  -> validate CSV headers exist in table
  -> normalize: reorder to DB column order, format datetime/decimal values, rewrite CSV in place
  -> import: skip computed/generated/rowversion columns, apply identity option, insert rows
  -> export: select table rows, format values by metadata, write typed DBeaver CSV
```

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

## Extension Points

- Add CLI subcommands for compare/copy/normalize once GUI behavior stabilizes.
- Add more database adapters by extending `database_io.py`.
- Move copy workflow into `autocompare_tool` after adding focused tests.
