from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests


from core.monitoring.diff import compute_session_events
from core.monitoring.mappers import resolve_media_user_id
from core.providers.registry import get_provider
from logging_utils import get_logger

logger = get_logger("monitoring.collector")


class AttrDict(dict):
    """
    Permet l'accès dict + attribut :
      srv["local_url"] ET srv.local_url
    Utile car certains providers utilisent encore server.local_url.
    """
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'AttrDict' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value



def _iso_now() -> str:
    # SQLite CURRENT_TIMESTAMP => "YYYY-MM-DD HH:MM:SS" (UTC)
    return datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")



def _load_single_server(db, server_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one(
        """
        SELECT id, type, url, local_url, public_url, token, server_identifier, settings_json
        FROM servers
        WHERE id = ?
          AND type IN ('plex','jellyfin')
        LIMIT 1
        """,
        (server_id,),
    )
    return AttrDict(dict(row)) if row else None


def _load_all_servers(db) -> List[Dict[str, Any]]:
    rows = db.query(
        """
        SELECT id, type, url, local_url, public_url, token, server_identifier, settings_json
        FROM servers
        WHERE type IN ('plex','jellyfin')
        ORDER BY id
        """
    )
    return [AttrDict(dict(r)) for r in rows]


def _fetch_existing_sessions(db, server_id: int) -> Dict[str, Dict[str, Any]]:
    rows = db.query(
        """
        SELECT session_key, state, progress_ms, media_key, external_user_id
        FROM media_sessions
        WHERE server_id = ?
        """,
        (server_id,),
    )

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[str(r["session_key"])] = {
            "session_key": str(r["session_key"]),
            "state": r["state"],
            "progress_ms": r["progress_ms"],
            "media_key": r["media_key"],
            "external_user_id": r["external_user_id"],
        }
    return out

def _has_recent_live_sessions(db, server_id: int, window_seconds: int = 180) -> bool:
    row = db.query_one(
        """
        SELECT COUNT(*) AS c
        FROM media_sessions
        WHERE server_id = ?
          AND datetime(last_seen_at) >= datetime('now', ?)
        """,
        (server_id, f"-{int(window_seconds)} seconds"),
    )
    try:
        return int(row["c"] or 0) > 0
    except Exception:
        return False


def _classify_status_from_exception(e: Exception) -> str:
    """
    Classe un statut serveur à partir d'une exception.
    Important: certains providers (ex: Jellyfin) encapsulent les erreurs requests
    dans un RuntimeError("... unreachable ...") avec __cause__ = RequestException.
    On déroule donc la chaîne des exceptions.
    """
    def iter_chain(exc: Exception):
        seen = set()
        cur = exc
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            yield cur
            cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)

    chain = list(iter_chain(e))

    # 1) Si dans la chaîne on trouve une vraie erreur réseau requests => DOWN
    for exc in chain:
        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return "down"

    # 2) Si dans la chaîne on trouve un HTTPError => classifier selon code
    for exc in chain:
        if isinstance(exc, requests.exceptions.HTTPError):
            resp = getattr(exc, "response", None)
            code = getattr(resp, "status_code", None)
            if code in (401, 403):
                return "unknown"  # auth/token
            if code and int(code) >= 500:
                return "down"
            return "unknown"

    # 3) Heuristique message: "unreachable"/"connection"/"timed out" => DOWN
    # (utile si le provider relance un RuntimeError avec ce texte)
    msg = " | ".join([(str(x) or "").lower() for x in chain])
    if any(k in msg for k in ("unreachable", "connection", "timed out", "timeout", "refused", "name or service not known")):
        return "down"

    # 4) Config manquante => UNKNOWN
    if any(k in msg for k in ("missing", "token", "url")):
        return "unknown"

    return "unknown"



