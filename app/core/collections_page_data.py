"""Audited read-only data for the initial Collections administration page."""
from db_manager import isolated_read_operation
from core.server_page_queries import LIBRARY_TYPE_SQL
from core.collections_repository import list_instances, collection_settings


@isolated_read_operation
def load_collections_page_data(db):
    libraries = [dict(row) for row in db.query(f"""
        SELECT l.id, l.name, l.server_id, s.name AS server_name, s.status AS server_status,
               LOWER(TRIM(s.type)) AS provider, {LIBRARY_TYPE_SQL} AS media_type
        FROM libraries l JOIN servers s ON s.id=l.server_id
        WHERE LOWER(TRIM(s.type)) IN ('plex', 'jellyfin')
        ORDER BY s.name COLLATE NOCASE, l.name COLLATE NOCASE, l.id
    """) or []]
    libraries = [row for row in libraries if row["media_type"] in ("movie", "shows")]
    arr_servers = [dict(row) for row in db.query("""
        SELECT id, name, LOWER(TRIM(type)) AS type FROM servers
        WHERE LOWER(TRIM(type)) IN ('radarr', 'sonarr') ORDER BY name COLLATE NOCASE
    """) or []]
    routes = {}
    if libraries:
        for row in db.query(f"""
            SELECT r.library_id, s.id, s.name
            FROM library_arr_routes r JOIN servers s ON s.id=r.arr_server_id
            JOIN libraries l ON l.id=r.library_id
            JOIN servers media_server ON media_server.id=l.server_id
            WHERE r.enabled=1 AND LOWER(TRIM(media_server.type)) IN ('plex', 'jellyfin')
              AND (({LIBRARY_TYPE_SQL}='movie' AND LOWER(TRIM(s.type))='radarr')
                OR ({LIBRARY_TYPE_SQL}='shows' AND LOWER(TRIM(s.type))='sonarr'))
            ORDER BY r.library_id,r.priority,r.arr_server_id
        """):
            routes.setdefault(row["library_id"], []).append({"id": row["id"], "name": row["name"]})
    for library in libraries:
        library["arr_routes"] = routes.get(library["id"], [])
    return {
        "libraries": libraries,
        "arr_servers": arr_servers,
        "instances": list_instances(db),
        "collection_settings": collection_settings(db),
    }
