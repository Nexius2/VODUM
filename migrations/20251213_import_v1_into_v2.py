#!/usr/bin/env python3
"""
VODUM – IMPORT DATABASE V1 → V2 (REBUILD STRATEGY)

Ce script :
- lit une base V1 sauvegardée (lecture seule)
- importe les données utiles dans une base V2 propre
- ne modifie JAMAIS la base V1
- suppose que le schéma V2 est déjà créé (tables.sql V2 exécuté)

IMPORTANT :
- La DB V1 est attachée via ATTACH DATABASE AS v1
- La DB V2 active reste le schéma principal (main)

Usage :
    python3 20251213_import_v1_into_v2.py /appdata/backups/database_v1_YYYYMMDD.db
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

V2_DB_PATH = Path("/appdata/database.db")

# ---------------------------------------------------------------------------
# Logging simple (stdout + docker logs)
# ---------------------------------------------------------------------------

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} | {level:<7} | import_v1_to_v2 | {message}")

def fatal(message: str):
    log("ERROR", message)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Validation des arguments
# ---------------------------------------------------------------------------

if len(sys.argv) != 2:
    fatal("Usage: python3 20251213_import_v1_into_v2.py <v1_database_path>")

V1_DB_PATH = Path(sys.argv[1])

if not V1_DB_PATH.exists():
    fatal(f"Base V1 introuvable : {V1_DB_PATH}")

if not V2_DB_PATH.exists():
    fatal(f"Base V2 introuvable : {V2_DB_PATH}")

log("INFO", f"Base V1 source : {V1_DB_PATH}")
log("INFO", f"Base V2 cible  : {V2_DB_PATH}")

# ---------------------------------------------------------------------------
# Connexion DB V2 (principale)
# ---------------------------------------------------------------------------

conn = sqlite3.connect(V2_DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON;")

cur = conn.cursor()

# ---------------------------------------------------------------------------
# Attacher la DB V1 comme base secondaire
# ---------------------------------------------------------------------------

log("INFO", "Attachement de la base V1")
conn.execute(
    "ATTACH DATABASE ? AS v1",
    (str(V1_DB_PATH),)
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def table_exists(schema: str, table: str) -> bool:
    cur.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cur.fetchone() is not None

def count_rows(table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]

# ---------------------------------------------------------------------------
# Pré-checks : tables V1 requises
# ---------------------------------------------------------------------------

REQUIRED_V1_TABLES = [
    "users",
    "servers",
    "libraries",
    "user_servers",
    "shared_libraries",
]

for table in REQUIRED_V1_TABLES:
    if not table_exists("v1", table):
        fatal(f"Table V1 manquante : {table}")

log("INFO", "Toutes les tables V1 requises sont présentes")

# ---------------------------------------------------------------------------
# IMPORT USERS
# ---------------------------------------------------------------------------

log("INFO", "Import des users")

def get_columns(schema: str, table: str) -> set[str]:
    cur.execute(f"PRAGMA {schema}.table_info({table})")
    return {row["name"] for row in cur.fetchall()}

v1_user_columns = get_columns("v1", "users")
log("INFO", f"Colonnes V1.users détectées : {sorted(v1_user_columns)}")

def col_or_default(col: str, default: str = "NULL") -> str:
    return col if col in v1_user_columns else default


sql_users = f"""
INSERT INTO users (
    plex_id,
    username,
    firstname,
    lastname,
    email,
    second_email,
    avatar,
    notes,
    expiration_date,
    renewal_method,
    renewal_date,
    creation_date,
    status,
    last_status,
    status_changed_at,
    created_at
)
SELECT
    plex_id,
    username,
    {col_or_default("firstname")},
    {col_or_default("lastname")},
    {col_or_default("email")},
    {col_or_default("second_email")},
    {col_or_default("avatar")},
    {col_or_default("notes")},
    {col_or_default("expiration_date", "'9999-12-31'")},
    {col_or_default("renewal_method")},
    {col_or_default("renewal_date")},
    {col_or_default("creation_date")},
    CASE
        WHEN {col_or_default("status")} IN ('active','pre_expired','reminder','expired')
            THEN {col_or_default("status")}
        ELSE 'expired'
    END,
    {col_or_default("last_status")},
    {col_or_default("status_changed_at")},
    {col_or_default("created_at", "CURRENT_TIMESTAMP")}
