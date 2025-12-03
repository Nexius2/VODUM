#!/usr/bin/env python3
import os
import time
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "appdata", "temp")
MAX_AGE_HOURS = 24

def clean_old_files():
    if not os.path.exists(TEMP_DIR):
        logger.warning(f"⚠️ Dossier temporaire introuvable : {TEMP_DIR}")
        return

    now = time.time()
    cutoff = MAX_AGE_HOURS * 3600
    deleted_count = 0
    total_files = 0

    logger.info(f"🧹 Nettoyage du dossier temporaire : {TEMP_DIR}")

    for filename in os.listdir(TEMP_DIR):
        filepath = os.path.join(TEMP_DIR, filename)
        if not os.path.isfile(filepath):
            continue

        total_files += 1
        mtime = os.path.getmtime(filepath)
        age_hours = (now - mtime) / 3600

        if age_hours > MAX_AGE_HOURS:
            os.remove(filepath)
            deleted_count += 1
            logger.info(f"🗑️ Supprimé : {filename} (âge ≈ {age_hours:.1f}h)")
        else:
            logger.info(f"⏱️ Conservé : {filename} (âge ≈ {age_hours:.1f}h)")

    logger.info(
        f"✅ Nettoyage terminé : {deleted_count} supprimé(s) sur {total_files} fichier(s) analysé(s)."
    )

def main():
    """Fonction appelée par tasks.py ou par cron."""
    logger.info("🚀 Début de la tâche : Nettoyage des fichiers temporaires")
    clean_old_files()
    logger.info("🏁 Fin de la tâche : Nettoyage terminé")

if __name__ == "__main__":
    main()
