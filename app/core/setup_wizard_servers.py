import uuid

from core.server_validation import validate_media_server
from core.setup_wizard_state import (
    decode_setup_wizard_state,
    load_setup_wizard_settings,
    save_setup_wizard_progress,
)
from secret_store import encrypt_secret, encrypt_server_settings_json
from tasks_engine import enqueue_server_discovery_sequence, ensure_tasks_enabled


def create_setup_media_server(
    db,
    *,
    server_type: str,
    url: str,
    token: str,
    expected_identifier: str | None = None,
) -> dict:
    server_type = str(server_type or "").strip().lower()
    url = str(url or "").strip().rstrip("/")
    token = str(token or "").strip()
    if (
        server_type not in {"plex", "jellyfin"}
        or not url.startswith(("http://", "https://"))
        or not token
    ):
        return {"ok": False, "reason": "setup_server_fields_required"}

    candidate = {
        "url": url,
        "local_url": None,
        "public_url": None,
        "settings_json": '{"verify_tls": true}',
    }
    validation = validate_media_server(
        server_type,
        url,
        token,
        server=candidate,
    )
    if validation[0] != "up":
        return {
            "ok": False,
            "reason": "setup_server_connection_failed",
            "detail": validation[3],
        }
    actual_identifier = str(validation[2] or "").strip()
    expected_identifier = str(expected_identifier or "").strip()
    if expected_identifier and actual_identifier != expected_identifier:
        return {"ok": False, "reason": "setup_server_identity_mismatch"}

    cursor = db.execute(
        """
        INSERT INTO servers(
          name,type,server_identifier,url,token,settings_json,status,server_version
        )
        SELECT ?,?,?,?,?,?,?,?
        WHERE NOT EXISTS (
          SELECT 1 FROM servers WHERE type=? AND server_identifier=?
        )
        """,
        (
            validation[1] or server_type.upper(),
            server_type,
            actual_identifier or str(uuid.uuid4()),
            url,
            encrypt_secret(token),
            encrypt_server_settings_json('{"verify_tls": true}'),
            "up",
            validation[3],
            server_type,
            actual_identifier,
        ),
    )
    if int(getattr(cursor, "rowcount", 1) or 0) == 0:
        return {"ok": False, "reason": "setup_server_duplicate"}
    server_id = int(cursor.lastrowid)
    sync_task = "sync_plex" if server_type == "plex" else "sync_jellyfin"
    ensure_tasks_enabled(["check_servers", sync_task, "update_user_status"])
    enqueue_server_discovery_sequence(server_type)
    return {"ok": True, "server_id": server_id, "server_type": server_type}


def record_setup_media_servers(db, server_ids) -> None:
    """Make externally-created validated servers visible to the active wizard."""
    normalized = set()
    for value in server_ids or ():
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return
    settings = load_setup_wizard_settings(db)
    if int(settings.get("wizard_active") or 0) != 1:
        return
    state = decode_setup_wizard_state(settings)
    for value in state.get("validated_server_ids") or ():
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    state["media_server"] = "configured"
    state["validated_server_ids"] = sorted(normalized)
    save_setup_wizard_progress(db, state=state)


def count_validated_setup_servers(db, state: dict) -> int:
    validated_ids = set()
    for value in state.get("validated_server_ids") or []:
        try:
            validated_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    if validated_ids:
        placeholders = ",".join("?" for _ in validated_ids)
        row = db.query_one(
            f"SELECT COUNT(*) AS cnt FROM servers WHERE id IN ({placeholders})",
            tuple(sorted(validated_ids)),
        )
        return int((row or {"cnt": 0})["cnt"] or 0)
    if state.get("media_server") == "configured":
        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        return int((row or {"cnt": 0})["cnt"] or 0)
    return 0
