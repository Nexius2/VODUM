from __future__ import annotations

def parse_enforcement_actor_key(actor_key):
    actor_key = (actor_key or "").strip()
    if actor_key.startswith("vodum:"):
        try:
            return "e.vodum_user_id = ?", int(actor_key.split(":", 1)[1]), None
        except (TypeError, ValueError):
            return None, None, "Invalid vodum actor key"
    if actor_key.startswith("ext:"):
        value = actor_key.split(":", 1)[1].strip()
        if value:
            return "COALESCE(e.external_user_id, '') = ?", value, None
        return None, None, "Invalid external actor key"
    return None, None, "Missing actor key"


def register(app):
    from flask import jsonify, request, url_for
    from web.helpers import get_db

    @app.route("/monitoring/policies/enforcements/<int:enforcement_id>")
    def monitoring_policy_enforcement_detail(enforcement_id):
        row = get_db().query_one(
            """
            SELECT e.id AS enforcement_id, e.created_at, e.action, e.reason,
              e.provider, e.session_key, e.policy_id, e.server_id,
              e.vodum_user_id, e.external_user_id, e.account_username,
              e.ips_json, e.details_json, p.rule_type, p.scope_type,
              p.scope_id, p.priority AS policy_priority,
              p.is_enabled AS policy_enabled, p.rule_value_json,
              s.name AS server_name, vu.username AS vodum_username,
              COALESCE(
                NULLIF(TRIM(e.account_username), ''),
                NULLIF(TRIM(vu.username), ''),
                NULLIF(TRIM(e.external_user_id), ''),
                '—'
              ) AS user_label
            FROM stream_enforcements e
            LEFT JOIN stream_policies p ON p.id = e.policy_id
            LEFT JOIN servers s ON s.id = e.server_id
            LEFT JOIN vodum_users vu ON vu.id = e.vodum_user_id
            WHERE e.id = ?
            LIMIT 1
            """,
            (enforcement_id,),
        )
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "row": dict(row)})

    @app.route("/monitoring/policies/enforcements/by-user")
    def monitoring_policy_enforcements_by_user():
        where_clause, actor_value, error = parse_enforcement_actor_key(
            request.args.get("actor_key")
        )
        if error:
            return jsonify({"ok": False, "error": error}), 400

        rows = get_db().query(
            f"""
            SELECT
              e.id AS enforcement_id, e.created_at, e.action, e.reason,
              e.provider, e.session_key, e.policy_id, e.server_id,
              e.vodum_user_id, e.external_user_id, e.account_username,
              p.rule_type, p.scope_type, p.scope_id,
              p.priority AS policy_priority,
              p.is_enabled AS policy_enabled,
              s.name AS server_name,
              vu.username AS vodum_username,
              CASE
                WHEN e.account_username IS NOT NULL
                  AND TRIM(e.account_username) <> ''
                    THEN e.account_username
                WHEN mu_acc.username IS NOT NULL
                  AND TRIM(mu_acc.username) <> ''
                    THEN mu_acc.username
                WHEN vu.username IS NOT NULL AND TRIM(vu.username) <> ''
                    THEN vu.username
                WHEN e.external_user_id IS NOT NULL
                  AND TRIM(e.external_user_id) <> ''
                  AND TRIM(e.external_user_id)
                    NOT GLOB '[0-9]*.[0-9]*.[0-9]*.[0-9]*'
                    THEN e.external_user_id
                ELSE '—'
              END AS user_label
            FROM stream_enforcements e
            LEFT JOIN stream_policies p ON p.id = e.policy_id
            LEFT JOIN servers s ON s.id = e.server_id
            LEFT JOIN vodum_users vu ON vu.id = e.vodum_user_id
            LEFT JOIN (
              SELECT server_id, external_user_id, MAX(username) AS username
              FROM media_users
              GROUP BY server_id, external_user_id
            ) mu_acc
              ON mu_acc.server_id = e.server_id
             AND mu_acc.external_user_id = e.external_user_id
            WHERE datetime(e.created_at) >= datetime('now', '-24 hours')
              AND {where_clause}
            ORDER BY e.created_at DESC
            LIMIT 200
            """,
            [actor_value],
        ) or []

        result = []
        for row in rows:
            item = dict(row)
            item["detail_url"] = url_for(
                "monitoring_policy_enforcement_detail",
                enforcement_id=item["enforcement_id"],
            )
            result.append(item)
        return jsonify({"ok": True, "rows": result})
