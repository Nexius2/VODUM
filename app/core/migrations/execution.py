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
from secret_store import decrypt_secret, encrypt_secret


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


def _campaign_options(campaign: dict) -> dict:
    raw = campaign.get("options_json") or "{}"
    try:
        options = json.loads(raw)
    except Exception:
        options = {}
    return options if isinstance(options, dict) else {}


def _jellyfin_password_for_campaign(options: dict) -> tuple[str, str | None]:
    strategy = str(options.get("jellyfin_password_strategy") or "generated").strip().lower()
    if strategy not in {"generated", "admin_defined", "preserve_existing"}:
        strategy = "generated"
    if strategy != "admin_defined":
        return strategy, None
    encrypted = str(options.get("jellyfin_temp_password") or "").strip()
    if not encrypted:
        raise ValueError("A temporary Jellyfin password is required for this campaign.")
    password = decrypt_secret(encrypted)
    if not password:
        raise ValueError("The configured temporary Jellyfin password cannot be decrypted.")
    return strategy, password


def _schedule_jellyfin_credentials_delivery(
    db,
    *,
    campaign: dict,
    migration_user: dict,
    vodum_user: dict,
    server: dict,
    login_username: str,
    temporary_password: str,
    result: dict,
) -> dict:
    from communications_engine import (
        enqueue_named_task,
        schedule_template_notification,
        select_comm_template_for_user,
    )

    template = select_comm_template_for_user(
        db=db,
        trigger_event="user_creation",
        provider="jellyfin",
        user_id=int(vodum_user["id"]),
    )
    if not template:
        result["credentials_delivery_skipped_reason"] = "no_jellyfin_user_creation_template"
        return result

    try:
        days_after = int(template.get("days_after")) if template.get("days_after") is not None else 0
    except Exception:
        days_after = 0

    payload = {
        "trigger_event": "user_creation",
        "migration_campaign_id": int(campaign["id"]),
        "migration_user_id": int(migration_user["id"]),
        "username": vodum_user.get("username") or login_username,
        "email": vodum_user.get("email") or "",
        "server_name": server.get("name") or "Jellyfin",
        "server_url": server.get("public_url") or server.get("url") or server.get("local_url") or "",
        "login_username": login_username,
        "temporary_password": temporary_password,
    }
    dedupe_key = (
        f"migration_jellyfin_credentials:campaign:{campaign['id']}:"
        f"user:{migration_user['id']}:template:{int(template['id'])}"
    )
    schedule_template_notification(
        db=db,
        template_id=int(template["id"]),
        user_id=int(vodum_user["id"]),
        provider="jellyfin",
        server_id=int(server["id"]),
        send_at_modifier=f"+{days_after} days" if days_after > 0 else None,
        payload=payload,
        dedupe_key=dedupe_key,
        max_attempts=10,
    )
    enqueue_named_task(db, "send_expiration_emails")
    result["credentials_delivery_queued_at"] = result.get("credentials_delivery_queued_at") or _utc_now()
    result["credentials_delivery_template_id"] = int(template["id"])
    result.pop("credentials_delivery_skipped_reason", None)
    return result




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
    source_rows = db.query(
        """
        SELECT DISTINCT source_access.library_id AS source_library_id
        FROM media_user_libraries source_access
        JOIN media_users source_account
          ON source_account.id = source_access.media_user_id
         AND source_account.server_id = ?
         AND source_account.vodum_user_id = ?
        ORDER BY source_access.library_id
        """,
        (source_server_id, vodum_user_id),
    )
    source_library_ids = [int(row["source_library_id"]) for row in source_rows]
    if not source_library_ids:
        return []

    migration_user_row = db.query_one(
        "SELECT options_json FROM migration_users WHERE campaign_id=? AND vodum_user_id=? ORDER BY id LIMIT 1",
        (campaign_id, vodum_user_id),
    )
    try:
        options = json.loads(_dict(migration_user_row).get("options_json") or "{}")
    except Exception:
        options = {}
    raw_overrides = options.get("library_mapping_overrides") if isinstance(options, dict) else {}
    overrides: dict[int, list[int]] = {}
    if isinstance(raw_overrides, dict):
        for source_id, destination_ids in raw_overrides.items():
            try:
                parsed_source_id = int(source_id)
            except (TypeError, ValueError):
                continue
            parsed_destination_ids = []
            for destination_id in destination_ids or []:
                try:
                    parsed_destination_ids.append(int(destination_id))
                except (TypeError, ValueError):
                    continue
            overrides[parsed_source_id] = sorted(set(parsed_destination_ids))

    global_mapping: dict[int, list[int]] = {source_id: [] for source_id in source_library_ids}
    for row in db.query(
        """
        SELECT source_library_id, destination_library_id
        FROM migration_library_mappings
        WHERE campaign_id = ?
        ORDER BY id
        """,
        (campaign_id,),
    ):
        source_id = int(row["source_library_id"])
        if source_id not in global_mapping or not row["destination_library_id"]:
            continue
        destination_id = int(row["destination_library_id"])
        if destination_id not in global_mapping[source_id]:
            global_mapping[source_id].append(destination_id)

    selected_destination_ids = []
    mapping_by_source: dict[int, list[int]] = {}
    for source_id in source_library_ids:
        destination_ids = overrides[source_id] if source_id in overrides else global_mapping.get(source_id, [])
        mapping_by_source[source_id] = destination_ids
        for destination_id in destination_ids:
            if destination_id not in selected_destination_ids:
                selected_destination_ids.append(destination_id)
    if not selected_destination_ids:
        return []

    placeholders = ",".join("?" for _ in selected_destination_ids)
    destination_rows = db.query(
        f"SELECT id, name, section_id FROM libraries WHERE id IN ({placeholders})",
        tuple(selected_destination_ids),
    )
    destinations = {int(row["id"]): _dict(row) for row in destination_rows}
    resolved = []
    for source_id in source_library_ids:
        for destination_id in mapping_by_source.get(source_id, []):
            destination = destinations.get(int(destination_id))
            if not destination:
                continue
            resolved.append({
                "source_library_id": source_id,
                "destination_library_id": int(destination["id"]),
                "destination_name": destination.get("name"),
                "destination_section_id": destination.get("section_id"),
            })
    return resolved


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


