from __future__ import annotations

from core.monitoring.artwork import (
    build_history_backdrop_url,
    build_history_poster_url,
)


LIBRARY_RANGES = {"7d", "30d", "90d", "1y", "all"}
LIBRARY_SORT_COLUMNS = {
    "server": "s.name",
    "library": "l.name",
    "type": "l.type",
    "users": "users_with_access",
    "items": "l.item_count",
    "last": "last_stream_at",
    "plays": "total_plays",
    "duration": "played_ms",
}
LIBRARY_RANGE_SQL = {
    "7d": "-7 days",
    "30d": "-30 days",
    "90d": "-90 days",
    "1y": "-1 year",
}


def build_monitoring_library_options(args, cookies, per_page=30):
    page = args.get("page", type=int, default=1)
    library_range = (args.get("lib_range") or "30d").strip().lower()
    if library_range not in LIBRARY_RANGES:
        library_range = "30d"

    library_user = (args.get("lib_user") or "all").strip()
    library_user_id = None
    if library_user != "all":
        try:
            library_user_id = int(library_user)
        except (TypeError, ValueError):
            library_user = "all"

    sort_key = (
        args.get("sort")
        or cookies.get("monitoring_libraries_sort")
        or "last"
    ).strip()
    sort_dir = (
        args.get("dir")
        or cookies.get("monitoring_libraries_dir")
        or "desc"
    ).strip().lower()
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    if sort_key not in LIBRARY_SORT_COLUMNS:
        sort_key = "last"

    return {
        "page": page,
        "per_page": per_page,
        "offset": (page - 1) * per_page,
        "library_range": library_range,
        "library_user": library_user,
        "library_user_id": library_user_id,
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "order_sql": (
            f"{LIBRARY_SORT_COLUMNS[sort_key]} "
            f"{'ASC' if sort_dir == 'asc' else 'DESC'}"
        ),
    }


def load_monitoring_library_table(db, options):
    count = db.query_one(
        """
        WITH plays AS (
          SELECT h.server_id,
            CAST(h.library_section_id AS TEXT) AS library_section_id
          FROM media_session_history h
          WHERE COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
          GROUP BY h.server_id, CAST(h.library_section_id AS TEXT)
        )
        SELECT COUNT(*) AS cnt
        FROM libraries l
        JOIN plays p
          ON p.server_id = l.server_id
         AND p.library_section_id = CAST(l.section_id AS TEXT)
        """
    )
    total_rows = int(dict(count).get("cnt") or 0) if count else 0
    rows = db.query(
        f"""
        WITH plays AS (
          SELECT h.server_id,
            CAST(h.library_section_id AS TEXT) AS library_section_id,
            MAX(h.stopped_at) AS stopped_at,
            (
              CAST(h.server_id AS TEXT) || '|' ||
              CAST(h.media_user_id AS TEXT) || '|' ||
              COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
              strftime('%Y-%m-%d %H:%M', h.started_at)
            ) AS play_key,
            MAX(MIN(
              COALESCE(h.watch_ms, 0),
              CASE WHEN COALESCE(h.duration_ms, 0) > 0
                THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            )) AS watch_ms
          FROM media_session_history h
          WHERE COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
          GROUP BY h.server_id, CAST(h.library_section_id AS TEXT),
            (
              CAST(h.server_id AS TEXT) || '|' ||
              CAST(h.media_user_id AS TEXT) || '|' ||
              COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
              strftime('%Y-%m-%d %H:%M', h.started_at)
            )
        ),
        lib_stats AS (
          SELECT server_id, library_section_id,
            MAX(stopped_at) AS last_stream_at,
            COUNT(*) AS total_plays,
            COALESCE(SUM(watch_ms), 0) AS played_ms
          FROM plays
          GROUP BY server_id, library_section_id
        )
        SELECT l.id AS library_id,
          l.section_id AS library_section_id,
          l.name AS library_name,
          s.id AS server_id, s.name AS server_name, s.type AS provider,
          l.type AS media_type,
          (
            SELECT COUNT(DISTINCT mul.media_user_id)
            FROM media_user_libraries mul
            JOIN media_users mu_acc ON mu_acc.id = mul.media_user_id
            WHERE mul.library_id = l.id
              AND LOWER(COALESCE(mu_acc.role, '')) != 'owner'
          ) AS users_with_access,
          l.item_count, ls.last_stream_at, ls.total_plays, ls.played_ms
        FROM libraries l
        JOIN servers s ON s.id = l.server_id
        JOIN lib_stats ls
          ON ls.server_id = l.server_id
         AND ls.library_section_id = CAST(l.section_id AS TEXT)
        ORDER BY {options["order_sql"]}
        LIMIT ? OFFSET ?
        """,
        (options["per_page"], options["offset"]),
    )
    libraries = [dict(row) for row in (rows or [])]
    for library in libraries:
        played_ms = library.get("played_ms") or 0
        library["played_duration"] = (
            f"{played_ms // 3600000}h "
            f"{((played_ms % 3600000) // 60000)}m"
        )
        library["has_last_stream"] = True
    return {
        "rows": libraries,
        "total_rows": total_rows,
        "hidden_libraries_count": 0,
    }


