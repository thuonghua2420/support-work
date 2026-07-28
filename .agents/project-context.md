# Project Context

## Purpose

AutoCompare Tool helps verify CSV-based UT output by copying expected input data, comparing before/after output folders, and normalizing CSV files against SQL Server table metadata.

The project is currently a local Windows desktop tool. It may grow into a larger test-data and comparison platform, so new changes should keep business logic modular and documented.

## Users

Primary users are developers or testers working with UT folders and SQL Server-backed CSV exports. They need repeatable, visible output and clear logs when files cannot be processed.

## Current Workflows

The GUI is organized by a left-side `Main Menu`:

- `Compare`: compare workflows and FIXME review.
- `Copy UT Files`: source/target copy workflow.
- `SQL Server`: DB login and CSV normalize.

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

### Copy UT Files

Input:

- `Source Path1`: source tree containing `UT*` folders.
- `Target Path2`: destination tree.

Behavior:

- Delegates to legacy `copy_ut_files.py`.
- `autocompare_tool/copy_ut.py` is a package wrapper for GUI integration.
- Existing target CSV files are compared/logged before overwrite.

### SQL Server CSV Normalize

Input:

- A selected folder.
- SQL Server connection settings and schema.

Behavior:

- Recursively scans every `*.csv` under the selected folder.
- Maps each CSV file to a DB table by file stem.
- Skips CSV files whose table does not exist in the DB.
- Reads DB column order and datatype metadata.
- Reorders CSV columns to DB order.
- Normalizes output values for known DB types.

Current output formatting:

- `datetime`, `datetime2`, `smalldatetime`: `yyyy-MM-dd HH:mm:ss.fff`.
- `decimal`, `numeric`, `money`, `smallmoney`: exactly 4 digits after the decimal point.
- Data cells are always quoted unless they are `NULL`.

Important rule:

- This workflow currently does not insert, update, truncate, or export rows from SQL Server. It reads metadata only and rewrites CSV files in place.

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
- Dependencies: `openpyxl`, `pyodbc`.
- SQL Server normalize requires a Microsoft ODBC Driver for SQL Server.
- CSV readers support `utf-8-sig`, `utf-8`, and `cp932`.
- Some docs/constants may display Japanese names as mojibake depending on console encoding.
- Runtime note values are stored in `fixme_notes.json` when users save notes in the GUI.
