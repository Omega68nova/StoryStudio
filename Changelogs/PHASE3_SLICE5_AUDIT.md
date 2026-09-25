# Phase 3 — Slice 5: Cleanup Audit

This is intentionally an audit-first slice.

Your local checkout now contains successful Phase 3 changes that are newer
than the GitHub baseline. The cleanup should therefore be driven by the local
tree instead of generating another blind replacement from remote source.

## What the audit does

`tools/phase3_cleanup_audit.py` scans the current checkout for:

- all current `test_*.py` files
- Phase 3 vs legacy tests
- raw SQL literals outside:
  - `app/data/`
  - `app/database.py`
  - `app/migrations/`
- transitional `db.*` persistence/facade calls outside repositories
- Python parse errors
- optionally, the complete pytest result and failing test node IDs

It writes:

    phase3_cleanup_report.md
    phase3_cleanup_report.json

## Run

From the StoryStudio repository root:

    python tools/phase3_cleanup_audit.py --run-tests

Also validate the architectural boundary checks:

    cd backend
    python -m pytest tests/test_phase3_repository_boundaries.py
    python -m compileall app

## Why old failures are not automatically deleted

A failing old test can mean either:

1. **Stale implementation assertion**
   - expected direct SQL
   - expected an old constructor
   - mocked a `Database` method that is now behind a repository

   These should be updated to the new boundary.

2. **Still-valid behavioral assertion**
   - branch behavior
   - cancellation
   - security/member visibility
   - transaction rollback
   - event ordering
   - projection equivalence

   These should remain and must be fixed if broken.

The generated report gives us the exact failing nodes and remaining persistence
hotspots so the final cleanup can distinguish those cases.

## Next

Return `phase3_cleanup_report.md` or paste its failing-test / top-SQL sections.
The final Phase 3 cleanup can then remove transitional calls and update stale
tests without weakening behavioral coverage.
