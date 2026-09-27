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
- `Compare Excel`: cell-by-cell compare for two OOXML workbooks.
- `Compare PDF`: semantic and rendered-page comparison with an evidence report.
- `File Utilities`: simple bulk file/folder operations.
- `Copy UT Files`: source/target copy workflow.
- `Database`: DB connection, CSV normalize/import/export, and database-to-database synchronization.

Long-running actions run one at a time in a background job. The web UI shows live status and incremental logs through a circular activity control anchored at the bottom-right edge of the fixed left navigation; on mobile it remains at the bottom-left of the viewport. On desktop, opening the log keeps that control fixed and renders a separate full-width panel across the lower workspace without covering the control; the panel header or close button collapses it, while a separate Clear log button only clears the content. The left navigation stays fixed across every feature while only the workspace scrolls. The log keeps previous task history, adds start/end timestamps, shows elapsed time, and writes a separator after each completed task.

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
- An output Excel workbook path for one-file export, or an output folder/path seed for per-file export.

Behavior:

- Supports two export modes:
  - `Export 1 file`: generates one compare workbook for the two selected folders, preserving the original behavior.
  - `Export từng file`: scans direct `*.csv` files from both folders, shows a three-column pairing table, lets users drag file names within each side to realign pairs, and exports each row to its own compare workbook.
- Uses the same Excel writer and row/column comparison rules as the UT compare flow.
- One-file export recursively includes CSV files that exist only on the left or only on the right side.
- Per-file export initially pairs exact file-name matches, then aligns remaining left/right files by sorted order so users can adjust timestamped or otherwise different file names before exporting.
- Returns FIXME entries to the GUI review state.

### Compare Excel

Input:

- An Old workbook and a New workbook in `.xlsx`, `.xlsm`, `.xltx`, or `.xltm` format.
- An `.xlsx` output path distinct from both source files.

Behavior:

- Pairs worksheets by exact name first, then pairs remaining sheets by tab order; Old workbook order is preserved and unmatched New tail sheets are appended.
- Creates three output worksheets per pair: `<name>_Old`, `<name>_New`, and `<name>_compare` (truncated and made unique within Excel's 31-character limit).
- Copies source cell values/formulas and basic worksheet formatting into the Old/New snapshots.
- Leaves equal compare cells blank. A differing cell contains rich text `Old:<old value> # New:<new value>`, with only `Old:` and `New:` bold.
- Treats sheets missing from either workbook as blank on that side, so added or removed sheets are not lost.

### Compare PDF

Input:

- An Old PDF, a New PDF, and a distinct PDF report path.

Behavior:

- Calculates file-level SHA-256 hashes for byte-for-byte evidence.
- Compares exact extracted text plus form-field and annotation values/positions for each page.
- Renders each page through PyMuPDF at 200 DPI and performs exact RGB pixel comparison.
- Produces one landscape PDF report with a verdict, per-page summary, and Old/New/red-highlighted Diff panels for changed pages.
- Writes a same-name JSON manifest containing the comparison algorithm, hashes, changed-pixel counts, ratios, and difference-region coordinates.
- Reports `BINARY IDENTICAL`, `CONTENT IDENTICAL`, or `DIFFERENT`; content identity requires page count, text, visual pixels, form fields, and annotations all to match.

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

Users can add/update/delete combobox note values and meanings. FIXME note comboboxes display the meaning text for readability, but store and apply the note value back to the matching workbook `FIXME` cells.

The web UI also renders the latest compare workbooks directly in the browser with Case, workbook, and sheet tabs. This preview reads the generated `.xlsx` files, keeps compare cell colors for visual diff cues, shows mapped and unmapped compare columns, and uses note comboboxes with a right-side checkbox column for bulk note assignment on rows that map to workbook `FIXME` entries. Font and size follow the web UI for consistency. The expanded table review is collapsed by default; users can open it when they need detailed filtering.

Users can run a remaining-FIXME check against the current compare workbooks. The check reports each workbook, sheet, and cell that still contains the exact `FIXME` marker.

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

### Excel Evidence Formatting

Behavior:

- Each sheet is split into old-system columns (A–R by default) and new-system columns (S onward), plus Input/Steps/Output row sections found from configured marker text in column A.
- An image belongs to the resulting region containing its original top-left cell; an oversized image crossing another region does not change ownership.
- Images in each of the six regions keep paste/z-order, are resized to the configured width, and are stacked independently with a 60 px default gap.
- Section row space grows to fit the taller old/new stack and shrinks only when the removed trailing rows contain no cell values.

### SQL Workspace

Behavior:

- SQL format, analysis, and Excel SQL loading use one shared editor; formatted SQL overwrites the editor content instead of appearing in a separate output panel.
- When loading SQL from Excel, a note in column C is attached inline to the formatted SQL fragment originating from column B on the same worksheet row; repeated fragments are matched in worksheet order.
- SQL analysis keeps every occurrence internally, but the table summary groups physical-table aliases into one row and removes duplicate aliases/scopes from that row.
- Table-analysis copy buttons export only unique physical database table names in analysis order, formatted as `Table1, Table2, Table3`; CTE and derived-query references are excluded. Each SQL statement has its own copy button, and the combined cross-statement summary has a final copy-all button.
- SQL Workspace runs SELECT statements directly. CUD/DDL is available by default but requires an explicit confirmation for each execution; the UI obtains and releases a temporary server-side write token automatically.
- SQL Workspace uses three nested tabs: `Input SQL` for the editor and commands, `Results SQL` for database query/source output, and `Analysis SQL` for parser diagnostics. Analyze and run actions automatically activate their matching result tab.
- The Input SQL editor automatically fills the remaining viewport height and recalculates when the window, workspace tab, or desktop navigation width changes.
- Table/alias analysis is rendered once per SQL statement, including an explicit empty result for statements without a table, followed by a combined cross-statement table summary that merges aliases, roles, and scopes and identifies the contributing statement numbers.
- The SQL editor and execution cards color SQL syntax and use a different accent per statement. Run-all attempts every parsed statement even when an earlier statement fails, while preserving rollback behavior for failed write batches.
- Query result grids show a stable row ordinal before database columns and preserve the database-provided column-name casing. The redundant Sources summary is hidden; Source Data groups aliases of the same physical table and keeps one row per primary key (or full-row hash when no key exists).

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
