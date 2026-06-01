#!/usr/bin/env python3
"""
cleanup_artwork_cache.py
- Nettoie le cache disque des posters/backdrops monitoring.
- Supprime les fichiers .img/.json plus vieux que la rétention définie.
- Supprime aussi les fichiers orphelins quand le binôme .img/.json n'existe plus.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

from tasks_engine import task_logs
from logging_utils import get_logger, is_debug_mode_enabled

log = get_logger("cleanup_artwork_cache")

ARTWORK_DISK_CACHE_DIR = os.environ.get("VODUM_ARTWORK_CACHE_DIR", "/appdata/artwork_cache")
ARTWORK_CACHE_RETENTION_DAYS = int(os.environ.get("VODUM_ARTWORK_CACHE_RETENTION_DAYS", "30"))


def _safe_retention_days(value) -> int:
    try:
        value = int(value)
        if value < 1:
            return 30
        return value
    except Exception:
        return 30


def _is_cache_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".img", ".json", ".tmp"}


def _counterpart_exists(path: Path) -> bool:
    if path.suffix.lower() == ".img":
        return path.with_suffix(".json").exists()
    if path.suffix.lower() == ".json":
        return path.with_suffix(".img").exists()
    return True


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_artwork_cache started")
    log.info("=== CLEANUP ARTWORK CACHE : STARTING ===")

    base = Path(ARTWORK_DISK_CACHE_DIR)

    if not base.exists():
        msg = f"Artwork cache directory not found: {base} (no action performed)."
        log.info(msg)
        task_logs(task_id, "info", msg)
        return {"scanned": 0, "deleted": 0, "retention_days": _safe_retention_days(ARTWORK_CACHE_RETENTION_DAYS)}

    retention_days = _safe_retention_days(ARTWORK_CACHE_RETENTION_DAYS)
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    cutoff_ts = cutoff.timestamp()

    scanned = 0
    deleted = 0
    errors = 0

    if is_debug_mode_enabled():
        log.debug(f"Artwork cache retention = {retention_days} days -> cutoff UTC = {cutoff}")
        log.debug(f"Artwork cache directory = {base}")

    for path in base.iterdir():
        if not _is_cache_file(path):
            continue

        scanned += 1

        try:
            stat = path.stat()
            too_old = stat.st_mtime < cutoff_ts
            orphan = path.suffix.lower() in {".img", ".json"} and not _counterpart_exists(path)
            tmp_file = path.suffix.lower() == ".tmp"

            if too_old or orphan or tmp_file:
                path.unlink()
                deleted += 1

        except Exception as e:
            errors += 1
            log.warning(f"Unable to process artwork cache file {path}: {e}", exc_info=True)

    msg = f"{deleted} artwork cache file(s) deleted (scanned {scanned}) — retention {retention_days} days."
    if errors:
        msg += f" Errors: {errors}."

    log.info(msg)
    task_logs(task_id, "success" if errors == 0 else "warning", msg)
    log.info("=== CLEANUP ARTWORK CACHE : FINISHED ===")

    return {
        "scanned": scanned,
        "deleted": deleted,
        "errors": errors,
        "retention_days": retention_days,
    }