def collect_sessions_for_server(
    db,
    server_id: int,
    provider: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Collecte Now Playing pour 1 serveur.
    - upsert media_sessions
    - insert media_events
    - push history sur stop
    - met à jour servers.last_checked et servers.status
    """
    srv = _load_single_server(db, server_id)


    
    if not srv:
        raise RuntimeError(f"Server id={server_id} not found or not plex/jellyfin")

    provider_name = (provider or (srv["type"] if "type" in srv else None) or "").lower().strip()
    if provider_name not in ("plex", "jellyfin"):
        raise RuntimeError(f"Unsupported provider '{provider_name}' for server id={server_id}")

    report = {"server_id": server_id, "provider": provider_name, "sessions_seen": 0, "events": 0}

    # IMPORTANT : si ça plante (auth/timeout/provider bug), on marque le serveur DOWN
    try:
        provider_impl = get_provider(srv)
        prev_map = _fetch_existing_sessions(db, server_id)

        current = provider_impl.get_active_sessions()  # liste normalisée
        report["sessions_seen"] = len(current)

        cur_map = {str(s["session_key"]): s for s in current if s.get("session_key")}

        # --- upsert + events (start/pause/resume/state_change)
        for sk, sess in cur_map.items():
            prev = prev_map.get(sk)
            events = compute_session_events(prev, sess)
            report["events"] += len(events)

            media_user_id = resolve_media_user_id(
                db,
                server_id,
                provider,
                sess.get("external_user_id"),
                sess.get("username"),
            )


            started_at = _iso_now() if "start" in events else None

            db.execute(
                """
                INSERT INTO media_sessions (
                  server_id, provider, session_key,
                  media_user_id, external_user_id,
                  media_key, media_type, title, grandparent_title, parent_title,
                  state, progress_ms, duration_ms,
                  is_transcode, bitrate, video_codec, audio_codec,
                  client_name, client_product, device, ip,
                  started_at, last_seen_at, raw_json, library_section_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, session_key) DO UPDATE SET
                  media_user_id=excluded.media_user_id,
                  external_user_id=excluded.external_user_id,

                  media_key=COALESCE(excluded.media_key, media_sessions.media_key),
                  media_type=COALESCE(excluded.media_type, media_sessions.media_type),
                  title=COALESCE(excluded.title, media_sessions.title),
                  grandparent_title=COALESCE(excluded.grandparent_title, media_sessions.grandparent_title),
                  parent_title=COALESCE(excluded.parent_title, media_sessions.parent_title),

                  state=excluded.state,
                  progress_ms=excluded.progress_ms,
                  duration_ms=COALESCE(excluded.duration_ms, media_sessions.duration_ms),

                  is_transcode=excluded.is_transcode,
                  bitrate=excluded.bitrate,
                  video_codec=excluded.video_codec,
                  audio_codec=excluded.audio_codec,
                  client_name=excluded.client_name,
                  client_product=excluded.client_product,
                  device=excluded.device,
                  ip=excluded.ip,

                  started_at=COALESCE(media_sessions.started_at, excluded.started_at, excluded.last_seen_at),
                  last_seen_at=excluded.last_seen_at,
                  raw_json=excluded.raw_json,
                  library_section_id=COALESCE(excluded.library_section_id, media_sessions.library_section_id)
                """,
                (
                    server_id, provider_name, sk,
                    media_user_id, sess.get("external_user_id"),
                    sess.get("media_key"), sess.get("media_type"),
                    sess.get("title"), sess.get("grandparent_title"), sess.get("parent_title"),
                    sess.get("state"), sess.get("progress_ms"), sess.get("duration_ms"),
                    int(bool(sess.get("is_transcode", 0))), sess.get("bitrate"),
                    sess.get("video_codec"), sess.get("audio_codec"),
                    sess.get("client_name"), sess.get("client_product"),
                    sess.get("device"), sess.get("ip"),
                    started_at, _iso_now(), sess.get("raw_json"),
                    sess.get("library_section_id"),
                ),
            )

            for ev in events:
                db.execute(
                    """
                    INSERT INTO media_events (
                      server_id, provider, event_type, ts,
                      session_key, media_user_id, external_user_id,
                      media_key, media_type, title,
                      payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_id, provider_name, ev, _iso_now(),
                        sk, media_user_id, sess.get("external_user_id"),
                        sess.get("media_key"), sess.get("media_type"), sess.get("title"),
                        json.dumps(sess, ensure_ascii=False),
                    ),
                )

        # --- stop + history + delete (sessions disparues)
        for sk, prev in prev_map.items():
            if sk in cur_map:
                continue

            report["events"] += 1

            db.execute(
                """
                INSERT INTO media_events (
                  server_id, provider, event_type, ts,
                  session_key, external_user_id, media_key, payload_json
                )
                VALUES (?, ?, 'stop', ?, ?, ?, ?, ?)
                """,
                (
                    server_id, provider_name, _iso_now(),
                    sk, prev.get("external_user_id"), prev.get("media_key"),
                    json.dumps(prev, ensure_ascii=False),
                ),
            )

            live = db.query_one(
                """
                SELECT *
                FROM media_sessions
                WHERE server_id=? AND session_key=?
                """,
                (server_id, sk),
            )

            if live:
                live = dict(live)  # ✅ sqlite3.Row -> dict (permet .get)
                watch_ms = int(live.get("progress_ms") or 0)
                started_at = live.get("started_at") or live.get("last_seen_at") or _iso_now()

                db.execute(
                    """
                    INSERT INTO media_session_history (
                      server_id, provider,
                      session_key, media_key, external_user_id, media_user_id,
                      media_type, title, grandparent_title, parent_title,
                      started_at, stopped_at,
                      duration_ms, watch_ms,
                      peak_bitrate, was_transcode,
                      client_name, client_product, device, ip,
                      raw_json, library_section_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_id, provider_name,
                        live.get("session_key"), live.get("media_key"), live.get("external_user_id"), live.get("media_user_id"),
                        live.get("media_type"), live.get("title"), live.get("grandparent_title"), live.get("parent_title"),
                        started_at, _iso_now(),
                        int(live.get("duration_ms") or 0), watch_ms,
                        int(live.get("bitrate") or 0) if live.get("bitrate") is not None else None,
                        int(live.get("is_transcode") or 0),

                        live.get("client_name"),
                        live.get("client_product"),
                        live.get("device"),
                        live.get("ip"),

                        live.get("raw_json"),
                        live.get("library_section_id"),
                    ),
                )


            db.execute("DELETE FROM media_sessions WHERE server_id=? AND session_key=?", (server_id, sk))

        # OK:
        # - si sessions actives => UP
        # - sinon, API a répondu => UP aussi (serveur joignable, juste idle)
        status = "up"
        db.execute(
            "UPDATE servers SET last_checked=CURRENT_TIMESTAMP, status=? WHERE id=?",
            (status, server_id),
        )
        return report

    except Exception as e:
        # Log en base pour diagnostic (et éviter "offline" injustifié)
        logger.exception("collect_sessions_for_server failed (server_id=%s)", server_id)


        # Règle d’or: si on a une session récente, on reste UP
        if _has_recent_live_sessions(db, server_id, window_seconds=180):
            db.execute(
                "UPDATE servers SET last_checked=CURRENT_TIMESTAMP, status='up' WHERE id=?",
                (server_id,),
            )
            raise

        # Sinon, on classe intelligemment
        status = _classify_status_from_exception(e)
        db.execute(
            "UPDATE servers SET last_checked=CURRENT_TIMESTAMP, status=? WHERE id=?",
            (status, server_id),
        )
        raise



def collect_sessions(db) -> Dict[str, Any]:
    """
    Wrapper debug (collecte tous les serveurs).
    """
    report = {"servers": 0, "sessions_seen": 0, "events": 0, "errors": []}
    servers = _load_all_servers(db)
    report["servers"] = len(servers)

    for srv in servers:
        server_id = int(srv["id"])
        provider_name = (srv["type"] or "").lower().strip()

        try:
            r = collect_sessions_for_server(db, server_id=server_id, provider=provider_name, payload=None)
            report["sessions_seen"] += int(r.get("sessions_seen", 0))
            report["events"] += int(r.get("events", 0))
        except Exception as e:
            report["errors"].append({"server_id": server_id, "provider": provider_name, "error": str(e)})

    return report
