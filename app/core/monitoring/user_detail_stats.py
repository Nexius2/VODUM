"""Background statistics of the Monitoring user page.

The refresh task computes them (``monitoring_precomputed`` kind
``monitoring_user``); the page only reads the stored result. The paginated
history stays a direct, bounded read.
"""

_PLAY_KEY = """(CAST(h.server_id AS TEXT) || '|' ||
                 CAST(h.media_user_id AS TEXT) || '|' ||
                 COALESCE(NULLIF(TRIM(h.media_key), ''), 'no_media') || '|' ||
                 strftime('%Y-%m-%d %H:%M', h.started_at)
                )"""

_CAPPED_WATCH = """MIN(
                  COALESCE(h.watch_ms, 0),
                  CASE
                    WHEN COALESCE(h.duration_ms, 0) > 0 THEN h.duration_ms
                    ELSE COALESCE(h.watch_ms, 0)
                  END
                )"""

_KIND = """CASE
                  WHEN TRIM(COALESCE(h.grandparent_title, '')) <> '' THEN 'serie'
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 'serie'
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('movie', 'film', 'video') THEN 'movie'
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 'music'
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 'photo'
                  ELSE 'other'
                END"""

_KIND_RANK = """CASE
                  WHEN TRIM(COALESCE(h.grandparent_title, '')) <> '' THEN 400
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('serie', 'series', 'episode', 'show', 'season') THEN 400
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('movie', 'film', 'video') THEN 300
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('music', 'audio', 'song', 'track', 'tracks') THEN 200
                  WHEN LOWER(TRIM(COALESCE(h.media_type, ''))) IN ('photo', 'photos', 'image', 'picture', 'pictures') THEN 100
                  ELSE 0
                END"""

IP_SORTS = {
    "ip": "ip",
    "first_seen": "first_seen_sort",
    "last_seen": "last_seen_sort",
    "last_platform": "last_platform",
    "last_player": "last_player",
    "last_played": "last_title",
    "plays": "play_count",
    "watch": "last_watch_ms",
}


def format_watch(ms):
    ms = int(ms or 0)
    return f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"


def linked_media_user_ids(db, media_user_id):
    """Every media account of the same VODUM user (one per server)."""
    row = db.query_one("SELECT id, server_id, vodum_user_id FROM media_users WHERE id = ?", (media_user_id,))
    if not row:
        return None
    if row["vodum_user_id"]:
        rows = db.query("SELECT id FROM media_users WHERE vodum_user_id = ? ORDER BY type, server_id",
                        (row["vodum_user_id"],))
        return [r["id"] for r in rows] or [media_user_id]
    return [media_user_id]


def _last_played(row):
    media_type = (row.get("last_media_type") or "").strip().lower()
    title = (row.get("last_title") or "").strip()
    grandparent = (row.get("last_grandparent_title") or "").strip()
    parent = (row.get("last_parent_title") or "").strip()
    if not title and not grandparent:
        return "-"
    if media_type in ("episode", "serie"):
        bits = [b for b in (grandparent, parent, title) if b]
        return " • ".join(bits) if bits else "-"
    if media_type == "movie":
        return title or "-"
    bits = [b for b in (grandparent, title) if b]
    return " • ".join(bits) if bits else "-"


