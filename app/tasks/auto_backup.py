import json
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from logging_utils import get_logger, is_debug_mode_enabled
from tasks_engine import task_logs
from config import Config
from secret_store import encryption_key_bytes

log = get_logger("auto_backup")


def _row_value(row, key, default=None):
    if not row:
        return default
    try:
        val = row[key]
    except Exception:
        try:
            val = row.get(key)
        except Exception:
            return default
    return default if val is None else val


def _sqlite_checkpoint_if_possible(db):
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        if is_debug_mode_enabled():
            log.debug(f"SQLite WAL checkpoint skipped/failed: {e}")


def _add_dir_to_zip(zipf: zipfile.ZipFile, source_dir: Path, archive_root: str) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        return

    for path in source_dir.rglob("*"):
        if path.is_file():
            rel = path.relative_to(source_dir)
            zipf.write(path, f"{archive_root}/{rel.as_posix()}")


def run(task_id: int, db):
    log.info("=== AUTO BACKUP : starting ===")
    start = time.monotonic()
    task_logs(task_id, "info", "Auto-backup started")

    try:
        row = db.query_one("SELECT backup_retention_days FROM settings WHERE id = 1")
        retention_days = _row_value(row, "backup_retention_days", 30)

        try:
            retention_days = int(retention_days)
            if retention_days < 1:
                retention_days = 30
        except Exception:
            retention_days = 30

        database_path = Path(Config.DATABASE)
        backup_dir = Path(os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups"))
        attachments_dir = database_path.parent / "attachments"
        encryption_key = encryption_key_bytes()

        if not database_path.exists():
            raise FileNotFoundError(f"Database not found: {database_path}")

        backup_dir.mkdir(parents=True, exist_ok=True)

        _sqlite_checkpoint_if_possible(db)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}.zip"
        backup_path = backup_dir / backup_name
        tmp_backup_path = backup_dir / f".{backup_name}.uploading"

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

        log.info(f"Creating full backup: {backup_name}")

        if tmp_backup_path.exists():
            tmp_backup_path.unlink()

        with zipfile.ZipFile(tmp_backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(database_path, "database.db")
            zipf.writestr("vodum.encryption_key", encryption_key)
            zipf.writestr("manifest.json", json.dumps(manifest, indent=2))
            _add_dir_to_zip(zipf, attachments_dir, "attachments")

        if tmp_backup_path.stat().st_size <= 0:
            raise RuntimeError("Backup zip was created empty")

        os.replace(tmp_backup_path, backup_path)

        cutoff_ts = time.time() - retention_days * 86400
        deleted = 0
        scanned = 0

        for pat in (
            "backup_*.zip",
            "backup_*.sqlite",
            "pre_restore_*.sqlite",
            "vodum-*.db",
            "database_v1_*.db",
        ):
            for f in backup_dir.glob(pat):
                scanned += 1
                try:
                    if f.stat().st_mtime < cutoff_ts:
                        f.unlink()
                        deleted += 1
                except Exception as e:
                    log.error(f"Error deleting {f}: {e}", exc_info=True)

        log.info(f"{deleted} backup(s) deleted (scanned {scanned})")
        task_logs(task_id, "success", f"Backup created: {backup_name}")

        duration = time.monotonic() - start
        log.info(f"=== AUTO BACKUP : COMPLETED SUCCESSFULLY IN {duration:.2f}s ===")

    except Exception as e:
        log.error("Error during AUTO BACKUP", exc_info=True)
        try:
            if "tmp_backup_path" in locals() and tmp_backup_path.exists():
                tmp_backup_path.unlink()
        except Exception:
            pass
        task_logs(task_id, "error", f"Auto-backup error: {e}")
        raise
