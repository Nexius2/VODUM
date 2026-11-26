"""Historical chart builders, executed only by the statistics worker."""

def load_activity(db, rng, user_id=None):
    if rng == 'all':
        where = '1=1'
        params = ()
    else:
        delta = {'7d': '-7 days', '1m': '-1 month', '6m': '-6 months', '12m': '-12 months'}.get(rng, '-7 days')
        where = "stopped_at >= datetime('now', ?)"
        params = (delta,)
    rows = db.query(f"""
            WITH base AS (
              SELECT
                stopped_at,
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at
              FROM base
              GROUP BY play_key
            )
            SELECT
              strftime('%Y-%m-%d', stopped_at) AS day,
              COUNT(*) AS sessions
            FROM plays
            GROUP BY strftime('%Y-%m-%d', stopped_at)
            ORDER BY day ASC
            """, params)
    return [dict(row) for row in rows]

def load_media_types(db, rng, user_id=None):
    if rng == 'all':
        where = '1=1'
        params = ()
    else:
        delta = {'7d': '-7 days', '1m': '-1 month', '6m': '-6 months', '12m': '-12 months'}.get(rng, '-7 days')
        where = "stopped_at >= datetime('now', ?)"
        params = (delta,)
    rows = db.query(f"""
            WITH base AS (
              SELECT
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key,

                CASE
                  -- Règle prioritaire : si grandparent_title existe, c'est une série/épisode
                  WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 'series'

                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'series'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 'movie'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                  ELSE 'other'
                END AS media_type,

                CASE
                  -- On évite MAX(text) alphabétique ; on choisit un rang métier
                  WHEN TRIM(COALESCE(grandparent_title, '')) <> '' THEN 400
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 400
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('movie', 'film', 'video') THEN 300
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 200
                  WHEN LOWER(TRIM(COALESCE(media_type,''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 100
                  ELSE 0
                END AS media_rank
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                CASE MAX(media_rank)
                  WHEN 400 THEN 'series'
                  WHEN 300 THEN 'movie'
                  WHEN 200 THEN 'music'
                  WHEN 100 THEN 'photo'
                  ELSE 'other'
                END AS media_type
              FROM base
              GROUP BY play_key
            )
            SELECT media_type, COUNT(*) AS sessions
            FROM plays
            GROUP BY media_type
            ORDER BY sessions DESC
            """, params)
    return [dict(row) for row in rows]

def load_per_server(db, rng, user_id=None):
    if rng == 'all':
        where = '1=1'
        params = ()
    else:
        delta = {'7d': '-7 days', '1m': '-1 month', '6m': '-6 months', '12m': '-12 months'}.get(rng, '-7 days')
        where = "h.stopped_at >= datetime('now', ?)"
        params = (delta,)
    rows = db.query(f"""
            WITH base AS (
              SELECT
                h.server_id,
                (CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE {where}
            ),
            plays AS (
              SELECT
                MAX(server_id) AS server_id,
                play_key
              FROM base
              GROUP BY play_key
            )
            SELECT
              COALESCE(NULLIF(s.name, ''), 'Server ' || p.server_id) AS server_name,
              COUNT(*) AS sessions
            FROM plays p
            LEFT JOIN servers s ON s.id = p.server_id
            GROUP BY p.server_id
            ORDER BY sessions DESC
            """, params)
    return [dict(row) for row in rows]

def load_weekday(db, rng, user_id=None):
    if rng == 'all':
        where = '1=1'
        params = ()
    else:
        delta = {'1m': '-1 month', '6m': '-6 months', '12m': '-12 months'}.get(rng, '-1 month')
        where = "stopped_at >= datetime('now', ?)"
        params = (delta,)
    rows = db.query(f"""
            WITH base AS (
              SELECT
                stopped_at,
                (CAST(server_id AS TEXT) || '|' ||
                 CAST(media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', started_at)
                ) AS play_key
              FROM media_session_history
              WHERE {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at
              FROM base
              GROUP BY play_key
            )
            SELECT
              CAST(strftime('%w', stopped_at) AS INTEGER) AS weekday,
              COUNT(*) AS sessions
            FROM plays
            GROUP BY CAST(strftime('%w', stopped_at) AS INTEGER)
            ORDER BY weekday
            """, params)
    return [dict(row) for row in rows]

def load_user_daily(db, rng, user_id=None):
    if rng == 'all':
        where = '1=1'
        params = (user_id,)
    else:
        delta = {'7d': '-7 days', '30d': '-30 days', '90d': '-90 days', '12m': '-12 months'}.get(rng, '-30 days')
        where = "h.stopped_at >= datetime('now', ?)"
        params = (user_id, delta)
    rows = db.query(f"""
            WITH base AS (
              SELECT
                h.started_at,
                h.stopped_at,
                MIN(
                  COALESCE(h.watch_ms, 0),
                  CASE
                    WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                    ELSE COALESCE(h.watch_ms, 0)
                  END
                ) AS watch_ms_capped,
                (CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', h.started_at)
                ) AS play_key
              FROM media_session_history h
              WHERE h.media_user_id = ?
                AND {where}
            ),
            plays AS (
              SELECT
                play_key,
                MAX(stopped_at) AS stopped_at,
                MAX(watch_ms_capped) AS watch_ms
              FROM base
              GROUP BY play_key
            )
            SELECT
              strftime('%Y-%m-%d', stopped_at) AS day,
              COUNT(*) AS plays,
              COALESCE(SUM(watch_ms), 0) AS watch_ms
            FROM plays
            GROUP BY strftime('%Y-%m-%d', stopped_at)
            ORDER BY day ASC
            """, params)
    return [dict(row) for row in rows]
