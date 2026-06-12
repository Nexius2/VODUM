"""Read-only analysis for user migration plans."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


PROVIDER_CAPABILITIES = {
    "plex": {
        "account_mode": "invite",
        "requires_email": True,
        "supports_library_access": True,
    },
    "jellyfin": {
        "account_mode": "create_local",
        "requires_email": False,
        "supports_library_access": True,
    },
}
SUPPORTED_PROVIDERS = set(PROVIDER_CAPABILITIES)


def _dict(row: Any) -> dict:
    return dict(row) if row is not None else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).lower())


def is_server_online(value: Any) -> bool:
    """Accept the current monitoring status and the legacy migration status."""
    return _clean(value).lower() in {"up", "online"}


def _server(db, server_id: int) -> dict | None:
    row = db.query_one(
        """
        SELECT id, name, type, status, server_identifier, last_checked
        FROM servers
        WHERE id = ?
        """,
        (int(server_id),),
    )
    return _dict(row) if row else None


def _plex_owner_id(db, server_id: int) -> str:
    row = db.query_one(
        """
        SELECT external_user_id
        FROM media_users
        WHERE server_id = ?
          AND type = 'plex'
          AND lower(COALESCE(role, '')) = 'owner'
          AND TRIM(COALESCE(external_user_id, '')) <> ''
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(server_id),),
    )
    return _clean(row["external_user_id"]) if row else ""


def migration_workspace_blocker(db, servers: list[dict]) -> str:
    """Return the reason why this installation has no useful migration path."""
    if len(servers) < 2:
        return "single_server"

    if all(_clean(server.get("type")).lower() == "plex" for server in servers):
        owner_ids = {_plex_owner_id(db, int(server["id"])) for server in servers}
        owner_ids.discard("")
        if len(owner_ids) == 1 and len(owner_ids) == len({
            _plex_owner_id(db, int(server["id"])) for server in servers
        }):
            return "shared_plex_account"

    return ""


def migration_pair_blocker(db, source_server_id: int, destination_server_id: int) -> str:
    """Return why a source/destination pair must never be migrated."""
    source_server_id = int(source_server_id)
    destination_server_id = int(destination_server_id)
    if source_server_id == destination_server_id:
        return "same_server"

    source = _server(db, source_server_id)
    destination = _server(db, destination_server_id)
    if not source or not destination:
        return "server_not_found"
    if not is_server_online(source.get("status")) or not is_server_online(destination.get("status")):
        return "server_offline"

    source_identifier = _clean(source.get("server_identifier"))
    destination_identifier = _clean(destination.get("server_identifier"))
    if (
        _clean(source.get("type")).lower() == _clean(destination.get("type")).lower()
        and source_identifier
        and destination_identifier
        and source_identifier == destination_identifier
    ):
        return "same_server"

    if _clean(source.get("type")).lower() == "plex" and _clean(destination.get("type")).lower() == "plex":
        source_owner = _plex_owner_id(db, source_server_id)
        destination_owner = _plex_owner_id(db, destination_server_id)
        if source_owner and destination_owner and source_owner == destination_owner:
            return "shared_plex_pair"
    return ""


def detect_migration_mode(db, source: dict, destination: dict) -> dict:
    source_type = _clean(source.get("type")).lower()
    destination_type = _clean(destination.get("type")).lower()
    migration_type = f"{source_type}_to_{destination_type}"

    if source_type == "plex" and destination_type == "plex":
        source_owner = _plex_owner_id(db, source["id"])
        destination_owner = _plex_owner_id(db, destination["id"])
        same_owner = bool(source_owner and destination_owner and source_owner == destination_owner)
        return {
            "migration_type": migration_type,
            "mode": "direct_share" if same_owner else "invite",
            "requires_email": not same_owner,
            "same_plex_owner": same_owner,
        }

    return {
        "migration_type": migration_type,
        "mode": "invite" if destination_type == "plex" else "create_local",
        "requires_email": destination_type == "plex",
        "same_plex_owner": False,
    }


def migration_policy_compatibility(source: dict, destination: dict) -> list[dict]:
    """Describe which VODUM and provider policies remain valid after migration."""
    source_type = _clean(source.get("type")).lower()
    destination_type = _clean(destination.get("type")).lower()
    destination_capabilities = PROVIDER_CAPABILITIES.get(destination_type, {})
    return [
        {
            "policy": "library_access",
            "status": "supported" if destination_capabilities.get("supports_library_access") else "unsupported",
        },
        {"policy": "vodum_subscription", "status": "preserved"},
        {"policy": "vodum_stream_policies", "status": "preserved"},
        {
            "policy": "provider_specific_rules",
            "status": "preserved" if source_type == destination_type else "unsupported",
        },
    ]


