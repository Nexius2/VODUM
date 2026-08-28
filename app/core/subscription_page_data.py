import json
import math

from core.subscription_value_format import format_subscription_value


SUBSCRIPTION_SETTINGS_COLUMNS = """
    default_subscription_days,
    delete_after_expiry_days,
    expiry_mode,
    warn_then_disable_days,
    usage_risk_enabled,
    usage_risk_send_upgrade_suggestions,
    usage_risk_send_stream_blocked_message,
    usage_risk_min_kills_before_suggestion,
    usage_risk_analysis_window_days,
    usage_risk_suggestion_cooldown_days,
    usage_risk_medium_threshold,
    usage_risk_high_threshold,
    subscription_plans_enabled_only,
    subscription_currency,
    enable_cron_jobs
"""


STREAM_POLICY_PAGE_COLUMNS = """
                  p.id,
                  p.rule_type,
                  p.scope_type,
                  p.scope_id,
                  p.provider,
                  p.server_id,
                  p.priority,
                  p.is_enabled,
                  p.rule_value_json
"""

STREAM_POLICY_EDITOR_COLUMNS = """
            id,
            rule_type,
            scope_type,
            scope_id,
            provider,
            server_id,
            priority,
            is_enabled,
            rule_value_json
"""


def load_subscription_page_catalog(db, *, tab: str) -> dict:
    """Load the tab-dependent settings, servers, gift users and templates."""
    settings_row = (
        db.query_one(
            f"SELECT {SUBSCRIPTION_SETTINGS_COLUMNS} FROM settings WHERE id = 1"
        )
        if tab in ("templates", "settings")
        else None
    )
    settings = dict(settings_row) if settings_row else {}

    servers = (
        db.query("SELECT id, name, type FROM servers ORDER BY name") or []
        if tab in ("templates", "applications", "policies", "gifts")
        else []
    )

    gift_users = []
    if tab == "gifts":
        gift_users = db.query("""
            SELECT
              vu.id,
              vu.username,
              vu.firstname,
              vu.lastname,
              vu.email,
              vu.second_email,
              vu.discord_name,
              vu.status,
              (
                SELECT GROUP_CONCAT(
                  COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
                  ' '
                )
                FROM media_users mu
                WHERE mu.vodum_user_id = vu.id
              ) AS media_search
            FROM vodum_users vu
            WHERE vu.status IN ('active', 'pre_expired', 'reminder')
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = vu.id
              )
            ORDER BY LOWER(COALESCE(vu.username, '')) ASC, vu.id ASC
        """) or []
    gift_users = [dict(row) for row in gift_users]

    templates = []
    if tab in ("templates", "applications"):
        templates = db.query("""
            SELECT
              id,
              name,
              notes,
              duration_days,
              subscription_value,
              is_default,
              is_enabled,
              is_lifetime,
              hide_from_portal,
              policies_json,
              created_at,
              updated_at
            FROM subscription_templates
            ORDER BY is_default DESC, name
        """) or []
    templates = [dict(row) for row in templates]
    for template in templates:
        template["subscription_value"] = format_subscription_value(
            template.get("subscription_value")
        )
        try:
            policies = json.loads(template.get("policies_json") or "[]")
            template["policies_count"] = len(policies) if isinstance(policies, list) else 0
        except (TypeError, ValueError):
            template["policies_count"] = 0

    return {
        "settings": settings,
        "servers": servers,
        "gift_users": gift_users,
        "templates": templates,
        "enabled_templates": [
            template
            for template in templates
            if int(template.get("is_enabled") or 0) == 1
        ],
    }


