"""Migration utility tests."""

from pathlib import Path

from scripts.run_migrations import _checksum


def test_checksum_is_stable(tmp_path: Path) -> None:
    migration = tmp_path / "001_test.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")

    assert _checksum(migration) == _checksum(migration)
