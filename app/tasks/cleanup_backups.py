"""Delete backups exceeding the configured age or maximum file count."""

import os
from pathlib import Path

from core.backup_retention import prune_backups, safe_positive_int
from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import task_logs


log = get_logger("cleanup_backups")
BACKUP_DIR = os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups")


def _row_value(row, key, default=None):
    if not row:
        return default
    try:
        value = row[key]
    except Exception:
        try:
            value = row.get(key)
        except Exception:
            return default
    return default if value is None else value


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_backups started")
    log.info("=== CLEANUP BACKUPS : STARTING ===")

    base = Path(BACKUP_DIR)
    if not base.exists():
        msg = f"Backup directory not found: {base} (no action performed)."
        log.warning(msg)
        task_logs(task_id, "info", msg)
        return

    row = db.query_one(
        "SELECT backup_retention_days, backup_retention_count FROM settings LIMIT 1"
    )
    retention_days = safe_positive_int(
        _row_value(row, "backup_retention_days", 30), 30
    )
    retention_count = safe_positive_int(
        _row_value(row, "backup_retention_count", 10), 10
    )

    if is_debug_mode_enabled():
        log.debug(f"Retention = {retention_days} days / {retention_count} files")
        log.debug(f"Directory analysis: {base}")

    try:
        stats = prune_backups(
            base,
            retention_days,
            retention_count,
            on_error=lambda path, exc: log.error(
                f"Error while processing file {path}: {exc}", exc_info=True
            ),
        )
        msg = (
            f"{stats['deleted']} backup(s) deleted (scanned {stats['scanned']}) "
            f"- retention {retention_days} days / {retention_count} files."
        )
        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP BACKUPS : FINISHED ===")
    except Exception as exc:
        log.error("Unexpected error during cleanup_backups", exc_info=True)
        task_logs(task_id, "error", f"cleanup_backups error: {exc}")
        raise
