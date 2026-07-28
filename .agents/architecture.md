# Architecture

## High-Level Shape

The application is a Tkinter GUI over small workflow modules.

```text
run.bat
  -> python -m autocompare_tool
    -> gui.py
      -> app_config.py      -> autocompare_config.ini
      -> processor.py       -> excel_writer.py -> compare.py -> csv_table.py
      -> fixme_notes.py     -> fixme_notes.json
      -> fixme_replacements.py
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
- Written `None` values are blank.

### `autocompare_tool/db_roundtrip.py`

Owns:

- SQL Server connection setup.
- Metadata lookup from `sys.schemas`, `sys.tables`, `sys.columns`, `sys.types`.
- CSV-to-table matching by file stem.
- Recursive CSV scanning under the selected folder.
- Column reorder and datatype-based output formatting.

Non-goals until requested:

- Truncate/insert/update database rows.
- Full DB export.
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

### SQL Normalize Flow

```text
Selected folder
  -> recursive CSV scan
  -> read DBeaver CSV
  -> lookup SQL table metadata by file stem
  -> skip if table missing
  -> validate CSV headers exist in table
  -> reorder to DB column order
  -> format datetime/decimal values
  -> rewrite CSV in place
```

## Extension Points

- Add CLI subcommands for compare/copy/normalize once GUI behavior stabilizes.
- Add a DB adapter layer if non-SQL Server databases become required.
- Move copy workflow into `autocompare_tool` after adding focused tests.
