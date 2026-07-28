# Decision Log

Use this file for lightweight architecture decisions. Add newest entries at the top.

## 2026-07-28 - Left-Side Main Menu

Decision:

- Replace the single stacked GUI surface with a left-side `Main Menu`.
- Keep Compare, Copy UT Files, and SQL Server as separate pages.

Reason:

- The tool now has enough features that separate work areas are easier to manage than one long screen.

Consequence:

- New GUI features should usually be added as a page or a section within the relevant page instead of adding another global frame.

## 2026-07-28 - Configurable Compare Workflows And FIXME Review

Decision:

- Add `autocompare_config.ini` for folder names, output workbook names, Excel headers, and default compare checkbox state.
- Add a third compare workflow for HTC after vs HTM after.
- Add GUI review table for generated `FIXME` mismatch entries.
- Persist note combobox values in `fixme_notes.json`.

Reason:

- The compare workflow needs to grow without hard-coded path and output names spread across modules.
- Users need a structured way to turn `FIXME` markers into meaningful review notes.

Consequence:

- `processor.py` now takes selected workflow keys.
- `excel_writer.py` returns detailed mismatch metadata in addition to writing workbooks.
- Future compare workflows should be added through config/workflow objects instead of branching in GUI code.

## 2026-07-28 - Establish Agent Documentation

Decision:

- Add root `AGENTS.md`.
- Add `.agents` project-memory docs for context, architecture, conventions, roadmap, and decisions.

Reason:

- The project is expected to grow, and future agents need stable orientation before changing behavior.

Consequence:

- Behavior changes should update docs together with code.

## 2026-07-28 - SQL CSV Normalize Scans Selected Folder

Decision:

- SQL CSV normalize scans all `*.csv` files recursively under the selected folder.
- Missing DB tables are skipped instead of treated as workflow errors.

Reason:

- Users may select arbitrary folders and need the tool to process every matching CSV it can safely map.

Consequence:

- Users should choose the normalize root carefully because CSV files are rewritten in place.
- Future dry-run support would reduce risk.

## ADR Template

```text
## YYYY-MM-DD - Title

Decision:

- What changed.

Reason:

- Why this option was chosen.

Alternatives:

- Other choices considered.

Consequence:

- Follow-up work, risk, or constraints introduced.
```
