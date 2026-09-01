# Project Context

## Purpose

AutoCompare Tool helps verify CSV-based UT output by copying expected input data, comparing before/after output folders, and moving CSV data to or from connected databases.

The project is a Windows-oriented local web tool. It starts an HTTP server on a user-selectable port and opens a browser UI while continuing to process local filesystem paths and database connections on the Python server. It may grow into a larger test-data and comparison platform, so new changes should keep business logic modular and documented.

## Users

Primary users are developers or testers working with UT folders and database-backed CSV exports. They need repeatable, visible output and clear logs when files cannot be processed.

## Current Workflows

The web UI is organized by a left-side navigation menu:

- `Compare`: compare workflows and FIXME review.
- `Compare CSV Folders`: ad-hoc compare for two user-selected CSV folders.
- `File Utilities`: simple bulk file/folder operations.
- `Copy UT Files`: source/target copy workflow.
- `Database`: DB connection, CSV normalize/import/export, and database-to-database synchronization.

Long-running actions run one at a time in a background job. The web UI shows live status and incremental logs in a bottom-right floating activity bubble that expands into the task log panel. The log keeps previous task history, adds start/end timestamps, shows elapsed time, and writes a separator after each completed task.

### Run Compare

Input:

- A root folder containing `UT*` test case folders.
- Each case has `Input` and `Output` folders.

Behavior:

- Copies CSV files from `Input` into before folders.
- Prunes before-only CSV files when corresponding after CSV files do not exist.
- Generates selected Excel compare workbooks in `Output\Compare`.

Important rule:

- Before/after compare sheets are based on right-side after CSV files.
- After/after compare sheets are based on the union of both after CSV folders.
- Rows are matched by the first column plus occurrence order.
- Compare workflow selection is controlled by GUI checkboxes and defaults in `autocompare_config.ini`.
- Configured workbook outputs for unchecked workflows are removed from `Output\Compare` during that run.

Current compare workflows:

- HTM before/after.
- HTC before/after.
- HTC after vs HTM after.

### Compare CSV Folders

Input:

- A left CSV folder.
- A right CSV folder.
- An output Excel workbook path.

Behavior:

- Generates one compare workbook for the two selected folders.
- Uses the same Excel writer and row/column comparison rules as the UT compare flow.
- Recursively includes CSV files that exist only on the left or only on the right side.
- Returns FIXME entries to the GUI review state.

### FIXME Review

After `Run Compare`, the GUI shows all mismatch items that produced `FIXME` notes in the generated workbooks.

Displayed fields:

- UT case folder.
- Excel file.
- Sheet.
- Column.
- Left and right values.
- Record number.
- Note combobox.

Users can add/update/delete combobox note values and meanings. Applying notes writes selected note text back to the matching workbook `FIXME` cells.

The web UI also renders the latest compare workbooks directly in the browser with Case, workbook, and sheet tabs. This preview reads the generated `.xlsx` files, keeps compare cell colors for visual diff cues, shows mapped and unmapped compare columns, and uses note comboboxes with a right-side checkbox column for bulk note assignment on rows that map to workbook `FIXME` entries. Font and size follow the web UI for consistency.

FIXME Review supports multi-header sorting. The default order is Case, workbook, sheet, then record number. After the first user click, clicked headers build a custom priority list in click order; clicking an existing sorted header toggles only its direction.

### File Utilities

Input:

- A shared root folder for folder-based operations.
- A separate Excel file path for sheet rename.

Behavior:

- Rename files/folders by exact name.
- Rename files/folders whose names contain a text fragment.
- Delete files/folders whose names contain a text fragment.
- Rename Excel sheets whose names contain a text fragment.
- Move files whose names contain a text fragment into a target folder beside each file.
- Find or delete empty folders under the selected root.

Important rule:

- Destructive operations are confirmed in the GUI before execution.
- Empty-folder deletion does not delete the selected root folder itself.

### Copy UT Files

Input:

- `Source Path1`: source tree containing `UT*` folders.
- `Target Path2`: destination tree.

Behavior:

- Delegates to legacy `copy_ut_files.py`.
- `autocompare_tool/copy_ut.py` is a package wrapper for GUI integration.
- Existing target CSV files are compared/logged before overwrite.

### Database CSV

Input:

- A selected CSV folder.
- Database connection settings, database type, and schema.
- Optional export table list.
- Keep-identity checkbox for import.

Behavior:

- Recursively scans every `*.csv` under the selected folder.
- Maps each CSV file to a database table by file stem.
- Skips CSV files whose table does not exist in the connected database.
- Reads column order, datatype, identity, generated/computed, scale, and primary-key metadata.
- Normalize rewrites CSV in place to database column order and known output formats.
- Import inserts CSV rows into matching tables.
- Export writes one CSV per selected table, or all tables in the current schema when no table list is provided.

Current output formatting:

- `datetime`, `datetime2`, `smalldatetime`: `yyyy-MM-dd HH:mm:ss.fff`.
- `decimal`, `numeric`, `money`, `smallmoney`: exactly 4 digits after the decimal point.
- Exported `NULL` is an unquoted blank cell.
- Exported empty string is `""`.
- Exported string columns are quoted.
- Exported numeric columns are not quoted.

Important rule:

- Import does not truncate tables.
- Import skips computed/generated/rowversion columns.
- Identity columns are included only when users choose to keep identity values and the adapter can support that database behavior.

### SQL Workspace

Behavior:

- SQL format, analysis, and Excel SQL loading use one shared editor; formatted SQL overwrites the editor content instead of appearing in a separate output panel.
- SQL analysis shows every table/reference occurrence so aliases, CTE references, and query scopes remain visible.
- The table-analysis copy button exports only unique physical database table names in analysis order, formatted as `Table1, Table2, Table3`; CTE and derived-query references are excluded.

## Domain Terms

- `before`: expected or copied baseline output.
- `after`: actual output to compare.
- `new/current`: two system variants represented by separate folder names.
- `DBeaver CSV`: CSV style where quoted empty string and unquoted blank cell mean different values.
- `HTC`: current/old system.
- `HTM`: new system.

## Known Constraints

- Python 3.10+.
- Windows-oriented startup via `run.bat`.
- Dependencies: `openpyxl`, `pyodbc`, `mysql-connector-python`, `psycopg`, `oracledb`.
- SQL Server connections require a Microsoft ODBC Driver for SQL Server.
- CSV readers support `utf-8-sig`, `utf-8`, and `cp932`.
- Some docs/constants may display Japanese names as mojibake depending on console encoding.
- Runtime note values are stored in `fixme_notes.json` when users save notes in the GUI.
- File utilities live in `autocompare_tool/file_utilities.py` and should stay UI-independent.
- Database import/export logic lives in `autocompare_tool/database_io.py` and should stay UI-independent.
