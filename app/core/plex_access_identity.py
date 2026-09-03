from __future__ import annotations

import json
from types import SimpleNamespace

from logging_utils import get_logger


logger = get_logger("plex_access_identity")


class PendingPlexInvite(RuntimeError):
    """The Plex invitation exists but has not been accepted yet."""


class PlexUserNotFound(RuntimeError):
    """The stored Plex identity no longer exists in the owner's user list."""


class PlexUserLookupUnavailable(RuntimeError):
    """Plex could not provide its user list; this failure may be temporary."""


def row_get(row, key, default=None):
    if row is None:
        return default
    try:
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
    except Exception:
        pass
    try:
        return getattr(row, key)
    except Exception:
        return default


def details_json_as_dict(user_row):
    raw = row_get(user_row, "details_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def is_pending_invite_media_user(user_row) -> bool:
    if str(row_get(user_row, "accepted_at") or "").strip():
        return False
    details = details_json_as_dict(user_row)
    invite_state = details.get("plex_invite_state") or {}
    if isinstance(invite_state, dict) and invite_state.get("is_pending"):
        return True
    external_id = str(row_get(user_row, "external_user_id") or "").strip()
    email = str(row_get(user_row, "email") or "").strip()
    username = str(row_get(user_row, "username") or "").strip()
    return not external_id and bool(email or username)


def _unique(values, normalizer):
    result = []
    for value in values:
        normalized = normalizer(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def resolve_plex_user(account, media_user_row):
    details = details_json_as_dict(media_user_row)
    plex_user_details = details.get("plex_user") or {}
    plex_share_details = details.get("plex_share") or {}
    normalize = lambda value: str(value or "").strip()
    normalize_lower = lambda value: normalize(value).lower()

    db_external_id = normalize(row_get(media_user_row, "external_user_id"))
    db_email = normalize_lower(row_get(media_user_row, "email"))
    db_username = normalize(row_get(media_user_row, "username"))
    candidate_ids = _unique(
        [db_external_id, plex_user_details.get("id")], normalize
    )
    candidate_emails = _unique(
        [
            db_email,
            plex_user_details.get("email"),
            plex_share_details.get("email"),
        ],
        normalize_lower,
    )
    candidate_usernames = _unique(
        [
            db_username,
            plex_user_details.get("username"),
            plex_share_details.get("username"),
        ],
        normalize,
    )

    list_error = None
    try:
        plex_users = list(account.users())
    except Exception as exc:
        logger.warning(
            "Unable to list Plex users via account.users(); trying server shares: %s",
            exc,
        )
        list_error = exc
        plex_users = []

    for wanted_values, attribute, normalizer in (
        (candidate_ids, "id", normalize),
        (candidate_emails, "email", normalize_lower),
        (candidate_usernames, "username", normalize),
        (candidate_usernames, "title", normalize),
    ):
        for wanted in wanted_values:
            for plex_user in plex_users:
                if normalizer(getattr(plex_user, attribute, None)) == wanted:
                    return plex_user

    for candidate in candidate_usernames + candidate_emails:
        try:
            return account.user(candidate)
        except Exception:
            pass

    if is_pending_invite_media_user(media_user_row):
        raise PendingPlexInvite(
            "Plex invite still pending acceptance "
            f"for username={db_username!r}, email={db_email!r}"
        )
    if list_error is not None:
        raise PlexUserLookupUnavailable(
            "Unable to retrieve the Plex owner user list"
        ) from list_error
    available = [
        {
            "id": normalize(getattr(user, "id", None)),
            "username": normalize(getattr(user, "username", None)),
            "title": normalize(getattr(user, "title", None)),
            "email": normalize(getattr(user, "email", None)),
        }
        for user in plex_users
    ]
    raise PlexUserNotFound(
        "Unable to resolve Plex user from media_users row "
        f"(external_user_id={db_external_id!r}, username={db_username!r}, "
        f"email={db_email!r}). details_json.plex_user={plex_user_details!r}. "
        f"details_json.plex_share={plex_share_details!r}. "
        f"Available Plex users sample={available[:10]}"
    )


def resolve_plex_user_from_shared_servers(shared_servers, media_user_row):
    """Recover a Plex user from an existing server share without re-inviting it."""
    details = details_json_as_dict(media_user_row)
    plex_user_details = details.get("plex_user") or {}
    plex_share_details = details.get("plex_share") or {}
    normalize = lambda value: str(value or "").strip()
    lower = lambda value: normalize(value).lower()
    candidate_ids = _unique(
        [row_get(media_user_row, "external_user_id"), plex_user_details.get("id")],
        normalize,
    )
    candidate_emails = _unique(
        [
            row_get(media_user_row, "email"),
            plex_user_details.get("email"),
            plex_share_details.get("email"),
        ],
        lower,
    )
    candidate_names = _unique(
        [
            row_get(media_user_row, "username"),
            plex_user_details.get("username"),
            plex_share_details.get("username"),
        ],
        lower,
    )

    for shared in shared_servers or []:
        shared_ids = {
            normalize(shared.get("userID")), normalize(shared.get("invitedId"))
        } - {""}
        if (
            shared_ids.intersection(candidate_ids)
            or (lower(shared.get("email")) in candidate_emails)
            or (lower(shared.get("username")) in candidate_names)
        ):
            plex_id = (
                normalize(shared.get("userID"))
                or normalize(shared.get("invitedId"))
                or (candidate_ids[0] if candidate_ids else "")
            )
            username = normalize(shared.get("username"))
            return SimpleNamespace(
                id=plex_id or None,
                username=username or None,
                title=username or None,
                email=normalize(shared.get("email")) or None,
                thumb=None,
                servers=[],
            )

    raise PlexUserNotFound(
        "Stored Plex user is absent from both the owner user list and this "
        "server's existing shares"
    )


def sync_media_user_identity_from_plex(db, media_user_row, plex_user_obj):
    media_user_id = row_get(media_user_row, "id")
    if not media_user_id:
        return
    new_username = str(
        getattr(plex_user_obj, "username", None)
        or getattr(plex_user_obj, "title", None)
        or ""
    ).strip()
    new_email = str(getattr(plex_user_obj, "email", None) or "").strip()
    new_external_id = str(getattr(plex_user_obj, "id", None) or "").strip()
    old_username = str(row_get(media_user_row, "username") or "").strip()
    old_email = str(row_get(media_user_row, "email") or "").strip()
    old_external_id = str(
        row_get(media_user_row, "external_user_id") or ""
    ).strip()
    old_accepted_at = str(row_get(media_user_row, "accepted_at") or "").strip()

    details = details_json_as_dict(media_user_row)
    details["plex_invite_state"] = {
        "is_friend": True,
        "is_pending": False,
        "primary_server_id": row_get(media_user_row, "server_id"),
    }
    details["plex_user"] = {
        **(details.get("plex_user") or {}),
        "id": new_external_id or old_external_id or None,
        "username": new_username or old_username or None,
        "email": new_email or old_email or None,
        "avatar": getattr(plex_user_obj, "thumb", None),
        "accepted_at": old_accepted_at or "synced",
    }
    changed = (
        (new_username and new_username != old_username)
        or (new_email and new_email != old_email)
        or (new_external_id and new_external_id != old_external_id)
        or not old_accepted_at
    )
    db.execute(
        """
        UPDATE media_users
        SET username = ?, email = ?, external_user_id = ?,
            accepted_at = CASE
                WHEN accepted_at IS NULL OR TRIM(accepted_at) = ''
                    THEN datetime('now')
                ELSE accepted_at
            END,
            details_json = ?
        WHERE id = ?
        """,
        (
            new_username or old_username,
            new_email or old_email,
            new_external_id or old_external_id or None,
            json.dumps(details),
            media_user_id,
        ),
    )
    if changed:
        logger.info(
            "[PLEX USER SYNC] media_user_id=%s username: %r -> %r, "
            "email: %r -> %r, external_user_id: %r -> %r, "
            "accepted_at was empty=%s",
            media_user_id,
            old_username,
            new_username,
            old_email,
            new_email,
            old_external_id,
            new_external_id,
            not bool(old_accepted_at),
        )
