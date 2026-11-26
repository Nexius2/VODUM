from __future__ import annotations

import xml.etree.ElementTree as ET

from core.library_access_repository import (
    apply_media_user_library_diff_for_server as apply_media_user_library_diff_for_server,
    get_media_user_library_ids_for_server as get_media_user_library_ids_for_server,
)


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
