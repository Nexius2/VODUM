from typing import List, Optional, Tuple

from core.stream_session_identity import safe_lower


def media_family_key(session: dict) -> str:
    media_type = safe_lower(session.get("media_type"))
    media_key = safe_lower(session.get("media_key"))
    grandparent = safe_lower(session.get("grandparent_title"))
    parent = safe_lower(session.get("parent_title"))
    title = safe_lower(session.get("title"))
    if media_type in ("episode", "series", "show") and grandparent:
        return f"series:{grandparent}"
    if media_type in ("movie", "film") and title:
        return f"movie:{title}"
    if grandparent:
        return f"series:{grandparent}"
    if media_key:
        return f"key:{media_key}"
    if parent and title:
        return f"parent_title:{parent}:{title}"
    return f"title:{title}" if title else ""


def is_coherent_media_transition(sessions: List[dict]) -> bool:
    families = {media_family_key(session) for session in sessions}
    families.discard("")
    return len(families) == 1


def ip_grace_key(
    policy_id: int,
    user_key: Tuple[Optional[int], str],
    sessions: List[dict],
) -> str:
    parts = [
        f"{session.get('server_id')}:{session.get('session_key')}:{session.get('ip')}:{media_family_key(session)}"
        for session in sessions
    ]
    return f"policy:{policy_id}|user:{user_key}|" + "|".join(sorted(parts))
