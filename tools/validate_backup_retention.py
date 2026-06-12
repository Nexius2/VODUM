"""Validate combined backup age and count retention."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.backup_retention import prune_backups  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        now = time.time()
        for index in range(6):
            path = base / f"backup_20260611_00000{index}.zip"
            path.write_bytes(b"backup")
            os.utime(path, (now - index * 86400, now - index * 86400))

        stats = prune_backups(base, retention_days=30, retention_count=3)
        remaining = sorted(path.name for path in base.glob("backup_*.zip"))
        assert stats == {"scanned": 6, "deleted": 3}
        assert remaining == [
            "backup_20260611_000000.zip",
            "backup_20260611_000001.zip",
            "backup_20260611_000002.zip",
        ]

        old = base / "backup_20200101_000000.zip"
        old.write_bytes(b"backup")
        os.utime(old, (now - 60 * 86400, now - 60 * 86400))
        stats = prune_backups(base, retention_days=30, retention_count=10)
        assert stats["deleted"] == 1
        assert not old.exists()

    print("OK - backup retention enforces both age and maximum file count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
