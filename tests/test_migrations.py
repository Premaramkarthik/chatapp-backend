"""Migration utility tests."""

from pathlib import Path

from scripts.run_migrations import _checksum


def test_checksum_is_stable(tmp_path: Path) -> None:
    migration = tmp_path / "001_test.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")

    assert _checksum(migration) == _checksum(migration)


def test_duplicate_versions_rejected(tmp_path):
    import pytest

    from scripts.run_migrations import _load_migration_files

    (tmp_path / "001_a.sql").write_text("SELECT 1;")
    (tmp_path / "001_b.sql").write_text("SELECT 2;")
    with pytest.raises(RuntimeError, match="unique"):
        _load_migration_files(tmp_path)


def test_repository_migration_versions_are_unique():
    from scripts.run_migrations import MIGRATIONS_DIR, _load_migration_files

    files = _load_migration_files(MIGRATIONS_DIR)
    assert len(files) == 15
