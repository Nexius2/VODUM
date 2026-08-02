LIBRARY_TYPE_SQL = """
                CASE LOWER(TRIM(COALESCE(l.type, '')))
                    WHEN 'tvshows' THEN 'shows'
                    WHEN 'tvshow' THEN 'shows'
                    WHEN 'show' THEN 'shows'
                    WHEN 'series' THEN 'shows'
                    WHEN 'movies' THEN 'movie'
                    WHEN 'film' THEN 'movie'
                    WHEN 'films' THEN 'movie'
                    WHEN 'music' THEN 'music'
                    WHEN 'artist' THEN 'music'
                    WHEN 'artists' THEN 'music'
                    WHEN 'audio' THEN 'music'
                    ELSE COALESCE(NULLIF(LOWER(TRIM(l.type)), ''), 'unknown')
                END
"""

SERVERS_LIST_COLUMNS = """
                s.id,
                s.name,
                s.type,
                s.url,
                s.local_url,
                s.public_url,
                s.status,
                s.server_version
"""

LIBRARIES_LIST_COLUMNS = f"""
                l.id,
                l.server_id,
                l.name,
{LIBRARY_TYPE_SQL} AS type,
                l.section_id
"""

SERVER_DETAIL_COLUMNS = """
            id,
            name,
            type,
            url,
            local_url,
            public_url,
            status,
            settings_json
"""

SERVER_DETAIL_LIBRARY_COLUMNS = f"""
                l.id,
                l.name,
{LIBRARY_TYPE_SQL} AS type,
                l.section_id
"""


def load_servers_list(db):
    return db.query(
        f"""
        SELECT
{SERVERS_LIST_COLUMNS},
            COUNT(DISTINCT l.id) AS libraries_count,
            COUNT(DISTINCT mu.vodum_user_id) AS users_count
        FROM servers s
        LEFT JOIN libraries l ON l.server_id = s.id
        LEFT JOIN media_users mu ON mu.server_id = s.id
        GROUP BY s.id
        ORDER BY s.name
        """
    )


def snapshot_deleting_server_ids(lock, in_progress: set) -> set[int]:
    with lock:
        return {
            int(str(key).split(":", 1)[1])
            for key in in_progress
            if str(key).startswith("server:")
        }


def normalize_libraries_sort(sort: str, order: str) -> tuple[str, str, str]:
    sort_map = {
        "server": "LOWER(s.name)",
        "name": "LOWER(l.name)",
        "type": "type",
        "section_id": "LOWER(COALESCE(l.section_id, ''))",
        "users": "users_count",
    }
    normalized_sort = sort if sort in sort_map else "server"
    normalized_order = order if order in ("asc", "desc") else "asc"
    direction = "DESC" if normalized_order == "desc" else "ASC"
    clause = (
        f"{sort_map[normalized_sort]} {direction}, LOWER(s.name) ASC, "
        "LOWER(l.name) ASC, l.id ASC"
    )
    return normalized_sort, normalized_order, clause


def load_libraries_page(db, *, per_page: int, offset: int, order_clause: str):
    return db.query(
        f"""
        SELECT
{LIBRARIES_LIST_COLUMNS},
            s.name AS server_name,
            COUNT(DISTINCT mu.vodum_user_id) AS users_count
        FROM libraries l
        JOIN servers s ON s.id = l.server_id
        LEFT JOIN media_user_libraries mul ON mul.library_id = l.id
        LEFT JOIN media_users mu ON mu.id = mul.media_user_id
        GROUP BY l.id
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
        """,
        (per_page, offset),
    )


def count_libraries(db) -> int:
    total_row = db.query_one("SELECT COUNT(*) AS total FROM libraries")
    return int(total_row["total"] if total_row and total_row["total"] is not None else 0)


def load_server_detail(db, server_id: int):
    return db.query_one(
        f"SELECT {SERVER_DETAIL_COLUMNS} FROM servers WHERE id = ?",
        (server_id,),
    )


def count_server_libraries(db, server_id: int) -> int:
    total_row = db.query_one(
        "SELECT COUNT(*) AS total FROM libraries WHERE server_id = ?",
        (server_id,),
    )
    return int(total_row["total"] if total_row and total_row["total"] is not None else 0)


def load_server_libraries(db, server_id: int, *, per_page: int, offset: int):
    return db.query(
        f"""
        SELECT
{SERVER_DETAIL_LIBRARY_COLUMNS},
            COUNT(DISTINCT mu.vodum_user_id) AS users_count
        FROM libraries l
        LEFT JOIN media_user_libraries mul ON mul.library_id = l.id
        LEFT JOIN media_users mu ON mu.id = mul.media_user_id
        WHERE l.server_id = ?
        GROUP BY l.id
        ORDER BY LOWER(l.name), l.id
        LIMIT ? OFFSET ?
        """,
        (server_id, per_page, offset),
    )


def count_server_users(db, server_id: int) -> int:
    total_row = db.query_one(
        """
        SELECT COUNT(DISTINCT vu.id) AS total
        FROM vodum_users vu
        JOIN media_users mu
            ON mu.vodum_user_id = vu.id
        WHERE mu.server_id = ?
        """,
        (server_id,),
    )
    return int(total_row["total"] if total_row and total_row["total"] is not None else 0)


def load_server_users(db, server_id: int, *, per_page: int, offset: int):
    return db.query(
        """
        SELECT
            vu.id,
            vu.username,
            vu.email
        FROM vodum_users vu
        JOIN media_users mu
            ON mu.vodum_user_id = vu.id
        WHERE mu.server_id = ?
        GROUP BY vu.id
        ORDER BY LOWER(vu.username), vu.id
        LIMIT ? OFFSET ?
        """,
        (server_id, per_page, offset),
    )
