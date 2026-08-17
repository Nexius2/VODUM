def _validated_server_ids(state: dict) -> set[int]:
    result = set()
    for value in state.get("validated_server_ids") or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def load_setup_wizard_page_data(db, settings: dict, state: dict) -> dict:
    validated_ids = _validated_server_ids(state)
    servers = [
        dict(row)
        for row in (
            db.query("SELECT id,name,type,url,status FROM servers ORDER BY id") or []
        )
    ]
    for server in servers:
        server["wizard_validated"] = int(server["id"]) in validated_ids or (
            not validated_ids and state.get("media_server") == "configured"
        )

    subscription_count = int(
        (
            db.query_one("SELECT COUNT(*) AS cnt FROM subscription_templates")
            or {"cnt": 0}
        )["cnt"]
        or 0
    )
    user_count = int(
        (db.query_one("SELECT COUNT(*) AS cnt FROM vodum_users") or {"cnt": 0})[
            "cnt"
        ]
        or 0
    )
    sync_running = bool(
        db.query_one(
            "SELECT id FROM tasks WHERE name IN ('sync_plex','sync_jellyfin') "
            "AND status IN ('queued','running') LIMIT 1"
        )
    )

    communication_settings = dict(settings)
    for secret_name in (
        "smtp_pass",
        "smtp_oauth_access_token",
        "discord_bot_token",
    ):
        communication_settings[f"{secret_name}_configured"] = bool(
            communication_settings.get(secret_name)
        )
        communication_settings[secret_name] = ""

    wizard_templates = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT id,key,name,enabled,subject,body FROM comm_templates
                WHERE key IN ('default_relance','default_fin','stream_blocked','usage_risk_upgrade_suggestion')
                ORDER BY CASE key
                  WHEN 'default_relance' THEN 1 WHEN 'default_fin' THEN 2
                  WHEN 'stream_blocked' THEN 3 ELSE 4 END
                """
            )
            or []
        )
    ]
    subscription_templates = [
        dict(row)
        for row in (
            db.query(
                "SELECT id,name,duration_days,is_lifetime,is_enabled "
                "FROM subscription_templates ORDER BY is_default DESC,name"
            )
            or []
        )
    ]
    wizard_users = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT u.id,u.username,u.email,u.subscription_template_id,st.name AS subscription_name
                FROM vodum_users u
                LEFT JOIN subscription_templates st ON st.id=u.subscription_template_id
                ORDER BY COALESCE(u.username,u.email),u.id LIMIT 500
                """
            )
            or []
        )
    ]
    return {
        "servers": servers,
        "subscription_count": subscription_count,
        "user_count": user_count,
        "sync_running": sync_running,
        "communication_settings": communication_settings,
        "wizard_templates": wizard_templates,
        "subscription_templates": subscription_templates,
        "wizard_users": wizard_users,
    }
