#!/usr/bin/env python3

"""
cleanup_backups.py — VERSION TXT LOGGING
---------------------------------------
✓ Tous les logs détaillés → TXT
✓ SQLite utilisé uniquement pour lire la rétention et écrire 2–3 task_logs()
✓ Aucune écriture DB dans les boucles → zéro risque de lock
✓ Tâche verbeuse (DEBUG, INFO, ERROR)
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from tasks_engine import task_logs
from logging_utils import get_logger



log = get_logger("cleanup_backups")

BACKUP_DIR = os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups")
def run(task_id: int, db):
    """
    Tâche cleanup_backups — version UNIFORME et FINALE
    DBManager fourni par tasks_engine
    """

    task_logs(task_id, "info", "Task cleanup_backups started")
    log.info("=== CLEANUP BACKUPS : STARTING ===")

    base = Path(BACKUP_DIR)

    if not base.exists():
        msg = "Backup directory not found, no action performed."
        log.warning(msg)
        task_logs(task_id, "info", msg)
        return

    # -------------------------------------------------
    # Lecture de la rétention depuis la DB
    # -------------------------------------------------
    row = db.query_one(
        "SELECT backup_retention_days FROM settings LIMIT 1"
    )

    retention = row["backup_retention_days"] if row and row["backup_retention_days"] else 30
    cutoff = datetime.utcnow() - timedelta(days=retention)

    log.debug(f"Retention = {retention} days -> Deadline = {cutoff}")
    log.debug(f"Directory analysis : {base}")

    deleted = 0

    try:
        for f in base.glob("vodum-*.db"):
            try:
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)

                log.debug(f"File found : {f.name} | Last modified = {mtime}")

                if mtime < cutoff:
                    log.info(f"Deleting old backup : {f.name}")
                    f.unlink()
                    deleted += 1
                else:
                    log.debug(f"Kept : {f.name}")

            except Exception as e:
                log.error(
                    f"Error while deleting file {f}: {e}",
                    exc_info=True
                )

        msg = f"{deleted} Backup(s) deleted — retention {retention} days."
        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP BACKUPS : FINISHED ===")

    except Exception as e:
        log.error("Unexpected error during cleanup_backups", exc_info=True)
        task_logs(task_id, "error", f"cleanup_backups error : {e}")
        raise


