"""Persistence helpers for migration drafts. No provider action is executed."""

from __future__ import annotations

import json

from core.migrations.analysis import analyze_migration
from secret_store import encrypt_secret


JELLYFIN_PASSWORD_STRATEGIES = {"generated", "admin_defined", "preserve_existing"}


def _clean_jellyfin_password_options(
    *,
    strategy: str = "generated",
    temp_password: str = "",
    auto_deliver_credentials: bool = False,
    existing_options: dict | None = None,
) -> dict:
    existing_options = existing_options or {}
    clean_strategy = str(strategy or "generated").strip().lower()
    if clean_strategy not in JELLYFIN_PASSWORD_STRATEGIES:
        clean_strategy = "generated"

    options = {
        "jellyfin_password_strategy": clean_strategy,
        "jellyfin_auto_deliver_credentials": 1 if auto_deliver_credentials else 0,
    }
    clean_password = str(temp_password or "").strip()
    if clean_strategy == "admin_defined":
        if clean_password:
            options["jellyfin_temp_password"] = encrypt_secret(clean_password)
        elif existing_options.get("jellyfin_temp_password"):
            options["jellyfin_temp_password"] = existing_options.get("jellyfin_temp_password")
        else:
            raise ValueError("A temporary Jellyfin password is required for this strategy.")
    return options


def _clean_draft_values(
    analysis: dict,
    *,
    name: str,
    safety_delay_days: int,
    scheduled_at: str,
    batch_size: int,
    intent: str,
    jellyfin_password_strategy: str = "generated",
    jellyfin_temp_password: str = "",
    jellyfin_auto_deliver_credentials: bool = False,
    existing_options: dict | None = None,
) -> dict:
    clean_intent = str(intent or "copy").strip().lower()
    if clean_intent not in {"copy", "progressive", "move"}:
        raise ValueError("Unsupported migration intent.")
    options = {"safety_delay_days": max(0, min(int(safety_delay_days), 365))}
    if str((analysis.get("destination") or {}).get("type") or "").lower() == "jellyfin":
        options.update(_clean_jellyfin_password_options(
            strategy=jellyfin_password_strategy,
            temp_password=jellyfin_temp_password,
            auto_deliver_credentials=jellyfin_auto_deliver_credentials,
            existing_options=existing_options,
        ))
    return {
        "name": str(name or "").strip() or f"{analysis['source']['name']} to {analysis['destination']['name']}",
        "intent": clean_intent,
        "options_json": json.dumps(options, sort_keys=True),
        "scheduled_at": str(scheduled_at or "").strip() or None,
        "batch_size": max(1, min(int(batch_size), 100)),
    }


def _replace_draft_snapshot(db, campaign_id: int, analysis: dict, source_server_id: int) -> None:
    db.execute("DELETE FROM migration_library_mappings WHERE campaign_id=?", (campaign_id,), commit=False)
    db.execute("DELETE FROM migration_steps WHERE migration_user_id IN (SELECT id FROM migration_users WHERE campaign_id=?)", (campaign_id,), commit=False)
    db.execute("DELETE FROM migration_users WHERE campaign_id=?", (campaign_id,), commit=False)
    for item in analysis["library_mappings"]:
        destinations = item.get("suggested_destinations") or []
        if not destinations:
            db.execute(
                """
                INSERT INTO migration_library_mappings(
                  campaign_id, source_library_id, destination_library_id, mapping_status
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    int(item["source"]["id"]),
                    None,
                    str(item.get("status") or "unmapped"),
                ),
                commit=False,
            )
            continue
        for destination in destinations:
            db.execute(
                """
                INSERT INTO migration_library_mappings(
                  campaign_id, source_library_id, destination_library_id, mapping_status
                ) VALUES (?, ?, ?, 'mapped')
                """,
                (campaign_id, int(item["source"]["id"]), int(destination["id"])),
                commit=False,
            )

    for user in analysis["users"]:
        source_access_rows = db.query(
            """
            SELECT mu.id AS media_user_id, mul.library_id
            FROM media_users mu
            JOIN media_user_libraries mul ON mul.media_user_id=mu.id
            JOIN libraries l ON l.id=mul.library_id AND l.server_id=?
            WHERE mu.server_id=? AND mu.vodum_user_id=?
            ORDER BY mu.id, mul.library_id
            """,
            (int(source_server_id), int(source_server_id), int(user["vodum_user_id"])),
        )
        source_access = {}
        for row in source_access_rows:
            source_access.setdefault(str(row["media_user_id"]), []).append(int(row["library_id"]))
        db.execute(
            """
            INSERT INTO migration_users(
              campaign_id, vodum_user_id, source_media_user_id, status,
              eligibility, blockers_json, source_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                int(user["vodum_user_id"]),
                int(user["source_media_user_id"]) if user.get("source_media_user_id") else None,
                "excluded" if user["classification"] == "excluded" else "pending",
                user["classification"],
                json.dumps(user["reasons"], sort_keys=True),
                json.dumps(
                    {
                        "username": user["username"],
                        "email": user["email"],
                        "source_library_count": user["source_library_count"],
                        "source_access": source_access,
                    },
                    sort_keys=True,
                ),
            ),
            commit=False,
        )


