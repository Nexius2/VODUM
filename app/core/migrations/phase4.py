"""Reusable, provider-neutral migration plan import and export."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.migrations.drafts import create_migration_draft


PLAN_FORMAT = "vodum-migration-plan"
PLAN_VERSION = 1


def _dict(row) -> dict:
    return dict(row) if row is not None else {}


def _server_ref(server: dict) -> dict:
    return {
        "type": str(server.get("type") or "").strip().lower(),
        "server_identifier": str(server.get("server_identifier") or "").strip(),
        "name": str(server.get("name") or "").strip(),
    }


def _library_ref(library: dict) -> dict:
    return {
        "section_id": str(library.get("section_id") or "").strip(),
        "name": str(library.get("name") or "").strip(),
        "type": str(library.get("type") or "").strip().lower(),
    }


def export_migration_plan(db, campaign_id: int) -> dict:
    campaign = _dict(db.query_one("SELECT id, name, source_server_id, destination_server_id, migration_type, migration_mode, intent, status, options_json, library_mapping_json, analysis_json, scheduled_at, batch_size, created_at, updated_at, started_at, completed_at FROM migration_campaigns WHERE id=?", (int(campaign_id),)))
    if not campaign:
        raise ValueError("Migration campaign not found.")
    source = _dict(db.query_one("SELECT id,name,type,server_identifier FROM servers WHERE id=?", (campaign["source_server_id"],)))
    destination = _dict(db.query_one("SELECT id,name,type,server_identifier FROM servers WHERE id=?", (campaign["destination_server_id"],)))
    mappings = []
    for raw in db.query(
        """
        SELECT source.id AS source_id, source.name AS source_name, source.type AS source_type,
               source.section_id AS source_section_id,
               destination.name AS destination_name, destination.type AS destination_type,
               destination.section_id AS destination_section_id
        FROM migration_library_mappings mlm
        JOIN libraries source ON source.id=mlm.source_library_id
        LEFT JOIN libraries destination ON destination.id=mlm.destination_library_id
        WHERE mlm.campaign_id=?
        ORDER BY source.name, source.id
        """,
        (int(campaign_id),),
    ):
        row = _dict(raw)
        mappings.append({
            "source": _library_ref({
                "name": row.get("source_name"),
                "type": row.get("source_type"),
                "section_id": row.get("source_section_id"),
            }),
            "destination": _library_ref({
                "name": row.get("destination_name"),
                "type": row.get("destination_type"),
                "section_id": row.get("destination_section_id"),
            }) if row.get("destination_name") is not None else None,
        })
    try:
        options = json.loads(campaign.get("options_json") or "{}")
    except Exception:
        options = {}
    return {
        "format": PLAN_FORMAT,
        "version": PLAN_VERSION,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "name": str(campaign.get("name") or ""),
        "source": _server_ref(source),
        "destination": _server_ref(destination),
        "intent": str(campaign.get("intent") or "copy"),
        "batch_size": int(campaign.get("batch_size") or 10),
        "options": {
            "safety_delay_days": max(0, int(options.get("safety_delay_days", 7))),
            "destination_access_policy": "merge",
        },
        "library_mappings": mappings,
    }


def _resolve_server(db, ref: dict) -> dict:
    provider = str(ref.get("type") or "").strip().lower()
    identifier = str(ref.get("server_identifier") or "").strip()
    name = str(ref.get("name") or "").strip()
    if identifier:
        rows = db.query(
            "SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE lower(trim(type))=? AND trim(COALESCE(server_identifier,''))=?",
            (provider, identifier),
        )
        if len(rows) == 1:
            return _dict(rows[0])
    rows = db.query(
        "SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE lower(trim(type))=? AND lower(trim(name))=lower(trim(?))",
        (provider, name),
    )
    if len(rows) != 1:
        raise ValueError(f"Migration plan server could not be resolved uniquely: {provider} / {name}.")
    return _dict(rows[0])


def _resolve_library(db, server_id: int, ref: dict | None) -> int | None:
    if not ref:
        return None
    section_id = str(ref.get("section_id") or "").strip()
    if section_id:
        rows = db.query("SELECT id FROM libraries WHERE server_id=? AND trim(COALESCE(section_id,''))=?", (server_id, section_id))
        if len(rows) == 1:
            return int(rows[0]["id"])
    rows = db.query(
        """
        SELECT id FROM libraries
        WHERE server_id=? AND lower(trim(name))=lower(trim(?))
          AND (?='' OR lower(trim(COALESCE(type,'')))=?)
        """,
        (server_id, str(ref.get("name") or ""), str(ref.get("type") or ""), str(ref.get("type") or "").lower()),
    )
    if len(rows) != 1:
        return None
    return int(rows[0]["id"])


def import_migration_plan(db, plan: dict, *, name_override: str = "") -> int:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT or int(plan.get("version") or 0) != PLAN_VERSION:
        raise ValueError("Unsupported migration plan format.")
    source = _resolve_server(db, plan.get("source") or {})
    destination = _resolve_server(db, plan.get("destination") or {})
    if int(source["id"]) == int(destination["id"]):
        raise ValueError("A migration plan cannot target its source server.")
    mappings: dict[int, list[int]] = {}
    for item in plan.get("library_mappings") or []:
        source_library_id = _resolve_library(db, int(source["id"]), item.get("source"))
        if source_library_id is None:
            continue
        destination_library_id = _resolve_library(db, int(destination["id"]), item.get("destination"))
        source_mappings = mappings.setdefault(source_library_id, [])
        if destination_library_id is not None and destination_library_id not in source_mappings:
            source_mappings.append(destination_library_id)
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    return create_migration_draft(
        db,
        name=name_override or str(plan.get("name") or ""),
        source_server_id=int(source["id"]),
        destination_server_id=int(destination["id"]),
        mapping_overrides=mappings,
        safety_delay_days=max(0, min(int(options.get("safety_delay_days", 7)), 365)),
        batch_size=max(1, min(int(plan.get("batch_size", 10)), 100)),
        intent=str(plan.get("intent") or "copy"),
    )
