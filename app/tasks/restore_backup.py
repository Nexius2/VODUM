import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import tasks_engine
from config import Config
from db_manager import DBManager
from logging_utils import get_logger
from tasks_engine import prepare_restored_database, task_logs

log = get_logger("restore_backup")

RESTORE_REQUEST_FILE = Path("/appdata/imports/restore_request_path.txt")


def _reset_tasks_engine_db_instance():
    try:
        tasks_engine.db._instance = None
    except Exception:
        pass


def _validate_sqlite_backup(candidate_path: Path) -> None:
    if not candidate_path.exists():
        raise FileNotFoundError(str(candidate_path))

    if candidate_path.stat().st_size == 0:
        raise ValueError("Backup file is empty")

    conn = None
    try:
        conn = sqlite3.connect(f"file:{candidate_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        row = conn.execute("PRAGMA integrity_check;").fetchone()
        integrity = row[0] if row else None
        if integrity != "ok":
            raise ValueError(f"SQLite integrity_check failed: {integrity}")

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        required_tables = {
            "settings",
            "tasks",
            "vodum_users",
            "servers",
        }

        missing = sorted(required_tables - tables)
        if missing:
            raise ValueError(
                "Backup is not a valid VODUM database. Missing tables: "
                + ", ".join(missing)
            )

    except sqlite3.DatabaseError as e:
        raise ValueError(f"Invalid SQLite database: {e}") from e
    finally:
        if conn is not None:
            conn.close()


def _safe_restore_from_path(backup_path: Path, db) -> None:
    db_path = Path(Config.DATABASE)
    backup_path = Path(backup_path)

    if not backup_path.exists():
        raise FileNotFoundError(str(backup_path))

    _validate_sqlite_backup(backup_path)

    pre_restore_path = db_path.with_suffix(db_path.suffix + ".pre_restore")
    if pre_restore_path.exists():
        try:
            pre_restore_path.unlink()
        except Exception:
            pass

    if db_path.exists():
        shutil.copy2(str(db_path), str(pre_restore_path))

    try:
        db.close()
    except Exception:
        pass
    _reset_tasks_engine_db_instance()

    for suffix in ("-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    tmp_path = db_path.with_suffix(db_path.suffix + ".restore_tmp")
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except Exception:
            pass

    shutil.copy2(str(backup_path), str(tmp_path))
    _validate_sqlite_backup(tmp_path)

    os.replace(str(tmp_path), str(db_path))

    for suffix in ("-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    try:
        restored_db = DBManager(str(db_path))
        prepare_restored_database(restored_db)

        try:
            restored_db.close()
        except Exception:
            pass

        _reset_tasks_engine_db_instance()

    except Exception as e:
        log.exception("Post-restore validation/update failed, restoring previous DB")

        try:
            if pre_restore_path.exists():
                if db_path.exists():
                    try:
                        db_path.unlink()
                    except Exception:
                        pass
                shutil.copy2(str(pre_restore_path), str(db_path))
        except Exception:
            log.exception("Automatic rollback after failed restore also failed")

        _reset_tasks_engine_db_instance()

        raise RuntimeError(
            f"Restore failed after swap, previous database restored automatically: {e}"
        ) from e

    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

    def _delayed_exit():
        time.sleep(1.5)
        os._exit(0)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    log.warning("Database restored. Maintenance mode ON. Process will exit for restart.")


def run(task_id: int, db):
    task_logs(task_id, "info", "restore_backup started")

    if not RESTORE_REQUEST_FILE.exists():
        raise FileNotFoundError(f"Missing restore request file: {RESTORE_REQUEST_FILE}")

    backup_path = Path(RESTORE_REQUEST_FILE.read_text(encoding="utf-8").strip())
    if not str(backup_path).strip():
        raise ValueError("Empty restore request path")

    try:
        RESTORE_REQUEST_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    _safe_restore_from_path(backup_path, db)

    task_logs(task_id, "success", f"restore_backup completed from {backup_path}")
    return {"status": "success", "backup_path": str(backup_path)}