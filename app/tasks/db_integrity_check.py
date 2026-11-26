#!/usr/bin/env python3
"""
db_integrity_check.py
- Vérifie régulièrement l'intégrité SQLite.
- Lance PRAGMA quick_check.
- Lance PRAGMA foreign_key_check.
- Optionnel : PRAGMA integrity_check complet avec VODUM_DB_INTEGRITY_FULL=1.
"""

import os

from tasks_engine import task_logs
from logging_utils import get_logger, is_debug_mode_enabled

log = get_logger("db_integrity_check")


def _row_first_value(row, default=None):
    if row is None:
        return default
    try:
        return row[0]
    except Exception:
        try:
            return next(iter(dict(row).values()))
        except Exception:
            return default


def _full_check_enabled() -> bool:
    return str(os.environ.get("VODUM_DB_INTEGRITY_FULL", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run(task_id: int, db):
    task_logs(task_id, "info", "Task db_integrity_check started")
    log.info("=== DB INTEGRITY CHECK : STARTING ===")

    quick_row = db.query_one("PRAGMA quick_check;")
    quick_result = _row_first_value(quick_row, "unknown")

    if quick_result != "ok":
        msg = f"SQLite quick_check failed: {quick_result}"
        log.error(msg)
        task_logs(task_id, "error", msg)
        raise RuntimeError(msg)

    foreign_rows = db.query("PRAGMA foreign_key_check;")
    foreign_errors = len(foreign_rows or [])

    if foreign_errors:
        sample = []
        for row in foreign_rows[:5]:
            try:
                sample.append(dict(row))
            except Exception:
                sample.append(str(row))

        msg = f"SQLite foreign_key_check found {foreign_errors} issue(s)."
        log.error(f"{msg} Sample: {sample}")
        task_logs(task_id, "error", msg, details={"sample": sample})
        raise RuntimeError(msg)

    full_result = None
    if _full_check_enabled():
        task_logs(task_id, "info", "Full SQLite integrity_check enabled")
        integrity_row = db.query_one("PRAGMA integrity_check;")
        full_result = _row_first_value(integrity_row, "unknown")

        if full_result != "ok":
            msg = f"SQLite integrity_check failed: {full_result}"
            log.error(msg)
            task_logs(task_id, "error", msg)
            raise RuntimeError(msg)

    msg = "Database integrity check passed."
    if full_result:
        msg += " Full integrity_check passed."

    if is_debug_mode_enabled():
        log.debug(f"quick_check={quick_result}, foreign_key_errors={foreign_errors}, full_check={full_result}")

    task_logs(task_id, "success", msg)
    log.info(msg)
    log.info("=== DB INTEGRITY CHECK : FINISHED ===")

    return {
        "quick_check": quick_result,
        "foreign_key_errors": foreign_errors,
        "full_integrity_check": full_result,
    }