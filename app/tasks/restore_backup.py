import os
import shutil
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import tasks_engine
from config import Config
from db_manager import DBManager
from logging_utils import get_logger
from tasks_engine import prepare_restored_database, task_logs
from core.archive_safety import validate_zip_limits
from core.app_paths import imports_dir as get_imports_dir
from secret_store import (
    encryption_key_file_path,
    install_encryption_key,
    validate_encryption_key,
)

log = get_logger("restore_backup")

RESTORE_REQUEST_FILE = get_imports_dir() / "restore_request_path.txt"


def _reset_tasks_engine_db_instance():
    try:
        tasks_engine.db._instance = None
    except Exception:
        log.warning("Unable to reset tasks engine database instance", exc_info=True)


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


def _safe_extract_zip_member(zipf: zipfile.ZipFile, member_name: str, target_path: Path) -> None:
    normalized = Path(member_name)

    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Unsafe zip member path: {member_name}")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    with zipf.open(member_name) as src, open(target_path, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _safe_extract_zip_dir(zipf: zipfile.ZipFile, archive_root: str, target_dir: Path) -> int:
    extracted = 0
    prefix = archive_root.rstrip("/") + "/"

    for member in zipf.infolist():
        if member.is_dir():
            continue

        name = member.filename

        if not name.startswith(prefix):
            continue

        rel_name = name[len(prefix):]
        rel_path = Path(rel_name)

        if not rel_name or rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"Unsafe zip member path: {name}")

        final_path = target_dir / rel_path
        final_path.parent.mkdir(parents=True, exist_ok=True)

        with zipf.open(member) as src, open(final_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

        extracted += 1

    return extracted


def _prepare_restore_source(
    backup_path: Path,
    work_dir: Path,
) -> tuple[Path, Path | None, Path | None]:
    """
    Returns:
      - sqlite database path to restore
      - optional attachments directory extracted from full backup
      - optional encryption key extracted from full backup
    """
    suffix = backup_path.suffix.lower()

    if suffix in {".sqlite", ".db"}:
        _validate_sqlite_backup(backup_path)
        return backup_path, None, None

    if suffix != ".zip":
        raise ValueError("Unsupported backup format. Expected .zip, .sqlite or .db")

    if not zipfile.is_zipfile(backup_path):
        raise ValueError("Invalid zip backup file")

    extracted_db = work_dir / "database.db"
    extracted_attachments = work_dir / "attachments"
    extracted_encryption_key = work_dir / "vodum.encryption_key"

    with zipfile.ZipFile(backup_path, "r") as zipf:
        validate_zip_limits(zipf)
        names = set(zipf.namelist())

        db_member = None
        for candidate in ("database.db", "database.sqlite"):
            if candidate in names:
                db_member = candidate
                break

        if not db_member:
            raise ValueError("Invalid VODUM full backup: database.db is missing")

        _safe_extract_zip_member(zipf, db_member, extracted_db)

        if "vodum.encryption_key" in names:
            _safe_extract_zip_member(
                zipf,
                "vodum.encryption_key",
                extracted_encryption_key,
            )

        if any(name.startswith("attachments/") for name in names):
            _safe_extract_zip_dir(zipf, "attachments", extracted_attachments)

    _validate_sqlite_backup(extracted_db)
    if extracted_encryption_key.exists():
        validate_encryption_key(
            extracted_encryption_key.read_bytes(),
            check_environment=True,
        )
    return (
        extracted_db,
        extracted_attachments if extracted_attachments.exists() else None,
        extracted_encryption_key if extracted_encryption_key.exists() else None,
    )


def _replace_directory(source_dir: Path | None, target_dir: Path) -> None:
    if source_dir is None:
        return

    tmp_target = target_dir.with_name(target_dir.name + ".restore_tmp")
    previous_target = target_dir.with_name(target_dir.name + ".pre_restore")

    if tmp_target.exists():
        shutil.rmtree(tmp_target, ignore_errors=True)

    if previous_target.exists():
        shutil.rmtree(previous_target, ignore_errors=True)

    shutil.copytree(source_dir, tmp_target)

    if target_dir.exists():
        target_dir.rename(previous_target)

    tmp_target.rename(target_dir)

    if previous_target.exists():
        shutil.rmtree(previous_target, ignore_errors=True)


def _safe_restore_from_path(backup_path: Path, db) -> None:
    db_path = Path(Config.DATABASE)
    appdata_dir = db_path.parent
    backup_path = Path(backup_path)

    if not backup_path.exists():
        raise FileNotFoundError(str(backup_path))

    work_dir = appdata_dir / "imports" / f"restore_work_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        (
            restore_db_path,
            restore_attachments_dir,
            restore_encryption_key_path,
        ) = _prepare_restore_source(backup_path, work_dir)

        pre_restore_path = db_path.with_suffix(db_path.suffix + ".pre_restore")
        encryption_key_path = encryption_key_file_path()
        pre_restore_key_path = encryption_key_path.with_name(
            encryption_key_path.name + ".pre_restore"
        )
        encryption_key_existed = encryption_key_path.exists()
        if pre_restore_path.exists():
            try:
                pre_restore_path.unlink()
            except Exception:
                pass

        if db_path.exists():
            shutil.copy2(str(db_path), str(pre_restore_path))

        if pre_restore_key_path.exists():
            pre_restore_key_path.unlink()
        if encryption_key_path.exists():
            pre_restore_key_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(encryption_key_path), str(pre_restore_key_path))

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

        shutil.copy2(str(restore_db_path), str(tmp_path))
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
            if restore_encryption_key_path is not None:
                install_encryption_key(restore_encryption_key_path.read_bytes())
            else:
                log.warning(
                    "Restore source contains no encryption key; existing key is kept"
                )

            if restore_attachments_dir is not None:
                _replace_directory(restore_attachments_dir, appdata_dir / "attachments")

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

                if pre_restore_key_path.exists():
                    install_encryption_key(pre_restore_key_path.read_bytes())
                elif not encryption_key_existed and encryption_key_path.exists():
                    encryption_key_path.unlink()
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

            if pre_restore_key_path.exists():
                try:
                    pre_restore_key_path.unlink()
                except Exception:
                    pass

    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    def _delayed_exit():
        time.sleep(1.5)
        os._exit(0)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    log.warning("Backup restored. Maintenance mode ON. Process will exit for restart.")


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
        log.warning("Unable to remove processed restore request marker", exc_info=True)

    _safe_restore_from_path(backup_path, db)

    task_logs(task_id, "success", f"restore_backup completed from {backup_path}")
    return {"status": "success", "backup_path": str(backup_path)}
