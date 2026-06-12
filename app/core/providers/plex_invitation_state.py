"""Shared Plex invitation-state helpers."""

from typing import Any, Iterable, Optional


PENDING_ERROR_MARKERS = (
    "already invited",
    "already been invited",
    "invite already sent",
    "invitation already sent",
    "request sent",
    "request already sent",
)

FRIEND_ERROR_MARKERS = (
    "already a friend",
    "already friends",
    "already sharing",
    "already shared",
)


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def plex_identity_values(obj: Any) -> Iterable[str]:
    for attr in ("id", "userID", "userId", "email", "user", "username", "title"):
        value = _clean(getattr(obj, attr, None))
        if value:
            yield value


def matches_plex_identity(
    obj: Any,
    *,
    email: str = "",
    username: str = "",
    external_user_id: str = "",
) -> bool:
    expected = {
        value
        for value in (_clean(email), _clean(username), _clean(external_user_id))
        if value
    }
    return bool(expected and expected.intersection(plex_identity_values(obj)))


def classify_plex_invite_error(error: Any) -> Optional[str]:
    text = _clean(error)
    if any(marker in text for marker in FRIEND_ERROR_MARKERS):
        return "friend"
    if any(marker in text for marker in PENDING_ERROR_MARKERS):
        return "pending"
    return None


def plex_invite_state_payload(
    state: str,
    *,
    primary_server_id: Optional[int] = None,
    detail: str = "",
) -> dict:
    normalized = state if state in {"friend", "pending", "missing", "unknown"} else "unknown"
    payload = {
        "state": normalized,
        "is_friend": normalized == "friend",
        "is_pending": normalized == "pending",
    }
    if primary_server_id is not None:
        payload["primary_server_id"] = int(primary_server_id)
    if detail:
        payload["detail"] = str(detail)
    return payload


def merge_accepted_plex_media_user(db, *, accepted_id: int, pending_id: int) -> bool:
    """Merge a stale pending-invite row into its accepted Plex account row."""
    accepted_id = int(accepted_id)
    pending_id = int(pending_id)
    if accepted_id == pending_id:
        return False

    db.execute(
        """
        INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
        SELECT ?, library_id
        FROM media_user_libraries
        WHERE media_user_id = ?
        """,
        (accepted_id, pending_id),
    )
    db.execute("DELETE FROM media_user_libraries WHERE media_user_id = ?", (pending_id,))
    for table in ("media_sessions", "media_events"):
        db.execute(
            f"UPDATE {table} SET media_user_id = ? WHERE media_user_id = ?",
            (accepted_id, pending_id),
        )
    db.execute(
        "UPDATE OR IGNORE media_session_history SET media_user_id = ? WHERE media_user_id = ?",
        (accepted_id, pending_id),
    )
    db.execute("DELETE FROM media_session_history WHERE media_user_id = ?", (pending_id,))
    db.execute("DELETE FROM media_users WHERE id = ?", (pending_id,))
    return True
