# Agent Guide

This file is the first stop for coding agents working in this repo. Keep it short, current, and practical.

## Project Snapshot

AutoCompare Tool is a Windows-oriented Python desktop utility for CSV-based UT verification.

Main capabilities:

- Copy UT CSV files from a source tree into a target tree.
- Compare before/after CSV folders and generate Excel workbooks.
- Normalize CSV files using database table metadata.
- Import CSV files into connected databases and export database tables back to CSV.

The GUI is Tkinter. Business logic lives in `autocompare_tool`.

## First Steps

1. Run `git status --short` before editing.
2. Read `.agents/README.md` and the task-relevant file under `.agents/`.
3. Prefer small, scoped changes that preserve existing CSV semantics.
4. Add or update tests under `tests` for behavior changes.

## Commands

Use these from the repo root:

```bat
run.bat
```

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

If `.venv` is broken or Python is unavailable, report that clearly instead of guessing test results.

## Guardrails

- DB import is a real database write and must stay behind explicit GUI confirmation.
- Preserve DBeaver-style CSV semantics: blank unquoted data cell is `NULL`, quoted empty string is `""`.
- Keep Tkinter code as orchestration only; put rules and transformations in non-GUI modules.
- Keep GUI features page-based under the left-side Main Menu.
- Use `autocompare_config.ini` for folder names, workbook names, Excel headers, and default compare checkbox states.
- Be careful with Japanese folder/file names and existing mojibake in docs/constants.
- Do not rewrite generated sample output files unless the task is specifically about those artifacts.
- Avoid broad refactors while user work is in progress.

## Important Paths

- `autocompare_tool/gui.py`: Tkinter UI and worker threads.
- `autocompare_config.ini`: user-editable workflow/folder/workbook/header config.
- `autocompare_tool/app_config.py`: typed config loader.
- `autocompare_tool/processor.py`: compare workflow orchestration.
- `autocompare_tool/compare.py`: before/after row matching.
- `autocompare_tool/excel_writer.py`: Excel workbook rendering.
- `autocompare_tool/fixme_notes.py`: note combobox persistence.
- `autocompare_tool/fixme_replacements.py`: apply selected notes to workbook FIXME cells.
- `autocompare_tool/database_io.py`: multi-database metadata lookup plus CSV normalize/import/export.
- `autocompare_tool/db_roundtrip.py`: legacy SQL Server metadata lookup and CSV normalize.
- `autocompare_tool/dbeaver_csv.py`: DBeaver-compatible CSV parser/writer.
- `copy_ut_files.py`: legacy copy workflow implementation.
- `autocompare_tool/copy_ut.py`: package wrapper around `copy_ut_files.py`.
- `tests`: unit and integration-style tests.
- `.agents`: long-lived project notes for future agents and maintainers.