def create_migration_draft(
    db,
    *,
    name: str,
    source_server_id: int,
    destination_server_id: int,
    mapping_overrides: dict[int, list[int]],
    safety_delay_days: int = 7,
    scheduled_at: str = "",
    batch_size: int = 10,
    intent: str = "copy",
    jellyfin_password_strategy: str = "generated",
    jellyfin_temp_password: str = "",
    jellyfin_auto_deliver_credentials: bool = False,
) -> int:
    analysis = analyze_migration(
        db,
        source_server_id,
        destination_server_id,
        mapping_overrides=mapping_overrides,
    )
    if analysis.get("same_plex_owner"):
        raise ValueError("These Plex servers already share their users.")
    values = _clean_draft_values(
        analysis,
        name=name,
        safety_delay_days=safety_delay_days,
        scheduled_at=scheduled_at,
        batch_size=batch_size,
        intent=intent,
        jellyfin_password_strategy=jellyfin_password_strategy,
        jellyfin_temp_password=jellyfin_temp_password,
        jellyfin_auto_deliver_credentials=jellyfin_auto_deliver_credentials,
    )
    mapping_snapshot = {
        str(item["source"]["id"]): [
            int(destination["id"])
            for destination in (item.get("suggested_destinations") or [])
        ]
        for item in analysis["library_mappings"]
    }
    analysis_summary = {
        "counts": analysis["counts"],
        "migration_type": analysis["migration_type"],
        "mode": analysis["mode"],
        "requires_email": analysis["requires_email"],
    }
    cursor = db.execute(
        """
        INSERT INTO migration_campaigns(
          name, source_server_id, destination_server_id, migration_type,
          migration_mode, intent, status, options_json, library_mapping_json, analysis_json,
          scheduled_at, batch_size
        ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
        """,
        (
            values["name"],
            int(source_server_id),
            int(destination_server_id),
            analysis["migration_type"],
            analysis["mode"],
            values["intent"],
            values["options_json"],
            json.dumps(mapping_snapshot, sort_keys=True),
            json.dumps(analysis_summary, sort_keys=True),
            values["scheduled_at"],
            values["batch_size"],
        ),
        commit=False,
    )
    campaign_id = int(cursor.lastrowid)

    _replace_draft_snapshot(db, campaign_id, analysis, source_server_id)

    db.execute("COMMIT", commit=False)
    return campaign_id


def update_migration_draft(
    db,
    campaign_id: int,
    *,
    name: str,
    mapping_overrides: dict[int, list[int]],
    safety_delay_days: int = 7,
    scheduled_at: str = "",
    batch_size: int = 10,
    intent: str = "copy",
    jellyfin_password_strategy: str = "generated",
    jellyfin_temp_password: str = "",
    jellyfin_auto_deliver_credentials: bool = False,
) -> None:
    campaign = db.query_one(
        "SELECT id,status,source_server_id,destination_server_id,options_json FROM migration_campaigns WHERE id=?",
        (int(campaign_id),),
    )
    if not campaign:
        raise ValueError("Migration campaign not found.")
    if str(campaign["status"] or "") != "draft":
        raise ValueError("Only draft migration campaigns can be edited.")
    analysis = analyze_migration(
        db,
        int(campaign["source_server_id"]),
        int(campaign["destination_server_id"]),
        mapping_overrides=mapping_overrides,
    )
    try:
        existing_options = json.loads(campaign["options_json"] or "{}")
    except Exception:
        existing_options = {}
    values = _clean_draft_values(
        analysis,
        name=name,
        safety_delay_days=safety_delay_days,
        scheduled_at=scheduled_at,
        batch_size=batch_size,
        intent=intent,
        jellyfin_password_strategy=jellyfin_password_strategy,
        jellyfin_temp_password=jellyfin_temp_password,
        jellyfin_auto_deliver_credentials=jellyfin_auto_deliver_credentials,
        existing_options=existing_options,
    )
    mapping_snapshot = {
        str(item["source"]["id"]): [
            int(destination["id"])
            for destination in (item.get("suggested_destinations") or [])
        ]
        for item in analysis["library_mappings"]
    }
    analysis_summary = {
        "counts": analysis["counts"],
        "migration_type": analysis["migration_type"],
        "mode": analysis["mode"],
        "requires_email": analysis["requires_email"],
    }
    db.execute(
        """
        UPDATE migration_campaigns
        SET name=?, intent=?, options_json=?, library_mapping_json=?, analysis_json=?,
            scheduled_at=?, batch_size=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='draft'
        """,
        (
            values["name"],
            values["intent"],
            values["options_json"],
            json.dumps(mapping_snapshot, sort_keys=True),
            json.dumps(analysis_summary, sort_keys=True),
            values["scheduled_at"],
            values["batch_size"],
            int(campaign_id),
        ),
        commit=False,
    )
    _replace_draft_snapshot(db, int(campaign_id), analysis, int(campaign["source_server_id"]))
    db.execute("COMMIT", commit=False)


def delete_migration_draft(db, campaign_id: int) -> None:
    campaign = db.query_one("SELECT status FROM migration_campaigns WHERE id=?", (int(campaign_id),))
    if not campaign:
        raise ValueError("Migration campaign not found.")
    if str(campaign["status"] or "") != "draft":
        raise ValueError("Only draft migration campaigns can be deleted.")
    db.execute("DELETE FROM migration_steps WHERE migration_user_id IN (SELECT id FROM migration_users WHERE campaign_id=?)", (int(campaign_id),), commit=False)
    db.execute("DELETE FROM migration_users WHERE campaign_id=?", (int(campaign_id),), commit=False)
    db.execute("DELETE FROM migration_library_mappings WHERE campaign_id=?", (int(campaign_id),), commit=False)
    db.execute("DELETE FROM migration_campaigns WHERE id=? AND status='draft'", (int(campaign_id),), commit=False)
    db.execute("COMMIT", commit=False)
