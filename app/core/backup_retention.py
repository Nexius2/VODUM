"""Shared backup-retention rules for automatic backup and cleanup tasks."""

from __future__ import annotations

import time
from pathlib import Path


BACKUP_PATTERNS = (
    "backup_*.zip",
    "backup_*.sqlite",
    "pre_restore_*.sqlite",
    "vodum-*.db",
    "database_v1_*.db",
)


def safe_positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def prune_backups(
    backup_dir: Path,
    retention_days: int,
    retention_count: int,
    *,
    on_error=None,
) -> dict[str, int]:
    """Delete backups exceeding either the age or count retention limit."""
    retention_days = safe_positive_int(retention_days, 30)
    retention_count = safe_positive_int(retention_count, 10)
    cutoff_ts = time.time() - retention_days * 86400

    files: dict[Path, Path] = {}
    for pattern in BACKUP_PATTERNS:
        for path in backup_dir.glob(pattern):
            try:
                if path.is_file():
                    files[path.resolve()] = path
            except OSError as exc:
                if on_error:
                    on_error(path, exc)

    ordered = sorted(
        files.values(),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    keep_by_count = set(ordered[:retention_count])
    deleted = 0

    for path in ordered:
        try:
            too_old = path.stat().st_mtime < cutoff_ts
            exceeds_count = path not in keep_by_count
            if too_old or exceeds_count:
                path.unlink()
                deleted += 1
        except OSError as exc:
            if on_error:
                on_error(path, exc)

    return {"scanned": len(ordered), "deleted": deleted}