def load_monitoring_library_users(db):
    rows = db.query(
        """
        SELECT DISTINCT vu.id,
          COALESCE(
            NULLIF(TRIM(vu.username), ''),
            NULLIF(TRIM(vu.email), ''),
            'User #' || vu.id
          ) AS label
        FROM media_session_history h
        JOIN media_users mu ON mu.id = h.media_user_id
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        ORDER BY label COLLATE NOCASE
        """
    )
    return [dict(row) for row in (rows or [])]


def build_library_top_filter(options):
    where = ["1=1"]
    params = []
    library_range = options["library_range"]
    if library_range != "all":
        where.append("h.stopped_at >= datetime('now', ?)")
        params.append(LIBRARY_RANGE_SQL[library_range])
    if options["library_user_id"] is not None:
        where.append("vu_ref.id = ?")
        params.append(options["library_user_id"])
    return " AND ".join(where), params


def load_monitoring_library_top_cards(db, options):
    where_hist_sql, params_hist = build_library_top_filter(
        options
    )

    top_rows = db.query(
        f"""
        WITH hist AS (
          SELECT
            h.id AS hist_id,
            l.id AS library_id,
            l.name AS library_name,
            l.type AS media_type,
            s.id AS server_id,
            s.name AS server_name,
            s.type AS provider,
            vu_ref.id AS vodum_user_id,
            COALESCE(
              CAST(vu_ref.id AS TEXT),
              'media:' || CAST(h.media_user_id AS TEXT),
              'external:' || NULLIF(TRIM(h.external_user_id), ''),
              'unknown'
            ) AS viewer_key,
            h.media_user_id,
            h.media_key,
            h.raw_json,
            h.poster_ref_json,
            h.backdrop_ref_json,
            CASE
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                THEN 2
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) NOT IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND COALESCE(NULLIF(TRIM(h.media_key), ''), '') <> ''
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.ratingKey')), ''), '') = TRIM(h.media_key)
                THEN 2
              WHEN COALESCE(NULLIF(TRIM(h.poster_ref_json), ''), '') <> ''
                THEN 1
              ELSE 0
            END AS artwork_rank,
            h.stopped_at,
            h.started_at,
            CAST(h.library_section_id AS TEXT) AS history_library_section_id,
            LOWER(TRIM(COALESCE(h.media_type, ''))) AS history_media_type,

            CASE
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle')), ''), '') <> ''
                THEN TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentTitle'))
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) NOT IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND COALESCE(NULLIF(TRIM(h.media_key), ''), '') <> ''
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.ratingKey')), ''), '') = TRIM(h.media_key)
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.title')), ''), '') <> ''
                THEN TRIM(json_extract(h.raw_json, '$.VideoOrTrack.title'))
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                THEN TRIM(COALESCE(h.grandparent_title, 'Unknown'))
              ELSE TRIM(COALESCE(h.title, 'Unknown'))
            END AS display_title,

            CASE
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND s.type = 'plex'
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey')), ''), '') <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                     TRIM(json_extract(h.raw_json, '$.VideoOrTrack.grandparentRatingKey'))
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND s.type = 'jellyfin'
                   AND COALESCE(NULLIF(TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId')), ''), '') <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-id:' ||
                     TRIM(json_extract(h.raw_json, '$.NowPlayingItem.SeriesId'))
              WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'show', 'episode', 'tv', 'season')
                   AND TRIM(COALESCE(h.grandparent_title, '')) <> ''
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|series-title:' || LOWER(TRIM(h.grandparent_title))
              WHEN NULLIF(TRIM(h.media_key), '') IS NOT NULL
                THEN 'server:' || CAST(h.server_id AS TEXT) || '|media:' || TRIM(h.media_key)
              ELSE 'server:' || CAST(h.server_id AS TEXT) || '|title:' || LOWER(TRIM(COALESCE(h.title, 'Unknown')))
            END AS media_group_key,

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
          JOIN libraries l
            ON l.server_id = h.server_id
           AND CAST(l.section_id AS TEXT) = CAST(h.library_section_id AS TEXT)
          JOIN servers s
            ON s.id = l.server_id
          LEFT JOIN media_users mu_ref
            ON mu_ref.id = h.media_user_id
          LEFT JOIN vodum_users vu_ref
            ON vu_ref.id = mu_ref.vodum_user_id
          WHERE {where_hist_sql}
            AND COALESCE(NULLIF(TRIM(h.library_section_id), ''), '') <> ''
        ),
        plays_ranked AS (
          SELECT
            h.hist_id,
            h.library_id,
            h.library_name,
            h.media_type,
            h.server_id,
            h.server_name,
            h.provider,
            h.vodum_user_id,
            h.viewer_key,
            h.media_key,
            h.raw_json,
            h.poster_ref_json,
            h.backdrop_ref_json,
            h.artwork_rank,
            h.stopped_at,
            h.display_title,
            h.media_group_key,
            h.play_key,
            ROW_NUMBER() OVER (
              PARTITION BY h.play_key
              ORDER BY h.stopped_at DESC, h.hist_id DESC
            ) AS rn
          FROM hist h
        ),
        plays AS (
          SELECT
            hist_id,
            library_id,
            library_name,
            media_type,
            server_id,
            server_name,
            provider,
            vodum_user_id,
            viewer_key,
            media_key,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            artwork_rank,
            stopped_at,
            display_title,
            media_group_key
          FROM plays_ranked
          WHERE rn = 1
        ),
        media_agg AS (
          SELECT
            library_id,
            library_name,
            media_type,
            server_id,
            server_name,
            provider,
            media_group_key,
            COUNT(*) AS plays,
            COUNT(DISTINCT viewer_key) AS user_count,
            MAX(stopped_at) AS last_play_at
          FROM plays
          GROUP BY
            library_id,
            library_name,
            media_type,
            server_id,
            server_name,
            provider,
            media_group_key
        ),
        latest_snapshots AS (
          SELECT
            hist_id,
            library_id,
            media_group_key,
            display_title,
            media_key,
            raw_json,
            poster_ref_json,
            backdrop_ref_json,
            artwork_rank,
            ROW_NUMBER() OVER (
              PARTITION BY library_id, media_group_key
              ORDER BY artwork_rank DESC, stopped_at DESC, hist_id DESC
            ) AS rn
          FROM plays
        ),
        ranked AS (
          SELECT
            m.library_id,
            m.library_name,
            m.media_type,
            m.server_id,
            m.server_name,
            m.provider,
            m.media_group_key,
            COALESCE(ls.display_title, 'Unknown') AS display_title,
            ls.hist_id AS hist_id,
            ls.media_key AS media_key,
            m.plays,
            m.user_count,
            m.last_play_at,
            ls.raw_json,
            ls.poster_ref_json,
            ls.backdrop_ref_json,
            ROW_NUMBER() OVER (
              PARTITION BY m.library_id
              ORDER BY m.plays DESC, m.user_count DESC, m.last_play_at DESC, COALESCE(ls.display_title, 'Unknown') ASC
            ) AS row_in_library
          FROM media_agg m
          LEFT JOIN latest_snapshots ls
            ON ls.library_id = m.library_id
           AND ls.media_group_key = m.media_group_key
           AND ls.rn = 1
        )
        SELECT
          library_id,
          library_name,
          media_type,
          server_id,
          server_name,
          provider,
          media_group_key,
          display_title,
          hist_id,
          media_key,
          plays,
          user_count,
          last_play_at,
          raw_json,
          poster_ref_json,
          backdrop_ref_json,
          row_in_library
        FROM ranked
        WHERE row_in_library <= 6
        ORDER BY library_name COLLATE NOCASE, row_in_library ASC
        """,
        tuple(params_hist),
    )

    top_rows = [dict(r) for r in (top_rows or [])]

    cards_by_library = {}
    for r in top_rows:
        card = cards_by_library.get(r["library_id"])
        if not card:
            card = {
                "library_id": r["library_id"],
                "library_name": r["library_name"],
                "server_name": r["server_name"],
                "media_type": r.get("media_type"),
                "items": [],
                "total_plays": 0,
                "total_users": 0,
            }
            cards_by_library[r["library_id"]] = card

        item = dict(r)
        item["poster_url"] = build_history_poster_url(item, db)
        item["backdrop_url"] = build_history_backdrop_url(item, db) or item["poster_url"]

        card["items"].append(item)
        card["total_plays"] += int(item.get("plays") or 0)

    library_top_cards = list(cards_by_library.values())

    for card in library_top_cards:
        card["total_users"] = sum(int(x.get("user_count") or 0) for x in card["items"])

    library_top_cards.sort(
        key=lambda c: (
            -(c.get("total_plays") or 0),
            str(c.get("library_name") or "").lower(),
        )
    )
    return library_top_cards


def build_monitoring_library_pagination(total_rows, options, build_url):
    page = options["page"]
    per_page = options["per_page"]
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    return {
        "page": page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "first_url": build_url(1),
        "prev_url": build_url(page - 1),
        "next_url": build_url(page + 1),
        "last_url": build_url(total_pages),
    }