FROM v1.users;
"""

cur.execute(sql_users)
log("INFO", f"Users importés : {count_rows('users')}")


log("INFO", f"Users importés : {count_rows('users')}")

# ---------------------------------------------------------------------------
# IMPORT SERVERS
# ---------------------------------------------------------------------------

log("INFO", "Import des servers")

cur.execute("""
    INSERT INTO servers (
        name,
        server_identifier,
        type,
        url,
        local_url,
        public_url,
        token,
        tautulli_url,
        tautulli_api_key,
        last_checked,
        status
    )
    SELECT
        name,
        server_id,          -- V1.server_id → V2.server_identifier
        type,
        url,
        local_url,
        public_url,
        token,
        tautulli_url,
        tautulli_api_key,
        last_checked,
        server_status       -- V1.server_status → V2.status
    FROM v1.servers
""")

log("INFO", f"Servers importés : {count_rows('servers')}")

# ---------------------------------------------------------------------------
# IMPORT LIBRARIES
# ---------------------------------------------------------------------------

log("INFO", "Import des libraries")

cur.execute("""
    INSERT INTO libraries (
        server_id,
        section_id,
        name,
        type
    )
    SELECT
        s2.id,
        l1.section_id,
        l1.name,
        NULL
    FROM v1.libraries l1
    JOIN v1.servers s1
        ON s1.server_id = l1.server_id
    JOIN servers s2
        ON s2.server_identifier = s1.server_id
""")

log("INFO", f"Libraries importées : {count_rows('libraries')}")

# ---------------------------------------------------------------------------
# IMPORT USER ↔ SERVER
# ---------------------------------------------------------------------------

log("INFO", "Import des accès user ↔ server")

cur.execute("""
    INSERT INTO user_servers (
        user_id,
        server_id,
        allow_sync,
        allow_camera_upload,
        allow_channels,
        filter_movies,
        filter_television,
        filter_music,
        source
    )
    SELECT
        u2.id,
        s2.id,
        us1.allow_sync,
        us1.allow_camera_upload,
        us1.allow_channels,
        us1.filter_movies,
        us1.filter_television,
        us1.filter_music,
        us1.source
    FROM v1.user_servers us1
    JOIN v1.users u1
        ON u1.id = us1.user_id
    JOIN users u2
        ON u2.plex_id = u1.plex_id
    JOIN v1.servers s1
        ON s1.server_id = us1.server_id
    JOIN servers s2
        ON s2.server_identifier = s1.server_id
""")

log("INFO", f"Accès user_servers importés : {count_rows('user_servers')}")

# ---------------------------------------------------------------------------
# IMPORT USER ↔ LIBRARY
# ---------------------------------------------------------------------------

log("INFO", "Import des accès user ↔ library")

cur.execute("""
    INSERT INTO shared_libraries (
        user_id,
        library_id
    )
    SELECT
        u2.id,
        l2.id
    FROM v1.shared_libraries sl1
    JOIN v1.users u1
        ON u1.id = sl1.user_id
    JOIN users u2
        ON u2.plex_id = u1.plex_id
    JOIN v1.libraries l1
        ON l1.id = sl1.library_id
    JOIN libraries l2
        ON l2.section_id = l1.section_id
""")

log("INFO", f"Accès shared_libraries importés : {count_rows('shared_libraries')}")

# ---------------------------------------------------------------------------
# Finalisation
# ---------------------------------------------------------------------------

conn.commit()

log("INFO", "Import V1 → V2 terminé avec succès 🎉")

conn.close()
