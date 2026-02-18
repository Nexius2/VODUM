#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VODUM - Import Tautulli SQLite database into VODUM database.

Rules:
- Import watch history from Tautulli into VODUM: media_session_history only.
- Match Plex server by machineIdentifier stored in Tautulli: recently_added.pms_identifier
  -> match VODUM servers.server_identifier (type='plex')
  -> if no match:
      - keep_all_servers = 1 => create offline plex server and import into it
      - keep_all_servers = 0 => refuse import
- Users:
  - keep_all_users = 0 => import only if user exists in VODUM (media_users linked to vodum_users)
  - keep_all_users = 1 => create missing users as EXPIRED (vodum_users + media_users) so they won't trigger mails/policies
- Libraries:
  - import only if library_section_id exists in VODUM libraries for that server
- Dedup:
  - unique index on (server_id, media_user_id, started_at, media_key, client_name)
  - started_at can be truncated to minute (env-controlled)
- Delete uploaded tautulli.db after processing if configured.
"""

from __future__ import annotations

import os
import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

# -------------------------
# CONFIG (override via env)
# -------------------------
BATCH_SIZE = int(os.getenv("VODUM_TAUTULLI_BATCH_SIZE", "1000"))
DEDUP_TRUNCATE_TO_MINUTE = os.getenv("VODUM_TAUTULLI_DEDUP_MINUTE", "1") == "1"

STATUS_FILE = os.getenv("VODUM_TAUTULLI_IMPORT_STATUS_FILE", "/appdata/tautulli_import_status.json")


def _write_status_file(payload: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@dataclass
class ImportStats:
    scanned: int = 0
    inserted: int = 0
    skipped_unknown_user: int = 0
    skipped_unknown_library: int = 0
    skipped_missing_user_key: int = 0
    skipped_duplicates: int = 0
    skipped_missing_required: int = 0
    skipped_unknown_server: int = 0


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _safe_int(v, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _dt_from_unix(ts: int, truncate_to_minute: bool) -> str:
    """
    Convert unix epoch seconds -> 'YYYY-MM-DD HH:MM:SS' in UTC.
    If truncate_to_minute True, seconds -> 00.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if truncate_to_minute:
        dt = dt.replace(second=0, microsecond=0)
    else:
        dt = dt.replace(microsecond=0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_unique_index(conn: sqlite3.Connection) -> None:
    """
    Ensure the unique dedup index exists on media_session_history.

    IMPORTANT:
    On prod databases, old versions / bugs may have created duplicates already.
    Creating the UNIQUE index would then fail with:
      UNIQUE constraint failed: media_session_history.server_id, ...

    Strategy:
    - Try to create the unique index.
    - If it fails because duplicates exist, deduplicate (keep the "best" row),
      then retry index creation.
    """
    create_sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_media_session_history_tautulli_dedup
    ON media_session_history (server_id, media_user_id, started_at, media_key, client_name)
    """

    try:
        conn.execute(create_sql)
        conn.commit()
        return
    except sqlite3.IntegrityError:
        # Duplicates exist -> dedupe then retry
        pass

    # Deduplicate:
    # Keep 1 row per (server_id, media_user_id, started_at, media_key, client_name)
    # Prefer the row with the highest watch_ms, then highest duration_ms, then latest stopped_at, then highest id.
    #
    # Uses window functions (SQLite >= 3.25, which is very common).
    dedupe_sql = """
    DELETE FROM media_session_history
    WHERE id IN (
      SELECT id FROM (
        SELECT
          id,
          ROW_NUMBER() OVER (
            PARTITION BY server_id, media_user_id, started_at, media_key, client_name
            ORDER BY
              COALESCE(watch_ms, 0) DESC,
              COALESCE(duration_ms, 0) DESC,
              COALESCE(stopped_at, '') DESC,
              id DESC
          ) AS rn
        FROM media_session_history
      )
      WHERE rn > 1
    )
    """

    try:
        conn.execute("BEGIN")
        conn.execute(dedupe_sql)
        conn.execute(create_sql)
        conn.commit()
    except Exception:
        conn.rollback()
        # Fallback without window functions: keep the lowest id
        conn.execute("BEGIN")
        conn.execute(
            """
            DELETE FROM media_session_history
            WHERE id NOT IN (
              SELECT MIN(id)
              FROM media_session_history
              GROUP BY server_id, media_user_id, started_at, media_key, client_name
            )
            """
        )
        conn.execute(create_sql)
        conn.commit()



def _get_known_library_section_ids(vodum_conn: sqlite3.Connection, server_id: int) -> Set[str]:
    """
    Load known Plex library section ids from VODUM.

    Expected table: libraries with columns (server_id, section_id)
    """
    section_ids: Set[str] = set()
    cur = vodum_conn.execute(
        "SELECT section_id FROM libraries WHERE server_id = ? AND section_id IS NOT NULL",
        (server_id,),
    )
    for (sid,) in cur.fetchall():
        if sid is None:
            continue
        section_ids.add(str(sid))
    return section_ids


def _build_user_maps(vodum_conn: sqlite3.Connection, server_id: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Returns:
    - email_to_media_user_id: normalized email -> media_users.id (for this server)
    - username_to_media_user_id: normalized username -> media_users.id (for this server)

    NOTE:
    - Plex user is expected to have an email => we match ONLY on primary email (vu.email)
      and on the media_users.email (which should normally mirror the Plex email if stored).
    - We DO NOT match on vu.second_email on purpose.
    """
    email_map: Dict[str, int] = {}
    username_map: Dict[str, int] = {}

    cur = vodum_conn.execute(
        """
        SELECT mu.id, vu.email, vu.username, mu.email, mu.username
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE mu.server_id = ?
        """,
        (server_id,),
    )

    for mu_id, vu_email, vu_username, mu_email, mu_username in cur.fetchall():
        # Email: primary only (+ media_users.email if present)
        for e in (vu_email, mu_email):
            ne = _norm(e)
            if ne:
                email_map.setdefault(ne, int(mu_id))

        # Username (unchanged)
        for u in (vu_username, mu_username):
            nu = _norm(u)
            if nu:
                username_map.setdefault(nu, int(mu_id))

    return email_map, username_map



def _vodum_find_or_create_expired_user(
    db,  # DBManager
    server_id: int,
    email: str,
    username: str,
    external_user_id: str,
) -> int:
    """
    Create missing users as EXPIRED to avoid policies/mails.
    Returns media_users.id
    """
    email_n = _norm(email)
    username_n = _norm(username)

    # 1) find vodum_user
    vodum_user_id = None

    if email_n:
        r = db.query_one(
            """
            SELECT id FROM vodum_users
            WHERE lower(email)=? OR lower(second_email)=?
            LIMIT 1
            """,
            (email_n, email_n),
        )
        if r:
            vodum_user_id = int(r["id"])

    if vodum_user_id is None and username_n:
        r = db.query_one(
            "SELECT id FROM vodum_users WHERE lower(username)=? LIMIT 1",
            (username_n,),
        )
        if r:
            vodum_user_id = int(r["id"])

    # 2) create vodum_user if missing (EXPIRED)
    if vodum_user_id is None:
        display_username = username or (email.split("@")[0] if email and "@" in email else "unknown")
        db.execute(
            """
            INSERT INTO vodum_users(username, email, expiration_date, status, status_changed_at, notes)
            VALUES (?, ?, datetime('now','-1 day'), 'expired', CURRENT_TIMESTAMP, ?)
            """,
            (
                display_username,
                email or None,
                "Auto-created from Tautulli import (expired to avoid mails/policies).",
            ),
        )
        vodum_user_id = int(db.query_one("SELECT last_insert_rowid() AS id")["id"])

    # 3) find existing media_user
    r = db.query_one(
        """
        SELECT id FROM media_users
        WHERE server_id=?
          AND (
            (email IS NOT NULL AND lower(email)=?)
            OR lower(username)=?
            OR (external_user_id IS NOT NULL AND external_user_id=?)
          )
        LIMIT 1
        """,
        (int(server_id), email_n or "", username_n or "", external_user_id or ""),
    )
    if r:
        return int(r["id"])

    # 4) create media_user
    db.execute(
        """
        INSERT INTO media_users(server_id, vodum_user_id, external_user_id, username, email, type, raw_json)
        VALUES (?, ?, ?, ?, ?, 'plex', NULL)
        """,
        (int(server_id), int(vodum_user_id), external_user_id or None, username or "unknown", email or None),
    )
    return int(db.query_one("SELECT last_insert_rowid() AS id")["id"])


def _is_valid_tautulli_db(db_path: str) -> bool:
    """
    Reject SQLite files that are not a Tautulli DB.
    We validate presence of required tables used by this importer.
    """
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        required = {"users", "session_history", "session_history_metadata", "recently_added"}
        return required.issubset(tables)
    except Exception:
        return False

def _detect_pms_identifier(tconn: sqlite3.Connection) -> str | None:
    """
    Try to detect Plex server identifier (machineIdentifier) from a Tautulli DB.
    Tautulli schema varies depending on versions; the value may not be stored
    in a column literally named 'pms_identifier'.

    Strategy:
    1) Keep current behavior: look for a 'pms_identifier' column.
    2) If not found, scan tables for other likely column names (machine_identifier, server_identifier, pms_id, etc.)
       and pick the first plausible value.
    3) (Best effort) try config-like tables if present.
    """
    import re

    def _looks_like_machine_id(v: str) -> bool:
        v = (v or "").strip()
        # Plex machineIdentifier is typically 40 hex chars
        if re.fullmatch(r"[0-9a-fA-F]{40}", v):
            return True
        # fallback: accept other non-empty identifiers that look “id-like”
        return len(v) >= 12

    tables = [r[0] for r in tconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    # ---- 1) Original strict lookup on 'pms_identifier'
    preferred_tables = ["recently_added", "session_history", "session_history_metadata", "plex_servers", "servers"]
    tables_with_pms_identifier: list[str] = []
    for t in tables:
        try:
            cols = [row[1] for row in tconn.execute(f"PRAGMA table_info({t})").fetchall()]
            if "pms_identifier" in cols:
                tables_with_pms_identifier.append(t)
        except Exception:
            continue

    if tables_with_pms_identifier:
        ordered = [t for t in preferred_tables if t in tables_with_pms_identifier] + \
                  [t for t in tables_with_pms_identifier if t not in preferred_tables]
        for t in ordered:
            try:
                row = tconn.execute(
                    f"""
                    SELECT pms_identifier
                    FROM {t}
                    WHERE pms_identifier IS NOT NULL AND TRIM(pms_identifier) != ''
                    LIMIT 1
                    """
                ).fetchone()
                if row and row[0]:
                    val = str(row[0]).strip()
                    if _looks_like_machine_id(val):
                        return val
            except Exception:
                continue

    # ---- 2) Wider scan for other likely columns
    candidate_cols_exact = {
        "machine_identifier",
        "machineidentifier",
        "server_identifier",
        "serveridentifier",
        "pms_id",
        "pms_uuid",
        "pms_machine_identifier",
        "plex_machine_identifier",
        "plex_identifier",
    }

    def _is_candidate_col(col: str) -> bool:
        c = col.lower()
        if c in candidate_cols_exact:
            return True
        # heuristic: contains identifier/machine and mentions pms/plex/server
        if ("identifier" in c or "machine" in c) and any(k in c for k in ("pms", "plex", "server")):
            return True
        return False

    for t in preferred_tables + [t for t in tables if t not in preferred_tables]:
        try:
            cols = [row[1] for row in tconn.execute(f"PRAGMA table_info({t})").fetchall()]
        except Exception:
            continue

        cand_cols = [c for c in cols if _is_candidate_col(c)]
        for c in cand_cols:
            try:
                row = tconn.execute(
                    f"""
                    SELECT {c}
                    FROM {t}
                    WHERE {c} IS NOT NULL AND TRIM(CAST({c} AS TEXT)) != ''
                    LIMIT 1
                    """
                ).fetchone()
                if row and row[0] is not None:
                    val = str(row[0]).strip()
                    if _looks_like_machine_id(val):
                        return val
            except Exception:
                continue

    # ---- 3) Best-effort config table lookup (varies a lot depending on Tautulli versions)
    # Try common patterns: config(key,value) / settings(key,value) / prefs(pref,value) etc.
    config_tables = ["config", "settings", "prefs", "preferences"]
    config_keys = ["pms_identifier", "PMS_IDENTIFIER", "machine_identifier", "MACHINE_IDENTIFIER"]

    for ct in config_tables:
        if ct not in tables:
            continue
        try:
            cols = [row[1] for row in tconn.execute(f"PRAGMA table_info({ct})").fetchall()]
            cols_l = {c.lower() for c in cols}
        except Exception:
            continue

        # (key,value) style
        if "key" in cols_l and "value" in cols_l:
            try:
                row = tconn.execute(
                    f"""
                    SELECT value
                    FROM {ct}
                    WHERE key IN ({",".join(["?"] * len(config_keys))})
                    AND value IS NOT NULL AND TRIM(CAST(value AS TEXT)) != ''
                    LIMIT 1
                    """,
                    tuple(config_keys),
                ).fetchone()
                if row and row[0]:
                    val = str(row[0]).strip()
                    if _looks_like_machine_id(val):
                        return val
            except Exception:
                pass

        # (setting,value) style
        if "setting" in cols_l and "value" in cols_l:
            try:
                row = tconn.execute(
                    f"""
                    SELECT value
                    FROM {ct}
                    WHERE setting IN ({",".join(["?"] * len(config_keys))})
                    AND value IS NOT NULL AND TRIM(CAST(value AS TEXT)) != ''
                    LIMIT 1
                    """,
                    tuple(config_keys),
                ).fetchone()
                if row and row[0]:
                    val = str(row[0]).strip()
                    if _looks_like_machine_id(val):
                        return val
            except Exception:
                pass

    return None

def _tautulli_list_library_sections(tconn: sqlite3.Connection) -> list[dict]:
    # returns rows: {server_id, section_id, section_name, section_type}
    rows = tconn.execute(
        """
        SELECT server_id, section_id, section_name, section_type
        FROM library_sections
        """
    ).fetchall()
    out = []
    for r in rows:
        # sqlite row tuple
        out.append({
            "server_id": (r[0] or "").strip(),
            "section_id": str(r[1]).strip() if r[1] is not None else "",
            "section_name": (r[2] or "").strip(),
            "section_type": (r[3] or "").strip(),
        })
    return out


def _vodum_pick_server_by_library_overlap(db_conn, tautulli_sections: list[dict]) -> int | None:
    """
    Pick the VODUM Plex server that matches the most libraries from this Tautulli DB.
    Uses overlap on (section_name, section_type). Returns vodum server_id or None.
    Raises RuntimeError if ambiguous (tie).
    """
    # Load VODUM plex servers
    vodum_servers = db_conn.execute(
        "SELECT id, name FROM servers WHERE type='plex' ORDER BY name ASC"
    ).fetchall()
    if not vodum_servers:
        return None

    # Group tautulli libs (all servers in this DB, since we don't have a reliable server identifier)
    tautulli_set = set()
    for s in tautulli_sections:
        n = (s.get("section_name") or "").strip().lower()
        t = (s.get("section_type") or "").strip().lower()
        if n:
            tautulli_set.add((n, t))

    # Build overlap score per vodum server
    scores = []
    for vs in vodum_servers:
        vid = int(vs[0])
        vname = vs[1]

        vlibs = db_conn.execute(
            "SELECT name, type FROM libraries WHERE server_id=?",
            (vid,),
        ).fetchall()

        vodum_set = set()
        for (lname, ltype) in vlibs:
            lname = (lname or "").strip().lower()
            ltype = (ltype or "").strip().lower()
            if lname:
                vodum_set.add((lname, ltype))

        score = len(tautulli_set.intersection(vodum_set))
        scores.append((score, vid, vname))

    scores.sort(reverse=True, key=lambda x: x[0])
    best_score, best_id, _ = scores[0]

    if best_score <= 0:
        return None

    # ambiguity check (tie)
    ties = [s for s in scores if s[0] == best_score]
    if len(ties) > 1:
        msg = "Ambiguous Plex server mapping from Tautulli libraries. Candidates:\n"
        for sc, vid, vname in ties:
            msg += f"- server_id={vid} name={vname} overlap={sc}\n"
        msg += "Please select a target Plex server in the import options and retry."
        raise RuntimeError(msg)

    return best_id




def import_tautulli_db(
    db,
    tautulli_db_path: str,
    keep_all_users: bool = False,
    keep_all_libraries: bool = False,
    import_only_available_libraries: bool = True,
    target_server_id: int = 0,
) -> ImportStats:

    stats = ImportStats()

    # Open Tautulli DB (read-only is not guaranteed with sqlite3 stdlib, but we only SELECT)
    tconn = sqlite3.connect(tautulli_db_path)
    tconn.row_factory = sqlite3.Row

    try:
        # ------------------------------------------------------------
        # Determine Plex machineIdentifier from Tautulli DB
        # ------------------------------------------------------------

        # ------------------------------------------------------------
        # Choose VODUM Plex server (multi-server safe)
        # Strategy:
        # - if user forced a server_id -> use it
        # - else try direct match using pms_identifier (if present)
        # - else pick by overlap of libraries (and if tie -> ask user to choose)
        # ------------------------------------------------------------
        forced_server_id = int(target_server_id or 0)

        if forced_server_id > 0:
            chk = db.query_one("SELECT id FROM servers WHERE id=? AND type='plex'", (forced_server_id,))
            if not chk:
                raise RuntimeError(f"Selected target Plex server_id={forced_server_id} not found in VODUM.")
            vodum_server_id = forced_server_id
        else:
            # Try pms_identifier (some DBs have it)
            tautulli_server_identifier = _detect_pms_identifier(tconn)

            if tautulli_server_identifier:
                existing = db.query_one(
                    "SELECT id FROM servers WHERE type='plex' AND server_identifier=?",
                    (tautulli_server_identifier,),
                )
                if existing:
                    vodum_server_id = int(existing["id"])
                else:
                    # No direct match -> fallback to overlap
                    tautulli_sections = _tautulli_list_library_sections(tconn)
                    vodum_server_id = _vodum_pick_server_by_library_overlap(db.conn, tautulli_sections)
                    if not vodum_server_id:
                        raise RuntimeError(
                            "Unable to map this Tautulli DB to a Plex server in VODUM. "
                            "Please select a target Plex server in the import options and retry."
                        )
            else:
                # No pms_identifier -> overlap
                tautulli_sections = _tautulli_list_library_sections(tconn)
                vodum_server_id = _vodum_pick_server_by_library_overlap(db.conn, tautulli_sections)
                if not vodum_server_id:
                    raise RuntimeError(
                        "Unable to determine Plex server from this Tautulli DB (no pms_identifier). "
                        "Please select a target Plex server in the import options and retry."
                    )

        # Ensure dedup index exists (safe)
        _ensure_unique_index(db.conn)

        # Build a map section_id -> vodum library_id
        tautulli_sections = _tautulli_list_library_sections(tconn)

        vodum_lib_map = {}  # section_id (str) -> library_id (int)
        for s in tautulli_sections:
            section_id = (s.get("section_id") or "").strip()
            if not section_id:
                continue

            row = db.query_one(
                "SELECT id FROM libraries WHERE server_id=? AND section_id=?",
                (vodum_server_id, section_id),
            )
            if row:
                vodum_lib_map[section_id] = int(row["id"])
                continue

            if keep_all_libraries:
                # create placeholder library in VODUM
                db.execute(
                    """
                    INSERT OR IGNORE INTO libraries(server_id, section_id, name, type, item_count)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (vodum_server_id, section_id, s.get("section_name") or f"Library {section_id}", s.get("section_type") or None),
                )
                row2 = db.query_one(
                    "SELECT id FROM libraries WHERE server_id=? AND section_id=?",
                    (vodum_server_id, section_id),
                )
                if row2:
                    vodum_lib_map[section_id] = int(row2["id"])
            else:
                # only_existing: do not map -> sessions in this library will be skipped
                pass

        if import_only_available_libraries and not vodum_lib_map:
            raise RuntimeError(
                "No matching libraries found between Tautulli and VODUM for the selected Plex server. "
                "Sync libraries in VODUM first, or use 'Keep all libraries'."
            )


        # Build user map
        email_to_mu, username_to_mu = _build_user_maps(db.conn, vodum_server_id)

        # ------------------------------------------------------------
        # Extract sessions
        # We use COALESCE(u.email, sh.user) for email.
        # ------------------------------------------------------------
        q = """
        SELECT
          sh.reference_id        AS session_key,
          sh.started             AS started,
          sh.stopped             AS stopped,
          sh.rating_key          AS rating_key,
          sh.section_id          AS section_id,
          sh.ip_address          AS ip_address,
          sh.player              AS player,
          sh.product             AS product,
          sh.platform            AS platform,
          sh.paused_counter      AS paused_counter,
          sh.media_type          AS sh_media_type,
          u.user_id              AS plex_user_id,
          u.username             AS u_username,
          COALESCE(u.email, sh.user) AS u_email,
          m.media_type           AS m_media_type,
          m.title                AS title,
          m.parent_title         AS parent_title,
          m.grandparent_title    AS grandparent_title,
          m.duration             AS duration_ms,
          m.guid                 AS guid
        FROM session_history sh
        LEFT JOIN users u
          ON u.user_id = sh.user_id
        LEFT JOIN session_history_metadata m
          ON m.id = sh.id

        ORDER BY sh.started ASC
        """

        cur = tconn.execute(q)

        insert_sql = """
        INSERT OR IGNORE INTO media_session_history (
          server_id, provider,
          session_key, media_key,
          external_user_id, media_user_id,
          media_type, title, grandparent_title, parent_title,
          started_at, stopped_at,
          duration_ms, watch_ms,
          client_name, device, raw_json, ip, client_product,
          library_section_id
        )
        VALUES (
          ?, ?, ?, ?,
          ?, ?,
          ?, ?, ?, ?,
          ?, ?,
          ?, ?,
          ?, ?, ?, ?, ?,
          ?
        )
        """

        batch: List[Tuple] = []

        def flush_batch() -> None:
            nonlocal batch
            if not batch:
                return

            before = db.conn.total_changes
            db.executemany(insert_sql, batch)
            after = db.conn.total_changes

            inserted_now = max(0, after - before)
            stats.inserted += inserted_now
            stats.skipped_duplicates += max(0, len(batch) - inserted_now)

            batch = []

        for row in cur:
            stats.scanned += 1

            section_id = str(row["section_id"] or "").strip()

            if not section_id:
                stats.skipped_unknown_library += 1
                continue

            if import_only_available_libraries and section_id not in vodum_lib_map:
                stats.skipped_unknown_library += 1
                continue


            email_raw = row["u_email"]
            username_raw = row["u_username"]

            email = _norm(email_raw)
            username = _norm(username_raw)

            media_user_id: Optional[int] = None
            if email:
                media_user_id = email_to_mu.get(email)
            if media_user_id is None and username:
                media_user_id = username_to_mu.get(username)

            external_user_id = row["plex_user_id"]
            external_user_id = str(external_user_id) if external_user_id is not None else ""

            if media_user_id is None:
                if keep_all_users:
                    if not email and not username and not external_user_id:
                        stats.skipped_missing_user_key += 1
                        continue

                    media_user_id = _vodum_find_or_create_expired_user(
                        db,
                        server_id=vodum_server_id,
                        email=email_raw or "",
                        username=username_raw or "",
                        external_user_id=external_user_id,
                    )
                    # refresh maps
                    if email:
                        email_to_mu[email] = int(media_user_id)
                    if username:
                        username_to_mu[username] = int(media_user_id)
                else:
                    if email or username:
                        stats.skipped_unknown_user += 1
                    else:
                        stats.skipped_missing_user_key += 1
                    continue

            started = _safe_int(row["started"])
            stopped = _safe_int(row["stopped"])
            if started <= 0 or stopped <= 0 or stopped < started:
                stats.skipped_missing_required += 1
                continue

            started_at = _dt_from_unix(started, truncate_to_minute=DEDUP_TRUNCATE_TO_MINUTE)
            stopped_at = _dt_from_unix(stopped, truncate_to_minute=False)

            media_key = row["rating_key"]
            if media_key is None:
                stats.skipped_missing_required += 1
                continue
            media_key = str(media_key)

            client_name = (row["player"] or "").strip()

            paused = _safe_int(row["paused_counter"])
            watch_s = max(0, (stopped - started - paused))
            watch_ms = watch_s * 1000

            duration_ms = _safe_int(row["duration_ms"], default=0)

            media_type = row["m_media_type"] or row["sh_media_type"] or ""
            title = row["title"] or ""
            parent_title = row["parent_title"] or ""
            grandparent_title = row["grandparent_title"] or ""

            raw_json = json.dumps(
                {
                    "tautulli": {
                        "guid": row["guid"],
                        "platform": row["platform"],
                    }
                },
                ensure_ascii=False,
            )

            ip = (row["ip_address"] or "").strip()
            device = (row["platform"] or "").strip()
            client_product = (row["product"] or "").strip()

            batch.append(
                (
                    int(vodum_server_id),
                    "plex",
                    str(row["session_key"] or ""),
                    media_key,
                    external_user_id,
                    int(media_user_id),
                    str(media_type),
                    str(title),
                    str(grandparent_title),
                    str(parent_title),
                    started_at,
                    stopped_at,
                    int(duration_ms),
                    int(watch_ms),
                    client_name,
                    device,
                    raw_json,
                    ip,
                    client_product,
                    vodum_lib_map.get(section_id),
                )
            )

            if len(batch) >= BATCH_SIZE:
                flush_batch()

        flush_batch()
        return stats

    finally:
        try:
            tconn.close()
        except Exception:
            pass




def run(task_id, db):
    """
    Entrypoint VODUM tasks_engine:
    - takes 1 queued job in tautulli_import_jobs
    - set running
    - import
    - persist stats_json + status file for UI
    - optional: email admin when done
    """
    from logging_utils import get_logger
    from email_sender import send_email

    logger = get_logger("task_import_tautulli")

    job = db.query_one(
        """
        SELECT *
        FROM tautulli_import_jobs
        WHERE status='queued'
        ORDER BY created_at ASC
        LIMIT 1
        """
    )

    if not job:
        # log explicite + compteur pour diagnostiquer "upload ok mais rien importé"
        row_cnt = db.query_one("SELECT COUNT(*) AS c FROM tautulli_import_jobs WHERE status='queued'")
        queued_count = int(row_cnt["c"]) if row_cnt and row_cnt["c"] is not None else 0
        logger.info(f"No queued Tautulli import job found (queued_count={queued_count})")
        return {"status": "idle", "message": "no queued job", "queued_count": queued_count}


    job_d = dict(job)

    job_id = int(job_d["id"])
    file_path = (job_d.get("file_path") or "").strip()
    keep_all_users = int(job_d.get("keep_all_users") or 0) == 1
    keep_all_libraries = int(job_d.get("keep_all_libraries") or 0) == 1
    import_only_available_libraries = int(job_d.get("import_only_available_libraries") or 1) == 1
    target_server_id = int(job_d.get("target_server_id") or 0)



    db.execute(
        """
        UPDATE tautulli_import_jobs
        SET status='running', started_at=CURRENT_TIMESTAMP, last_error=NULL
        WHERE id=? AND status='queued'
        """,
        (job_id,),
    )

    if not file_path or not os.path.exists(file_path):
        err = f"File not found: {file_path}"
        db.execute(
            """
            UPDATE tautulli_import_jobs
            SET status='error', finished_at=CURRENT_TIMESTAMP, last_error=?
            WHERE id=?
            """,
            (err, job_id),
        )
        _write_status_file({"status": "error", "job_id": job_id, "error": err})
        logger.error(err)
        return {"status": "error", "error": err}

    if not _is_valid_tautulli_db(file_path):
        err = "Invalid Tautulli database (missing required tables)"
        db.execute(
            """
            UPDATE tautulli_import_jobs
            SET status='error', finished_at=CURRENT_TIMESTAMP, last_error=?
            WHERE id=?
            """,
            (err, job_id),
        )
        _write_status_file({"status": "error", "job_id": job_id, "error": err})
        logger.error(err)
        # IMPORTANT: do not return before cleanup -> handled in finally below
        return {"status": "error", "job_id": job_id, "error": err}


    try:
        stats = import_tautulli_db(
            db,
            file_path,
            keep_all_users=keep_all_users,
            keep_all_libraries=keep_all_libraries,
            import_only_available_libraries=import_only_available_libraries,
            target_server_id=target_server_id,
        )

        payload = {
            "scanned": stats.scanned,
            "inserted": stats.inserted,
            "skipped_duplicates": stats.skipped_duplicates,
            "skipped_unknown_user": stats.skipped_unknown_user,
            "skipped_unknown_library": stats.skipped_unknown_library,
            "skipped_missing_user_key": stats.skipped_missing_user_key,
            "skipped_missing_required": stats.skipped_missing_required,
        }

        db.execute(
            """
            UPDATE tautulli_import_jobs
            SET status='success', finished_at=CURRENT_TIMESTAMP, stats_json=?, last_error=NULL
            WHERE id=?
            """,
            (json.dumps(payload, ensure_ascii=False), job_id),
        )

        _write_status_file({"status": "success", "job_id": job_id, "stats": payload})
        logger.info(f"Tautulli import success (job_id={job_id}) {payload}")

        # optional admin email...
        try:
            settings = db.query_one("SELECT * FROM settings WHERE id=1")
            if settings:
                settings_d = dict(settings)
                if int(settings_d.get("mailing_enabled") or 0) == 1:
                    to_email = (settings_d.get("admin_email") or "").strip()
                    if to_email:
                        subject = "VODUM - Tautulli import completed"
                        body = "Import completed successfully.\n\n" + json.dumps(payload, indent=2, ensure_ascii=False)
                        ok, err2 = send_email(subject, body, to_email, settings_d)
                        if not ok:
                            logger.warning(f"Email notification failed: {err2}")
        except Exception as e:
            logger.warning(f"Notification step failed: {e}")

        return {"status": "success", "job_id": job_id, "stats": payload}

    except Exception as e:
        err = str(e)
        db.execute(
            """
            UPDATE tautulli_import_jobs
            SET status='error', finished_at=CURRENT_TIMESTAMP, last_error=?
            WHERE id=?
            """,
            (err[:2000], job_id),
        )

        _write_status_file({"status": "error", "job_id": job_id, "error": err})
        logger.error(f"Tautulli import failed (job_id={job_id}): {err}", exc_info=True)
        return {"status": "error", "job_id": job_id, "error": err}

    finally:
        # Always delete the uploaded file AFTER processing attempt (success or error)
        try:
            os.remove(file_path)
            logger.info(f"Deleted uploaded Tautulli DB after processing: {file_path}")
        except FileNotFoundError:
            logger.warning(f"Tautulli DB already deleted: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to delete Tautulli DB '{file_path}': {e}")



def main():
    from db_manager import DBManager
    import argparse
    from logging_utils import get_logger

    logger = get_logger("task_import_tautulli_cli")

    p = argparse.ArgumentParser(description="Import Tautulli database into VODUM.")
    p.add_argument("--tautulli-db", required=True)
    p.add_argument("--keep-all-users", action="store_true")
    p.add_argument("--keep-all-libraries", action="store_true")
    p.add_argument("--target-server-id", type=int, default=0)
    args = p.parse_args()

    db = DBManager()

    stats = import_tautulli_db(
        db,
        args.tautulli_db,
        keep_all_users=bool(args.keep_all_users),
        keep_all_libraries=bool(args.keep_all_libraries),
        import_only_available_libraries=not bool(args.keep_all_libraries),
        target_server_id=int(args.target_server_id or 0),
    )

    logger.info("=== Tautulli import completed ===")
    logger.info(f"Scanned: {stats.scanned}")
    logger.info(f"Inserted: {stats.inserted}")
    logger.info(f"Skipped (duplicates): {stats.skipped_duplicates}")
    logger.info(f"Skipped (unknown user): {stats.skipped_unknown_user}")
    logger.info(f"Skipped (unknown lib): {stats.skipped_unknown_library}")
    logger.info(f"Skipped (invalid row): {stats.skipped_missing_required}")




if __name__ == "__main__":
    main()
