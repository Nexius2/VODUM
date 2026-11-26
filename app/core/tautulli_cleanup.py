"""Conservative cleanup of old Tautulli import diagnostics and job records."""

from __future__ import annotations

import time
from pathlib import Path


DIAGNOSTIC_PATTERNS = ("tautulli_*.invalid.db", "tautulli_*.too_small", ".tautulli_*.uploading")


def cleanup_tautulli_imports(db, imports_dir: Path, retention_days: int = 30, *, on_error=None) -> dict[str, int]:
    retention_days = max(1, int(retention_days or 30))
    cutoff_ts = time.time() - retention_days * 86400
    protected = {
        str(Path(row["file_path"]).resolve())
        for row in db.query(
            "SELECT file_path FROM tautulli_import_jobs WHERE status IN ('queued','running')"
        )
        if row["file_path"]
    }

    scanned = 0
    deleted_files = 0
    if imports_dir.exists():
        for pattern in DIAGNOSTIC_PATTERNS:
            for path in imports_dir.glob(pattern):
                scanned += 1
                try:
                    if str(path.resolve()) not in protected and path.stat().st_mtime < cutoff_ts:
                        path.unlink()
                        deleted_files += 1
                except OSError as exc:
                    if on_error:
                        on_error(path, exc)

    cursor = db.execute(
        """
        DELETE FROM tautulli_import_jobs
        WHERE status IN ('success','error')
          AND COALESCE(finished_at, created_at) < datetime('now', ?)
        """,
        (f"-{retention_days} days",),
    )
    deleted_jobs = max(0, int(getattr(cursor, "rowcount", 0) or 0))
    return {"scanned": scanned, "deleted_files": deleted_files, "deleted_jobs": deleted_jobs}
