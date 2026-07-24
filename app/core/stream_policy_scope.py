from logging_utils import get_logger, is_debug_mode_enabled


logger = get_logger("stream_enforcer")


def has_vip_override(vodum_user_id, overrides: dict[int, int]) -> bool:
    if vodum_user_id is None:
        return False
    try:
        return int(overrides.get(int(vodum_user_id), 0)) > 0
    except Exception:
        return False


def policy_applies(policy: dict, session: dict) -> bool:
    provider = policy.get("provider")
    if provider and provider != session.get("provider"):
        return False
    server_id = policy.get("server_id")
    if server_id and int(server_id) != int(session.get("server_id")):
        return False
    scope_type = policy.get("scope_type")
    scope_id = policy.get("scope_id")
    if scope_type == "global":
        return True
    if scope_type == "server":
        return scope_id is not None and int(scope_id) == int(session.get("server_id"))
    if scope_type == "user":
        vodum_user_id = session.get("vodum_user_id")
        if vodum_user_id is None:
            if is_debug_mode_enabled():
                logger.debug(
                    "[stream_enforcer] policy scope=user skipped (vodum_user_id is NULL) "
                    "scope_id=%s media_user_id=%s external_user_id=%s server_id=%s provider=%s",
                    scope_id, session.get("media_user_id"), session.get("external_user_id"),
                    session.get("server_id"), session.get("provider"),
                )
            return False
        return scope_id is not None and int(scope_id) == int(vodum_user_id)
    return False
