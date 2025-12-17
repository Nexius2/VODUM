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

    task_logs(task_id, "info", "Tâche cleanup_backups démarrée")
    log.info("=== CLEANUP BACKUPS : DÉMARRAGE ===")

    base = Path(BACKUP_DIR)

    if not base.exists():
        msg = "Dossier de backup introuvable, aucune action effectuée."
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

    log.debug(f"Rétention = {retention} jours -> Date limite = {cutoff}")
    log.debug(f"Analyse du dossier : {base}")

    deleted = 0

    try:
        for f in base.glob("vodum-*.db"):
            try:
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)

                log.debug(f"Fichier trouvé : {f.name} | Dernière modif = {mtime}")

                if mtime < cutoff:
                    log.info(f"Suppression du backup ancien : {f.name}")
                    f.unlink()
                    deleted += 1
                else:
                    log.debug(f"Conservé : {f.name}")

            except Exception as e:
                log.error(
                    f"Erreur lors de la suppression du fichier {f}: {e}",
                    exc_info=True
                )

        msg = f"{deleted} backup(s) supprimé(s) — rétention {retention} jours."
        log.info(msg)
        task_logs(task_id, "success", msg)
        log.info("=== CLEANUP BACKUPS : TERMINÉ ===")

    except Exception as e:
        log.error("Erreur inattendue pendant cleanup_backups", exc_info=True)
        task_logs(task_id, "error", f"cleanup_backups error : {e}")
        raise


