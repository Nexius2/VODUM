from __future__ import annotations

import json
from collections.abc import Callable


def _parse_json_list(raw: str):
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def delete_locked_subscription_policies(db, vodum_user_id: int):
    rows = db.query(
        """
        SELECT id, rule_value_json
        FROM stream_policies
        WHERE scope_type = 'user' AND scope_id = ?
        """,
        (vodum_user_id,),
    ) or []
    for row in rows:
        try:
            rule = json.loads(row["rule_value_json"] or "{}")
        except Exception:
            rule = {}
        if rule.get("locked") and rule.get("subscription_name"):
            db.execute(
                "DELETE FROM stream_policies WHERE id = ?",
                (int(row["id"]),),
            )


def clear_template_snapshot(db, vodum_user_id: int):
    delete_locked_subscription_policies(db, vodum_user_id)
    db.execute(
        "UPDATE vodum_users SET subscription_template_id = NULL WHERE id = ?",
        (vodum_user_id,),
    )


def apply_template_snapshot(
    db,
    vodum_user_id: int,
    template_id: int,
    auto_enable_stream_enforcer: Callable[[], object],
):
    template = db.query_one(
        """
        SELECT id, name, policies_json
        FROM subscription_templates
        WHERE id = ?
        """,
        (template_id,),
    )
    if not template:
        raise ValueError("subscription_template_not_found")

    template = dict(template)
    template_name = template.get("name") or ""
    policies = _parse_json_list(template.get("policies_json") or "[]")
    delete_locked_subscription_policies(db, vodum_user_id)
    any_enabled = False

    for policy in policies:
        if not isinstance(policy, dict):
            continue
        rule_type = (policy.get("rule_type") or "").strip()
        if not rule_type:
            continue

        rule = (
            dict(policy["rule"])
            if isinstance(policy.get("rule"), dict)
            else {}
        )
        rule["locked"] = True
        rule["subscription_name"] = template_name

        provider = (policy.get("provider") or "").strip() or None
        server_id = (
            int(policy["server_id"])
            if str(policy.get("server_id", "")).isdigit()
            else None
        )
        is_enabled = 1 if str(policy.get("is_enabled", "1")) == "1" else 0
        any_enabled = any_enabled or is_enabled == 1
        priority = int(policy.get("priority") or 100)

        db.execute(
            """
            INSERT INTO stream_policies(
                scope_type, scope_id, provider, server_id, is_enabled,
                priority, rule_type, rule_value_json
            )
            VALUES ('user', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vodum_user_id,
                provider,
                server_id,
                is_enabled,
                priority,
                rule_type,
                json.dumps(rule),
            ),
        )

    db.execute(
        """
        UPDATE vodum_users
        SET subscription_template_id = ?
        WHERE id = ?
        """,
        (template_id, vodum_user_id),
    )
    if any_enabled:
        auto_enable_stream_enforcer()
    return template_name
