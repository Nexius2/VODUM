import json
from typing import List, Optional, Tuple

from core.stream_policy_utils import best_account_username, loads_json, same_actor_reference


def build_enforcement_snapshot(
    target: dict,
    violation_sessions: List[dict],
    live_sessions: List[dict],
    policy: Optional[dict] = None,
    reason: Optional[str] = None,
) -> Tuple[Optional[str], str, str]:
    related = []
    seen = set()

    def add_session(session: dict):
        key = int(session.get("server_id") or 0), str(session.get("session_key") or "")
        if key not in seen:
            seen.add(key)
            related.append(session)

    for session in live_sessions or []:
        if same_actor_reference(session, target):
            add_session(session)
    for session in violation_sessions or []:
        add_session(session)
    if not related:
        add_session(target)

    def session_snapshot(session: dict) -> dict:
        raw_value = session.get("raw_json")
        raw_parsed = None
        if raw_value:
            try:
                raw_parsed = session.get("_parsed_raw_json")
                if raw_parsed is None:
                    raw_parsed = json.loads(raw_value)
            except Exception:
                raw_parsed = raw_value
        return {
            "server_id": session.get("server_id"),
            "provider": session.get("provider"),
            "session_key": session.get("session_key"),
            "media_user_id": session.get("media_user_id"),
            "external_user_id": session.get("external_user_id"),
            "vodum_user_id": session.get("vodum_user_id"),
            "media_username": session.get("media_username"),
            "media_key": session.get("media_key"),
            "media_type": session.get("media_type"),
            "title": session.get("title"),
            "grandparent_title": session.get("grandparent_title"),
            "parent_title": session.get("parent_title"),
            "state": session.get("state"),
            "progress_ms": session.get("progress_ms"),
            "duration_ms": session.get("duration_ms"),
            "is_transcode": int(session.get("is_transcode") or 0),
            "bitrate": session.get("bitrate"),
            "device": session.get("device"),
            "client_name": session.get("client_name"),
            "client_product": session.get("client_product"),
            "ip": session.get("ip"),
            "started_at": session.get("started_at"),
            "last_seen_at": session.get("last_seen_at"),
            "raw_json": raw_parsed,
        }

    account_username = next(
        (username for session in [target] + related if (username := best_account_username(session))),
        None,
    )
    ips = []
    for session in related:
        ip_value = str(session.get("ip") or "").strip()
        if ip_value and ip_value.lower() != "unknown" and ip_value not in ips:
            ips.append(ip_value)
    related.sort(key=lambda session: (
        int(session.get("server_id") or 0),
        str(session.get("started_at") or ""),
        str(session.get("session_key") or ""),
    ))
    details = {
        "account_username": account_username,
        "all_ips": ips,
        "reason": reason,
        "policy": {
            "id": policy.get("id") if policy else None,
            "scope_type": policy.get("scope_type") if policy else None,
            "scope_id": policy.get("scope_id") if policy else None,
            "provider": policy.get("provider") if policy else None,
            "server_id": policy.get("server_id") if policy else None,
            "priority": policy.get("priority") if policy else None,
            "rule_type": policy.get("rule_type") if policy else None,
            "rule_value": loads_json(policy.get("rule_value_json")) if policy else None,
        },
        "target_session": session_snapshot(target),
        "all_sessions": [session_snapshot(session) for session in related],
        "session_count": len(related),
    }
    return account_username, json.dumps(ips, ensure_ascii=False), json.dumps(details, ensure_ascii=False)
