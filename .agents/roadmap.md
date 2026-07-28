# Roadmap

This is not a promise list. It is a parking lot for useful next steps as the project grows.

## Near-Term

- Restore local Python environment and make tests easy to run.
- Add `.gitignore` cleanup strategy for future generated artifacts.
- Add tests for `copy_ut_files.py` behavior before moving it into the package.
- Add CLI subcommands for `compare`, `copy-ut`, `normalize-csv`, `import-csv`, and `export-csv`.
- Add a dry-run mode for DB CSV normalize/import/export.
- Add a summary report for skipped files, processed files, and errors.
- Add horizontal scrolling or a richer grid widget for large FIXME review tables.

## Medium-Term

- Retire or wrap `db_roundtrip.py` once `database_io.py` covers all legacy SQL Server normalize behavior.
- Convert legacy copy logic into package modules with tests.
- Add a structured logging layer that can write GUI logs and file logs consistently.
- Add integration tests using fake filesystem trees and fake DB metadata.
- Add packaging instructions for distributing the tool to tester machines.

## Larger Product Ideas

- Project profiles for different systems or schemas.
- Configurable key columns for compare, not only the first column.
- Compare report filters for inserted/deleted/changed-only rows.
- Batch normalization presets.
- Non-GUI automation mode for CI or nightly UT verification.
- Backup/rollback helpers for real DB import/export workflows.

## Risks To Watch

- Encoding drift around Japanese folder names.
- Accidental destructive DB behavior if "roundtrip" semantics are expanded.
- GUI growth making business rules hard to test.
- Large CSV files causing memory or workbook-size pressure.
- Generated artifacts entering source control unintentionally.
