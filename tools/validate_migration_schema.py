"""Validate the production migration schema from tables.sql."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = {
    "migration_campaigns",
    "migration_users",
    "migration_steps",
    "migration_library_mappings",
}


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "vodum.db"
        connection = sqlite3.connect(path)
        connection.executescript((ROOT / "tables.sql").read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = REQUIRED_TABLES - names
        assert not missing, f"Missing migration tables: {sorted(missing)}"
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert not foreign_key_errors, foreign_key_errors
        connection.close()
    print("OK - production migration tables build with valid foreign keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
