from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


ALLOWED_ENFORCEMENT_PAGE_SIZES = (20, 50, 100)
POLICY_COLUMNS = """
    p.id, p.scope_type, p.scope_id, p.provider, p.server_id,
    p.is_enabled, p.priority, p.rule_type, p.rule_value_json,
    p.created_at, p.updated_at
""".strip()


def _decorate_policy(row):
    policy = dict(row)
    try:
        rule = json.loads(policy.get("rule_value_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        rule = {}
    if not isinstance(rule, dict):
        rule = {}
    policy["_rule"] = rule
    policy["_is_system"] = bool(rule.get("system_tag"))
    policy["_is_locked"] = bool(rule.get("locked"))
    policy["_subscription_name"] = rule.get("subscription_name") or ""
    return policy


def load_policy_catalog(db, edit_policy_id=None):
    policies = [
        _decorate_policy(row)
        for row in (
            db.query(
                f"""
                SELECT {POLICY_COLUMNS},
                  s.name AS server_name,
                  vu.username AS scope_username
                FROM stream_policies p
                LEFT JOIN servers s ON s.id = p.server_id
                LEFT JOIN vodum_users vu
                  ON p.scope_type = 'user' AND vu.id = p.scope_id
                ORDER BY p.is_enabled DESC, p.priority ASC, p.id DESC
                """
            )
            or []
        )
    ]
    edit_policy = None
    if edit_policy_id:
        row = db.query_one(
            f"""
            SELECT {POLICY_COLUMNS}
            FROM stream_policies p
            WHERE p.id = ?
            """,
            (edit_policy_id,),
        )
        edit_policy = _decorate_policy(row) if row else None
    return {
        "policies": policies,
        "edit_policy": edit_policy,
        "system_count": sum(policy["_is_system"] for policy in policies),
        "locked_count": sum(policy["_is_locked"] for policy in policies),
        "subscription_managed_count": sum(
            bool(policy["_subscription_name"]) for policy in policies
        ),
    }


def load_policy_dashboard(db, catalog):
    base = db.query_one(
        """
        SELECT COUNT(*) AS total,
          SUM(CASE WHEN is_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
          SUM(CASE WHEN is_enabled = 0 THEN 1 ELSE 0 END) AS disabled,
          SUM(CASE WHEN scope_type = 'global' THEN 1 ELSE 0 END) AS scope_global,
          SUM(CASE WHEN scope_type = 'server' THEN 1 ELSE 0 END) AS scope_server,
          SUM(CASE WHEN scope_type = 'user' THEN 1 ELSE 0 END) AS scope_user,
          SUM(CASE WHEN provider = 'plex' THEN 1 ELSE 0 END) AS provider_plex,
          SUM(CASE WHEN provider = 'jellyfin' THEN 1 ELSE 0 END)
            AS provider_jellyfin,
          SUM(CASE WHEN provider IS NULL OR provider = '' THEN 1 ELSE 0 END)
            AS provider_both,
          COUNT(DISTINCT CASE WHEN scope_type = 'user' THEN scope_id END)
            AS targeted_users,
          COUNT(DISTINCT CASE WHEN server_id IS NOT NULL THEN server_id END)
            AS targeted_servers
        FROM stream_policies
        """
    )
    enforcement_sql = """
        SELECT COUNT(*) AS total_actions,
          SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
          SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count,
          COUNT(DISTINCT policy_id) AS affected_policies,
          COUNT(DISTINCT COALESCE(
            CAST(vodum_user_id AS TEXT), external_user_id
          )) AS affected_actors
        FROM stream_enforcements
        WHERE datetime(created_at) >= datetime('now', ?)
    """
    last_24h = db.query_one(enforcement_sql, ("-24 hours",))
    last_7d = db.query_one(enforcement_sql, ("-7 days",))
    base = dict(base) if base else {}
    last_24h = dict(last_24h) if last_24h else {}
    last_7d = dict(last_7d) if last_7d else {}
    value = lambda row, key: int(row.get(key) or 0)
    return {
        "total": value(base, "total"),
        "enabled": value(base, "enabled"),
        "disabled": value(base, "disabled"),
        "scope_global": value(base, "scope_global"),
        "scope_server": value(base, "scope_server"),
        "scope_user": value(base, "scope_user"),
        "provider_plex": value(base, "provider_plex"),
        "provider_jellyfin": value(base, "provider_jellyfin"),
        "provider_both": value(base, "provider_both"),
        "targeted_users": value(base, "targeted_users"),
        "targeted_servers": value(base, "targeted_servers"),
        "system_count": int(catalog["system_count"] or 0),
        "locked_count": int(catalog["locked_count"] or 0),
        "subscription_managed_count": int(
            catalog["subscription_managed_count"] or 0
        ),
        "actions_24h": value(last_24h, "total_actions"),
        "warn_24h": value(last_24h, "warn_count"),
        "kill_24h": value(last_24h, "kill_count"),
        "affected_policies_24h": value(last_24h, "affected_policies"),
        "affected_actors_24h": value(last_24h, "affected_actors"),
        "actions_7d": value(last_7d, "total_actions"),
        "warn_7d": value(last_7d, "warn_count"),
        "kill_7d": value(last_7d, "kill_count"),
    }


def load_policy_breakdowns(db, period="-30 days"):
    scopes = db.query(
        """
        SELECT scope_type AS label, COUNT(*) AS value
        FROM stream_policies
        GROUP BY scope_type
        ORDER BY value DESC, label ASC
        """
    )
    providers = db.query(
        """
        SELECT CASE
            WHEN provider IS NULL OR provider = '' THEN 'both'
            ELSE provider
          END AS label,
          COUNT(*) AS value
        FROM stream_enforcements
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY CASE
          WHEN provider IS NULL OR provider = '' THEN 'both'
          ELSE provider
        END
        ORDER BY value DESC, label ASC
        """,
        (period,),
    )
    rules = db.query(
        """
        SELECT p.rule_type AS label, COUNT(*) AS total,
          SUM(CASE WHEN e.action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
          SUM(CASE WHEN e.action = 'kill' THEN 1 ELSE 0 END) AS kill_count
        FROM stream_enforcements e
        JOIN stream_policies p ON p.id = e.policy_id
        WHERE datetime(e.created_at) >= datetime('now', ?)
        GROUP BY p.rule_type
        ORDER BY total DESC, p.rule_type ASC
        LIMIT 10
        """,
        (period,),
    )
    return {
        "policy_scope_breakdown": [dict(row) for row in (scopes or [])],
        "policy_provider_breakdown_30d": [
            dict(row) for row in (providers or [])
        ],
        "policy_rule_breakdown_30d": [dict(row) for row in (rules or [])],
    }


def load_policy_top_users(db, period="-30 days", limit=10):
    rows = db.query(
        """
        SELECT label, COUNT(*) AS total,
          SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
          SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count
        FROM (
          SELECT CASE
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
              ELSE NULL
            END AS label,
            e.action
          FROM stream_enforcements e
          LEFT JOIN vodum_users vu ON vu.id = e.vodum_user_id
          LEFT JOIN (
            SELECT server_id, external_user_id, MAX(username) AS username
            FROM media_users
            GROUP BY server_id, external_user_id
          ) mu_acc
            ON mu_acc.server_id = e.server_id
           AND mu_acc.external_user_id = e.external_user_id
          WHERE datetime(e.created_at) >= datetime('now', ?)
        ) q
        WHERE label IS NOT NULL
        GROUP BY label
        ORDER BY total DESC, label ASC
        LIMIT ?
        """,
        (period, int(limit)),
    )
    return [dict(row) for row in (rows or [])]


def load_recent_policy_enforcements(db, pagination):
    rows = db.query(
        """
        SELECT e.id AS enforcement_id, e.created_at, e.action, e.reason,
          e.provider, e.session_key, e.policy_id, e.server_id,
          e.vodum_user_id, e.external_user_id, e.account_username,
          e.ips_json, e.details_json,
          p.rule_type, p.scope_type, p.scope_id,
          p.priority AS policy_priority,
          p.is_enabled AS policy_enabled, p.rule_value_json,
          s.name AS server_name, vu.username AS vodum_username,
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
        ORDER BY e.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (pagination["per_page"], pagination["offset"]),
    )
    return [dict(row) for row in (rows or [])]


def load_grouped_policy_enforcements(
    db,
    period="-24 hours",
    source_limit=1000,
    result_limit=50,
):
    rows = db.query(
        """
        SELECT e.id AS enforcement_id, e.created_at, e.action, e.reason,
          e.provider, e.server_id, e.vodum_user_id, e.external_user_id,
          p.rule_type, s.name AS server_name,
          CASE WHEN e.vodum_user_id IS NOT NULL
            THEN 'vodum:' || CAST(e.vodum_user_id AS TEXT)
            ELSE 'ext:' || COALESCE(e.external_user_id, '')
          END AS actor_key,
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
        WHERE datetime(e.created_at) >= datetime('now', ?)
        ORDER BY e.created_at DESC
        LIMIT ?
        """,
        (period, int(source_limit)),
    )
    grouped = {}
    for raw_row in rows or []:
        row = dict(raw_row)
        actor_key = row.get("actor_key") or "unknown"
        if actor_key not in grouped:
            grouped[actor_key] = {
                "actor_key": actor_key,
                "user_label": row.get("user_label") or "—",
                "warn_count": 0,
                "kill_count": 0,
                "total_count": 0,
                "last_action": row.get("action"),
                "last_created_at": row.get("created_at"),
                "last_server_name": row.get("server_name"),
                "last_rule_type": row.get("rule_type"),
                "last_reason": row.get("reason"),
            }
        grouped[actor_key]["total_count"] += 1
        if row.get("action") == "warn":
            grouped[actor_key]["warn_count"] += 1
        elif row.get("action") == "kill":
            grouped[actor_key]["kill_count"] += 1
    return sorted(
        grouped.values(),
        key=lambda item: (
            int(item.get("kill_count") or 0),
            int(item.get("warn_count") or 0),
            int(item.get("total_count") or 0),
            str(item.get("last_created_at") or ""),
        ),
        reverse=True,
    )[: int(result_limit)]


def load_policy_tracked_state(db, period="-1 hour"):
    row = db.query_one(
        """
        SELECT COUNT(*) AS tracked_1h,
          SUM(CASE WHEN warned_at IS NOT NULL
            AND datetime(warned_at) >= datetime('now', ?)
            THEN 1 ELSE 0 END) AS warned_1h,
          SUM(CASE WHEN killed_at IS NOT NULL
            AND datetime(killed_at) >= datetime('now', ?)
            THEN 1 ELSE 0 END) AS killed_1h
        FROM stream_enforcement_state
        WHERE datetime(last_seen_at) >= datetime('now', ?)
        """,
        (period, period, period),
    )
    state = dict(row) if row else {}
    return {
        "tracked_1h": int(state.get("tracked_1h") or 0),
        "warned_1h": int(state.get("warned_1h") or 0),
        "killed_1h": int(state.get("killed_1h") or 0),
    }


def load_policy_hits_timeline(db, days=30, today=None):
    days = max(1, int(days))
    rows = db.query(
        """
        SELECT date(created_at) AS day,
          SUM(CASE WHEN action = 'warn' THEN 1 ELSE 0 END) AS warn_count,
          SUM(CASE WHEN action = 'kill' THEN 1 ELSE 0 END) AS kill_count,
          COUNT(*) AS total
        FROM stream_enforcements
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY date(created_at)
        ORDER BY day ASC
        """,
        (f"-{days} days",),
    )
    by_day = {}
    for raw_row in rows or []:
        row = dict(raw_row)
        by_day[row["day"]] = {
            "day": row["day"],
            "warn_count": int(row.get("warn_count") or 0),
            "kill_count": int(row.get("kill_count") or 0),
            "total": int(row.get("total") or 0),
        }
    current_day = today or datetime.now(timezone.utc).date()
    return [
        by_day.get(
            (current_day - timedelta(days=offset)).isoformat(),
            {
                "day": (current_day - timedelta(days=offset)).isoformat(),
                "warn_count": 0,
                "kill_count": 0,
                "total": 0,
            },
        )
        for offset in range(days - 1, -1, -1)
    ]


def load_policy_enforcement_pagination(db, args):
    page = max(args.get("enforcement_page", 1, type=int), 1)
    per_page = args.get("enforcement_per_page", 20, type=int)
    if per_page not in ALLOWED_ENFORCEMENT_PAGE_SIZES:
        per_page = 20

    count = db.query_one(
        "SELECT COUNT(*) AS total FROM stream_enforcements"
    )
    total = int(dict(count).get("total") or 0) if count else 0
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "offset": (page - 1) * per_page,
    }
