from __future__ import annotations

from core.plex_library_access import plex_section_total_items
from logging_utils import get_logger


log = get_logger("plex_library_sync")


def plex_get_libraries(server):
    from core.http_security import plex_server_http_session
    from core.plex_connection import find_working_plex_base_url
    from core.plex_rate_limit import wait_for_plex_slot

    base_url = find_working_plex_base_url(
        server,
        endpoint="/library/sections",
        accept="application/json",
    )
    token = (server.get("token") or "").strip()
    if not base_url or not token:
        log.error(
            "[SYNC LIBRARIES] Server %s without URL or token.",
            server["name"],
        )
        return []
    url = f"{base_url}/library/sections"
    try:
        wait_for_plex_slot(base_url)
        response = plex_server_http_session(server).get(
            url,
            headers={
                "X-Plex-Token": token,
                "Accept": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        log.error("[SYNC LIBRARIES] Error API %s: %s", url, exc)
        return []
    directories = response.json().get("MediaContainer", {}).get("Directory", [])
    libraries = [
        {
            "section_id": str(item.get("key")),
            "name": item.get("title"),
            "type": item.get("type", "unknown"),
        }
        for item in directories
    ]
    log.info(
        "[SYNC LIBRARIES] %s Libraries detected on %s",
        len(libraries),
        server["name"],
    )
    return libraries


def sync_plex_libraries(db, server, libraries):
    from core.http_security import plex_server_http_session
    from core.plex_connection import find_working_plex_base_url
    from core.plex_rate_limit import install_plex_rate_limit

    server_id = server["id"]
    base_url = find_working_plex_base_url(
        server,
        endpoint="/library/sections",
        accept="application/json",
    )
    token = (server.get("token") or "").strip()
    rows = [
        dict(row)
        for row in db.query(
            """
            SELECT id, section_id, name, type
            FROM libraries
            WHERE server_id = ?
            """,
            (server_id,),
        )
    ]
    normalize = lambda value: str(value or "").strip().casefold()
    by_section = {
        str(row["section_id"]): dict(row)
        for row in rows
        if str(row.get("section_id") or "").strip()
    }
    by_identity = {}
    for row in rows:
        key = (normalize(row.get("name")), normalize(row.get("type")))
        if key not in by_identity:
            by_identity[key] = dict(row)
        else:
            log.warning(
                "[SYNC LIBRARIES] Duplicate identity for server_id=%s "
                "name=%s type=%s (ids %s and %s)",
                server_id,
                row.get("name"),
                row.get("type"),
                by_identity[key]["id"],
                row["id"],
            )

    found_ids = set()
    session = plex_server_http_session(server)
    install_plex_rate_limit(session, base_url)
    for library in libraries:
        section_id = str(library.get("section_id") or "").strip()
        name = (library.get("name") or "").strip()
        library_type = (library.get("type") or "unknown").strip()
        if not section_id:
            log.warning(
                "[SYNC LIBRARIES] Skipped library without section_id "
                "on server_id=%s: %s",
                server_id,
                library,
            )
            continue

        identity = (normalize(name), normalize(library_type))
        matched = by_section.get(section_id)
        if matched:
            db.execute(
                "UPDATE libraries SET name = ?, type = ? WHERE id = ?",
                (name, library_type, matched["id"]),
            )
        elif identity in by_identity:
            matched = dict(by_identity[identity])
            old_section = str(matched.get("section_id") or "").strip()
            db.execute(
                """
                UPDATE libraries
                SET section_id = ?, name = ?, type = ?
                WHERE id = ?
                """,
                (section_id, name, library_type, matched["id"]),
            )
            matched.update(
                section_id=section_id,
                name=name,
                type=library_type,
            )
            by_section.pop(old_section, None)
            by_section[section_id] = matched
            by_identity[identity] = matched
        else:
            db.execute(
                """
                INSERT INTO libraries(server_id, section_id, name, type)
                VALUES (?, ?, ?, ?)
                """,
                (server_id, section_id, name, library_type),
            )
            inserted = db.query_one(
                """
                SELECT id, section_id, name, type
                FROM libraries
                WHERE server_id = ? AND section_id = ?
                """,
                (server_id, section_id),
            )
            matched = dict(inserted) if inserted else None
            if matched:
                by_section[section_id] = matched
                by_identity[identity] = matched

        if matched:
            found_ids.add(int(matched["id"]))
        if base_url and token:
            try:
                count = plex_section_total_items(
                    session,
                    base_url,
                    token,
                    section_id,
                    timeout=10,
                )
            except Exception:
                count = None
            if count is not None:
                db.execute(
                    """
                    UPDATE libraries SET item_count = ?
                    WHERE server_id = ? AND section_id = ?
                    """,
                    (int(count), server_id, section_id),
                )

    for row in rows:
        library_id = int(row["id"])
        if library_id in found_ids:
            continue
        db.execute(
            "DELETE FROM media_user_libraries WHERE library_id = ?",
            (library_id,),
        )
        db.execute(
            "DELETE FROM libraries WHERE id = ?",
            (library_id,),
        )
