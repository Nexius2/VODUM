import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from logging_utils import get_logger
from tasks_engine import task_logs
from config import Config

log = get_logger("auto_backup")


def _row_value(row, key, default=None):
    """
    Support sqlite3.Row (pas de .get()) + support dict si jamais.
    """
    if not row:
        return default
    try:
        val = row[key]  # sqlite3.Row supporte row["col"]
    except Exception:
        try:
            val = row.get(key)  # fallback dict
        except Exception:
            return default
    return default if val is None else val


def _sqlite_checkpoint_if_possible(db):
    """
    Essaie de réduire le risque de backup incohérent si SQLite est en WAL.
    Ne casse jamais la tâche si ça échoue.
    """
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        log.debug("SQLite WAL checkpoint executed (TRUNCATE).")
    except Exception as e:
        log.debug(f"SQLite WAL checkpoint skipped/failed: {e}")


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

        row = db.query_one("SELECT backup_retention_days FROM settings WHERE id = 1")
        retention_days = _row_value(row, "backup_retention_days", 30)

        try:
            retention_days = int(retention_days)
            if retention_days < 1:
                retention_days = 30
        except Exception:
            retention_days = 30

        log.info(f"Configured retention: {retention_days} days")

        # ---------------------------------
        # 2) Chemins
        # ---------------------------------
        database_path = Path(Config.DATABASE)

        # IMPORTANT: on utilise le dossier standard de Vodum (persistant)
        backup_dir = Path(os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups"))

        log.debug(f"Database path from Config : {database_path}")
        log.debug(f"Backup directory          : {backup_dir}")

        if not database_path.exists():
            raise FileNotFoundError(f"Database not found: {database_path}")

        backup_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------
        # 2bis) Sécurisation SQLite
        # ---------------------------------
        _sqlite_checkpoint_if_possible(db)

        # ---------------------------------
        # 3) Créer un nouveau backup
        # ---------------------------------
        # On garde TON format historique pour ne rien casser:
        # vodum-YYYYmmdd-HHMMSS.db
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"backup_{timestamp}.sqlite"
        backup_path = backup_dir / backup_name

        log.info(f"Creating backup: {backup_name}")
        shutil.copy2(database_path, backup_path)

        # ---------------------------------
        # 4) Nettoyage des vieux backups (tous formats)
        # ---------------------------------
        cutoff_ts = time.time() - retention_days * 86400
        deleted = 0
        scanned = 0

        patterns = (
            "vodum-*.db",          # ancien format auto_backup
            "backup_*.sqlite",     # nouveau format (manuel + auto)
            "pre_restore_*.sqlite",
            "database_v1_*.db",
        )

        for pat in patterns:
            for f in backup_dir.glob(pat):
                scanned += 1
                try:
                    if f.stat().st_mtime < cutoff_ts:
                        log.debug(f"Deleting old backup: {f.name}")
                        f.unlink()
                        deleted += 1
                except Exception as e:
                    log.error(f"Error deleting {f}: {e}", exc_info=True)

        log.info(f"{deleted} backup(s) deleted (scanned {scanned})")

        # ---------------------------------
        # 5) Log DB pour la tâche
        # ---------------------------------
        task_logs(task_id, "success", f"Backup created: {backup_name}")

        duration = time.monotonic() - start
        log.info(f"=== AUTO BACKUP : COMPLETED SUCCESSFULLY IN {duration:.2f}s ===")

    except Exception as e:
        log.error("Error during AUTO BACKUP", exc_info=True)
        task_logs(task_id, "error", f"Auto-backup error: {e}")
        raise