def compute_monitoring_user_stats(db, options):
    """Aggregates shown on the profile and IP views of a Monitoring user."""
    linked_ids = linked_media_user_ids(db, int(options["media_user_id"]))
    if linked_ids is None:
        return None
    in_sql = "(" + ",".join(["?"] * len(linked_ids)) + ")"
    ids = tuple(linked_ids)

    server_rows = db.query(f"""
            SELECT mu.server_id AS server_id, COUNT(*) AS plays
            FROM media_session_history h
            JOIN media_users mu ON mu.id = h.media_user_id
            WHERE h.media_user_id IN {in_sql}
              AND h.stopped_at >= datetime('now', '-30 days')
            GROUP BY mu.server_id
            ORDER BY plays DESC""", ids)
    server_ids = [r["server_id"] for r in server_rows if r["server_id"] is not None]
    names = {}
    if server_ids:
        marks = ",".join(["?"] * len(server_ids))
        names = {r["id"]: f'{r["name"]}' for r in db.query(f"SELECT id, name, type FROM servers WHERE id IN ({marks})", tuple(server_ids))}
    server_usage = [{"server_id": r["server_id"],
                     "label": names.get(r["server_id"], f"server#{r['server_id']}" if r["server_id"] is not None else "unknown"),
                     "plays": int(r["plays"] or 0)} for r in server_rows]

    media_rows = db.query(f"""
            WITH base AS (
              SELECT {_KIND} AS kind, {_KIND_RANK} AS kind_rank, {_PLAY_KEY} AS play_key
              FROM media_session_history h
              WHERE h.media_user_id IN {in_sql}
                AND h.stopped_at >= datetime('now', '-30 days')
            ),
            plays AS (
              SELECT play_key,
                CASE MAX(kind_rank) WHEN 400 THEN 'serie' WHEN 300 THEN 'movie' WHEN 200 THEN 'music'
                  WHEN 100 THEN 'photo' ELSE 'other' END AS kind
              FROM base GROUP BY play_key
            )
            SELECT kind, COUNT(*) AS plays FROM plays GROUP BY kind ORDER BY plays DESC""", ids)
    media_types = [{"label": r["kind"], "plays": int(r["plays"] or 0)} for r in media_rows]

    def period(modifier=None):
        where = "AND h.stopped_at >= datetime('now', ?)" if modifier else ""
        row = db.query_one(f"""
            WITH base AS (
              SELECT h.stopped_at, {_CAPPED_WATCH} AS watch_ms_capped, {_PLAY_KEY} AS play_key
              FROM media_session_history h
              WHERE h.media_user_id IN {in_sql} {where}
            ),
            plays AS (
              SELECT play_key, MAX(stopped_at) AS stopped_at, MAX(watch_ms_capped) AS watch_ms
              FROM base GROUP BY play_key
            )
            SELECT COUNT(*) AS plays, COALESCE(SUM(watch_ms), 0) AS watch_ms, MAX(stopped_at) AS last_watch_at
            FROM plays""", ids + ((modifier,) if modifier else ()))
        row = dict(row) if row else {}
        watch = int(row.get("watch_ms") or 0)
        return {"plays": int(row.get("plays") or 0), "watch_ms": watch,
                "watch_time": format_watch(watch), "last_watch_at": row.get("last_watch_at")}

    all_time = period()
    profile = {
        "last_24h": period("-24 hours"),
        "last_7d": period("-7 days"),
        "last_30d": period("-30 days"),
        "all_time": all_time,
        "policy_hits": {"total": 0, "kills": 0, "warns": 0, "last_hit_at": None},
        "peak_streams": 0,
    }
    profile["top_players"] = [dict(r) for r in db.query(f"""
            WITH base AS (
              SELECT COALESCE(NULLIF(h.client_name, ''), NULLIF(h.client_product,''), NULLIF(h.device,''), 'Unknown') AS player,
                     {_PLAY_KEY} AS play_key
              FROM media_session_history h
              WHERE h.media_user_id IN {in_sql}
            ),
            plays AS (SELECT play_key, MAX(player) AS player FROM base GROUP BY play_key)
            SELECT player, COUNT(*) AS plays FROM plays GROUP BY player ORDER BY plays DESC LIMIT 12""", ids)]

    ip_rows = [dict(r) for r in db.query(f"""
            WITH ranked AS (
              SELECT ip, started_at, stopped_at, media_type, title, grandparent_title, parent_title,
                     watch_ms, duration_ms,
                     COALESCE(NULLIF(device,''), NULLIF(client_product,''), '-') AS platform,
                     COALESCE(NULLIF(client_name,''), NULLIF(client_product,''), '-') AS player,
                     ROW_NUMBER() OVER (PARTITION BY ip ORDER BY datetime(stopped_at) DESC) AS rn
              FROM media_session_history
              WHERE media_user_id IN {in_sql} AND ip IS NOT NULL AND ip != ''
            ),
            last_per_ip AS (
              SELECT ip, stopped_at AS last_seen, platform AS last_platform, player AS last_player,
                     media_type AS last_media_type, title AS last_title,
                     grandparent_title AS last_grandparent_title, parent_title AS last_parent_title,
                     watch_ms AS last_watch_ms, duration_ms AS last_duration_ms
              FROM ranked WHERE rn = 1
            ),
            agg AS (
              SELECT ip, MIN(started_at) AS first_seen, MAX(stopped_at) AS last_seen, COUNT(*) AS play_count
              FROM media_session_history
              WHERE media_user_id IN {in_sql} AND ip IS NOT NULL AND ip != ''
              GROUP BY ip
            )
            SELECT a.ip, a.first_seen, a.last_seen, datetime(a.first_seen) AS first_seen_sort,
                   datetime(a.last_seen) AS last_seen_sort, l.last_platform, l.last_player,
                   l.last_media_type, l.last_title, l.last_grandparent_title, l.last_parent_title,
                   l.last_watch_ms, l.last_duration_ms, a.play_count
            FROM agg a LEFT JOIN last_per_ip l ON l.ip = a.ip
            ORDER BY datetime(a.last_seen) DESC""", ids + ids)]
    for row in ip_rows:
        row["last_played"] = _last_played(row)
        row["watch_time"] = format_watch(row.get("last_watch_ms") or 0)

    return {
        "server_usage_30d": server_usage,
        "media_types_30d": media_types,
        "total_plays": all_time["plays"],
        "watch_ms": all_time["watch_ms"],
        "last_watch_at": all_time["last_watch_at"],
        "profile": profile,
        "ip_rows": ip_rows,
    }


def sort_ip_rows(rows, sort_key, sort_dir):
    """Same order as the former SQL ORDER BY: NULL first ascending, last descending."""
    column = IP_SORTS.get(sort_key, "last_seen_sort")
    return sorted(rows, key=lambda row: (row.get(column) is not None, row.get(column) if row.get(column) is not None else 0),
                  reverse=sort_dir == "desc")
