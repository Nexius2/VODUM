from communications_engine import fetch_campaign_attachments, fetch_template_attachments
from core.communication_template_admin import apply_template_translation
from core.communications.default_templates import is_stream_blocked_template
from core.communication_history_rendering import render_communication_history_message


def load_campaign_page_data(db, load_id, editor_columns: str, list_columns: str) -> dict:
    servers = db.query("SELECT id, name FROM servers ORDER BY name")
    subscriptions = db.query("""
        SELECT id, name, is_default FROM subscription_templates
        WHERE COALESCE(is_enabled, 1) = 1 ORDER BY is_default DESC, name ASC
    """) or []
    loaded = None
    if load_id:
        row = db.query_one(f"SELECT {editor_columns} FROM comm_campaigns WHERE id = ?", (load_id,))
        loaded = dict(row) if row else None
        if loaded:
            loaded["attachments"] = fetch_campaign_attachments(db, int(loaded["id"]))
    campaigns = db.query(f"""
        SELECT {list_columns}, st.name AS subscription_template_name
        FROM comm_campaigns c
        LEFT JOIN subscription_templates st ON st.id = c.subscription_template_id
        ORDER BY c.created_at DESC, c.id DESC LIMIT 200
    """)
    return {
        "campaigns": [dict(row) for row in (campaigns or [])],
        "servers": servers,
        "subscription_templates": subscriptions,
        "loaded_campaign": loaded,
    }


def load_template_page_data(
    db, *, load_id, page: int, per_page: int, language: str,
    editor_columns: str, list_columns: str,
) -> dict:
    loaded = None
    loaded_is_stream_blocked = False
    if load_id:
        row = db.query_one(f"SELECT {editor_columns} FROM comm_templates WHERE id = ?", (load_id,))
        loaded = dict(row) if row else None
        if loaded:
            loaded = apply_template_translation(db, loaded, language)
            loaded["attachments"] = fetch_template_attachments(db, int(loaded["id"]))
            loaded_is_stream_blocked = is_stream_blocked_template(loaded)
    total_row = db.query_one("SELECT COUNT(*) AS total FROM comm_templates") or {"total": 0}
    total_rows = int(total_row["total"] or 0)
    total_pages = max((total_rows + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    templates = db.query(f"""
        SELECT {list_columns}, st.name AS subscription_template_name
        FROM comm_templates ct
        LEFT JOIN comm_template_translations ctl ON ctl.template_id = ct.id AND ctl.language = ?
        LEFT JOIN subscription_templates st ON st.id = ct.subscription_template_id
        ORDER BY ct.enabled DESC, LOWER(ct.name), ct.id DESC LIMIT ? OFFSET ?
    """, (language, per_page, (page - 1) * per_page))
    subscriptions = db.query("""
        SELECT id, name FROM subscription_templates
        WHERE COALESCE(is_enabled, 1) = 1 ORDER BY name COLLATE NOCASE
    """) or []
    return {
        "templates": [dict(row) for row in (templates or [])],
        "loaded_template": loaded,
        "loaded_is_stream_blocked": loaded_is_stream_blocked,
        "subscription_templates": [dict(row) for row in subscriptions],
        "page": page, "per_page": per_page,
        "total_rows": total_rows, "total_pages": total_pages,
    }


def load_history_detail(db, history_id: int, history_columns: str) -> dict | None:
    row = db.query_one(f"""
        SELECT {history_columns}, u.id AS user_id, u.username AS user_username,
          u.firstname AS user_firstname, u.lastname AS user_lastname, u.email AS user_email,
          u.expiration_date AS user_expiration_date, u.subscription_template_id AS user_subscription_template_id,
          st.name AS subscription_name, st.duration_days AS subscription_duration_days,
          st.subscription_value AS subscription_value, t.subject AS template_subject, t.body AS template_body,
          c.subject AS campaign_subject, c.body AS campaign_body
        FROM comm_history h
        LEFT JOIN vodum_users u ON u.id = h.user_id
        LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
        LEFT JOIN comm_templates t ON t.id = h.template_id
        LEFT JOIN comm_campaigns c ON c.id = h.campaign_id
        WHERE h.id = ? LIMIT 1
    """, (history_id,))
    if not row:
        return None
    settings = db.query_one("SELECT brand_name FROM settings WHERE id = 1") or {}
    return render_communication_history_message(dict(row), dict(settings).get("brand_name") or "VODUM")


def load_configuration_page_data(db, settings_columns: str) -> dict:
    row = db.query_one(f"SELECT {settings_columns} FROM settings WHERE id = 1")
    settings = dict(row) if row else {}
    for key in ("smtp_pass", "smtp_oauth_access_token", "discord_bot_token"):
        settings[f"{key}_configured"] = bool(settings.get(key))
        settings[key] = ""
    queue_row = db.query_one("""
        SELECT SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
        FROM comm_scheduled
    """) or {}
    return {
        "settings": settings,
        "queue_summary": {key: int(value or 0) for key, value in dict(queue_row).items()},
    }
