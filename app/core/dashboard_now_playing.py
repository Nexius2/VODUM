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
        WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
        ORDER BY datetime(ms.last_seen_at) DESC
        LIMIT ?
        """,
        (window_sql, int(limit)),
    ) or []
    return [dict(row) for row in rows]


def load_dashboard_now_playing(db, *, live_window_seconds: int = 300) -> dict:
    live_window_sql = f"-{int(live_window_seconds)} seconds"
    sessions = _sessions(db, live_window_sql)
    stale_fallback = False

    # The task engine is deliberately sequential. A long-running task can delay
    # collection without ending playback, so retain unconfirmed DB sessions for
    # a bounded period while the queue is genuinely busy.
    if not sessions and _task_queue_busy(db):
        sessions = _sessions(db, "-30 minutes")
        stale_fallback = bool(sessions)

    total_live = len(sessions)
    total_transcode = sum(int(row.get("is_transcode") or 0) for row in sessions)
    return {
        "sessions": sessions,
        "total_live": total_live,
        "total_transcode": total_transcode,
        "stale_fallback": stale_fallback,
    }
