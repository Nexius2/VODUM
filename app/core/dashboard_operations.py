"""Small, action-oriented operational summary for the dashboard."""

from __future__ import annotations


def _count(db, sql, params=()):
    row = db.query_one(sql, params)
    return int((row["cnt"] if row else 0) or 0)


def build_operations_summary(db, table_exists) -> dict:
    servers = {"total": 0, "online": 0, "offline": 0, "stale": 0}
    if table_exists(db, "servers"):
        row = db.query_one(
            """
            SELECT COUNT(*) AS total,
              SUM(CASE WHEN LOWER(TRIM(COALESCE(status,''))) IN ('up','online') THEN 1 ELSE 0 END) AS online,
              SUM(CASE WHEN LOWER(TRIM(COALESCE(status,''))) IN ('down','offline') THEN 1 ELSE 0 END) AS offline,
              SUM(CASE WHEN last_checked IS NULL OR datetime(last_checked) < datetime('now','-20 minutes') THEN 1 ELSE 0 END) AS stale
            FROM servers
            """
        )
        if row:
            servers = {key: int(row[key] or 0) for key in servers}

    tasks = {"running": 0, "queued": 0, "errors": 0, "disabled": 0}
    recent_errors = []
    if table_exists(db, "tasks"):
        row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
              SUM(CASE WHEN COALESCE(queued_count,0)>0 OR status='queued' THEN 1 ELSE 0 END) AS queued,
              SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
              SUM(CASE WHEN COALESCE(enabled,0)=0 THEN 1 ELSE 0 END) AS disabled
            FROM tasks
            """
        )
        if row:
            tasks = {key: int(row[key] or 0) for key in tasks}
        recent_errors = [dict(row) for row in (db.query(
            """SELECT name,last_error,COALESCE(last_attempt_at,last_run,updated_at) AS occurred_at
               FROM tasks WHERE status='error'
               ORDER BY datetime(COALESCE(last_attempt_at,last_run,updated_at)) DESC LIMIT 3"""
        ) or [])]

    jobs = {"queued": 0, "running": 0, "errors": 0}
    if table_exists(db, "media_jobs"):
        row = db.query_one(
            """SELECT
              SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued,
              SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
              SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
              FROM media_jobs"""
        )
        if row:
            jobs = {key: int(row[key] or 0) for key in jobs}

    if servers["offline"] or tasks["errors"] or jobs["errors"]:
        level = "critical"
    elif servers["stale"] or tasks["queued"] >= 10 or jobs["queued"] >= 25:
        level = "warning"
    else:
        level = "healthy"

    return {"level": level, "servers": servers, "tasks": tasks, "jobs": jobs, "recent_errors": recent_errors}
