from __future__ import annotations

import xml.etree.ElementTree as ET


def plex_section_total_items(
    session,
    base_url: str,
    token: str,
    section_id: str,
    timeout: int = 10,
) -> int | None:
    response = session.get(
        f"{base_url.rstrip('/')}/library/sections/{section_id}/all",
        headers={"X-Plex-Token": token},
        params={
            "X-Plex-Container-Start": 0,
            "X-Plex-Container-Size": 0,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    container = (
        root
        if root.tag == "MediaContainer"
        else root.find("MediaContainer")
    )
    if container is None:
        return None
    total = container.attrib.get("totalSize") or container.attrib.get("size")
    try:
        return int(total)
    except (TypeError, ValueError):
        return None


def get_media_user_library_ids_for_server(
    db,
    media_user_id: int,
    server_id: int,
) -> set[int]:
    rows = db.query(
        """
        SELECT mul.library_id
        FROM media_user_libraries mul
        JOIN libraries l ON l.id = mul.library_id
        WHERE mul.media_user_id = ?
          AND l.server_id = ?
        """,
        (media_user_id, server_id),
    ) or []
    return {
        int(row["library_id"])
        for row in rows
        if row["library_id"] is not None
    }


def apply_media_user_library_diff_for_server(
    db,
    media_user_id: int,
    server_id: int,
    desired_library_ids: set[int],
):
    current = get_media_user_library_ids_for_server(
        db,
        media_user_id,
        server_id,
    )
    to_add = sorted(desired_library_ids - current)
    to_remove = sorted(current - desired_library_ids)
    for library_id in to_add:
        db.execute(
            """
            INSERT OR IGNORE INTO media_user_libraries(
                media_user_id, library_id
            )
            VALUES (?, ?)
            """,
            (media_user_id, library_id),
        )
    for library_id in to_remove:
        db.execute(
            """
            DELETE FROM media_user_libraries
            WHERE media_user_id = ? AND library_id = ?
            """,
            (media_user_id, library_id),
        )
    return current, to_add, to_remove
