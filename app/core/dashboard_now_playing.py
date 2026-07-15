"""Reliable dashboard preview for live media sessions."""

from web.helpers import table_exists


def _task_queue_busy(db) -> bool:
    if not table_exists(db, "tasks"):
        return False

    row = db.query_one(
        """
        SELECT COUNT(*) AS total
        FROM tasks
        WHERE status IN ('running', 'queued')
           OR COALESCE(queued_count, 0) > 0
        """
    )
    return int(row["total"] or 0) > 0 if row else False


def _totals(db, window_sql: str) -> dict:
    row = db.query_one(
        """
        SELECT
          COUNT(*) AS total_live,
          COALESCE(SUM(CASE WHEN ms.is_transcode = 1 THEN 1 ELSE 0 END), 0) AS total_transcode
        FROM media_sessions ms
        JOIN servers s ON s.id = ms.server_id
        WHERE LOWER(TRIM(s.type)) IN ('plex', 'jellyfin')
          AND datetime(ms.last_seen_at) >= datetime('now', ?)
          AND COALESCE(ms.missing_count, 0) = 0
        """,
        (window_sql,),
    )

    return {
        "total_live": int(row["total_live"] or 0) if row else 0,
        "total_transcode": int(row["total_transcode"] or 0) if row else 0,
    }


def _sessions(db, window_sql: str, limit: int = 6) -> list[dict]:
    rows = db.query(
        """
        SELECT
          ms.id,
          ms.server_id,
          ms.provider,
          ms.session_key,
          ms.media_user_id,
          ms.external_user_id,
          ms.media_key,
          ms.media_type,
          ms.title,
          ms.grandparent_title,
          ms.parent_title,
          ms.state,
          ms.progress_ms,
          ms.duration_ms,
          ms.is_transcode,
          ms.bitrate,
          ms.video_codec,
          ms.audio_codec,
          ms.client_name,
          ms.client_product,
          ms.device,
          ms.ip,
          ms.started_at,
          ms.last_seen_at,
          ms.raw_json,
          ms.poster_ref_json,
          ms.backdrop_ref_json,
          ms.library_section_id,
          ms.missing_count,
          s.name AS server_name,
          s.type AS provider,
          mu.username AS username
        FROM media_sessions ms
        JOIN servers s ON s.id = ms.server_id
        LEFT JOIN media_users mu ON mu.id = ms.media_user_id
        WHERE LOWER(TRIM(s.type)) IN ('plex', 'jellyfin')
          AND datetime(ms.last_seen_at) >= datetime('now', ?)
          AND COALESCE(ms.missing_count, 0) = 0
        ORDER BY
          datetime(COALESCE(ms.started_at, '1970-01-01')) DESC,
          ms.id ASC
        LIMIT ?
        """,
        (window_sql, int(limit)),
    ) or []
    return [dict(row) for row in rows]


def load_dashboard_now_playing(db, *, live_window_seconds: int = 300) -> dict:
    live_window_sql = f"-{int(live_window_seconds)} seconds"

    sessions = _sessions(db, live_window_sql, limit=6)
    totals = _totals(db, live_window_sql)
    stale_fallback = False

    # The task engine is deliberately sequential. A long-running task can delay
    # collection without ending playback, so retain unconfirmed DB sessions for
    # a bounded period while the queue is genuinely busy.
    if totals["total_live"] <= 0 and _task_queue_busy(db):
        fallback_window_sql = "-30 minutes"
        sessions = _sessions(db, fallback_window_sql, limit=6)
        totals = _totals(db, fallback_window_sql)
        stale_fallback = totals["total_live"] > 0

    return {
        "sessions": sessions,
        "total_live": totals["total_live"],
        "total_transcode": totals["total_transcode"],
        "stale_fallback": stale_fallback,
    }
