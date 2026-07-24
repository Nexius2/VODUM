from __future__ import annotations

import json


ACTIVE_POLICY_COLUMNS = """
                p.id,
                p.rule_type,
                p.scope_type,
                p.scope_id,
                p.provider,
                p.server_id,
                p.priority,
                p.rule_value_json
"""


def load_active_policies_for_user(db, vodum_user_id: int):
    media_rows = db.query(
        """
        SELECT
            mu.server_id,
            LOWER(COALESCE(s.type, mu.type, '')) AS provider,
            COALESCE(s.name, '') AS server_name
        FROM media_users mu
        LEFT JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        """,
        (vodum_user_id,),
    ) or []

    server_ids = []
    providers = set()
    server_names = {}
    for row in media_rows:
        item = dict(row)
        if item.get("server_id") is not None:
            server_id = int(item["server_id"])
            server_ids.append(server_id)
            server_names[server_id] = item.get("server_name") or f"#{server_id}"
        provider = (item.get("provider") or "").strip().lower()
        if provider:
            providers.add(provider)

    clauses = [
        "p.scope_type = 'global'",
        "(p.scope_type = 'user' AND p.scope_id = ?)",
    ]
    params = [vodum_user_id]
    if server_ids:
        placeholders = ",".join("?" for _ in server_ids)
        clauses.append(
            f"(p.scope_type = 'server' AND p.scope_id IN ({placeholders}))"
        )
        params.extend(server_ids)
        clauses.append(f"(p.server_id IN ({placeholders}))")
        params.extend(server_ids)

    rows = db.query(
        f"""
        SELECT
{ACTIVE_POLICY_COLUMNS},
            s.name AS policy_server_name
        FROM stream_policies p
        LEFT JOIN servers s ON s.id = p.server_id
        WHERE p.is_enabled = 1
          AND ({' OR '.join(clauses)})
        ORDER BY p.priority ASC, p.id ASC
        """,
        tuple(params),
    ) or []

    policies = []
    for row in rows:
        policy = dict(row)
        provider = (policy.get("provider") or "").strip().lower()
        if provider and providers and provider not in providers:
            continue

        try:
            rule = json.loads(policy.get("rule_value_json") or "{}")
            if not isinstance(rule, dict):
                rule = {}
        except Exception:
            rule = {}

        scope_type = (policy.get("scope_type") or "").strip()
        scope_label = scope_type
        if scope_type == "global":
            scope_label = "Global"
        elif scope_type == "user":
            scope_label = "User"
        elif scope_type == "server":
            server_id = policy.get("scope_id")
            scope_label = (
                server_names.get(int(server_id), f"Server #{server_id}")
                if server_id is not None
                else "Server"
            )

        origin_type = "Manual"
        origin_label = "Manual"
        system_tag = (rule.get("system_tag") or "").strip()
        subscription_name = (rule.get("subscription_name") or "").strip()
        if system_tag == "expired_subscription":
            origin_type = "System"
            origin_label = "Expired subscription"
        elif subscription_name:
            origin_type = "Subscription"
            origin_label = subscription_name

        value_parts = []
        if "max" in rule:
            value_parts.append(f"max={rule.get('max')}")
        elif (
            policy.get("rule_type") == "max_bitrate_kbps"
            and rule.get("kbps") is not None
        ):
            value_parts.append(f"kbps={rule.get('kbps')}")
        elif policy.get("rule_type") == "device_allowlist":
            devices = rule.get("devices") or rule.get("allowed_devices") or []
            if isinstance(devices, list):
                value_parts.append(
                    ", ".join(str(value) for value in devices)
                    if devices
                    else "empty"
                )
            else:
                value_parts.append(str(devices))
        elif policy.get("rule_type") == "ban_4k_transcode":
            value_parts.append("enabled")
        else:
            value_parts.append("configured")

        selector = rule.get("selector")
        if selector:
            value_parts.append(f"selector={selector}")
        if rule.get("allow_local_ip") or rule.get("local_ip"):
            value_parts.append("local_ip=yes")

        policies.append(
            {
                "id": policy.get("id"),
                "rule_type": policy.get("rule_type"),
                "scope_type": scope_type,
                "scope_label": scope_label,
                "origin_type": origin_type,
                "origin_label": origin_label,
                "provider": provider or "both",
                "priority": policy.get("priority"),
                "value": " | ".join(value_parts),
            }
        )

    return policies
