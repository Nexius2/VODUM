# core/backup.py
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from logging_utils import get_logger


@dataclass(frozen=True)
class BackupConfig:
    backup_dir: str
    database_path: str


def ensure_backup_dir(cfg: BackupConfig) -> Path:
    """
    S'assure que le dossier de sauvegarde existe.

    - Aucun accès DB
    - Logging applicatif via logging_utils
    - Exception explicite si le dossier ne peut pas être créé
    """
    logger = get_logger("backup")

    if not cfg.backup_dir:
        logger.error("[BACKUP] BACKUP_DIR non défini dans la configuration")
        raise KeyError("BACKUP_DIR missing")

    backup_dir = Path(cfg.backup_dir)

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(
            f"[BACKUP] Impossible de créer le dossier de sauvegarde ({backup_dir}): {e}",
            exc_info=True,
        )
        raise

    logger.debug(f"[BACKUP] Dossier de sauvegarde prêt: {backup_dir}")
    return backup_dir


def create_backup_file(get_db: Callable[[], object], cfg: BackupConfig) -> str | None:
    """
    Crée un fichier de sauvegarde de la base SQLite.

    - Compatible DBManager (une seule connexion)
    - WAL checkpoint safe
    - Aucun close manuel
    - Aucun lock long
    - Logs applicatifs UNIQUEMENT via logging_utils
    - Retourne le nom du fichier de sauvegarde ou None
    """
    logger = get_logger("backup")
    db = get_db()

    # 0) Dossier de sauvegarde
    try:
        backup_dir = ensure_backup_dir(cfg)
    except Exception:
        return None

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.sqlite"
    backup_path = backup_dir / backup_filename

    try:
        # 1) Forcer un checkpoint WAL (sans fermer la DB)
        # DBManager doit exposer execute(sql) comme dans ton code actuel.
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")

        # 2) Copie fichier DB → backup
        db_path = cfg.database_path

        if not db_path or not os.path.exists(db_path):
            logger.error(f"[BACKUP] Fichier DB introuvable: {db_path}")
            return None

        shutil.copy2(db_path, backup_path)

        logger.info(f"[BACKUP] Sauvegarde créée: {backup_filename}")
        return backup_filename

    except Exception as e:
        logger.error(f"[BACKUP] Erreur création backup: {e}", exc_info=True)
        return None


def list_backups(cfg: BackupConfig) -> list[dict]:
    """
    Liste les fichiers de sauvegarde disponibles.

    - Aucun accès DB
    - Logging via logging_utils
    - Retourne une liste de métadonnées triée par date décroissante
    """
    logger = get_logger("backup")

    try:
        backup_dir = ensure_backup_dir(cfg)
    except Exception:
        return []

    backups: list[dict] = []

    try:
        files = sorted(
            backup_dir.glob("backup_*.sqlite"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for f in files:
            stat = f.stat()
            backups.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
            )

        logger.debug(f"[BACKUP] {len(backups)} sauvegarde(s) trouvée(s)")
        return backups

    except Exception as e:
        logger.error(
            f"[BACKUP] Erreur lors de la liste des sauvegardes: {e}",
            exc_info=True,
        )
        return []


def restore_backup_file(uploaded_path: Path, cfg: BackupConfig) -> None:
    """
    Écrase la base actuelle par le fichier fourni.

    ⚠️ Action destructive :
    - crée une sauvegarde de précaution avant écrasement
    - un redémarrage du conteneur est recommandé après restauration

    - Aucun accès DB
    - Logging via logging_utils
    """
    logger = get_logger("backup")

    db_path = Path(cfg.database_path)

    # Validation
    if not uploaded_path or not uploaded_path.exists():
        logger.error("[BACKUP] Fichier de restauration introuvable")
        raise FileNotFoundError("Backup file not found")

    if uploaded_path.stat().st_size == 0:
        logger.error("[BACKUP] Fichier de restauration vide")
        raise ValueError("Backup file is empty")

    # Sauvegarde de précaution
    try:
        if db_path.exists():
            backup_dir = ensure_backup_dir(cfg)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            pre_restore_backup = backup_dir / f"pre_restore_{timestamp}.sqlite"

            shutil.copy2(db_path, pre_restore_backup)
            logger.info(
                f"[BACKUP] Sauvegarde pré-restauration créée: {pre_restore_backup.name}"
            )
    except Exception as e:
        logger.error(
            f"[BACKUP] Impossible de créer la sauvegarde pré-restauration: {e}",
            exc_info=True,
        )
        raise

    # Restauration
    try:
        shutil.copy2(uploaded_path, db_path)
        logger.warning("[BACKUP] Base restaurée avec succès – redémarrage recommandé")
    except Exception as e:
        logger.error(
            f"[BACKUP] Erreur lors de la restauration de la base: {e}",
            exc_info=True,
        )
        raise
