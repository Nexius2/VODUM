import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from logging_utils import get_logger
from tasks_engine import task_logs
from config import Config     



log = get_logger("auto_backup")

def run(task_id: int, db):

    log.info("=== AUTO BACKUP : starting ===")
    log.debug(f"task_id={task_id}, db Provided={db is not None}")

    start = time.monotonic()
    task_logs(task_id, "info", "Auto-backup started")

    try:
        # ---------------------------------
        # 1) Lire configuration depuis settings
        # ---------------------------------
        log.debug("Reading settings configuration…")

        row = db.query_one(
            "SELECT backup_retention_days FROM settings WHERE id = 1"
        )

        retention_days = row["backup_retention_days"] if row else 30

        log.info(f"Configured retention: {retention_days} days")

        # ---------------------------------
        # 2) Récupérer le chemin DB depuis Config
        # ---------------------------------
        database_path = Path(Config.DATABASE)
        backup_dir = Path("/backups")

        log.debug(f"Database path from Config: {database_path}")
        log.debug(f"Backup directory            : {backup_dir}")

        if not database_path.exists():
            raise FileNotFoundError(f"Database not found : {database_path}")

        backup_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------
        # 3) Créer un nouveau backup
        # ---------------------------------
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"vodum-{timestamp}.db"
        backup_path = backup_dir / backup_name

        log.info(f"Creating backup: {backup_name}")
        shutil.copy2(database_path, backup_path)

        # ---------------------------------
        # 4) Nettoyage des vieux backups
        # ---------------------------------
        cutoff_ts = time.time() - retention_days * 86400
        deleted = 0

        for f in backup_dir.glob("vodum-*.db"):
            if f.stat().st_mtime < cutoff_ts:
                log.debug(f"Deleting old backup: {f.name}")
                f.unlink()
                deleted += 1

        log.info(f"{deleted} backup(s) deleted")

        # ---------------------------------
        # 5) Log DB pour la tâche
        # ---------------------------------
        task_logs(task_id, "info", f"Backup created: {backup_name}")

        duration = time.monotonic() - start
        log.info(f"=== AUTO BACKUP : COMPLETED SUCCESSFULLY IN {duration:.2f}s ===")

    except Exception as e:
        log.error("Error during AUTO BACKUP", exc_info=True)
        task_logs(task_id, "error", f"Auto-backup error: {e}")
        raise