def _media_user_library_ids(db, media_user_id: int) -> list[int]:
    return [
        int(row["library_id"])
        for row in db.query(
            "SELECT library_id FROM media_user_libraries WHERE media_user_id=? ORDER BY library_id",
            (int(media_user_id),),
        )
    ]


def _record_destination_access_delta(db, result: dict, media_user_id: int, destination_library_ids: list[int]) -> dict:
    before = set(_media_user_library_ids(db, media_user_id))
    desired = {int(library_id) for library_id in destination_library_ids}
    if "destination_access_before" not in result:
        result["destination_access_before"] = sorted(before)
    existing_added = {
        int(library_id)
        for library_id in result.get("destination_library_ids_added", [])
        if str(library_id).isdigit()
    }
    result["destination_library_ids_added"] = sorted(existing_added | (desired - before))
    return result


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

    result = _record_destination_access_delta(db, result, media_user_id, destination_library_ids)
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

    options = _campaign_options(campaign)
    password_strategy, admin_password = _jellyfin_password_for_campaign(options)
    should_set_password = not account or account_created_by_campaign
    if password_strategy == "preserve_existing" and account and not account_created_by_campaign:
        should_set_password = False

    if should_set_password and not existing_result.get("encrypted_generated_password"):
        credential_password = admin_password if password_strategy == "admin_defined" else secrets.token_urlsafe(18)
        jellyfin_set_password(server, external_user_id, credential_password)
        existing_result = {
            **existing_result,
            "destination_media_user_id": media_user_id,
            "destination_created_at": existing_result.get("destination_created_at") or _utc_now(),
            "encrypted_generated_password": encrypt_secret(credential_password),
            "credentials_pending_delivery": True,
            "credentials_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "jellyfin_password_strategy": password_strategy,
        }
        if options.get("jellyfin_auto_deliver_credentials"):
            existing_result = _schedule_jellyfin_credentials_delivery(
                db,
                campaign=campaign,
                migration_user=migration_user,
                vodum_user=vodum_user,
                server=server,
                login_username=str((account or {}).get("username") or vodum_user.get("username") or "").strip(),
                temporary_password=credential_password,
                result=existing_result,
            )
        db.execute(
            "UPDATE migration_users SET destination_media_user_id = ?, result_json = ? WHERE id = ?",
            (media_user_id, json.dumps(existing_result), migration_user["id"]),
        )

    jellyfin_set_policy_folders(server, external_user_id, enabled_folders)
    existing_result = _record_destination_access_delta(db, existing_result, media_user_id, destination_library_ids)
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
