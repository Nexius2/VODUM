import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from logging_utils import get_logger
from tasks_engine import task_logs
from db_utils import open_db
from config import Config     # <--- LA solution propre

log = get_logger("auto_backup")


def run(task_id, db=None):

    log.info("=== AUTO BACKUP : démarrage ===")
    log.debug(f"task_id={task_id}, db fourni={db is not None}")

    start = time.monotonic()
    task_logs(task_id, "info", "Auto-backup démarré")

    try:
        # ---------------------------------
        # 1) Lire configuration depuis settings
        # ---------------------------------
        conn = db or open_db()
        cur = conn.cursor()

        log.debug("Lecture des paramètres dans settings…")

        row = cur.execute(
            "SELECT backup_retention_days FROM settings WHERE id = 1"
        ).fetchone()

        retention_days = row["backup_retention_days"] if row else 30
        log.info(f"Rétention configurée : {retention_days} jours")

        # ---------------------------------
        # 2) Récupérer le chemin DB depuis Config
        # ---------------------------------
        database_path = Path(Config.DATABASE)
        backup_dir = Path("/backups")

        log.debug(f"Chemin DB fourni par Config : {database_path}")
        log.debug(f"Backup dir                   : {backup_dir}")

        if not database_path.exists():
            raise FileNotFoundError(f"Database introuvable : {database_path}")

        backup_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------
        # 3) Créer un nouveau backup
        # ---------------------------------
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"vodum-{timestamp}.db"
        backup_path = backup_dir / backup_name

        log.info(f"Création du backup : {backup_name}")
        shutil.copy2(database_path, backup_path)

        # ---------------------------------
        # 4) Nettoyage des vieux backups
        # ---------------------------------
        cutoff_ts = time.time() - retention_days * 86400
        deleted = 0

        for f in backup_dir.glob("vodum-*.db"):
            if f.stat().st_mtime < cutoff_ts:
                log.debug(f"Suppression ancien backup : {f.name}")
                f.unlink()
                deleted += 1

        log.info(f"{deleted} backup(s) supprimé(s)")

        # ---------------------------------
        # 5) Log DB pour la tâche
        # ---------------------------------
        task_logs(task_id, "success", f"Backup créé : {backup_name}")

        duration = time.monotonic() - start
        log.info(f"=== AUTO BACKUP : terminé OK en {duration:.2f}s ===")

    except Exception as e:
        log.error("Erreur dans AUTO BACKUP", exc_info=True)
        task_logs(task_id, "error", f"Erreur auto-backup : {e}")

        duration = time.monotonic() - start
        log.error(f"=== AUTO BACKUP : ÉCHEC après {duration:.2f}s ===")
