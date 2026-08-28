import json
from datetime import datetime, timezone
from typing import Iterable


def _details(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def set_plex_media_user_presence(
    db, media_user_id: int, external_user_id: str, presence: str,
) -> None:
    row = db.query_one(
        "SELECT details_json FROM media_users WHERE id = ?",
        (int(media_user_id),),
    )
    details = _details(row["details_json"] if row else None)
    details.update({
        "provider_presence": str(presence),
        "provider_presence_external_user_id": str(external_user_id or ""),
        "provider_presence_checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), int(media_user_id)),
    )
    from core.portal_provider_identity_state import reconcile_portal_provider_identity
    reconcile_portal_provider_identity(db, int(media_user_id))


def preserve_plex_presence_metadata(new_raw, existing_raw) -> str:
    """Keep reconciliation metadata when the provider payload is refreshed."""
    new_details = _details(new_raw)
    existing_details = _details(existing_raw)
    for key in (
        "provider_presence",
        "provider_presence_external_user_id",
        "provider_presence_checked_at",
    ):
        if key in existing_details:
            new_details[key] = existing_details[key]
    return json.dumps(new_details, ensure_ascii=False)


def reconcile_plex_media_user_presence(
    db,
    seen_pairs: Iterable[tuple[str, int]],
    verified_server_ids: Iterable[int],
) -> dict:
    """Reconcile accepted Plex friends only on servers with a usable response."""
    seen = {(str(external_id), int(server_id)) for external_id, server_id in seen_pairs}
    verified = {int(server_id) for server_id in verified_server_ids}
    counts = {"present": 0, "removed": 0}
    if not verified:
        return counts

    placeholders = ",".join("?" for _ in verified)
    rows = db.query(
        f"""
        SELECT id, server_id, external_user_id, role, accepted_at, details_json
        FROM media_users
        WHERE type = 'plex'
          AND server_id IN ({placeholders})
          AND TRIM(COALESCE(external_user_id, '')) <> ''
        """,
        tuple(sorted(verified)),
    ) or []
    for raw in rows:
        account = dict(raw)
        role = str(account.get("role") or "").strip().lower()
        details = _details(account.get("details_json"))
        invite = details.get("plex_invite_state") or {}
        is_pending = isinstance(invite, dict) and bool(invite.get("is_pending"))
        if role == "owner" or is_pending:
            continue

        external_id = str(account.get("external_user_id") or "").strip()
        pair = (external_id, int(account["server_id"]))
        presence = "present" if pair in seen else "removed"
        if str(details.get("provider_presence") or "").lower() == presence:
            continue
        set_plex_media_user_presence(db, int(account["id"]), external_id, presence)
        counts[presence] += 1
    return counts
