import json

from secret_store import (
    encrypt_secret,
    encrypt_server_settings_json,
    keep_existing_secret,
)
from tasks_engine import (
    enqueue_server_discovery_sequence,
    ensure_tasks_enabled,
    force_task_run,
    mark_auto_enable_dirty,
)


def prepare_new_server_secrets(settings: dict, token):
    settings_json = encrypt_server_settings_json(
        json.dumps(settings) if settings else None
    )
    return settings_json, encrypt_secret(token)


def insert_server(
    db,
    *,
    name: str,
    server_type: str,
    server_identifier: str,
    url: str,
    local_url,
    public_url,
    token,
    settings_json,
):
    return db.execute(
        """
        INSERT INTO servers (
            name,
            type,
            server_identifier,
            url,
            local_url,
            public_url,
            token,
            settings_json,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            server_type,
            server_identifier,
            url,
            local_url,
            public_url,
            token,
            settings_json,
            "unknown",
        ),
    )


def commit_server_creation(db) -> bool:
    try:
        db.commit()
    except Exception:
        return False
    return True


def queue_server_discovery(server_type: str, logger) -> bool:
    try:
        enqueue_server_discovery_sequence(server_type)
    except Exception as exc:
        logger.warning(f"Failed to queue sequence after server creation: {exc}")
        return False
    return True


def ensure_new_server_tasks() -> None:
    ensure_tasks_enabled(["check_servers", "update_user_status"])


def wake_new_server_tasks() -> None:
    mark_auto_enable_dirty()
    force_task_run("check_servers")


def server_creation_flash(server_type: str) -> tuple[str, str]:
    if server_type == "plex":
        return "plex_server_created_sync_planned", "success"
    if server_type == "jellyfin":
        return "jellyfin_server_created_sync_planned", "success"
    return "server_created_no_sync", "success"


def load_server_secrets(db, server_id: int):
    return db.query_one(
        "SELECT token, settings_json FROM servers WHERE id = ?",
        (server_id,),
    )


def decode_server_settings(row):
    if not row or not row["settings_json"]:
        return {}
    try:
        settings = json.loads(row["settings_json"])
    except Exception:
        return {}
    return settings


def merge_updated_server_settings(
    settings: dict,
    *,
    tautulli_url,
    tautulli_api_key,
    verify_tls: bool,
) -> dict:
    existing_tautulli = settings.get("tautulli")
    if not isinstance(existing_tautulli, dict):
        existing_tautulli = {}
    if tautulli_url is not None or tautulli_api_key is not None:
        settings["tautulli"] = {
            "url": tautulli_url or existing_tautulli.get("url"),
            "api_key": keep_existing_secret(
                tautulli_api_key,
                existing_tautulli.get("api_key"),
            ),
        }
    settings["verify_tls"] = bool(verify_tls)
    return settings


def prepare_updated_server_secrets(settings: dict, token, existing_token):
    settings_json = encrypt_server_settings_json(
        json.dumps(settings) if settings else None
    )
    encrypted_token = encrypt_secret(
        keep_existing_secret(token, existing_token)
    )
    return settings_json, encrypted_token


def wake_updated_server_tasks() -> None:
    mark_auto_enable_dirty()
    force_task_run("check_servers")


def update_server(
    db,
    server_id: int,
    *,
    name: str,
    server_type: str,
    url,
    local_url,
    public_url,
    token,
    settings_json,
    status,
):
    return db.execute(
        """
        UPDATE servers
        SET name = ?,
            type = ?,
            url = ?,
            local_url = ?,
            public_url = ?,
            token = ?,
            settings_json = ?,
            status = ?
        WHERE id = ?
        """,
        (
            name,
            server_type,
            url,
            local_url,
            public_url,
            token,
            settings_json,
            status,
            server_id,
        ),
    )
