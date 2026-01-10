#!/usr/bin/env python3
"""
VODUM – IMPORT DATABASE V1 → V2 (REBUILD STRATEGY)

- Lit une base V1 (attachée en "v1")
- Insère dans la DB V2 (main) déjà initialisée via tables.sql V2
- Ne modifie JAMAIS la V1

Usage:
    python3 20251213_import_v1_into_v2.py /appdata/backups/database_v1_to_import.db

Option:
    VODUM_DB_PATH=/appdata/database.db  (par défaut)
"""

import os
import sqlite3
import sys
import json
from datetime import datetime
from pathlib import Path


V2_DB_PATH = Path(os.environ.get("VODUM_DB_PATH", "/appdata/database.db"))


def log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} | {level:<5} | import_v1_to_v2 | {msg}")


def fatal(msg: str) -> None:
    log("ERROR", msg)
    sys.exit(1)


def table_exists(cur: sqlite3.Cursor, schema: str, table: str) -> bool:
    cur.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def normalize_status(v1_status: str | None) -> str:
    # V2 n'accepte que 4 valeurs
    if v1_status in ("active", "pre_expired", "reminder", "expired"):
        return v1_status
    return "expired"


def safe_json(obj) -> str | None:
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


def nz_str(*vals: object) -> str:
    """Retourne la 1ère valeur non vide (strip), sinon chaîne vide."""
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def main() -> None:
    if len(sys.argv) != 2:
        fatal("Usage: python3 20251213_import_v1_into_v2.py <v1_db_path>")

    v1_path = Path(sys.argv[1])
    if not v1_path.exists():
        fatal(f"Base V1 introuvable: {v1_path}")

    if not V2_DB_PATH.exists():
        fatal(f"Base V2 introuvable: {V2_DB_PATH}")

    conn = sqlite3.connect(V2_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    log("INFO", f"V1: {v1_path}")
    log("INFO", f"V2: {V2_DB_PATH}")

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("ATTACH DATABASE ? AS v1", (str(v1_path),))

    # Checks V1
    required_v1 = ["users", "servers", "libraries", "shared_libraries", "user_servers", "settings", "email_templates"]
    for t in required_v1:
        if not table_exists(cur, "v1", t):
            fatal(f"Table V1 manquante: {t}")

    # Checks V2
    required_v2 = [
        "vodum_users",
        "user_identities",
        "media_users",
        "servers",
        "libraries",
        "media_user_libraries",
        "settings",
        "email_templates",
    ]
    for t in required_v2:
        if not table_exists(cur, "main", t):
            fatal(f"Table V2 manquante (tables.sql pas exécuté ?): {t}")

    try:
        conn.execute("BEGIN")

        # ------------------------------------------------------------------
        # 1) SERVERS
        # ------------------------------------------------------------------
        log("INFO", "Import servers")
        v1_server_identifier_to_v2_id: dict[str, int] = {}

        cur.execute("SELECT * FROM v1.servers")
        for s in cur.fetchall():
            server_identifier = nz_str(s["server_id"])
            if not server_identifier:
                continue

            name = s["name"]
            server_type = nz_str(s["type"], s["server_type"], "plex")

            url = nz_str(s["url"], s["plex_url"])
            token = nz_str(s["token"], s["plex_token"])
            local_url = s["local_url"]
            public_url = s["public_url"]
            last_checked = s["last_checked"]
            status = nz_str(s["server_status"], s["plex_status"])

            settings_json = safe_json(
                {
                    "tautulli_url": s["tautulli_url"],
                    "tautulli_api_key": s["tautulli_api_key"],
                    "tautulli_status": s["tautulli_status"],
                }
            )

            cur.execute(
                """
                INSERT INTO servers (name, server_identifier, type, url, local_url, public_url, token, settings_json, last_checked, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, server_identifier, server_type, url or None, local_url, public_url, token or None, settings_json, last_checked, status or None),
            )
            v1_server_identifier_to_v2_id[server_identifier] = cur.lastrowid

        log("INFO", f"Servers importés: {len(v1_server_identifier_to_v2_id)}")

        # ------------------------------------------------------------------
        # 2) USERS -> vodum_users + user_identities (plex)
        # ------------------------------------------------------------------
        log("INFO", "Import users -> vodum_users + user_identities")
        v1_user_id_to_v2_vodum_user_id: dict[int, int] = {}

        cur.execute("SELECT * FROM v1.users")
        for u in cur.fetchall():
            v1_uid = int(u["id"])
            plex_id = nz_str(u["plex_id"])

            # ⚠️ éviter les NULL problématiques en aval : on calcule un "display name" fiable
            username = nz_str(u["username"], u["email"], u["firstname"], plex_id, f"user_{v1_uid}")

            cur.execute(
                """
                INSERT INTO vodum_users (
                    username, firstname, lastname, email, second_email,
                    expiration_date, renewal_method, renewal_date,
                    created_at, notes,
                    status, last_status, status_changed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, COALESCE(?, CURRENT_TIMESTAMP), NULL, ?, ?, ?)
                """,
                (
                    username,
                    u["firstname"],
                    u["lastname"],
                    u["email"],
                    u["second_email"],
                    u["expiration_date"],
                    None,  # created_at absent en V1
                    normalize_status(u["status"]),
                    u["last_status"],
                    u["status_changed_at"],
                ),
            )
            v2_vid = cur.lastrowid
            v1_user_id_to_v2_vodum_user_id[v1_uid] = v2_vid

            if plex_id:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO user_identities (vodum_user_id, type, server_id, external_user_id)
                    VALUES (?, 'plex', NULL, ?)
                    """,
                    (v2_vid, plex_id),
                )

        log("INFO", f"Vodum users importés: {len(v1_user_id_to_v2_vodum_user_id)}")

        # ------------------------------------------------------------------
        # 3) LIBRARIES
        # ------------------------------------------------------------------
        log("INFO", "Import libraries")
        v1_library_id_to_v2_library_id: dict[int, int] = {}

        cur.execute("SELECT * FROM v1.libraries")
        for l in cur.fetchall():
            v1_lid = int(l["id"])
            section_id = nz_str(l["section_id"])
            name = l["name"]
            v1_server_identifier = nz_str(l["server_id"])

            v2_server_id = v1_server_identifier_to_v2_id.get(v1_server_identifier)
            if not v2_server_id:
                continue

            cur.execute(
                """
                INSERT OR IGNORE INTO libraries (server_id, section_id, name, type)
                VALUES (?, ?, ?, NULL)
                """,
                (v2_server_id, section_id, name),
            )

            cur.execute("SELECT id FROM libraries WHERE server_id=? AND section_id=?", (v2_server_id, section_id))
            row = cur.fetchone()
            if row:
                v1_library_id_to_v2_library_id[v1_lid] = int(row["id"])

        log("INFO", f"Libraries importées: {len(v1_library_id_to_v2_library_id)}")

        # ------------------------------------------------------------------
        # 4) MEDIA_USERS (via user_servers)
        # ------------------------------------------------------------------
        log("INFO", "Import media_users (user_servers)")
        vodum_server_to_media_user_id: dict[tuple[int, int], int] = {}

        cur.execute("SELECT * FROM v1.user_servers")
        for us in cur.fetchall():
            v1_uid = int(us["user_id"])
            v1_server_identifier = nz_str(us["server_id"])

            v2_vid = v1_user_id_to_v2_vodum_user_id.get(v1_uid)
            v2_server_id = v1_server_identifier_to_v2_id.get(v1_server_identifier)
            if not v2_vid or not v2_server_id:
                continue

            cur.execute("SELECT username, email FROM vodum_users WHERE id=?", (v2_vid,))
            vu = cur.fetchone()
            if not vu:
                continue

            username = nz_str(vu["username"], vu["email"], f"user_{v2_vid}")

            # external_user_id = plex_id V1 si présent
            cur.execute("SELECT plex_id FROM v1.users WHERE id=?", (v1_uid,))
            urow = cur.fetchone()
            plex_id = nz_str(urow["plex_id"] if urow else None)

            details = {
                "source": us["source"],
                "allowSync": us["allow_sync"],
                "allowCameraUpload": us["allow_camera_upload"],
                "allowChannels": us["allow_channels"],
                "filterMovies": us["filter_movies"],
                "filterTelevision": us["filter_television"],
                "filterMusic": us["filter_music"],
            }

            cur.execute(
                """
                INSERT INTO media_users (
                    server_id, vodum_user_id,
                    external_user_id, username, email, avatar,
                    type, role, joined_at, accepted_at,
                    raw_json, details_json
                )
                VALUES (?, ?, ?, ?, ?, NULL, 'plex', NULL, NULL, NULL, NULL, ?)
                """,
                (v2_server_id, v2_vid, plex_id or None, username, vu["email"], safe_json(details)),
            )
            vodum_server_to_media_user_id[(v2_vid, v2_server_id)] = cur.lastrowid

        log("INFO", f"media_users créés: {len(vodum_server_to_media_user_id)}")

        # ------------------------------------------------------------------
        # 5) MEDIA_USER_LIBRARIES (via shared_libraries)
        # ------------------------------------------------------------------
        log("INFO", "Import media_user_libraries (shared_libraries)")
        inserted = 0

        cur.execute("SELECT * FROM v1.shared_libraries")
        for sl in cur.fetchall():
            v1_uid = int(sl["user_id"])
            v1_lid = int(sl["library_id"])

            v2_vid = v1_user_id_to_v2_vodum_user_id.get(v1_uid)
            v2_lid = v1_library_id_to_v2_library_id.get(v1_lid)
            if not v2_vid or not v2_lid:
                continue

            cur.execute("SELECT server_id FROM libraries WHERE id=?", (v2_lid,))
            lib = cur.fetchone()
            if not lib:
                continue
            v2_server_id = int(lib["server_id"])

            media_user_id = vodum_server_to_media_user_id.get((v2_vid, v2_server_id))
            if not media_user_id:
                # user a un share mais pas de user_servers => créer media_user minimal
                cur.execute("SELECT username, email FROM vodum_users WHERE id=?", (v2_vid,))
                vu = cur.fetchone()
                if not vu:
                    continue

                username = nz_str(vu["username"], vu["email"], f"user_{v2_vid}")

                cur.execute("SELECT plex_id FROM v1.users WHERE id=?", (v1_uid,))
                urow = cur.fetchone()
                plex_id = nz_str(urow["plex_id"] if urow else None)

                cur.execute(
                    """
                    INSERT INTO media_users (
                        server_id, vodum_user_id,
                        external_user_id, username, email, avatar,
                        type, role, joined_at, accepted_at,
                        raw_json, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, NULL, 'plex', NULL, NULL, NULL, NULL, NULL)
                    """,
                    (v2_server_id, v2_vid, plex_id or None, username, vu["email"]),
                )
                media_user_id = cur.lastrowid
                vodum_server_to_media_user_id[(v2_vid, v2_server_id)] = media_user_id

            cur.execute(
                """
                INSERT OR IGNORE INTO media_user_libraries (media_user_id, library_id)
                VALUES (?, ?)
                """,
                (media_user_id, v2_lid),
            )
            if cur.rowcount == 1:
                inserted += 1

        log("INFO", f"media_user_libraries ajoutés: {inserted}")

        # ------------------------------------------------------------------
        # 6) SETTINGS + EMAIL_TEMPLATES
        # ------------------------------------------------------------------
        log("INFO", "Import settings + email_templates")

        cur.execute("SELECT * FROM v1.settings WHERE id=1")
        s = cur.fetchone()
        if s:
            cur.execute(
                """
                INSERT OR REPLACE INTO settings (
                    id, mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass,
                    disable_on_expiry, delete_after_expiry_days, send_reminders,
                    default_language, timezone, admin_email,
                    enable_cron_jobs, default_expiration_days,
                    maintenance_mode, debug_mode
                )
                VALUES (
                    1, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?
                )
                """,
                (
                    s["mail_from"],
                    s["smtp_host"],
                    s["smtp_port"],
                    s["smtp_tls"],
                    s["smtp_user"],
                    s["smtp_pass"],
                    s["disable_on_expiry"],
                    s["delete_after_expiry_days"],
                    s["send_reminders"],
                    s["default_language"],
                    s["timezone"],
                    s["admin_email"],
                    s["enable_cron_jobs"],
                    s["default_expiration_days"],
                    s["maintenance_mode"],
                    s["debug_mode"],
                ),
            )

        cur.execute("SELECT * FROM v1.email_templates")
        for t in cur.fetchall():
            cur.execute(
                """
                INSERT OR REPLACE INTO email_templates (type, subject, days_before, body)
                VALUES (?, ?, COALESCE(?, 0), ?)
                """,
                (t["type"], t["subject"], t["days_before"], t["body"]),
            )

        # ------------------------------------------------------------------
        # 7) Forcer sortie maintenance (sans toucher schema_migrations)
        # ------------------------------------------------------------------
        cur.execute("INSERT OR IGNORE INTO settings (id, maintenance_mode) VALUES (1, 0)")
        cur.execute("UPDATE settings SET maintenance_mode = 0 WHERE id = 1")

        conn.commit()
        log("INFO", "Import V1 -> V2 terminé ✅")

    except Exception as e:
        conn.rollback()
        fatal(f"Erreur import: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
