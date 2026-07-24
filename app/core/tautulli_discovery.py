import sqlite3

from db_manager import open_sqlite_connection


def _is_valid_tautulli_db(db_path: str) -> bool:
    """
    Reject SQLite files that are not a Tautulli DB.
    We validate presence of required tables used by this importer.
    """
    try:
        conn = open_sqlite_connection(db_path, read_only=True)
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()
        required = {"users", "session_history", "session_history_metadata", "library_sections"}
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
