import json


INVALID_IP_STREAMS_LIMIT = "subscription_template_invalid_ip_streams_limit"


def parse_json_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def normalize_template_policies(policies: list) -> list[dict]:
    clean = []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        rule_type = (policy.get("rule_type") or "").strip()
        if not rule_type:
            continue
        clean.append({
            "rule_type": rule_type,
            "provider": (policy.get("provider") or "").strip() or None,
            "server_id": int(policy["server_id"]) if str(policy.get("server_id", "")).isdigit() else None,
            "is_enabled": 1 if str(policy.get("is_enabled", "1")) == "1" else 0,
            "priority": int(policy.get("priority") or 100),
            "rule": policy.get("rule") if isinstance(policy.get("rule"), dict) else {},
        })
    return clean


def _policy_int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None


def _stream_user_policy_applies_to_policy(stream_policy, target_policy) -> bool:
    stream_provider = (stream_policy.get("provider") or "").strip() or None
    target_provider = (target_policy.get("provider") or "").strip() or None
    stream_server_id = _policy_int_or_none(stream_policy.get("server_id"))
    target_server_id = _policy_int_or_none(target_policy.get("server_id"))

    if stream_provider and not target_provider:
        return False
    if stream_provider and target_provider and stream_provider != target_provider:
        return False
    if stream_server_id is not None and target_server_id is None:
        return False
    if stream_server_id is not None and target_server_id is not None and stream_server_id != target_server_id:
        return False
    return True


def validate_subscription_template_policy_limits(policies: list) -> str | None:
    stream_user_policies = []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        if int(policy.get("is_enabled") or 0) != 1:
            continue
        if (policy.get("rule_type") or "").strip() != "max_streams_per_user":
            continue
        rule = policy.get("rule") if isinstance(policy.get("rule"), dict) else {}
        max_streams = _policy_int_or_none(rule.get("max"))
        if max_streams is not None and max_streams > 0:
            stream_user_policies.append(policy)

    for policy in policies:
        if not isinstance(policy, dict):
            continue
        if int(policy.get("is_enabled") or 0) != 1:
            continue
        if (policy.get("rule_type") or "").strip() != "max_ips_per_user":
            continue
        rule = policy.get("rule") if isinstance(policy.get("rule"), dict) else {}
        max_ips = _policy_int_or_none(rule.get("max"))
        if max_ips is None or max_ips <= 0:
            continue

        applicable_stream_limits = []
        for stream_policy in stream_user_policies:
            if not _stream_user_policy_applies_to_policy(stream_policy, policy):
                continue
            stream_rule = stream_policy.get("rule") if isinstance(stream_policy.get("rule"), dict) else {}
            max_streams = _policy_int_or_none(stream_rule.get("max"))
            if max_streams is not None and max_streams > 0:
                applicable_stream_limits.append(max_streams)

        if applicable_stream_limits and max_ips > min(applicable_stream_limits):
            return INVALID_IP_STREAMS_LIMIT
    return None
