# core/backup.py
from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from logging_utils import get_logger, is_debug_mode_enabled
from secret_store import encryption_key_bytes


@dataclass(frozen=True)
class BackupConfig:
    backup_dir: str
    database_path: str


def ensure_backup_dir(cfg: BackupConfig) -> Path:
    logger = get_logger("backup")

    if not cfg.backup_dir:
        logger.error("[BACKUP] BACKUP_DIR non défini")
        raise KeyError("BACKUP_DIR missing")

    backup_dir = Path(cfg.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _appdata_dir_from_db(db_path: Path) -> Path:
    return db_path.parent


def _add_dir_to_zip(zipf: zipfile.ZipFile, source_dir: Path, archive_root: str) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        return

    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue

        rel = path.relative_to(source_dir)
        zipf.write(path, f"{archive_root}/{rel.as_posix()}")


def create_backup_file(get_db: Callable[[], object], cfg: BackupConfig) -> str | None:
    logger = get_logger("backup")
    db = get_db()

    try:
        backup_dir = ensure_backup_dir(cfg)
    except Exception:
        logger.error("[BACKUP] Unable to prepare backup directory", exc_info=True)
        return None

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.zip"
    backup_path = backup_dir / backup_filename
    tmp_backup_path = backup_dir / f".{backup_filename}.uploading"

    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")

        db_path = Path(cfg.database_path)
        if not db_path.exists():
            logger.error(f"[BACKUP] Fichier DB introuvable: {db_path}")
            return None

        appdata_dir = _appdata_dir_from_db(db_path)
        attachments_dir = appdata_dir / "attachments"
        encryption_key = encryption_key_bytes()

        manifest = {
            "format": "vodum-full-backup",
            "version": 2,
            "created_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "database": "database.db",
            "includes": {
                "database": True,
                "attachments": attachments_dir.exists(),
                "encryption_key": True,
            },
        }

        if tmp_backup_path.exists():
            tmp_backup_path.unlink()

        with zipfile.ZipFile(tmp_backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(db_path, "database.db")
            zipf.writestr("vodum.encryption_key", encryption_key)
            zipf.writestr("manifest.json", json.dumps(manifest, indent=2))
            _add_dir_to_zip(zipf, attachments_dir, "attachments")

        if tmp_backup_path.stat().st_size <= 0:
            raise RuntimeError("Backup zip was created empty")

        os.replace(tmp_backup_path, backup_path)

        logger.info(f"[BACKUP] Sauvegarde complète créée: {backup_filename}")
        return backup_filename

    except Exception as e:
        logger.error(f"[BACKUP] Erreur création backup: {e}", exc_info=True)
        try:
            if "tmp_backup_path" in locals() and tmp_backup_path.exists():
                tmp_backup_path.unlink()
        except Exception:
            logger.warning("[BACKUP] Unable to remove failed temporary backup", exc_info=True)
        return None


def list_backups(cfg: BackupConfig) -> list[dict]:
    logger = get_logger("backup")

    try:
        backup_dir = ensure_backup_dir(cfg)
    except Exception:
        logger.error("[BACKUP] Unable to list backups because backup directory is unavailable", exc_info=True)
        return []

    backups: list[dict] = []

    try:
        files = []
        for pattern in (
            "backup_*.zip",
            "backup_*.sqlite",
            "pre_restore_*.sqlite",
            "vodum-*.db",
            "database_v1_*.db",
        ):
            files.extend(backup_dir.glob(pattern))

        files = sorted(
            {f.resolve(): f for f in files}.values(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for f in files:
            stat = f.stat()
            if stat.st_size <= 0:
                continue
            backups.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        if is_debug_mode_enabled():
            logger.debug(f"[BACKUP] {len(backups)} sauvegarde(s) trouvée(s)")

        return backups

    except Exception as e:
        logger.error(f"[BACKUP] Erreur liste backups: {e}", exc_info=True)
        return []
