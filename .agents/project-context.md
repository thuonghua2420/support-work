# Project Context

## Purpose

AutoCompare Tool helps verify CSV-based UT output by copying expected input data, comparing before/after output folders, and moving CSV data to or from connected databases.

The project is a Windows-oriented local web tool. It starts an HTTP server on a user-selectable port and opens a browser UI while continuing to process local filesystem paths and database connections on the Python server. It may grow into a larger test-data and comparison platform, so new changes should keep business logic modular and documented.

## Users

Primary users are developers or testers working with UT folders and database-backed CSV exports. They need repeatable, visible output and clear logs when files cannot be processed.

## Current Workflows

The web UI is organized by a left-side navigation menu:

- `Compare CSV`: one page with two modes plus a results tab. `Theo cấu trúc folder` runs the UT workflows over every case found under a root; `So sánh 2 thư mục` is the ad-hoc compare of two user-selected CSV folders. `Kết quả` holds the workbook preview and FIXME review for both.
- `Compare Excel`: cell-by-cell compare for two OOXML workbooks.
- `Compare PDF`: semantic and rendered-page comparison with an evidence report.
- `File Utilities`: simple bulk file/folder operations.
- `Copy UT Files`: source/target copy workflow.
- `Database`: DB connection, CSV normalize/import/export, and database-to-database synchronization.

Long-running actions run one at a time in a background job. The web UI shows live status and incremental logs through a circular LOG control inside the fixed left navigation footer; the control is hidden whenever the navigation is hidden, including full-workspace compare view and the closed mobile menu. On desktop, opening the log renders a separate full-width panel across the lower workspace; the panel header or close button collapses it, while a separate Clear log button only clears the content. The left navigation stays fixed across every feature while only the workspace scrolls. The log keeps previous task history, adds start/end timestamps, shows elapsed time, and writes a separator after each completed task.

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
- The Compare page accepts a 10–400% sheet zoom for generated Excel workbooks; the web UI remembers the last value locally.
- Preview bulk notes apply only to checked rows currently visible under the active filters. Each row has one FIXME cell shared by its differing records, so assigning a note replaces the prior note for every record represented by that cell, including records hidden by the filter. Other rows retain their notes; assigned ticks are cleared.
- A single FIXME cell can collect differences from several records. When those records have different selected notes, the preview lists every note in that cell while the input remains available to replace all of them.
- Configured workbook outputs for unchecked workflows are removed from `Output\Compare` during that run.

Current compare workflows:

- HTM before/after.
- HTC before/after.
- HTC after vs HTM after.

### Compare CSV page layout

- Tabs: `Theo cấu trúc folder` (form `#compare-form`), `So sánh 2 thư mục` (form `#folder-compare-form`), `Kết quả` (preview card, badge shows the workbook count). The last used mode is remembered in localStorage; `#folder-compare` still opens mode 2.
- Mode 1 previews its input before running: `GET /api/compare-cases?root=` (`processor.describe_test_cases`) lists the cases found and whether each workflow's before/after folders exist; the right-hand tree renders `compare_structure` from the config and dims folders unused by the selected workflows. `Chỉnh sửa` opens the existing structure dialog; saving re-renders the tree and rescans.
- Mode 2 pairs files automatically for the pair-based export styles, derives the output path from the right folder until the user edits it, and switches the output field between a file and a folder (`separate`).
- Both modes feed the same compare view; success switches to the `Kết quả` tab. Diagnostics panels sit above each mode's form.
- Styles live in `web/compare-csv.css` (`cc-*`), behaviour in `web/compare-csv.js`; legacy `choice-card` / `folder-export-*` / `folder-pair-*` rules were removed.

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
- An `.xlsx` output path distinct from both source files. The web page suggests `<New file name>_compare.xlsx` beside the New file until the user edits the path.
- Option `pair_by_position` (default on): pair sheets whose names differ by tab order.

Behavior:

- Pairs worksheets by exact name first, then (when `pair_by_position`) pairs remaining sheets by tab order; Old workbook order is preserved and unmatched New tail sheets are appended. With the option off, unmatched sheets are reported as Old-only / New-only.
- A formula cell differs when its formula differs, or when both files store a cached result and the results differ. A missing cached result on either side is not a difference (openpyxl-written files have none).
- When both sides render to the same text but differ (text `"5"` vs number `5`, trailing or doubled spaces), the compare cell adds `(văn bản)` / `(số)` hints or wraps both values in quotes.
- The job result carries per-sheet summaries (`sheets`: pairing, difference count, up to 100 sample cells) so the page can show the outcome without opening the workbook.
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
- The job result carries `pages` (per-page status, text/visual/field flags, pixel ratio, and a short text diff) so the page can show which pages differ without opening the report.
- Reports `BINARY IDENTICAL`, `CONTENT IDENTICAL`, or `DIFFERENT`; content identity requires page count, text, visual pixels, form fields, and annotations all to match.

### Compare Excel / PDF / Image page flow

- Excel and PDF share `web/file-compare.js` + `file-compare.css` (`dc-*` classes): pick Old and New, optional advanced options (output path, sheet pairing), one `So sánh` button, then an inline verdict, stats and per-sheet / per-page list. Image uses the same `dc-*` header/steps and compares automatically once both images are present.
- Result files are opened through `POST /api/open-result`, which only serves paths produced by Excel/PDF compare jobs in the current server session (`_openable_results`).
- Excel/PDF failures are explained inline on the page; the activity log is not force-opened for them.
- Global `table` CSS in `app.css` (min-width, sticky uppercase headers) is meant for the big review grids; `.dc-table` overrides it.

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

### Excel Workbook Formatting

Behavior:

- The compact Format Excel page offers independent checkboxes for font name, font size, row-specific size exclusions, selecting A1, resetting scroll, and activating the first sheet. Only selected workbook-format options run; at least one main option is required.
- Existing images and shapes are preserved in place. The web action does not expose or execute the old Evidence image layout step, even when a request includes its former `run_image_format` option.
- Users can save a copy under `Formatted` or explicitly confirm an overwrite of source workbooks.

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
- SQL Server connections prefer modern Microsoft ODBC Driver 18/17 before falling back to SQL Server Native Client. To preserve compatibility with long-running legacy SQL Server setups, connection encryption is off by default and exposed as an explicit UI checkbox. Native Client and the legacy `SQL Server` driver omit `Encrypt` and `TrustServerCertificate`; modern ODBC Driver 17/18 connections include those options only in their supported connection-string form.
- The web server rejects a second process on the same port. On Windows, enabling `SO_REUSEADDR` let an old backend and a newly launched backend both listen on port 8765, causing the browser to reach stale code. Keep `AutoCompareServer.allow_reuse_address` disabled.
- CSV readers support `utf-8-sig`, `utf-8`, and `cp932`.
- Some docs/constants may display Japanese names as mojibake depending on console encoding.
- Runtime note values are stored in `fixme_notes.json` when users save notes in the GUI.
- File utilities live in `autocompare_tool/file_utilities.py` and should stay UI-independent.
- Database import/export logic lives in `autocompare_tool/database_io.py` and should stay UI-independent.
