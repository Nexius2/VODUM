import json

from core.stream_notification_delivery import media_title_from_session
from core.stream_policy_utils import normalize_user_key


def build_notification_policy_context(policy: dict, target: dict, related_sessions: list[dict] | None, translate) -> dict:
    try:
        rule = json.loads(policy.get("rule_value_json") or "{}")
    except Exception:
        rule = {}
    if not isinstance(rule, dict):
        rule = {}

    rule_type = str(policy.get("rule_type") or "").strip()

    try:
        limit = int(rule.get("max") or rule.get("max_kbps") or 0)
    except (TypeError, ValueError):
        limit = 0

    target_key = normalize_user_key(target)
    target_session_key = str(target.get("session_key") or "")
    target_ip = str(target.get("ip") or "").strip()
    target_server_id = target.get("server_id")

    all_related = list(related_sessions or [])

    if not any(str(s.get("session_key") or "") == target_session_key for s in all_related):
        all_related.append(target)

    # Sessions réellement utiles pour expliquer le blocage.
    if rule_type == "max_ips_per_user":
        involved = [
            s for s in all_related
            if normalize_user_key(s) == target_key
        ]

    elif rule_type == "max_streams_per_user":
        involved = [
            s for s in all_related
            if normalize_user_key(s) == target_key
        ]

    elif rule_type == "max_streams_per_ip":
        involved = [
            s for s in all_related
            if str(s.get("ip") or "").strip() == target_ip
        ]

    elif rule_type in {
        "max_streams_per_server",
        "max_transcodes_per_server",
        "max_transcodes_global",
        "max_bitrate_kbps",
        "ban_4k_transcode",
    }:
        involved = [
            s for s in all_related
            if s.get("server_id") == target_server_id
        ]

    else:
        involved = [
            s for s in all_related
            if normalize_user_key(s) == target_key
        ]

    if not involved:
        involved = [target]

    def session_media(session: dict) -> str:
        return media_title_from_session(session) or "Unknown media"

    def session_device(session: dict) -> str:
        return (
            str(session.get("device") or "").strip()
            or str(session.get("client_product") or "").strip()
            or str(session.get("client_name") or "").strip()
            or "Unknown device"
        )

    def summary(session: dict) -> str:
        parts = [session_media(session)]

        device = session_device(session)
        if device:
            parts.append(device)

        ip = str(session.get("ip") or "").strip()
        if ip:
            parts.append(ip)

        server_name = str(session.get("server_name") or "").strip()
        if server_name:
            parts.append(server_name)

        return " - ".join(parts)

    def device_summary(session: dict) -> str:
        parts = [session_device(session)]

        ip = str(session.get("ip") or "").strip()
        if ip:
            parts.append(ip)

        server_name = str(session.get("server_name") or "").strip()
        if server_name:
            parts.append(server_name)

        media = session_media(session)
        if media:
            parts.append(media)

        return " - ".join(parts)

    unique_ips = sorted({
        str(s.get("ip") or "").strip()
        for s in involved
        if str(s.get("ip") or "").strip()
    })

    unique_devices = []
    seen_devices = set()
    for s in involved:
        line = device_summary(s)
        key = line.lower()
        if key in seen_devices:
            continue
        seen_devices.add(key)
        unique_devices.append(line)

    if rule_type == "max_ips_per_user":
        observed = len(unique_ips)
        limit_label = translate("policy_limit_label_max_ips_per_user")
        explanation = translate(
            "policy_explanation_max_ips_per_user",
            limit=limit,
            observed=observed,
        )

    elif rule_type == "max_streams_per_user":
        observed = len(involved)
        limit_label = translate("policy_limit_label_max_streams_per_user")
        explanation = translate(
            "policy_explanation_max_streams_per_user",
            limit=limit,
            observed=observed,
        )

    elif rule_type == "max_streams_per_ip":
        observed = len(involved)
        limit_label = translate("policy_limit_label_max_streams_per_ip")
        explanation = translate(
            "policy_explanation_max_streams_per_ip",
            limit=limit,
            observed=observed,
            ip=target_ip or "unknown",
        )

    elif rule_type == "max_streams_per_server":
        observed = len(involved)
        limit_label = translate("policy_limit_label_max_streams_per_server")
        explanation = translate(
            "policy_explanation_max_streams_per_server",
            limit=limit,
            observed=observed,
        )

    elif rule_type in {"max_transcodes_per_server", "max_transcodes_global"}:
        observed = sum(int(s.get("is_transcode") or 0) for s in involved)
        limit_label = translate("policy_limit_label_max_transcodes")
        explanation = translate(
            "policy_explanation_max_transcodes",
            limit=limit,
            observed=observed,
        )

    elif rule_type == "max_bitrate_kbps":
        observed = ""
        limit_label = translate("policy_limit_label_max_bitrate")
        explanation = translate(
            "policy_explanation_max_bitrate",
            limit=limit,
        )

    elif rule_type == "ban_4k_transcode":
        observed = ""
        limit_label = translate("policy_limit_label_ban_4k_transcode")
        explanation = translate("policy_explanation_ban_4k_transcode")

    else:
        observed = len(involved)
        limit_label = translate("policy_limit_label_unknown")
        explanation = translate(
            "policy_explanation_unknown",
            rule_type=rule_type or "unknown",
        )

    policy_translation_key = "subscription_expired" if rule.get("system_tag") == "expired_subscription" else (rule_type or "unknown")
    policy_translation_variables = {
        "limit": limit,
        "value": observed,
        "observed": observed,
        "ip": target_ip or "unknown",
        "rule_type": rule_type or "unknown",
    }
    policy_limit_label_key = f"limit_label_{policy_translation_key}"
    if policy_translation_key == "subscription_expired":
        policy_limit_label_key = "limit_label_max_streams_per_user"

    others = [
        s for s in involved
        if str(s.get("session_key") or "") != target_session_key
    ]

    return {
        "policy_rule_type": rule_type,
        "policy_limit": limit,
        "policy_limit_label": limit_label,
        "policy_observed": observed,
        "policy_explanation": explanation,
        "policy_reason_key": policy_translation_key,
        "policy_reason_variables": policy_translation_variables,
        "policy_explanation_key": policy_translation_key,
        "policy_explanation_variables": policy_translation_variables,
        "policy_limit_label_key": policy_limit_label_key,
        "policy_limit_label_variables": policy_translation_variables,

        "maximum_streams": limit if "streams" in rule_type else "",
        "maximum_ips": limit if "ips" in rule_type else "",

        "stream_count": len(involved),
        "ip_count": len(unique_ips),

        "active_streams_count": len(involved),
        "active_streams": "\n".join(f"- {summary(s)}" for s in involved) or "None",

        "active_ips_count": len(unique_ips),
        "active_ips": "\n".join(f"- {ip}" for ip in unique_ips) or "None",

        "active_devices_count": len(unique_devices),
        "active_devices": "\n".join(f"- {device}" for device in unique_devices) or "None",

        "stream_killed": summary(target),
        "other_streams_count": len(others),
        "other_streams": "\n".join(f"- {summary(s)}" for s in others) or "None",
        "all_streams": "\n".join(f"- {summary(s)}" for s in involved) or "None",
    }

