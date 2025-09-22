# /app/backup.py
import os
import shutil
from datetime import datetime
from config import DATABASE_PATH
from logger import logger
from tasks import update_task_status

BACKUP_DIR = "/app/appdata/backup"
MAX_BACKUPS = 7  # Nombre max de fichiers à conserver

def run_backup():
    """Effectue une sauvegarde de la base SQLite avec horodatage."""
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if not os.path.exists(DATABASE_PATH):
        logger.error(f"🚨 Base introuvable : {DATABASE_PATH}")
        return False

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"database_{ts}.db")

    try:
        shutil.copy2(DATABASE_PATH, backup_file)
        logger.info(f"✅ Sauvegarde créée : {backup_file}")
        update_task_status("backup")            # ⬅️ ajouter
    except Exception as e:
        logger.error(f"❌ Erreur lors du backup : {e}")
        return False

    cleanup_old_backups()
    return True

def cleanup_old_backups():
    """Supprime les anciennes sauvegardes au-delà de MAX_BACKUPS."""
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("database_") and f.endswith(".db")]
    )
    while len(backups) > MAX_BACKUPS:
        old = backups.pop(0)
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
            logger.info(f"🧹 Ancien backup supprimé : {old}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de supprimer {old} : {e}")

if __name__ == "__main__":
    run_backup()
