"""Shared rules for library/media association and Top played identities."""

from __future__ import annotations

import json


SERIES_TYPES = {"serie", "series", "show", "episode", "season", "tv", "tv_episode"}
JELLYFIN_LIBRARY_TYPES = {"collectionfolder", "userrootfolder"}


def normalize_library_section_id(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def jellyfin_library_section_id(now_playing: dict, item: dict, ancestors: list[dict]) -> str | None:
    """Return the Jellyfin collection-folder id without mistaking a season for a library."""
    for source in (now_playing or {}, item or {}):
        for key in ("CollectionFolderId", "LibraryId", "TopParentId"):
            value = normalize_library_section_id(source.get(key))
            if value:
                return value

    for ancestor in ancestors or []:
        ancestor_type = str(ancestor.get("Type") or "").strip().lower()
        collection_type = str(ancestor.get("CollectionType") or "").strip().lower()
        if ancestor_type in JELLYFIN_LIBRARY_TYPES or collection_type:
            value = normalize_library_section_id(ancestor.get("Id"))
            if value:
                return value
    return None


def stable_media_group_key(row: dict) -> str:
    row = dict(row or {})
    server_id = str(row.get("server_id") or "0")
    provider = str(row.get("provider") or "").strip().lower()
    media_type = str(row.get("media_type") or "").strip().lower()
    raw = row.get("raw_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    if media_type in SERIES_TYPES:
        if provider == "plex":
            series_id = ((raw.get("VideoOrTrack") or {}).get("grandparentRatingKey"))
        elif provider == "jellyfin":
            series_id = ((raw.get("NowPlayingItem") or {}).get("SeriesId") or raw.get("SeriesId"))
        else:
            series_id = None
        if series_id:
            return f"server:{server_id}|series-id:{series_id}"
        title = str(row.get("grandparent_title") or row.get("title") or "unknown").strip().lower()
        return f"server:{server_id}|series-title:{title}"

    media_key = normalize_library_section_id(row.get("media_key"))
    if media_key:
        return f"server:{server_id}|media:{media_key}"
    title = str(row.get("title") or "unknown").strip().lower()
    return f"server:{server_id}|title:{title}"


def stable_play_key(row: dict) -> str:
    """Keep repeated plays distinct while merging duplicate snapshots of one native session."""
    row = dict(row or {})
    server_id = str(row.get("server_id") or "0")
    session_key = normalize_library_section_id(row.get("session_key"))
    if session_key:
        started_at = str(row.get("started_at") or "")
        return f"server:{server_id}|session:{session_key}|started:{started_at}"

    viewer = (
        normalize_library_section_id(row.get("media_user_id"))
        or normalize_library_section_id(row.get("external_user_id"))
        or "unknown"
    )
    return "|".join(
        (
            f"server:{server_id}",
            f"viewer:{viewer}",
            f"media:{normalize_library_section_id(row.get('media_key')) or 'unknown'}",
            f"started:{row.get('started_at') or ''}",
            f"client:{str(row.get('client_name') or '').strip().lower()}",
        )
    )


def repair_unambiguous_library_associations(db, server_id: int) -> dict:
    """Repair missing library ids only when one compatible library is possible."""
    repaired = {"live": 0, "history": 0}
    type_groups = (
        (("movie",), ("movie", "movies")),
        (("serie", "series", "show", "episode", "season", "tv", "tv_episode"), ("show", "shows", "tv", "tvshows")),
        (("music", "track", "audio"), ("artist", "music", "musicvideos")),
    )

    for media_types, library_types in type_groups:
        media_marks = ",".join("?" for _ in media_types)
        library_marks = ",".join("?" for _ in library_types)
        row = db.query_one(
            f"""
            SELECT MIN(section_id) AS section_id, COUNT(*) AS cnt
            FROM libraries
            WHERE server_id=?
              AND LOWER(TRIM(COALESCE(type, ''))) IN ({library_marks})
            """,
            (server_id, *library_types),
        )
        if not row or int(row["cnt"] or 0) != 1:
            continue
        section_id = normalize_library_section_id(row["section_id"])
        if not section_id:
            continue

        for table_name, result_key in (("media_sessions", "live"), ("media_session_history", "history")):
            cursor = db.execute(
                f"""
                UPDATE {table_name}
                SET library_section_id=?
                WHERE server_id=?
                  AND COALESCE(NULLIF(TRIM(library_section_id), ''), '')=''
                  AND LOWER(TRIM(COALESCE(media_type, ''))) IN ({media_marks})
                """,
                (section_id, server_id, *media_types),
            )
            repaired[result_key] += max(0, int(getattr(cursor, "rowcount", 0) or 0))
    return repaired