def load_subscription_application_users(
    db,
    *,
    page: int = 1,
    per_page: int = 20,
    search: str = "",
) -> dict:
    """Load and paginate the users shown in the plan application tab."""
    page = max(int(page or 1), 1)
    per_page = int(per_page or 20)
    if per_page not in (20, 50, 100):
        per_page = 20
    search = " ".join(str(search or "").split()).strip()

    where = []
    params = []
    if search:
        like = f"%{search}%"
        where.append("""
            (
                COALESCE(vu.username, '') LIKE ?
                OR COALESCE(vu.email, '') LIKE ?
                OR COALESCE(vu.second_email, '') LIKE ?
                OR COALESCE(vu.firstname, '') LIKE ?
                OR COALESCE(vu.lastname, '') LIKE ?
                OR COALESCE(vu.notes, '') LIKE ?
                OR COALESCE(vu.discord_name, '') LIKE ?
                OR COALESCE(vu.status, '') LIKE ?
                OR COALESCE(st.name, '') LIKE ?
                OR CAST(vu.id AS TEXT) LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM media_users mu_search
                    WHERE mu_search.vodum_user_id = vu.id
                      AND (
                        COALESCE(mu_search.username, '') LIKE ?
                        OR COALESCE(mu_search.email, '') LIKE ?
                      )
                )
            )
        """)
        params.extend([like] * 12)

    from_sql = """
        FROM vodum_users vu
        LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
    """
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    total_row = db.query_one(
        "SELECT COUNT(*) AS total " + from_sql + where_sql,
        tuple(params),
    ) or {"total": 0}
    total_users = int(total_row["total"] or 0)
    total_pages = max(math.ceil(total_users / per_page), 1)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    users = db.query(
        """
        SELECT
          vu.id,
          vu.username,
          vu.email,
          vu.second_email,
          vu.firstname,
          vu.lastname,
          vu.notes,
          vu.discord_name,
          vu.status,
          vu.subscription_template_id,
          vu.max_streams_override,
          st.name AS subscription_template_name,
          (
            SELECT GROUP_CONCAT(
              COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
              ' '
            )
            FROM media_users mu
            WHERE mu.vodum_user_id = vu.id
          ) AS media_search
        """
        + from_sql
        + where_sql
        + """
        ORDER BY LOWER(COALESCE(vu.username, '')) ASC, vu.id ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [per_page, offset]),
    ) or []

    return {
        "users": [dict(row) for row in users],
        "page": page,
        "per_page": per_page,
        "search": search,
        "total_users": total_users,
        "total_pages": total_pages,
    }


def _decorate_policy(row) -> dict:
    policy = dict(row)
    try:
        rule = json.loads(policy.get("rule_value_json") or "{}")
    except (TypeError, ValueError):
        rule = {}
    if not isinstance(rule, dict):
        rule = {}
    policy["_rule"] = rule
    policy["_is_system"] = bool(rule.get("system_tag"))
    policy["_is_locked"] = bool(rule.get("locked"))
    policy["_subscription_name"] = rule.get("subscription_name") or ""
    return policy


def load_subscription_policy_context(db, *, edit_policy_id: int | None = None) -> dict:
    """Load policy rows and the optional policy editor record."""
    policies = db.query(f"""
        SELECT
{STREAM_POLICY_PAGE_COLUMNS},
          s.name AS server_name,
          vu.username AS scope_username,
          vu.firstname AS scope_firstname,
          vu.lastname AS scope_lastname,
          vu.email AS scope_email,
          vu.second_email AS scope_second_email,
          vu.discord_name AS scope_discord_name,
          (
            SELECT GROUP_CONCAT(
              COALESCE(mu.username, '') || ' ' || COALESCE(mu.email, ''),
              ' '
            )
            FROM media_users mu
            WHERE mu.vodum_user_id = vu.id
          ) AS scope_media_search
        FROM stream_policies p
        LEFT JOIN servers s ON s.id = p.server_id
        LEFT JOIN vodum_users vu
          ON (p.scope_type = 'user' AND vu.id = p.scope_id)
        ORDER BY p.is_enabled DESC, p.priority ASC, p.id DESC
    """) or []
    policies = [_decorate_policy(row) for row in policies]

    edit_policy = None
    if edit_policy_id:
        row = db.query_one(
            f"SELECT {STREAM_POLICY_EDITOR_COLUMNS} FROM stream_policies WHERE id = ?",
            (edit_policy_id,),
        )
        if row:
            edit_policy = _decorate_policy(row)

    return {"policies": policies, "edit_policy": edit_policy}
