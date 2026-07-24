from __future__ import annotations

from core.server_cooldown import (
    clear_server_cooldown,
    mark_server_unreachable,
    should_skip_unreachable_server,
)
from logging_utils import get_logger, is_debug_mode_enabled


log = get_logger("plex_sync_orchestrator")


def sync_all_servers(
    db,
    *,
    ensure_server_identity,
    sync_users,
    get_libraries,
    sync_libraries,
    sync_owner,
    find_base_url,
    sync_user_access,
):
    servers = db.query(
        """
        SELECT id, name, server_identifier, type, url, local_url, public_url,
               token, settings_json, server_version, unavailable_since,
               cooldown_until, last_failure, last_checked, status
        FROM servers
        WHERE type = 'plex'
        """
    )
    for row in servers:
        server = dict(row)
        if should_skip_unreachable_server(server):
            log.info(
                "[SYNC IDENTITY] skipped Plex server=%s id=%s because it is in cooldown",
                server.get("name"),
                server.get("id"),
            )
            continue
        ensure_server_identity(db, server)

    sync_users(db)
    if not servers:
        raise RuntimeError("No Plex server found in the database")

    any_success = False
    skipped_unreachable = 0
    for row in servers:
        server = dict(row)
        server_name = server.get("name") or f"server_{server.get('id')}"
        if should_skip_unreachable_server(server):
            skipped_unreachable += 1
            log.info(
                "[SYNC ALL] skipped Plex server=%s id=%s because it is down or in cooldown",
                server_name,
                server.get("id"),
            )
            continue

        try:
            libraries = get_libraries(server)
            sync_libraries(db, server, libraries)
            sync_owner(db, server)
        except Exception as exc:
            log.error(
                "[SYNC LIBS] Library synchronization error for %s: %s",
                server_name,
                exc,
                exc_info=is_debug_mode_enabled(),
            )
            mark_server_unreachable(
                db,
                int(server["id"]),
                str(exc),
                cooldown_seconds=300,
            )
            continue

        base_url = find_base_url(
            server,
            endpoint="/identity",
            accept="application/xml",
        )
        token = (server.get("token") or "").strip()
        if not base_url or not token:
            reason = "No working Plex URL or missing token"
            log.warning("[SYNC ACCESS] Server %s %s -> access ignored", server_name, reason)
            mark_server_unreachable(
                db,
                int(server["id"]),
                reason,
                cooldown_seconds=300,
            )
            continue

        try:
            from plexapi.server import PlexServer
            from core.http_security import plex_server_http_session
            from core.plex_rate_limit import install_plex_rate_limit

            session = plex_server_http_session(server, default_timeout=20)
            install_plex_rate_limit(session, base_url)
            response = session.get(f"{base_url}/identity")
            log.info(
                "[SYNC ACCESS] /identity OK (%s) HTTP=%s",
                server_name,
                response.status_code,
            )
            plex = PlexServer(base_url, token, session=session)
            sync_user_access(db, plex, server)
            db.execute(
                """
                UPDATE servers
                SET status = 'up', last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(server["id"]),),
            )
            clear_server_cooldown(db, int(server["id"]))
            any_success = True
        except Exception as exc:
            log.error(
                "[SYNC ACCESS] Connection or synchronization failed for %s: %s",
                server_name,
                exc,
                exc_info=is_debug_mode_enabled(),
            )
            mark_server_unreachable(
                db,
                int(server["id"]),
                str(exc),
                cooldown_seconds=300,
            )

    if not any_success and skipped_unreachable == len(servers):
        log.info("[SYNC ALL] all Plex servers skipped because they are unavailable")
    return {
        "success": any_success,
        "skipped_unreachable": skipped_unreachable,
        "server_count": len(servers),
    }