def suggest_library_mappings(
    db,
    source_server_id: int,
    destination_server_id: int,
    mapping_overrides: dict[int, int | None] | None = None,
) -> list[dict]:
    mapping_overrides = mapping_overrides or {}
    source_libraries = [
        _dict(row)
        for row in db.query(
            "SELECT id, name, type, section_id FROM libraries WHERE server_id = ? ORDER BY name",
            (int(source_server_id),),
        )
    ]
    destination_libraries = [
        _dict(row)
        for row in db.query(
            "SELECT id, name, type, section_id FROM libraries WHERE server_id = ? ORDER BY name",
            (int(destination_server_id),),
        )
    ]

    learned_rows = []
    try:
        learned_rows = [
            _dict(row)
            for row in db.query(
                """
                SELECT
                  lower(trim(source.name)) AS source_name,
                  lower(trim(COALESCE(source.type, ''))) AS source_type,
                  lower(trim(destination.name)) AS destination_name,
                  lower(trim(COALESCE(destination.type, ''))) AS destination_type,
                  COUNT(*) AS uses
                FROM migration_library_mappings mlm
                JOIN migration_campaigns mc ON mc.id=mlm.campaign_id
                JOIN libraries source ON source.id=mlm.source_library_id
                JOIN libraries destination ON destination.id=mlm.destination_library_id
                WHERE mc.source_server_id=?
                  AND mc.destination_server_id=?
                  AND mlm.mapping_status='mapped'
                GROUP BY source_name, source_type, destination_name, destination_type
                ORDER BY uses DESC
                """,
                (int(source_server_id), int(destination_server_id)),
            )
        ]
    except Exception:
        learned_rows = []

    mappings = []
    for source in source_libraries:
        source_name = _normalized(source.get("name"))
        source_type = _clean(source.get("type")).lower()
        candidates = []
        for destination in destination_libraries:
            reason = ""
            if source_name and source_name == _normalized(destination.get("name")):
                score = 100
                reason = "name"
                if source_type and source_type == _clean(destination.get("type")).lower():
                    score += 20
                    reason = "name_and_type"
                candidates.append((score, destination, reason))
            for learned in learned_rows:
                if (
                    _normalized(learned.get("source_name")) == source_name
                    and _normalized(learned.get("destination_name")) == _normalized(destination.get("name"))
                    and (
                        not source_type
                        or not learned.get("source_type")
                        or source_type == _clean(learned.get("source_type")).lower()
                    )
                ):
                    candidates.append((200 + min(int(learned.get("uses") or 0), 50), destination, "learned"))
        candidates.sort(key=lambda item: (-item[0], _clean(item[1].get("name")).lower()))
        suggested = candidates[0][1] if candidates else None
        suggestion_reason = candidates[0][2] if candidates else ""
        suggestion_score = candidates[0][0] if candidates else 0
        if int(source["id"]) in mapping_overrides:
            destination_id = mapping_overrides[int(source["id"])]
            suggested = next(
                (
                    destination
                    for destination in destination_libraries
                    if destination_id is not None and int(destination["id"]) == int(destination_id)
                ),
                None,
            )
            suggestion_reason = "manual" if suggested else ""
            suggestion_score = 1000 if suggested else 0
        mappings.append(
            {
                "source": source,
                "suggested_destination": suggested,
                "status": "suggested" if suggested else "unmapped",
                "suggestion_reason": suggestion_reason,
                "suggestion_score": suggestion_score,
                "destination_options": destination_libraries,
            }
        )
    return mappings


def _source_users(db, source_server_id: int) -> list[dict]:
    rows = db.query(
        """
        SELECT
          vu.id AS vodum_user_id,
          vu.username AS vodum_username,
          vu.email AS vodum_email,
          vu.status AS vodum_status,
          vu.expiration_date,
          mu.id AS source_media_user_id,
          mu.username AS source_username,
          mu.email AS source_email,
          mu.external_user_id AS source_external_user_id,
          mu.role AS source_role
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE mu.server_id = ?
          AND mu.vodum_user_id IS NOT NULL
          AND lower(COALESCE(mu.role, '')) <> 'owner'
        ORDER BY lower(COALESCE(vu.username, mu.username, '')), vu.id, mu.id
        """,
        (int(source_server_id),),
    )
    unique = {}
    for row in rows:
        item = _dict(row)
        unique.setdefault(int(item["vodum_user_id"]), item)
    return list(unique.values())


def _source_library_ids_by_user(db, source_server_id: int) -> dict[int, list[int]]:
    rows = db.query(
        """
        SELECT DISTINCT mu.vodum_user_id, l.id AS library_id
        FROM media_users mu
        JOIN media_user_libraries mul ON mul.media_user_id = mu.id
        JOIN libraries l ON l.id = mul.library_id
        WHERE mu.server_id = ?
          AND l.server_id = ?
          AND mu.vodum_user_id IS NOT NULL
        """,
        (int(source_server_id), int(source_server_id)),
    )
    result: dict[int, list[int]] = {}
    for row in rows:
        result.setdefault(int(row["vodum_user_id"]), []).append(int(row["library_id"]))
    return result


