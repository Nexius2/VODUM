from __future__ import annotations


HISTORY_SORT_COLUMNS = {
    "date": "h.stopped_at",
    "user": "mu.username",
    "server": "s.name",
    "media": "h.title",
    "type": "h.media_type",
    "playback": "playback_type",
    "device": "h.device",
    "duration": "h.watch_ms",
}


def load_monitoring_history(db, args, cookies, build_url, per_page=30):
    page = args.get("page", type=int, default=1)
    offset = (page - 1) * per_page
    filters = {
        "q": (args.get("q") or "").strip(),
        "provider": (args.get("provider") or "").strip(),
        "media_type": (args.get("media_type") or "").strip(),
        "playback": (args.get("playback") or "").strip(),
        "server": args.get("server", type=int),
    }
    sort_key = (
        args.get("sort") or cookies.get("monitoring_history_sort") or "date"
    ).strip()
    sort_dir = (
        args.get("dir") or cookies.get("monitoring_history_dir") or "desc"
    ).strip().lower()
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"
    if sort_key not in HISTORY_SORT_COLUMNS:
        sort_key = "date"
    order_sql = (
        f"{HISTORY_SORT_COLUMNS[sort_key]} "
        f"{'ASC' if sort_dir == 'asc' else 'DESC'}"
    )

    where = ["1=1"]
    params = []
    if filters["q"]:
        like = f"%{filters['q']}%"
        where.append(
            """
            (
              COALESCE(h.title, '') LIKE ?
              OR COALESCE(h.grandparent_title, '') LIKE ?
              OR COALESCE(h.media_type, '') LIKE ?
              OR COALESCE(h.device, '') LIKE ?
              OR COALESCE(h.client_name, '') LIKE ?
              OR COALESCE(h.ip, '') LIKE ?
              OR COALESCE(mu.username, '') LIKE ?
              OR COALESCE(mu.email, '') LIKE ?
              OR COALESCE(vu.username, '') LIKE ?
              OR COALESCE(vu.email, '') LIKE ?
              OR COALESCE(vu.second_email, '') LIKE ?
              OR COALESCE(vu.firstname, '') LIKE ?
              OR COALESCE(vu.lastname, '') LIKE ?
              OR COALESCE(vu.discord_name, '') LIKE ?
              OR COALESCE(s.name, '') LIKE ?
            )
            """
        )
        params.extend([like] * 15)
    if filters["provider"]:
        where.append("s.type = ?")
        params.append(filters["provider"])
    if filters["media_type"]:
        where.append("h.media_type = ?")
        params.append(filters["media_type"])
    playback = filters["playback"].lower()
    if playback in ("transcode", "transcoding"):
        where.append("h.was_transcode = 1")
    elif playback in ("directplay", "direct", "direct_play"):
        where.append("h.was_transcode = 0")
    if filters["server"]:
        where.append("h.server_id = ?")
        params.append(filters["server"])
    where_sql = " AND ".join(where)

    count = db.query_one(
        f"""
        SELECT COUNT(*) AS cnt
        FROM media_session_history h
        JOIN servers s ON s.id = h.server_id
        LEFT JOIN media_users mu ON mu.id = h.media_user_id
        LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE {where_sql}
        """,
        tuple(params),
    )
    total_rows = int(dict(count).get("cnt") or 0) if count else 0
    rows = db.query(
        f"""
        SELECT h.stopped_at, s.name AS server_name, s.type AS provider,
          mu.username, h.title, h.grandparent_title, h.media_type,
          CASE WHEN h.was_transcode = 1
            THEN 'transcode' ELSE 'directplay'
          END AS playback_type,
          h.device, h.client_name, h.watch_ms
        FROM media_session_history h
        JOIN servers s ON s.id = h.server_id
        LEFT JOIN media_users mu ON mu.id = h.media_user_id
        LEFT JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        """,
        tuple(params + [per_page, offset]),
    )
    history_rows = [dict(row) for row in (rows or [])]
    for row in history_rows:
        watch_ms = row.get("watch_ms") or 0
        row["watch_time"] = (
            f"{watch_ms // 3600000}h "
            f"{((watch_ms % 3600000) // 60000)}m"
        )
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    return {
        "rows": history_rows,
        "filters": filters,
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "pagination": {
            "page": page,
            "total_pages": total_pages,
            "total_rows": total_rows,
            "first_url": build_url(1),
            "prev_url": build_url(page - 1),
            "next_url": build_url(page + 1),
            "last_url": build_url(total_pages),
        },
    }
