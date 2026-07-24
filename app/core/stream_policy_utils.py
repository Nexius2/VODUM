import ipaddress
import json
from typing import List, Optional, Tuple

from logging_utils import get_logger, is_debug_mode_enabled


logger = get_logger("stream_enforcer")


def loads_json(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def is_strict_expired_subscription_policy(policy: dict) -> bool:
    if not policy or policy.get("rule_type") != "max_streams_per_user":
        return False
    rule = loads_json(policy.get("rule_value_json"))
    if rule.get("system_tag") != "expired_subscription":
        return False
    try:
        return int(rule.get("max", 1)) <= 0
    except Exception:
        return False


def jellyfin_session_id_from_target(target: dict, fallback_session_key: str) -> str:
    try:
        session_id = (target.get("_parsed_raw_json") or {}).get("Id")
        if session_id:
            return str(session_id)
    except Exception as exc:
        if is_debug_mode_enabled():
            logger.debug("[stream_enforcer] failed to extract jellyfin session id: %s", exc)
    return str(fallback_session_key)


def actor_key(vodum_user_id: Optional[int], external_user_id: str) -> str:
    if vodum_user_id is not None:
        return f"vodum:{int(vodum_user_id)}"
    external_user_id = (external_user_id or "").strip()
    return f"ext:{external_user_id}" if external_user_id else "ext:unknown"


def session_started_ts(row: dict) -> str:
    return row.get("started_at") or row.get("last_seen_at") or ""


def pick_kill_target(sessions: List[dict], selector: str) -> Optional[dict]:
    if not sessions:
        return None
    selector = (selector or "kill_newest").strip()
    if selector == "kill_oldest":
        return sorted(sessions, key=session_started_ts)[0]
    if selector == "kill_transcoding_first":
        transcoding = [session for session in sessions if int(session.get("is_transcode") or 0) == 1]
        if transcoding:
            return sorted(transcoding, key=session_started_ts, reverse=True)[0]
    return sorted(sessions, key=session_started_ts, reverse=True)[0]


def is_global_policy(policy: dict) -> bool:
    return policy.get("scope_type") == "global" and not policy.get("server_id")


def normalize_user_key(session: dict) -> Tuple[Optional[int], str]:
    return session.get("vodum_user_id"), str(session.get("external_user_id") or "")


def is_local_ip(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip or ip.lower() == "unknown":
        return False
    try:
        address = ipaddress.ip_address(ip)
        return bool(address.is_private or address.is_loopback or address.is_link_local)
    except Exception:
        return False


def is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address((value or "").strip())
        return bool((value or "").strip())
    except Exception:
        return False


def best_account_username(session: dict) -> Optional[str]:
    media_username = str(session.get("media_username") or "").strip()
    if media_username:
        return media_username
    external_id = str(session.get("external_user_id") or "").strip()
    return external_id if external_id and not is_ip_literal(external_id) else None


def same_actor_reference(candidate: dict, target: dict) -> bool:
    target_user_id = target.get("vodum_user_id")
    candidate_user_id = candidate.get("vodum_user_id")
    if target_user_id is not None and candidate_user_id is not None:
        try:
            return int(target_user_id) == int(candidate_user_id)
        except Exception:
            pass
    target_external_id = str(target.get("external_user_id") or "").strip()
    candidate_external_id = str(candidate.get("external_user_id") or "").strip()
    if target_external_id and candidate_external_id:
        try:
            return int(candidate.get("server_id") or 0) == int(target.get("server_id") or 0) and candidate_external_id == target_external_id
        except Exception:
            return candidate_external_id == target_external_id
    return False