def analyze_migration(
    db,
    source_server_id: int,
    destination_server_id: int,
    mapping_overrides: dict[int, int | None] | None = None,
) -> dict:
    source_server_id = int(source_server_id)
    destination_server_id = int(destination_server_id)
    pair_blocker = migration_pair_blocker(db, source_server_id, destination_server_id)
    if pair_blocker:
        raise ValueError(f"Migration pair is not allowed: {pair_blocker}.")

    source = _server(db, source_server_id)
    destination = _server(db, destination_server_id)
    if not source or not destination:
        raise ValueError("Source or destination server not found.")
    source["type"] = _clean(source.get("type")).lower()
    destination["type"] = _clean(destination.get("type")).lower()
    if source["type"] not in SUPPORTED_PROVIDERS or destination["type"] not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported migration provider.")

    mode = detect_migration_mode(db, source, destination)
    destination_status = _clean(destination.get("status")).lower()
    destination_unavailable = destination_status in {"down", "offline", "unreachable"}
    mappings = suggest_library_mappings(
        db,
        source_server_id,
        destination_server_id,
        mapping_overrides=mapping_overrides,
    )
    mapping_by_source = {
        int(item["source"]["id"]): item.get("suggested_destination")
        for item in mappings
    }
    source_library_ids = _source_library_ids_by_user(db, source_server_id)
    used_source_library_ids = {
        library_id
        for library_ids in source_library_ids.values()
        for library_id in library_ids
    }
    for mapping in mappings:
        if (
            int(mapping["source"]["id"]) not in used_source_library_ids
            and not mapping.get("suggested_destination")
        ):
            mapping["status"] = "unused"

    users = []
    counts = Counter()
    for source_user in _source_users(db, source_server_id):
        user_id = int(source_user["vodum_user_id"])
        username = _clean(source_user.get("vodum_username") or source_user.get("source_username"))
        email = _clean(source_user.get("vodum_email") or source_user.get("source_email"))
        reasons = []

        destination_account = db.query_one(
            """
            SELECT id, username, email, external_user_id
            FROM media_users
            WHERE server_id = ? AND vodum_user_id = ?
            ORDER BY id ASC LIMIT 1
            """,
            (destination_server_id, user_id),
        )
        if destination_account and not email:
            email = _clean(destination_account["email"])
        destination_exists = bool(destination_account)
        if destination_exists:
            reasons.append("destination_account_exists")
        email_conflict = None
        if email and not destination_exists:
            email_conflict = db.query_one(
                """
                SELECT vodum_user_id
                FROM media_users
                WHERE server_id = ?
                  AND lower(COALESCE(email, '')) = lower(?)
                  AND COALESCE(vodum_user_id, 0) <> ?
                LIMIT 1
                """,
                (destination_server_id, email, user_id),
            )
        username_conflict = None
        if destination["type"] == "jellyfin" and username and not destination_exists:
            username_conflict = db.query_one(
                """
                SELECT vodum_user_id
                FROM media_users
                WHERE server_id = ?
                  AND lower(COALESCE(username, '')) = lower(?)
                  AND COALESCE(vodum_user_id, 0) <> ?
                LIMIT 1
                """,
                (destination_server_id, username, user_id),
            )

        user_source_libraries = source_library_ids.get(user_id, [])
        unmapped = [library_id for library_id in user_source_libraries if not mapping_by_source.get(library_id)]
        blockers = []
        if destination_unavailable:
            blockers.append("destination_unavailable")
        if mode["requires_email"] and not email:
            blockers.append("needs_email")
        if destination["type"] == "jellyfin" and not username and not destination_exists:
            blockers.append("needs_username")
        if mode["mode"] == "direct_share" and not _clean(source_user.get("source_external_user_id")):
            blockers.append("ambiguous_identity")
        if email_conflict:
            blockers.append("ambiguous_identity")
        if username_conflict:
            blockers.append("username_conflict")
        if destination_exists and destination["type"] == "jellyfin" and not _clean(destination_account["external_user_id"]):
            blockers.append("destination_identity_missing")
        if not user_source_libraries:
            blockers.append("no_source_access")
        if unmapped:
            blockers.append("needs_library_mapping")
        reasons.extend(blockers)

        classification = (
            "excluded"
            if blockers == ["no_source_access"]
            else "blocked" if blockers
            else "already_present" if destination_exists
            else "ready"
        )

        counts[classification] += 1
        users.append(
            {
                **source_user,
                "username": username,
                "email": email,
                "classification": classification,
                "reasons": reasons,
                "source_library_count": len(source_library_ids.get(user_id, [])),
            }
        )

    return {
        "source": source,
        "destination": destination,
        **mode,
        "users": users,
        "library_mappings": mappings,
        "policy_compatibility": migration_policy_compatibility(source, destination),
        "destination_available": not destination_unavailable,
        "counts": {
            "total": len(users),
            "ready": counts["ready"],
            "blocked": counts["blocked"],
            "already_present": counts["already_present"],
            "unmapped_libraries": sum(1 for item in mappings if item["status"] == "unmapped"),
        },
    }
