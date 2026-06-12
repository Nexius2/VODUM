def get_live_session_stats(db, live_window_seconds=300, fallback_max_age_seconds=600):
    """
    Return current live totals, with a short-lived snapshot fallback while the
    monitoring pipeline is busy.

    The fallback is deliberately disabled when the pipeline is idle so a stale
    snapshot cannot make ended sessions appear live indefinitely.
    """
    live_window_sql = f"-{int(live_window_seconds)} seconds"
    current = db.query_one(
        """
        SELECT
          COUNT(*) AS live_sessions,
          COALESCE(SUM(CASE WHEN is_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
        FROM media_sessions
        WHERE datetime(last_seen_at) >= datetime('now', ?)
        """,
        (live_window_sql,),
    )

    live_sessions = int(current["live_sessions"] or 0) if current else 0
    transcodes = int(current["transcodes"] or 0) if current else 0
    result = {
        "live_sessions": live_sessions,
        "transcodes": transcodes,
        "direct_plays": max(0, live_sessions - transcodes),
        "is_snapshot_fallback": False,
        "snapshot_ts": None,
    }

    if live_sessions > 0:
        return result

    pipeline_busy = db.query_one(
        """
        SELECT 1
        WHERE EXISTS (
          SELECT 1
          FROM tasks
          WHERE name IN ('monitor_enqueue_refresh', 'media_jobs_worker')
            AND (status = 'running' OR COALESCE(queued_count, 0) > 0)
        )
        OR EXISTS (
          SELECT 1
          FROM media_jobs
          WHERE action = 'refresh'
            AND status IN ('queued', 'running')
        )
        LIMIT 1
        """
    )
    if not pipeline_busy:
        return result

    snapshot = db.query_one(
        """
        SELECT ts, live_sessions, transcodes
        FROM monitoring_snapshots
        WHERE datetime(ts) >= datetime('now', ?)
          AND live_sessions > 0
        ORDER BY datetime(ts) DESC, id DESC
        LIMIT 1
        """,
        (f"-{int(fallback_max_age_seconds)} seconds",),
    )
    if not snapshot:
        return result

    live_sessions = int(snapshot["live_sessions"] or 0)
    transcodes = int(snapshot["transcodes"] or 0)
    return {
        "live_sessions": live_sessions,
        "transcodes": transcodes,
        "direct_plays": max(0, live_sessions - transcodes),
        "is_snapshot_fallback": True,
        "snapshot_ts": snapshot["ts"],
    }
