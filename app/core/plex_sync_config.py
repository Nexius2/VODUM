from __future__ import annotations


def get_plex_user_import_mode(db) -> str:
    row = db.query_one("SELECT plex_user_import_mode FROM settings LIMIT 1")
    if not row:
        return "global"
    value = str(row["plex_user_import_mode"] or "global").strip().lower()
    return value if value in {"global", "shared_only"} else "global"
