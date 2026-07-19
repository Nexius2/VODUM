from __future__ import annotations

from core.monitoring.resource_stats import (
    apply_server_resource_stats,
    load_server_resource_stats,
)


EMPTY_SERVER_STATS = {"online": 0, "offline": 0, "total": 0}


def load_monitoring_server_context(db, tab):
    servers = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT id, name, LOWER(TRIM(type)) AS type, url, local_url,
                       public_url, token, status, last_checked
                FROM servers
                WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
                ORDER BY LOWER(TRIM(type)), name
                """
            )
            or []
        )
    ]
    resource_stats = {}
    if tab in {"overview", "now_playing", "servers"}:
        resource_stats = load_server_resource_stats(
            db,
            [server.get("id") for server in servers],
            max_age_seconds=600,
        )
    stats_row = db.query_one(
        """
        SELECT
          SUM(
            CASE WHEN LOWER(TRIM(COALESCE(status, 'unknown'))) = 'up'
              THEN 1 ELSE 0 END
          ) AS online,
          SUM(
            CASE WHEN LOWER(TRIM(COALESCE(status, 'unknown'))) = 'down'
              THEN 1 ELSE 0 END
          ) AS offline,
          COUNT(*) AS total
        FROM servers
        WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
        """
    )
    return {
        "servers": servers,
        "configured_server_count": len(servers),
        "server_resource_stats": resource_stats,
        "server_stats": dict(stats_row) if stats_row else dict(EMPTY_SERVER_STATS),
    }


def load_monitoring_servers_tab(
    db,
    args,
    live_window_sql,
    server_resource_stats,
):
    server_range = args.get("range", "7d")
    # Range filter.
    # Les stats historiques utilisent media_session_history.
    # Les sessions live utilisent media_sessions et rejoignent les memes agregats.
    if server_range == "all":
        where_hist = "1=1"
        params_hist = ()
    else:
        delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(server_range, "-7 days")
        where_hist = "datetime(stopped_at) >= datetime('now', ?)"
        params_hist = (delta,)

    source_cte = f"""
        source AS (
          SELECT
            server_id,
            media_user_id,
            external_user_id,
            session_key,
            media_key,
            media_type,
            title,
            grandparent_title,
            parent_title,
            started_at,
            stopped_at,
            MIN(
              COALESCE(watch_ms, 0),
              CASE
                WHEN COALESCE(duration_ms, 0) > 0 THEN duration_ms
                ELSE COALESCE(watch_ms, 0)
              END
            ) AS watch_ms,
            was_transcode,
            peak_bitrate,
            ip,
            client_product,
            device,
            library_section_id
          FROM media_session_history
          WHERE {where_hist}

          UNION ALL

          SELECT
            server_id,
            media_user_id,
            external_user_id,
            session_key,
            media_key,
            media_type,
            title,
            grandparent_title,
            parent_title,
            COALESCE(started_at, last_seen_at, CURRENT_TIMESTAMP) AS started_at,
            CURRENT_TIMESTAMP AS stopped_at,
            CASE
              WHEN started_at IS NOT NULL AND COALESCE(duration_ms, 0) > 0 THEN
                MIN(
                  COALESCE(duration_ms, 0),
                  MAX(0, CAST((julianday('now') - julianday(started_at)) * 86400000 AS INTEGER))
                )
              WHEN started_at IS NOT NULL THEN
                MAX(0, CAST((julianday('now') - julianday(started_at)) * 86400000 AS INTEGER))
              ELSE 0
            END AS watch_ms,
            is_transcode AS was_transcode,
            bitrate AS peak_bitrate,
            ip,
            client_product,
            device,
            library_section_id
          FROM media_sessions
          WHERE datetime(last_seen_at) >= datetime('now', ?)
        ),
        plays AS (
          SELECT
            (CAST(server_id AS TEXT) || '|' ||
             COALESCE(CAST(media_user_id AS TEXT), external_user_id, 'unknown_user') || '|' ||
             COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
             strftime('%Y-%m-%d %H:%M', started_at)
            ) AS play_key,

            MAX(server_id) AS server_id,
            MAX(media_user_id) AS media_user_id,
            MAX(external_user_id) AS external_user_id,
            MAX(session_key) AS session_key,
            MAX(media_key) AS media_key,
            MAX(media_type) AS media_type,
            MAX(title) AS title,
            MAX(grandparent_title) AS grandparent_title,
            MAX(parent_title) AS parent_title,
            MIN(started_at) AS started_at,
            MAX(stopped_at) AS stopped_at,
            MAX(COALESCE(watch_ms, 0)) AS watch_ms,
            MAX(COALESCE(was_transcode, 0)) AS was_transcode,
            MAX(COALESCE(peak_bitrate, 0)) AS peak_bitrate,
            MAX(ip) AS ip,
            MAX(client_product) AS client_product,
            MAX(device) AS device,
            MAX(library_section_id) AS library_section_id
          FROM source
          GROUP BY play_key
        )
    """

    params_source = tuple(params_hist) + (live_window_sql,)

    servers_combined = db.query_one(
        f"""
        WITH {source_cte}
        SELECT
          COUNT(*) AS sessions,
          COUNT(DISTINCT COALESCE(CAST(media_user_id AS TEXT), external_user_id)) AS active_users,
          COALESCE(SUM(watch_ms), 0) AS watch_ms,
          COALESCE(SUM(CASE WHEN was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes,
          AVG(NULLIF(peak_bitrate, 0)) AS avg_peak_bitrate,
          MAX(peak_bitrate) AS max_peak_bitrate,
          COUNT(DISTINCT NULLIF(TRIM(ip), '')) AS unique_ips
        FROM plays
        """,
        params_source,
    ) or {}
    servers_combined = dict(servers_combined)

    servers_details = db.query(
        f"""
        WITH {source_cte},
        live AS (
          SELECT server_id, is_transcode
          FROM media_sessions
          WHERE datetime(last_seen_at) >= datetime('now', ?)
        )
        SELECT
          s.id AS server_id,
          s.name,
          LOWER(TRIM(s.type)) AS type,
          LOWER(TRIM(COALESCE(s.status, 'unknown'))) AS status,
          s.last_checked,

          (SELECT COUNT(*) FROM libraries l WHERE l.server_id = s.id) AS libraries,
          (SELECT COUNT(*) FROM media_users mu WHERE mu.server_id = s.id) AS users,

          (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id) AS live_sessions,
          (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id AND x.is_transcode = 1) AS live_transcodes,
          (SELECT COUNT(*) FROM live x WHERE x.server_id = s.id AND COALESCE(x.is_transcode, 0) = 0) AS live_direct_plays,

          (SELECT COUNT(*) FROM plays h WHERE h.server_id = s.id) AS sessions,
          (SELECT COUNT(DISTINCT COALESCE(CAST(h.media_user_id AS TEXT), h.external_user_id)) FROM plays h WHERE h.server_id = s.id) AS active_users,
          (SELECT COALESCE(SUM(h.watch_ms), 0) FROM plays h WHERE h.server_id = s.id) AS watch_ms,
          (SELECT COALESCE(SUM(CASE WHEN h.was_transcode = 1 THEN 1 ELSE 0 END), 0) FROM plays h WHERE h.server_id = s.id) AS transcodes,
          (SELECT AVG(NULLIF(h.peak_bitrate, 0)) FROM plays h WHERE h.server_id = s.id) AS avg_peak_bitrate,
          (SELECT MAX(h.peak_bitrate) FROM plays h WHERE h.server_id = s.id) AS max_peak_bitrate,
          (SELECT COUNT(DISTINCT NULLIF(TRIM(h.ip), '')) FROM plays h WHERE h.server_id = s.id) AS unique_ips

        FROM servers s
        WHERE LOWER(TRIM(s.type)) IN ('plex','jellyfin')
        ORDER BY LOWER(TRIM(s.type)), s.name
        """,
        params_source + (live_window_sql,),
    )
    servers_details = [dict(r) for r in servers_details]
    apply_server_resource_stats(servers_details, server_resource_stats)

    servers_sessions_day = db.query(
        f"""
        WITH {source_cte}
        SELECT
          date(stopped_at) AS day,
          server_id,
          COUNT(*) AS sessions
        FROM plays
        GROUP BY day, server_id
        ORDER BY day ASC
        """,
        params_source,
    )
    servers_sessions_day = [dict(r) for r in servers_sessions_day]

    servers_media_types = db.query(
        f"""
        WITH {source_cte},
        typed AS (
          SELECT
            server_id,
            CASE
              WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 'serie'
              WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'serie'
              WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 'movie'
              WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
              WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
              ELSE 'other'
            END AS media_type,
            watch_ms
          FROM plays
        )
        SELECT
          server_id,
          media_type,
          COUNT(*) AS sessions,
          COALESCE(SUM(watch_ms), 0) AS watch_ms
        FROM typed
        GROUP BY server_id, media_type
        ORDER BY server_id, sessions DESC
        """,
        params_source,
    )
    servers_media_types = [dict(r) for r in servers_media_types]

    servers_clients = db.query(
        f"""
        WITH {source_cte}
        SELECT
          p.server_id,
          s.name AS server_name,
          COALESCE(NULLIF(TRIM(p.client_product), ''), NULLIF(TRIM(p.device), ''), 'unknown') AS client,
          COUNT(*) AS sessions,
          COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
          COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
        FROM plays p
        JOIN servers s ON s.id = p.server_id
        GROUP BY p.server_id, s.name, client
        ORDER BY sessions DESC
        LIMIT 200
        """,
        params_source,
    )
    servers_clients = [dict(r) for r in servers_clients]

    servers_top_users = db.query(
        f"""
        WITH {source_cte}
        SELECT
          p.server_id,
          s.name AS server_name,
          p.media_user_id,
          COALESCE(mu.username, mu.email, p.external_user_id, 'Unknown user') AS user_label,
          COUNT(*) AS sessions,
          COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
          COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
        FROM plays p
        JOIN servers s ON s.id = p.server_id
        LEFT JOIN media_users mu ON mu.id = p.media_user_id
        GROUP BY p.server_id, s.name, p.media_user_id, p.external_user_id, user_label
        ORDER BY watch_ms DESC
        LIMIT 200
        """,
        params_source,
    )
    servers_top_users = [dict(r) for r in servers_top_users]

    servers_top_titles = db.query(
        f"""
        WITH {source_cte}
        SELECT
          p.server_id,
          s.name AS server_name,
          TRIM(
            COALESCE(NULLIF(TRIM(p.grandparent_title), '') || ' - ', '') ||
            COALESCE(NULLIF(TRIM(p.parent_title), '') || ' - ', '') ||
            COALESCE(NULLIF(TRIM(p.title), ''), 'Unknown')
          ) AS full_title,
          COUNT(*) AS sessions,
          COALESCE(SUM(p.watch_ms), 0) AS watch_ms,
          COALESCE(SUM(CASE WHEN p.was_transcode = 1 THEN 1 ELSE 0 END), 0) AS transcodes
        FROM plays p
        JOIN servers s ON s.id = p.server_id
        GROUP BY p.server_id, s.name, full_title
        ORDER BY watch_ms DESC
        LIMIT 200
        """,
        params_source,
    )
    servers_top_titles = [dict(r) for r in servers_top_titles]

    servers_unique_ips = db.query(
        f"""
        WITH {source_cte}
        SELECT
          p.server_id,
          s.name AS server_name,
          COALESCE(NULLIF(TRIM(p.ip), ''), 'unknown') AS ip,
          COUNT(*) AS sessions,
          COALESCE(SUM(p.watch_ms), 0) AS watch_ms
        FROM plays p
        JOIN servers s ON s.id = p.server_id
        GROUP BY p.server_id, s.name, ip
        ORDER BY sessions DESC
        LIMIT 200
        """,
        params_source,
    )
    servers_unique_ips = [dict(r) for r in servers_unique_ips]
    return {
        "server_range": server_range,
        "servers_combined": servers_combined,
        "servers_details": servers_details,
        "servers_sessions_day": servers_sessions_day,
        "servers_media_types": servers_media_types,
        "servers_clients": servers_clients,
        "servers_top_users": servers_top_users,
        "servers_top_titles": servers_top_titles,
        "servers_unique_ips": servers_unique_ips,
    }
