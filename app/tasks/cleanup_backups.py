#!/usr/bin/env python3
"""
cleanup_backups.py
- Nettoie les backups selon la rétention
- Supporte plusieurs formats (legacy + UI + migration)
- Pas d'écriture DB dans les boucles
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("cleanup_backups")

BACKUP_DIR = os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups")


def _row_value(row, key, default=None):
    if not row:
        return default
    try:
        val = row[key]  # sqlite3.Row
    except Exception:
        try:
            val = row.get(key)  # dict fallback
        except Exception:
            return default
    return default if val is None else val


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_backups started")
    log.info("=== CLEANUP BACKUPS : STARTING ===")

    base = Path(BACKUP_DIR)

    if not base.exists():
        msg = f"Backup directory not found: {base} (no action performed)."
        log.warning(msg)
        task_logs(task_id, "info", msg)
        return

    # Réglage rétention
    row = db.query_one("SELECT backup_retention_days FROM settings LIMIT 1")
    retention = _row_value(row, "backup_retention_days", 30)

    try:
        retention = int(retention)
        if retention < 1:
            retention = 30
    except Exception:
        retention = 30

    cutoff = datetime.utcnow() - timedelta(days=retention)

    log.debug(f"Retention = {retention} days -> Deadline (UTC) = {cutoff}")
    log.debug(f"Directory analysis : {base}")

    deleted = 0
    scanned = 0

    patterns = (
        "vodum-*.db",          # legacy auto_backup
        "backup_*.sqlite",     # UI / core.backup
        "pre_restore_*.sqlite",
        "database_v1_*.db",
    )

    try:
        for pat in patterns:
            for f in base.glob(pat):
                scanned += 1
                try:
                    mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
                    log.debug(f"File found : {f.name} | Last modified (UTC) = {mtime}")

                    if mtime < cutoff:
                        log.info(f"Deleting old backup : {f.name}")
                        f.unlink()
                        deleted += 1
                    else:
                        log.debug(f"Kept : {f.name}")

                except Exception as e:
                    log.error(f"Error while processing file {f}: {e}", exc_info=True)

        msg = f"{deleted} backup(s) deleted (scanned {scanned}) — retention {retention} days."
        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP BACKUPS : FINISHED ===")

    except Exception as e:
        log.error("Unexpected error during cleanup_backups", exc_info=True)
        task_logs(task_id, "error", f"cleanup_backups error: {e}")
        raise
