"""Validate conservative cleanup of old Tautulli import artifacts."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.tautulli_cleanup import cleanup_tautulli_imports  # noqa: E402


class TestDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor


def main() -> int:
    db = TestDB()
    db.conn.execute(
        "CREATE TABLE tautulli_import_jobs(id INTEGER PRIMARY KEY, file_path TEXT, status TEXT, created_at TEXT, finished_at TEXT)"
    )
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        protected = base / ".tautulli_protected.uploading"
        old_invalid = base / "tautulli_old.invalid.db"
        recent_invalid = base / "tautulli_recent.invalid.db"
        for path in (protected, old_invalid, recent_invalid):
            path.write_bytes(b"test")
        old = time.time() - 40 * 86400
        os.utime(protected, (old, old))
        os.utime(old_invalid, (old, old))

        db.conn.execute(
            "INSERT INTO tautulli_import_jobs VALUES(1, ?, 'running', datetime('now','-40 days'), NULL)",
            (str(protected),),
        )
        db.conn.execute(
            "INSERT INTO tautulli_import_jobs VALUES(2, ?, 'success', datetime('now','-40 days'), datetime('now','-40 days'))",
            (str(old_invalid),),
        )
        db.conn.commit()

        stats = cleanup_tautulli_imports(db, base, 30)
        assert stats == {"scanned": 3, "deleted_files": 1, "deleted_jobs": 1}
        assert protected.exists() and recent_invalid.exists() and not old_invalid.exists()

    print("OK - old Tautulli diagnostics are cleaned while active imports remain protected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
