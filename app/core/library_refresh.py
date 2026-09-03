from core.providers.registry import get_provider


class LibraryRefreshError(Exception):
    def __init__(self, flash_key: str):
        super().__init__(flash_key)
        self.flash_key = flash_key


def refresh_library(db, library_id: int) -> str:
    row = db.query_one(
        """
        SELECT
            l.id AS library_id,
            l.section_id,
            s.id,
            s.type,
            s.url,
            s.local_url,
            s.public_url,
            s.token,
            s.server_identifier,
            s.settings_json
        FROM libraries l
        JOIN servers s ON s.id = l.server_id
        WHERE l.id = ?
        LIMIT 1
        """,
        (library_id,),
    )
    if not row:
        raise LibraryRefreshError("library_not_found")

    server = dict(row)
    provider_name = str(server.get("type") or "").strip().lower()
    if provider_name not in ("plex", "jellyfin"):
        raise LibraryRefreshError("unsupported_server_type")

    get_provider(server).refresh_library(str(server.get("section_id") or ""))
    return provider_name
