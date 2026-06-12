"""Destination-only execution for migration campaigns."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from core.providers.jellyfin_users import (
    jellyfin_create_user,
    jellyfin_set_password,
    jellyfin_set_policy_folders,
)
from core.providers.plex_users import plex_invite_and_share
from secret_store import encrypt_secret


def _dict(row) -> dict:
    return dict(row) if row is not None else {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _result_json(migration_user: dict) -> dict:
    try:
        result = json.loads(migration_user.get("result_json") or "{}")
    except Exception:
        result = {}
    return result if isinstance(result, dict) else {}


def _schedule_plex_reminders(db, campaign: dict, migration_user: dict, vodum_user: dict, server_id: int, result: dict) -> dict:
    invited_at = str(result.get("plex_invited_at") or "").strip()
    if not invited_at:
        return result
    try:
        invited = datetime.strptime(invited_at[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return result
    waiting_days = max(0, (datetime.utcnow() - invited).days)

    from communications_engine import (
        enqueue_named_task,
        schedule_template_notification,
        select_comm_templates_for_user,
    )

    templates = select_comm_templates_for_user(
        db=db,
        trigger_event="pending_invite_reminder",
        provider="plex",
        user_id=int(vodum_user["id"]),
    )
    queued = 0
    scheduled_templates = {
        int(template_id)
        for template_id in result.get("plex_reminder_templates", [])
        if str(template_id).isdigit()
    }
    for template in templates:
        template_id = int(template["id"])
        if template_id in scheduled_templates:
            continue
        try:
            delay_days = max(0, int(template.get("days_after") or 0))
        except (TypeError, ValueError):
            delay_days = 0
        if waiting_days < delay_days:
            continue
        schedule_template_notification(
            db=db,
            template_id=template_id,
            user_id=int(vodum_user["id"]),
            provider="plex",
            server_id=int(server_id),
            send_at_modifier=None,
            payload={
                "trigger_event": "pending_invite_reminder",
                "username": vodum_user.get("username") or "",
                "email": vodum_user.get("email") or "",
                "pending_invite_days": waiting_days,
                "migration_campaign_id": int(campaign["id"]),
            },
            dedupe_key=(
                f"migration_pending_invite:campaign:{campaign['id']}:"
                f"user:{migration_user['id']}:template:{template_id}"
            ),
            max_attempts=10,
        )
        scheduled_templates.add(template_id)
        queued += 1
    if queued:
        enqueue_named_task(db, "send_expiration_emails")
        result["plex_reminder_templates"] = sorted(scheduled_templates)
        result["plex_reminder_count"] = len(scheduled_templates)
        result["plex_last_reminder_at"] = _utc_now()
    return result


def _mapping_for_user(db, campaign_id: int, source_server_id: int, vodum_user_id: int) -> list[dict]:
    return [
        _dict(row)
        for row in db.query(
            """
            SELECT mlm.source_library_id, mlm.destination_library_id,
                   l.name AS destination_name, l.section_id AS destination_section_id
            FROM migration_library_mappings mlm
            JOIN media_user_libraries source_access
              ON source_access.library_id = mlm.source_library_id
            JOIN media_users source_account
              ON source_account.id = source_access.media_user_id
             AND source_account.server_id = ?
             AND source_account.vodum_user_id = ?
            LEFT JOIN libraries l ON l.id = mlm.destination_library_id
            WHERE mlm.campaign_id = ?
            ORDER BY mlm.id
            """,
            (source_server_id, vodum_user_id, campaign_id),
        )
    ]


def _destination_account(db, vodum_user_id: int, server_id: int) -> dict | None:
    row = db.query_one(
        """
        SELECT *
        FROM media_users
        WHERE vodum_user_id = ? AND server_id = ?
        ORDER BY id ASC LIMIT 1
        """,
        (vodum_user_id, server_id),
    )
    return _dict(row) if row else None


def _ensure_library_links(db, media_user_id: int, destination_library_ids: list[int]) -> None:
    for library_id in destination_library_ids:
        db.execute(
            "INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id) VALUES (?, ?)",
            (media_user_id, library_id),
        )


def _ensure_plex_destination(db, campaign: dict, migration_user: dict, vodum_user: dict, mappings: list[dict]) -> str:
    server = _dict(db.query_one("SELECT * FROM servers WHERE id = ?", (campaign["destination_server_id"],)))
    account = _destination_account(db, int(vodum_user["id"]), int(server["id"]))
    email = str(vodum_user.get("email") or (account or {}).get("email") or "").strip()
    if not email:
        raise ValueError("Email is required for a Plex destination.")

    destination_library_ids = [int(item["destination_library_id"]) for item in mappings if item.get("destination_library_id")]
    library_names = [str(item["destination_name"]) for item in mappings if item.get("destination_name")]
    if not destination_library_ids:
        raise ValueError("No destination library is mapped.")

    provider_result = plex_invite_and_share(
        server,
        email=email,
        libraries_names=library_names,
        raise_on_update_error=True,
    )
    result = _result_json(migration_user)
    result["plex_last_checked_at"] = _utc_now()
    if provider_result.get("invited") and not result.get("plex_invited_at"):
        result["plex_invited_at"] = _utc_now()
    if provider_result.get("is_pending") and not result.get("plex_invited_at"):
        result["plex_invited_at"] = _utc_now()
    if provider_result.get("is_friend"):
        result["plex_accepted_at"] = _utc_now()
        result["destination_validated_at"] = result.get("destination_validated_at") or _utc_now()
    elif provider_result.get("is_pending"):
        result = _schedule_plex_reminders(
            db, campaign, migration_user, vodum_user, int(server["id"]), result
        )
    details = {
        "migration_campaign_id": int(campaign["id"]),
        "plex_invite_state": {
            "state": provider_result.get("state") or ("friend" if provider_result.get("is_friend") else "pending"),
            "is_friend": bool(provider_result.get("is_friend")),
            "is_pending": bool(provider_result.get("is_pending")),
            "primary_server_id": int(server["id"]),
        },
    }
    if account:
        media_user_id = int(account["id"])
        db.execute(
            """
            UPDATE media_users
            SET external_user_id = COALESCE(?, external_user_id),
                username = COALESCE(?, username),
                email = ?,
                details_json = ?
            WHERE id = ?
            """,
            (
                provider_result.get("external_user_id"),
                provider_result.get("username"),
                email,
                json.dumps(details),
                media_user_id,
            ),
        )
    else:
        cursor = db.execute(
            """
            INSERT INTO media_users(
              server_id, vodum_user_id, external_user_id, username, email, type, details_json
            ) VALUES (?, ?, ?, ?, ?, 'plex', ?)
            """,
            (
                int(server["id"]),
                int(vodum_user["id"]),
                provider_result.get("external_user_id"),
                provider_result.get("username") or vodum_user.get("username") or email,
                email,
                json.dumps(details),
            ),
        )
        media_user_id = int(cursor.lastrowid)

    _ensure_library_links(db, media_user_id, destination_library_ids)
    db.execute(
        "UPDATE migration_users SET destination_media_user_id = ?, result_json = ? WHERE id = ?",
        (media_user_id, json.dumps(result), migration_user["id"]),
    )
    if provider_result.get("is_friend"):
        db.execute(
            """
            UPDATE media_users
            SET accepted_at=COALESCE(accepted_at,CURRENT_TIMESTAMP)
            WHERE id=?
            """,
            (media_user_id,),
        )
        return "completed"
    if provider_result.get("is_pending"):
        return "waiting_acceptance"
    raise RuntimeError("Plex invitation state could not be determined.")


def _ensure_jellyfin_destination(db, campaign: dict, migration_user: dict, vodum_user: dict, mappings: list[dict]) -> str:
    server = _dict(db.query_one("SELECT * FROM servers WHERE id = ?", (campaign["destination_server_id"],)))
    destination_library_ids = [int(item["destination_library_id"]) for item in mappings if item.get("destination_library_id")]
    enabled_folders = [str(item["destination_section_id"]) for item in mappings if item.get("destination_section_id")]
    if not destination_library_ids:
        raise ValueError("No destination library is mapped.")

    account = _destination_account(db, int(vodum_user["id"]), int(server["id"]))
    existing_result = _result_json(migration_user)
    account_created_by_campaign = False
    if account:
        media_user_id = int(account["id"])
        external_user_id = str(account.get("external_user_id") or "").strip()
        if not external_user_id:
            raise ValueError("Existing Jellyfin destination account has no native identifier.")
        try:
            account_details = json.loads(account.get("details_json") or "{}")
        except Exception:
            account_details = {}
        account_created_by_campaign = (
            int(account_details.get("migration_campaign_id") or 0) == int(campaign["id"])
            or bool(existing_result.get("destination_created_at"))
        )
    else:
        username = str(vodum_user.get("username") or "").strip()
        if not username:
            raise ValueError("A username is required for a Jellyfin destination.")
        created = jellyfin_create_user(server, username)
        external_user_id = str(created.get("Id") or "").strip()
        if not external_user_id:
            raise RuntimeError("Jellyfin did not return a user identifier.")
        cursor = db.execute(
            """
            INSERT INTO media_users(
              server_id, vodum_user_id, external_user_id, username, email, type, details_json
            ) VALUES (?, ?, ?, ?, ?, 'jellyfin', ?)
            """,
            (
                int(server["id"]),
                int(vodum_user["id"]),
                external_user_id,
                created.get("Name") or username,
                vodum_user.get("email"),
                json.dumps({"migration_campaign_id": int(campaign["id"])}),
            ),
        )
        media_user_id = int(cursor.lastrowid)

    if (not account or account_created_by_campaign) and not existing_result.get("encrypted_generated_password"):
        generated_password = secrets.token_urlsafe(18)
        jellyfin_set_password(server, external_user_id, generated_password)
        existing_result = {
            **existing_result,
            "destination_media_user_id": media_user_id,
            "destination_created_at": existing_result.get("destination_created_at") or _utc_now(),
            "encrypted_generated_password": encrypt_secret(generated_password),
            "credentials_pending_delivery": True,
            "credentials_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        db.execute(
            "UPDATE migration_users SET destination_media_user_id = ?, result_json = ? WHERE id = ?",
            (media_user_id, json.dumps(existing_result), migration_user["id"]),
        )

    jellyfin_set_policy_folders(server, external_user_id, enabled_folders)
    _ensure_library_links(db, media_user_id, destination_library_ids)
    result = {**existing_result, "destination_media_user_id": media_user_id}
    db.execute(
        "UPDATE migration_users SET destination_media_user_id = ?, result_json = ? WHERE id = ?",
        (media_user_id, json.dumps(result), migration_user["id"]),
    )
    if account and not account_created_by_campaign:
        result["destination_validated_at"] = result.get("destination_validated_at") or _utc_now()
        result["destination_validation_method"] = result.get("destination_validation_method") or "existing_account"
        db.execute(
            "UPDATE migration_users SET result_json = ? WHERE id = ?",
            (json.dumps(result), migration_user["id"]),
        )
        return "completed"
    return "waiting_validation" if result.get("credentials_pending_delivery") else "completed"


def process_migration_user(db, campaign: dict, migration_user: dict) -> str:
    vodum_user = _dict(
        db.query_one(
            "SELECT id, username, email, status FROM vodum_users WHERE id = ?",
            (migration_user["vodum_user_id"],),
        )
    )
    if not vodum_user:
        raise ValueError("VODUM user no longer exists.")
    source_account = _dict(
        db.query_one(
            "SELECT username,email FROM media_users WHERE id=?",
            (migration_user.get("source_media_user_id"),),
        )
    )
    if not str(vodum_user.get("username") or "").strip():
        vodum_user["username"] = source_account.get("username")
    if not str(vodum_user.get("email") or "").strip():
        vodum_user["email"] = source_account.get("email")
    mappings = _mapping_for_user(
        db,
        int(campaign["id"]),
        int(campaign["source_server_id"]),
        int(migration_user["vodum_user_id"]),
    )
    provider = str(campaign["destination_type"] or "").lower()
    if provider == "plex":
        return _ensure_plex_destination(db, campaign, migration_user, vodum_user, mappings)
    if provider == "jellyfin":
        return _ensure_jellyfin_destination(db, campaign, migration_user, vodum_user, mappings)
    raise ValueError(f"Unsupported destination provider: {provider}")


def refresh_campaign_status(db, campaign_id: int) -> str:
    scheduled = _dict(
        db.query_one(
            """
            SELECT status, scheduled_at,
                   CASE WHEN datetime(scheduled_at) > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS is_future
            FROM migration_campaigns WHERE id=?
            """,
            (campaign_id,),
        )
    )
    if (
        scheduled.get("status") == "scheduled"
        and int(scheduled.get("is_future") or 0) == 1
    ):
        return "scheduled"
    row = _dict(
        db.query_one(
            """
            SELECT
              SUM(CASE WHEN status IN ('pending','processing') THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status IN ('waiting_acceptance','waiting_validation') THEN 1 ELSE 0 END) AS waiting,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM migration_users WHERE campaign_id = ?
            """,
            (campaign_id,),
        )
    )
    status = (
        "running" if int(row.get("pending") or 0) > 0
        else "waiting_users" if int(row.get("waiting") or 0) > 0
        else "needs_attention" if int(row.get("failed") or 0) > 0
        else "completed"
    )
    db.execute(
        """
        UPDATE migration_campaigns
        SET status = ?, updated_at = CURRENT_TIMESTAMP,
            completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END
        WHERE id = ?
        """,
        (status, status, campaign_id),
    )
    return status
