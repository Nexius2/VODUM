#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Routine de nettoyage du dossier temporaire.
Supprime les fichiers de /app/appdata/temp plus anciens que 24 heures.
Les logs sont enregistrés via le logger central (BDD + app.log).
"""

import os
import time
from datetime import datetime
from logger import logger


# === CONFIGURATION ===
TEMP_DIR = "/app/appdata/temp"
MAX_AGE_HOURS = 24


def clean_temp_folder():
    """
    Supprime tous les fichiers du dossier temporaire datant de plus de 24h.
    """
    now = time.time()
    max_age = MAX_AGE_HOURS * 3600
    deleted_files = 0

    if not os.path.exists(TEMP_DIR):
        logger.warning(f"Le dossier temporaire {TEMP_DIR} est introuvable.")
        return

    logger.info("🧹 Démarrage du nettoyage du dossier temporaire...")

    for filename in os.listdir(TEMP_DIR):
        filepath = os.path.join(TEMP_DIR, filename)
        try:
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age:
                    os.remove(filepath)
                    logger.debug(f"Fichier supprimé : {filename}")
                    deleted_files += 1
            elif os.path.isdir(filepath):
                # On gère aussi les sous-dossiers si jamais il y en a
                folder_age = now - os.path.getmtime(filepath)
                if folder_age > max_age:
                    try:
                        os.rmdir(filepath)
                        logger.debug(f"Dossier supprimé : {filename}")
                        deleted_files += 1
                    except OSError:
                        # Si le dossier n'est pas vide, on le laisse
                        pass
        except Exception as e:
            logger.error(f"Erreur lors du traitement de {filename} : {e}")

    logger.info(f"✅ Nettoyage terminé — {deleted_files} élément(s) supprimé(s).")


def main():
    """
    Point d’entrée du script.
    """
    start_time = datetime.now()
    logger.info("=== Tâche automatique : nettoyage du dossier temp ===")
    clean_temp_folder()
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"Tâche terminée en {duration:.2f} secondes.")


if __name__ == "__main__":
    main()
