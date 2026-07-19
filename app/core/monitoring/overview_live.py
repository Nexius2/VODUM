from __future__ import annotations

from core.monitoring.resource_stats import apply_server_resource_stats
from core.monitoring.snapshots import get_live_session_stats


LIVE_SESSION_COLUMNS = """
    ms.id, ms.server_id, ms.provider, ms.session_key, ms.media_user_id,
    ms.external_user_id, ms.media_key, ms.media_type, ms.title,
    ms.grandparent_title, ms.parent_title, ms.state, ms.progress_ms,
    ms.duration_ms, ms.is_transcode, ms.bitrate, ms.video_codec,
    ms.audio_codec, ms.client_name, ms.client_product, ms.device, ms.ip,
    ms.started_at, ms.last_seen_at, ms.raw_json, ms.poster_ref_json,
    ms.backdrop_ref_json, ms.library_section_id, ms.missing_count
""".strip()


def _enrich_live_session_artwork(session, db):
    from core.monitoring.artwork import enrich_live_session_artwork

    return enrich_live_session_artwork(session, db)


def _format_duration(milliseconds) -> str:
    try:
        milliseconds = max(0, int(milliseconds or 0))
    except (TypeError, ValueError):
        milliseconds = 0
    total_seconds = milliseconds // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}"
        if hours > 0
        else f"{minutes}:{seconds:02d}"
    )


def _apply_progress(session):
    try:
        progress = max(0, int(session.get("progress_ms") or 0))
    except (TypeError, ValueError):
        progress = 0
    try:
        duration = max(0, int(session.get("duration_ms") or 0))
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        session["progress_pct"] = 0
        session["progress_text"] = None
        session["remaining_text"] = None
        return
    session["progress_pct"] = round(
        min(100.0, max(0.0, progress / duration * 100.0)),
        1,
    )
    session["progress_text"] = (
        f"{_format_duration(progress)} / {_format_duration(duration)}"
    )
    session["remaining_text"] = _format_duration(max(0, duration - progress))


def load_monitoring_live_context(
    db,
    tab,
    server_resource_stats,
    *,
    live_window_seconds=300,
):
    empty = {
        "sessions_stats": {
            "live_sessions": 0,
            "transcodes": 0,
            "direct_plays": 0,
        },
        "live_servers": [],
        "sessions": [],
    }
    if tab not in {"overview", "now_playing"}:
        return empty

    live_window_sql = f"-{int(live_window_seconds)} seconds"
    sessions_stats = get_live_session_stats(
        db,
        live_window_seconds=live_window_seconds,
        fallback_max_age_seconds=600,
    )
    live_servers = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT ms.server_id, s.name AS server_name,
                  COUNT(*) AS live_sessions,
                  SUM(
                    CASE WHEN ms.is_transcode = 1 THEN 1 ELSE 0 END
                  ) AS transcodes
                FROM media_sessions ms
                JOIN servers s ON s.id = ms.server_id
                WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
                  AND datetime(ms.last_seen_at) >= datetime('now', ?)
                GROUP BY ms.server_id, s.name
                HAVING COUNT(*) > 0
                ORDER BY transcodes DESC, live_sessions DESC, s.name ASC
                LIMIT 6
                """,
                (live_window_sql,),
            )
            or []
        )
    ]
    for row in live_servers:
        row["live_sessions"] = int(row.get("live_sessions") or 0)
        row["transcodes"] = int(row.get("transcodes") or 0)
        row["direct_plays"] = max(
            0,
            row["live_sessions"] - row["transcodes"],
        )
    apply_server_resource_stats(live_servers, server_resource_stats)

    sessions = [
        dict(row)
        for row in (
            db.query(
                f"""
                SELECT {LIVE_SESSION_COLUMNS},
                  s.name AS server_name,
                  s.type AS provider,
                  mu.username AS username
                FROM media_sessions ms
                JOIN servers s ON s.id = ms.server_id
                LEFT JOIN media_users mu ON mu.id = ms.media_user_id
                WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
                ORDER BY datetime(ms.last_seen_at) DESC
                """,
                (live_window_sql,),
            )
            or []
        )
    ]
    apply_server_resource_stats(sessions, server_resource_stats)
    for session in sessions:
        _apply_progress(session)
        session.update(_enrich_live_session_artwork(session, db))
    return {
        "sessions_stats": sessions_stats,
        "live_servers": live_servers,
        "sessions": sessions,
    }
