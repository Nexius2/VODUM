from __future__ import annotations
from db_manager import isolated_read_operation


USER_SORT_COLUMNS = {
    "user": "n.username",
    "last": "lr.last_watch_at",
    "plays": "a.total_plays",
    "watch": "a.watch_ms",
    "ip": "lr.ip",
    "player": "COALESCE(lr.client_name, lr.client_product, '-')",
}


@isolated_read_operation
def load_monitoring_users_total(db, query):
    if query:
        like = f"%{query}%"
        row = db.query_one(
            """
            WITH base AS (
              SELECT h.media_user_id, mu.username AS mu_username,
                mu.email AS mu_email, mu.vodum_user_id,
                CASE WHEN mu.vodum_user_id IS NOT NULL
                  THEN ('v:' || mu.vodum_user_id)
                  ELSE ('m:' || mu.id)
                END AS group_key
              FROM media_session_history h
              JOIN media_users mu ON mu.id = h.media_user_id
              WHERE h.media_user_id IS NOT NULL
            ),
            names AS (
              SELECT b.group_key,
                MAX(b.vodum_user_id) AS vodum_user_id,
                MIN(b.media_user_id) AS user_id,
                COALESCE(vu.username, MIN(b.mu_username)) AS username,
                GROUP_CONCAT(
                  COALESCE(b.mu_username, '') || ' ' ||
                  COALESCE(b.mu_email, ''),
                  ' '
                ) AS media_search
              FROM base b
              LEFT JOIN vodum_users vu ON vu.id = b.vodum_user_id
              GROUP BY b.group_key
            )
            SELECT COUNT(*) AS cnt
            FROM names n
            LEFT JOIN vodum_users vu ON vu.id = n.vodum_user_id
            WHERE (
              COALESCE(n.username, '') LIKE ?
              OR COALESCE(vu.username, '') LIKE ?
              OR COALESCE(vu.email, '') LIKE ?
              OR COALESCE(vu.second_email, '') LIKE ?
              OR COALESCE(vu.firstname, '') LIKE ?
              OR COALESCE(vu.lastname, '') LIKE ?
              OR COALESCE(vu.notes, '') LIKE ?
              OR COALESCE(vu.discord_name, '') LIKE ?
              OR COALESCE(n.media_search, '') LIKE ?
            )
            """,
            (like,) * 9,
        )
    else:
        row = db.query_one(
            """
            WITH base AS (
              SELECT CASE WHEN mu.vodum_user_id IS NOT NULL
                  THEN ('v:' || mu.vodum_user_id)
                  ELSE ('m:' || mu.id)
                END AS group_key
              FROM media_users mu
              WHERE EXISTS (
                SELECT 1 FROM media_session_history h WHERE h.media_user_id = mu.id
              )
            )
            SELECT COUNT(DISTINCT group_key) AS cnt
            FROM base
            """
        )
    return int(dict(row).get("cnt") or 0) if row else 0


