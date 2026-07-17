"""Cached read-only aggregates for the Monitoring overview."""

from core.aggregate_cache import cached_aggregate, cached_query_rows
from core.monitoring.artwork import build_history_backdrop_url, build_history_poster_url
from core.monitoring.daily_stats import load_materialized_window

def build_monitoring_overview_aggregates(db, sessions_stats):
    stats_7d = {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
    top_users_30d = []
    top_content_30d = []
    top_movies_30d = []
    concurrent_7d = {"peak_streams": 0}

    
    materialized_7d = cached_aggregate(
        "monitoring:overview:materialized-7d", 120,
        lambda: load_materialized_window(db, 7),
    )
    stats_7d = materialized_7d or cached_aggregate(
        "monitoring:overview:stats-7d",
        120,
        lambda: dict(db.query_one(
            """
        WITH base AS (
          SELECT
            h.server_id,
            h.started_at,
            h.stopped_at,
            h.media_key,
            h.watch_ms,
            h.duration_ms,
            COALESCE(
              CAST(mu.vodum_user_id AS TEXT),
              'media:' || CAST(mu.id AS TEXT)
            ) AS viewer_id,
            MIN(
              COALESCE(h.watch_ms, 0),
              CASE
                WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            ) AS watch_ms_capped,
            (CAST(h.server_id AS TEXT) || '|' ||
             COALESCE(CAST(mu.vodum_user_id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
             COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
             strftime('%Y-%m-%d %H:%M', h.started_at)
            ) AS play_key
          FROM media_session_history h
          LEFT JOIN media_users mu ON mu.id = h.media_user_id
          WHERE h.stopped_at >= datetime('now', '-7 days')
        ),
        plays AS (
          SELECT
            play_key,
            MAX(viewer_id) AS viewer_id,
            MAX(watch_ms_capped) AS watch_ms
          FROM base
          GROUP BY play_key
        )
        SELECT
          COUNT(*) AS sessions,
          COUNT(DISTINCT viewer_id) AS active_users,
          COALESCE(SUM(watch_ms), 0) AS total_watch_ms,
          AVG(NULLIF(watch_ms, 0)) AS avg_watch_ms
        FROM plays
            """
        ) or {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}),
    )
    stats_7d = dict(stats_7d) if stats_7d else {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
    
    materialized_30d = cached_aggregate(
        "monitoring:overview:materialized-30d", 120,
        lambda: load_materialized_window(db, 30),
    )
    top_users_30d = (materialized_30d or {}).get("top_users") or cached_aggregate(
        "monitoring:overview:top-users-30d",
        120,
        lambda: [dict(row) for row in (db.query(
            """
        WITH base AS (
          SELECT
            h.server_id,
            h.started_at,
            h.stopped_at,
            h.media_key,
            COALESCE(vu.username, mu.username, '-') AS username,
            COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) AS viewer_id,
            MIN(
              COALESCE(h.watch_ms, 0),
              CASE
                WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            ) AS watch_ms_capped,
            (CAST(h.server_id AS TEXT) || '|' ||
             COALESCE(CAST(vu.id AS TEXT), 'media:' || CAST(mu.id AS TEXT)) || '|' ||
             COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
             strftime('%Y-%m-%d %H:%M', h.started_at)
            ) AS play_key
          FROM media_session_history h
          LEFT JOIN media_users mu ON mu.id = h.media_user_id
          LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
          WHERE h.stopped_at >= datetime('now', '-30 days')
        ),
        plays AS (
          SELECT
            viewer_id,
            MAX(username) AS username,
            play_key,
            MAX(watch_ms_capped) AS watch_ms
          FROM base
          GROUP BY play_key
        )
        SELECT
          username,
          COUNT(*) AS sessions,
          COALESCE(SUM(watch_ms), 0) AS watch_ms
        FROM plays
        GROUP BY viewer_id
        ORDER BY watch_ms DESC
        LIMIT 10
            """
        ) or [])],
    )
    
    top_content_30d = cached_query_rows(
        db,
        "monitoring:overview:top-series-30d",
        180,
        """
        WITH base AS (
          SELECT
            h.id AS hist_id,
            h.server_id,
            s.type AS provider,
            h.started_at,
            h.stopped_at,
            CASE
              WHEN COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle')), ''), '') <> ''
                THEN TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle'))
              ELSE TRIM(h.grandparent_title)
            END AS series_title,
            h.media_key,
            h.media_type,
            h.raw_json,
            h.poster_ref_json,
            h.backdrop_ref_json,
            CASE
              WHEN s.type = 'plex'
                   AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                THEN 3
              WHEN COALESCE(NULLIF(TRIM(h.poster_ref_json), ''), '') <> ''
                THEN 1
              ELSE 0
            END AS artwork_rank,
            COALESCE(
              CAST(mu.vodum_user_id AS TEXT),
              'media:' || CAST(mu.id AS TEXT),
              'external:' || NULLIF(TRIM(h.external_user_id), ''),
              'unknown'
            ) AS viewer_id,
            CASE
              WHEN s.type = 'plex'
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                     TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey'))
              WHEN s.type = 'jellyfin'
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId')), ''), '') <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                     TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId'))
              ELSE 'server:' || CAST(h.server_id AS TEXT) || '|series-title:' ||
                   LOWER(TRIM(COALESCE(h.grandparent_title, h.title, 'Unknown')))
            END AS media_group_key,
            MIN(
              COALESCE(h.watch_ms, 0),
              CASE
                WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            ) AS watch_ms_capped,
            CASE
              WHEN COALESCE(NULLIF(TRIM(h.session_key), ''), '') <> ''
                THEN CAST(h.server_id AS TEXT) || '|session:' || TRIM(h.session_key) ||
                     '|started:' || COALESCE(h.started_at, '')
              ELSE CAST(h.server_id AS TEXT) || '|viewer:' ||
                   COALESCE(CAST(h.media_user_id AS TEXT), NULLIF(TRIM(h.external_user_id), ''), 'unknown') ||
                   '|media:' || COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') ||
                   '|started:' || COALESCE(h.started_at, '') ||
                   '|client:' || LOWER(TRIM(COALESCE(h.client_name, '')))
            END AS play_key
          FROM media_session_history h
          LEFT JOIN media_users mu ON mu.id = h.media_user_id
          LEFT JOIN servers s ON s.id = h.server_id
          WHERE h.stopped_at >= datetime('now', '-30 days')
            AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
        ),
        plays_ranked AS (
          SELECT
            b.hist_id,
            b.server_id,
            b.provider,
            b.started_at,
            b.stopped_at,
            b.series_title,
            b.media_key,
            b.media_type,
            b.raw_json,
            b.poster_ref_json,
            b.backdrop_ref_json,
            b.artwork_rank,
            b.viewer_id,
            b.media_group_key,
            b.watch_ms_capped,
            b.play_key,
            ROW_NUMBER() OVER (
              PARTITION BY b.play_key
              ORDER BY b.stopped_at DESC, b.hist_id DESC
            ) AS rn
          FROM base b
        ),
        plays AS (
          SELECT
            hist_id,
            server_id,
            provider,
            series_title,
            media_group_key,
            media_key,
            media_type,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            artwork_rank,
            viewer_id,
            watch_ms_capped AS watch_ms,
            stopped_at
          FROM plays_ranked
          WHERE rn = 1
        ),
        agg AS (
          SELECT
            media_group_key,
            COUNT(DISTINCT viewer_id) AS viewers,
            COUNT(*) AS plays,
            COALESCE(SUM(watch_ms), 0) AS watch_ms
          FROM plays
          GROUP BY media_group_key
        ),
        latest AS (
          SELECT
            hist_id,
            media_group_key,
            series_title AS title,
            server_id,
            provider,
            media_key,
            media_type,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            artwork_rank,
            ROW_NUMBER() OVER (
              PARTITION BY media_group_key
              ORDER BY
                CASE WHEN provider = 'plex' AND artwork_rank > 0 THEN 1 ELSE 0 END DESC,
                artwork_rank DESC,
                stopped_at DESC,
                hist_id DESC
            ) AS rn
          FROM plays
        )
        SELECT
          COALESCE(l.title, 'Unknown') AS title,
          a.viewers,
          a.plays,
          a.watch_ms,
          l.hist_id AS hist_id,
          l.server_id,
          l.provider,
          l.media_key,
          l.media_type,
          l.raw_json,
          l.poster_ref_json,
          l.backdrop_ref_json,
          a.media_group_key
        FROM agg a
        LEFT JOIN latest l
          ON l.media_group_key = a.media_group_key
         AND l.rn = 1
        ORDER BY a.viewers DESC, a.watch_ms DESC
        LIMIT 10
        """,
    )
    
    top_movies_30d = cached_query_rows(
        db,
        "monitoring:overview:top-movies-30d",
        180,
        """
        WITH base AS (
          SELECT
            h.id AS hist_id,
            h.server_id,
            s.type AS provider,
            h.started_at,
            h.stopped_at,
            TRIM(COALESCE(NULLIF(h.title, ''), '-')) AS movie_title,
            h.media_key,
            h.media_type,
            h.raw_json,
            h.poster_ref_json,
            h.backdrop_ref_json,
            COALESCE(
              CAST(mu.vodum_user_id AS TEXT),
              'media:' || CAST(mu.id AS TEXT),
              'external:' || NULLIF(TRIM(h.external_user_id), ''),
              'unknown'
            ) AS viewer_id,
            ('server:' || CAST(h.server_id AS TEXT) || '|movie:' || TRIM(h.media_key)) AS media_group_key,
            MIN(
              COALESCE(h.watch_ms, 0),
              CASE
                WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            ) AS watch_ms_capped,
            CASE
              WHEN COALESCE(NULLIF(TRIM(h.session_key), ''), '') <> ''
                THEN CAST(h.server_id AS TEXT) || '|session:' || TRIM(h.session_key) ||
                     '|started:' || COALESCE(h.started_at, '')
              ELSE CAST(h.server_id AS TEXT) || '|viewer:' ||
                   COALESCE(CAST(h.media_user_id AS TEXT), NULLIF(TRIM(h.external_user_id), ''), 'unknown') ||
                   '|media:' || TRIM(h.media_key) ||
                   '|started:' || COALESCE(h.started_at, '') ||
                   '|client:' || LOWER(TRIM(COALESCE(h.client_name, '')))
            END AS play_key
          FROM media_session_history h
          LEFT JOIN media_users mu ON mu.id = h.media_user_id
          LEFT JOIN servers s ON s.id = h.server_id
          WHERE h.stopped_at >= datetime('now', '-30 days')
            AND TRIM(COALESCE(h.grandparent_title, '')) = ''
            AND COALESCE(NULLIF(TRIM(h.media_key), ''), '') <> ''
        ),
        plays_ranked AS (
          SELECT
            b.hist_id,
            b.server_id,
            b.provider,
            b.started_at,
            b.stopped_at,
            b.movie_title,
            b.media_key,
            b.media_type,
            b.raw_json,
            b.poster_ref_json,
            b.backdrop_ref_json,
            b.viewer_id,
            b.media_group_key,
            b.watch_ms_capped,
            b.play_key,
            ROW_NUMBER() OVER (
              PARTITION BY b.play_key
              ORDER BY b.stopped_at DESC, b.hist_id DESC
            ) AS rn
          FROM base b
        ),
        plays AS (
          SELECT
            hist_id,
            server_id,
            provider,
            movie_title,
            media_group_key,
            media_key,
            media_type,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            viewer_id,
            watch_ms_capped AS watch_ms,
            stopped_at
          FROM plays_ranked
          WHERE rn = 1
        ),
        agg AS (
          SELECT
            media_group_key,
            COUNT(DISTINCT viewer_id) AS viewers,
            COUNT(*) AS plays,
            COALESCE(SUM(watch_ms), 0) AS watch_ms
          FROM plays
          GROUP BY media_group_key
        ),
        latest AS (
          SELECT
            hist_id,
            media_group_key,
            movie_title AS title,
            server_id,
            provider,
            media_key,
            media_type,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            ROW_NUMBER() OVER (
              PARTITION BY media_group_key
              ORDER BY stopped_at DESC, hist_id DESC
            ) AS rn
          FROM plays
        )
        SELECT
          COALESCE(l.title, '-') AS title,
          a.viewers,
          a.plays,
          a.watch_ms,
          l.hist_id AS hist_id,
          l.server_id,
          l.provider,
          l.media_key,
          l.media_type,
          l.raw_json,
          l.poster_ref_json,
          l.backdrop_ref_json,
          a.media_group_key
        FROM agg a
        LEFT JOIN latest l
          ON l.media_group_key = a.media_group_key
         AND l.rn = 1
        ORDER BY a.viewers DESC, a.watch_ms DESC
        LIMIT 10
        """,
    )
    
    top_content_30d = [dict(r) for r in (top_content_30d or [])]
    for item in top_content_30d:
        item["poster_url"] = build_history_poster_url(item, db)
        item["backdrop_url"] = build_history_backdrop_url(item, db) or item["poster_url"]
    
    top_movies_30d = [dict(r) for r in (top_movies_30d or [])]
    for item in top_movies_30d:
        item["poster_url"] = build_history_poster_url(item, db)
        item["backdrop_url"] = build_history_backdrop_url(item, db) or item["poster_url"]
    
    concurrent_7d = cached_aggregate(
        "monitoring:overview:concurrent-7d",
        120,
        lambda: dict(db.query_one(
            """
        SELECT COALESCE(MAX(live_sessions), 0) AS peak_streams
        FROM monitoring_snapshots
        WHERE ts >= datetime('now', '-7 days')
            """
        ) or {"peak_streams": 0}),
    )
    concurrent_7d = dict(concurrent_7d) if concurrent_7d else {"peak_streams": 0}
    
    live_now = int(sessions_stats.get("live_sessions") or 0)
    peak = int(concurrent_7d.get("peak_streams") or 0)
    concurrent_7d["peak_streams"] = max(peak, live_now)
    

    return {
        "stats_7d": stats_7d,
        "top_users_30d": top_users_30d,
        "top_content_30d": top_content_30d,
        "top_movies_30d": top_movies_30d,
        "concurrent_7d": concurrent_7d,
    }
