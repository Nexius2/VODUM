#!/usr/bin/env python3
"""
cleanup_data_retention.py
- Purge des données d'historique selon settings.data_retention_years
- 0 = illimité (aucune suppression)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("cleanup_data_retention")


def _row_value(row, key, default=None):
    if not row:
        return default
    try:
        return row[key]  # sqlite3.Row
    except Exception:
        try:
            return row.get(key)  # dict
        except Exception:
            return default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def run(task_id: int, db):
    task_logs(task_id, "info", "Task cleanup_data_retention started")
    log.info("=== CLEANUP DATA RETENTION : START ===")

    row = None
    try:
        row = db.query_one("SELECT data_retention_years FROM settings LIMIT 1")
    except Exception as e:
        log.error(f"Cannot read settings.data_retention_years: {e}")

    years = _safe_int(_row_value(row, "data_retention_years", 0), 0)

    if years <= 0:
        msg = "data_retention_years=0 (unlimited) -> nothing to delete"
        task_logs(task_id, "info", msg)
        log.info(msg)
        return

    # Approximation : 1 an = 365 jours (rétention 'grossière' et prévisible)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=years * 365)
    cutoff_iso = cutoff_dt.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_epoch = int(cutoff_dt.timestamp())

    task_logs(task_id, "info", f"Retention={years}y -> cutoff={cutoff_iso} (UTC)")
    log.info(f"Retention={years}y -> cutoff={cutoff_iso} (UTC)")

    total_deleted = 0

    def _del(sql: str, params: tuple, label: str):
        nonlocal total_deleted
        cur = db.execute(sql, params)
        deleted = getattr(cur, "rowcount", 0) or 0
        total_deleted += deleted
        task_logs(task_id, "info", f"{label}: deleted={deleted}")
        log.info(f"{label}: deleted={deleted}")

    # -------------------------------------------------
    # Purges (historiques uniquement)
    # -------------------------------------------------
    _del("DELETE FROM sent_emails WHERE sent_at < ?", (cutoff_iso,), "sent_emails")
    _del("DELETE FROM sent_discord WHERE sent_at IS NOT NULL AND sent_at < ?", (cutoff_epoch,), "sent_discord")
    _del("DELETE FROM media_session_history WHERE stopped_at < ?", (cutoff_iso,), "media_session_history")
    _del("DELETE FROM media_events WHERE ts < ?", (cutoff_iso,), "media_events")
    _del("DELETE FROM media_jobs WHERE created_at < ?", (cutoff_iso,), "media_jobs")
    _del("DELETE FROM tautulli_import_jobs WHERE created_at < ?", (cutoff_iso,), "tautulli_import_jobs")

    task_logs(task_id, "success", f"Cleanup finished. total_deleted={total_deleted}")
    log.info(f"=== CLEANUP DATA RETENTION : DONE (total_deleted={total_deleted}) ===")