@isolated_read_operation
def load_monitoring_users_rows(db, options):
    query = options["q"]
    where_sql = ""
    params = []
    # Only filtered searches use the concatenated identity text. Keep the
    # original concatenation for searches, including SQL wildcard semantics.
    media_search_sql = """
            , GROUP_CONCAT(
              COALESCE(b.mu_username, '') || ' ' ||
              COALESCE(b.mu_email, ''), ' '
            ) AS media_search
    """ if query else ""
    names_source = "base" if query else "last_candidates"
    # These sorts depend only on identity/latest playback, so choose the page
    # before aggregating its history. Aggregate sorts still need every group.
    page_first = not query and options["order_sql"] in {
        f"({column} IS NULL) ASC, {column} {direction}"
        for key, column in USER_SORT_COLUMNS.items()
        if key not in {"plays", "watch"}
        for direction in ("ASC", "DESC")
    }
    page_cte = ""
    history_source = "media_session_history h JOIN media_users mu ON mu.id = h.media_user_id"
    if page_first:
        page_cte = f""",
        selected_groups AS MATERIALIZED (
          SELECT n.group_key
          FROM names n JOIN last_rows lr ON lr.group_key = n.group_key
          ORDER BY {options["order_sql"]}, n.group_key
          LIMIT ? OFFSET ?
        ),
        selected_accounts AS (
          SELECT c.media_user_id
          FROM last_candidates c
          JOIN selected_groups s ON s.group_key = c.group_key
        )
        """
        history_source = """selected_accounts selected
          CROSS JOIN media_session_history h ON h.media_user_id = selected.media_user_id
          JOIN media_users mu ON mu.id = h.media_user_id"""
    if query:
        like = f"%{query}%"
        where_sql = """
        WHERE (
          COALESCE(n.username, '') LIKE ?
          OR COALESCE(vu.username, '') LIKE ?
          OR COALESCE(vu.email, '') LIKE ?
          OR COALESCE(vu.second_email, '') LIKE ?
          OR COALESCE(vu.firstname, '') LIKE ?
          OR COALESCE(vu.lastname, '') LIKE ?
          OR COALESCE(vu.notes, '') LIKE ?
          OR COALESCE(vu.discord_name, '') LIKE ?
          OR COALESCE(n.media_search, '') LIKE ?
        )
        """
        params.extend([like] * 9)

    rows = db.query(
        f"""
        WITH base AS (
          SELECT h.media_user_id,
            mu.username AS mu_username, mu.email AS mu_email,
            mu.vodum_user_id,
            CASE WHEN mu.vodum_user_id IS NOT NULL
              THEN ('v:' || mu.vodum_user_id)
              ELSE ('m:' || mu.id)
            END AS group_key,
            MIN(
              COALESCE(h.watch_ms, 0),
              CASE WHEN COALESCE(h.duration_ms, 0) > 0
                THEN h.duration_ms
                ELSE COALESCE(h.watch_ms, 0)
              END
            ) AS watch_ms_capped,
            (
              CAST(h.server_id AS TEXT) || '|' ||
              CASE WHEN mu.vodum_user_id IS NOT NULL
                THEN ('v:' || mu.vodum_user_id)
                ELSE ('m:' || mu.id)
              END || '|' ||
              COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
              strftime('%Y-%m-%d %H:%M', h.started_at)
            ) AS play_key
          FROM {history_source}
          WHERE h.media_user_id IS NOT NULL
        ),
        plays AS (
          SELECT group_key, play_key,
            MAX(watch_ms_capped) AS watch_ms
          FROM base
          GROUP BY play_key
        ),
        agg AS (
          SELECT group_key,
            COUNT(*) AS total_plays,
            COALESCE(SUM(watch_ms), 0) AS watch_ms
          FROM plays
          GROUP BY group_key
        ),
        last_candidates AS (
          SELECT h.id, h.stopped_at, mu.id AS media_user_id,
            mu.username AS mu_username, mu.vodum_user_id,
            CASE WHEN mu.vodum_user_id IS NOT NULL
              THEN ('v:' || mu.vodum_user_id)
              ELSE ('m:' || mu.id)
            END AS group_key
          FROM media_users mu
          JOIN media_session_history h ON h.id = (
            SELECT recent.id
            FROM media_session_history recent
            WHERE recent.media_user_id = mu.id
            ORDER BY recent.stopped_at DESC, recent.id ASC
            LIMIT 1
          )
        ),
        ranked AS (
          SELECT group_key, id,
            ROW_NUMBER() OVER (
              PARTITION BY group_key ORDER BY stopped_at DESC, id ASC
            ) AS rn
          FROM last_candidates
        ),
        last_rows AS (
          SELECT r.group_key, h.stopped_at AS last_watch_at, h.ip, h.device,
            h.client_name, h.client_product
          FROM ranked r
          JOIN media_session_history h ON h.id = r.id
          WHERE r.rn = 1
        ),
        names AS (
          SELECT b.group_key,
            MAX(b.vodum_user_id) AS vodum_user_id,
            MIN(b.media_user_id) AS user_id,
            COALESCE(vu.username, MIN(b.mu_username)) AS username
            {media_search_sql}
          FROM {names_source} b
          LEFT JOIN vodum_users vu ON vu.id = b.vodum_user_id
          GROUP BY b.group_key
        )
        {page_cte}
        SELECT n.user_id, n.username, lr.last_watch_at,
          a.total_plays, a.watch_ms, lr.ip AS last_ip,
          COALESCE(lr.device, lr.client_product, '-') AS platform,
          COALESCE(lr.client_name, lr.client_product, '-') AS player
        FROM agg a
        JOIN last_rows lr ON lr.group_key = a.group_key
        JOIN names n ON n.group_key = a.group_key
        LEFT JOIN vodum_users vu ON vu.id = n.vodum_user_id
        {where_sql}
        ORDER BY {options["order_sql"]}
        {"" if page_first else "LIMIT ? OFFSET ?"}
        """,
        tuple(params + [options["per_page"], options["offset"]]),
    )
    return format_monitoring_users(rows)


def build_monitoring_users_options(args, cookies, per_page=30):
    page = args.get("page", type=int, default=1)
    query = (args.get("q") or "").strip()
    sort_key = (
        args.get("sort")
        or cookies.get("monitoring_users_sort")
        or "last"
    ).strip()
    sort_dir = (
        args.get("dir")
        or cookies.get("monitoring_users_dir")
        or "desc"
    ).strip().lower()

    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    if sort_key not in USER_SORT_COLUMNS:
        sort_key = "last"

    column = USER_SORT_COLUMNS[sort_key]
    direction = "ASC" if sort_dir == "asc" else "DESC"
    return {
        "page": page,
        "per_page": per_page,
        "offset": (page - 1) * per_page,
        "q": query,
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "order_sql": f"({column} IS NULL) ASC, {column} {direction}",
    }


def format_monitoring_users(rows):
    users = [dict(row) for row in rows]
    for user in users:
        watch_ms = user.get("watch_ms") or 0
        user["watch_time"] = (
            f"{watch_ms // 3600000}h "
            f"{((watch_ms % 3600000) // 60000)}m"
        )
        if not user.get("last_ip"):
            user["last_ip"] = "-"
    return users


def build_monitoring_users_pagination(total_rows, options, build_url):
    per_page = options["per_page"]
    page = options["page"]
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
