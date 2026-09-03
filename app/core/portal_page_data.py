from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import urlsplit

from core.subscription_value_format import format_subscription_value


_PORTAL_POLICY_RULES = {
    "max_streams_per_user": "portal_limit_streams_user",
    "max_streams_per_ip": "portal_limit_streams_ip",
    "max_ips_per_user": "portal_limit_ips_user",
    "max_bitrate_kbps": "portal_limit_bitrate",
    "max_transcodes_global": "portal_limit_transcodes",
    "device_allowlist": "portal_limit_devices",
}


def _json_object(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _subscription_limits(raw) -> list[dict]:
    try:
        policies = json.loads(raw or "[]")
    except (TypeError, ValueError):
        policies = []
    limits = []
    for policy in policies if isinstance(policies, list) else []:
        if not isinstance(policy, dict) or str(policy.get("is_enabled", "1")) != "1":
            continue
        rule_type = str(policy.get("rule_type") or "")
        label = _PORTAL_POLICY_RULES.get(rule_type)
        rule = policy.get("rule") if isinstance(policy.get("rule"), dict) else {}
        if not label:
            continue
        value = rule.get("max")
        if rule_type == "max_bitrate_kbps":
            value = rule.get("max_kbps", value)
        if rule_type == "device_allowlist":
            devices = rule.get("allowed_devices") or rule.get("devices") or []
            value = len(devices) if isinstance(devices, list) else None
        if value is not None:
            limits.append({"label": label, "value": value})
    return limits


def load_portal_home(db, vodum_user_id: int) -> dict | None:
    user = db.query_one(
        """
        SELECT vu.id,vu.username,vu.firstname,vu.lastname,vu.email,vu.status,
               vu.expiration_date,vu.renewal_date,st.name AS subscription_name
        FROM vodum_users vu
        LEFT JOIN subscription_templates st ON st.id=vu.subscription_template_id
        WHERE vu.id=?
        """,
        (int(vodum_user_id),),
    )
    if not user:
        return None
    stats = db.query_one(
        """
        SELECT COUNT(DISTINCT mu.server_id) AS server_count,
               COUNT(DISTINCT mul.library_id) AS library_count
        FROM media_users mu
        LEFT JOIN media_user_libraries mul ON mul.media_user_id=mu.id
        WHERE mu.vodum_user_id=?
        """,
        (int(vodum_user_id),),
    )
    playback = db.query_one(
        """
        WITH base AS (
          SELECT (CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||
                  COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                 MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
          FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id
          WHERE mu.vodum_user_id=?
        ), plays AS (SELECT play_key,MAX(watch_ms) AS watch_ms FROM base GROUP BY play_key)
        SELECT COUNT(*) AS session_count,COALESCE(SUM(watch_ms),0) AS watch_ms FROM plays
        """,
        (int(vodum_user_id),),
    )
    provider_rows = db.query(
        "SELECT mu.type,mu.details_json,s.status AS server_status FROM media_users mu "
        "JOIN servers s ON s.id=mu.server_id WHERE mu.vodum_user_id=?",
        (int(vodum_user_id),),
    ) or []
    alerts = []
    status = str(user["status"] or "").lower()
    if status in {"pre_expired", "reminder", "expired", "suspended"}:
        alerts.append({"level": "warning", "message": f"portal_alert_status_{status}", "target": "subscription"})
    if any(str(row["server_status"] or "").lower() == "down" for row in provider_rows):
        alerts.append({"level": "warning", "message": "portal_alert_server_unavailable", "target": "media"})
    if any(str(_json_object(row["details_json"]).get("provider_presence") or "").lower() in {"removed", "disabled"} for row in provider_rows):
        alerts.append({"level": "warning", "message": "portal_alert_provider_access", "target": "media"})
    user = dict(user)
    expiration = None
    raw_expiration = str(user.get("expiration_date") or "").strip()
    if raw_expiration:
        try:
            expiration = datetime.fromisoformat(raw_expiration.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                expiration = date.fromisoformat(raw_expiration[:10])
            except ValueError:
                expiration = None
    user["expiration_display"] = expiration.strftime("%d/%m/%Y") if expiration else None
    user["days_remaining"] = max(0, (expiration - date.today()).days) if expiration else None
    user["subscription_expired"] = bool(expiration and expiration < date.today())
    user["subscription_inactive"] = status in {"inactive", "disabled", "suspended", "deleted"}
    session_count = int(playback["session_count"] or 0) if playback else 0
    watch_ms = int(playback["watch_ms"] or 0) if playback else 0
    return {
        "user": user,
        "server_count": int(stats["server_count"] or 0) if stats else 0,
        "library_count": int(stats["library_count"] or 0) if stats else 0,
        "session_count": session_count,
        "session_count_display": f"{session_count:,}".replace(",", " "),
        "watch_ms": watch_ms,
        "watch_hours": watch_ms // 3600000,
        "watch_minutes": (watch_ms % 3600000) // 60000,
        "alerts": alerts,
    }


def load_portal_profile(db, vodum_user_id: int) -> dict | None:
    row = db.query_one(
        """
        SELECT id,username,firstname,lastname,email,second_email,phone,status,created_at,
               preferred_language,notifications_order_override,discord_user_id,discord_name
        FROM vodum_users WHERE id=?
        """,
        (int(vodum_user_id),),
    )
    return dict(row) if row else None


def normalize_portal_profile(form) -> tuple[dict, tuple[str, ...]]:
    from core.user_phone import normalize_phone

    phone_error = None
    try:
        phone = normalize_phone(form.get("phone"))
    except ValueError as exc:
        phone = None
        phone_error = str(exc)
    values = {
        "firstname": str(form.get("firstname") or "").strip()[:100] or None,
        "lastname": str(form.get("lastname") or "").strip()[:100] or None,
        "second_email": str(form.get("second_email") or "").strip().lower()[:254] or None,
        "phone": phone,
        "preferred_language": str(form.get("preferred_language") or "").strip().lower()[:10] or None,
        "notifications_order_override": str(form.get("notifications_order_override") or "").strip().lower() or None,
        "discord_user_id": str(form.get("discord_user_id") or "").strip()[:64] or None,
        "discord_name": str(form.get("discord_name") or "").strip()[:100] or None,
    }
    errors = []
    if phone_error:
        errors.append(phone_error)
    email = values["second_email"]
    if email and (" " in email or email.count("@") != 1 or "." not in email.rsplit("@", 1)[1]):
        errors.append("portal_profile_email_invalid")
    if values["preferred_language"] not in {None, "en", "fr", "de", "es", "it"}:
        errors.append("portal_profile_language_invalid")
    if values["notifications_order_override"] not in {None, "email", "discord", "email,discord", "discord,email"}:
        errors.append("portal_profile_notifications_invalid")
    return values, tuple(errors)


def update_portal_profile(db, vodum_user_id: int, values: dict, *, notifications_can_override=True, discord_enabled=False) -> None:
    db.execute(
        "UPDATE vodum_users SET firstname=?,lastname=?,second_email=?,phone=?,preferred_language=?,"
        "notifications_order_override=CASE WHEN ?=1 THEN ? ELSE notifications_order_override END,"
        "discord_user_id=CASE WHEN ?=1 THEN ? ELSE discord_user_id END,"
        "discord_name=CASE WHEN ?=1 THEN ? ELSE discord_name END WHERE id=?",
        (
            values.get("firstname"), values.get("lastname"),
            values.get("second_email"), values.get("phone"), values.get("preferred_language"),
            int(bool(notifications_can_override)), values.get("notifications_order_override"),
            int(bool(discord_enabled)), values.get("discord_user_id"),
            int(bool(discord_enabled)), values.get("discord_name"), int(vodum_user_id),
        ),
    )


def load_portal_subscription(
    db, vodum_user_id: int, *, include_available_plans: bool = False
) -> dict | None:
    row = db.query_one(
        """
        SELECT vu.id,vu.status,vu.created_at,vu.expiration_date,vu.renewal_date,
               vu.username,vu.renewal_method,vu.max_streams_override,vu.subscription_template_id,
               st.name AS subscription_name,st.notes AS subscription_notes,
               st.duration_days,st.subscription_value,st.is_lifetime,st.policies_json,
               (SELECT portal_payment_url FROM settings WHERE id=1) AS portal_payment_url,
               (SELECT portal_payment_label FROM settings WHERE id=1) AS portal_payment_label,
               0 AS portal_show_payment,
               (SELECT subscription_currency FROM settings WHERE id=1) AS subscription_currency
        FROM vodum_users vu
        LEFT JOIN subscription_templates st ON st.id=vu.subscription_template_id
        WHERE vu.id=?
        """,
        (int(vodum_user_id),),
    )
    if not row:
        return None
    subscription = dict(row)
    from core.payment_links import load_applicable_payment_links
    subscription["subscription_value"] = format_subscription_value(
        subscription.get("subscription_value")
    )
    subscription["payment_links"] = load_applicable_payment_links(db, subscription.get("subscription_template_id"), {
        "username": subscription.get("username"), "user_id": subscription.get("id"),
        "plan": subscription.get("subscription_name"), "amount": subscription.get("subscription_value"),
        "currency": subscription.get("subscription_currency"),
    })
    subscription["days_remaining"] = None
    if not subscription.get("is_lifetime"):
        try:
            expiration = date.fromisoformat(
                str(subscription.get("expiration_date") or "")[:10]
            )
            subscription["days_remaining"] = max(0, (expiration - date.today()).days)
        except ValueError:
            pass
    subscription["limits"] = _subscription_limits(subscription.pop("policies_json", "[]"))
    if subscription.get("max_streams_override") is not None:
        subscription["limits"] = [
            limit for limit in subscription["limits"]
            if limit["label"] != "portal_limit_streams_user"
        ]
        subscription["limits"].insert(0, {
            "label": "portal_limit_streams_user",
            "value": subscription["max_streams_override"],
        })
    renewal = str(subscription.get("renewal_method") or "").strip()
    parsed = urlsplit(renewal)
    subscription["renewal_url"] = renewal if parsed.scheme == "https" and parsed.netloc else None
    plans = []
    if include_available_plans:
        plans = db.query(
            "SELECT id,name,notes,duration_days,subscription_value,is_lifetime "
            "FROM subscription_templates WHERE is_enabled=1 AND hide_from_portal=0 AND id<>COALESCE(?,0) "
            "ORDER BY subscription_value ASC,name ASC",
            (subscription.get("subscription_template_id"),),
        ) or []
    subscription["available_plans"] = []
    for source in plans:
        plan = dict(source)
        plan["subscription_value"] = format_subscription_value(plan.get("subscription_value"))
        subscription["available_plans"].append(plan)
    return subscription


def load_portal_media_access(db, vodum_user_id: int) -> list[dict]:
    rows = db.query(
        """
        SELECT mu.id,mu.type,mu.username,mu.accepted_at,mu.joined_at,
               mu.details_json,mu.raw_json,
               s.name AS server_name,s.type AS server_type,s.status AS server_status,
               l.id AS library_id,l.name AS library_name,l.type AS library_type
        FROM media_users mu
        JOIN servers s ON s.id=mu.server_id
        LEFT JOIN media_user_libraries mul ON mul.media_user_id=mu.id
        LEFT JOIN libraries l ON l.id=mul.library_id
        WHERE mu.vodum_user_id=?
        ORDER BY LOWER(COALESCE(s.name,'')),mu.id,LOWER(COALESCE(l.name,''))
        """,
        (int(vodum_user_id),),
    ) or []
    accounts = {}
    for source in rows:
        row = dict(source)
        account = accounts.setdefault(row["id"], {
            "id": row["id"], "type": (row.get("type") or row.get("server_type") or "").lower(),
            "username": row.get("username"), "server_name": row.get("server_name"),
            "server_status": row.get("server_status"), "accepted_at": row.get("accepted_at"),
            "joined_at": row.get("joined_at"), "libraries": [], "invitation_status": "active",
        })
        state = {**_json_object(row.get("raw_json")), **_json_object(row.get("details_json"))}
        if account["type"] == "plex" and (state.get("is_pending") or (not row.get("accepted_at") and state.get("is_friend") is False)):
            account["invitation_status"] = "pending"
        if row.get("library_id") is not None:
            account["libraries"].append({"name": row.get("library_name"), "type": row.get("library_type")})
    return list(accounts.values())


def load_portal_monitoring(db, vodum_user_id: int) -> dict:
    periods = {}
    for key, modifier in (("last_24h", "-24 hours"), ("last_7d", "-7 days"), ("last_30d", "-30 days")):
        row = db.query_one(
            """
            WITH base AS (
              SELECT (CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||
                       COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                     MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
              FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id
              WHERE mu.vodum_user_id=? AND h.stopped_at>=datetime('now',?)
            ), plays AS (SELECT play_key,MAX(watch_ms) AS watch_ms FROM base GROUP BY play_key)
            SELECT COUNT(*) AS plays,COALESCE(SUM(watch_ms),0) AS watch_ms FROM plays
            """,
            (int(vodum_user_id), modifier),
        )
        row = dict(row) if row else {}
        periods[key] = {"plays": int(row.get("plays") or 0), "watch_ms": int(row.get("watch_ms") or 0)}
    row = db.query_one(
        """WITH base AS (
             SELECT (CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                    MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
             FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id WHERE mu.vodum_user_id=?
           ), plays AS (SELECT play_key,MAX(watch_ms) AS watch_ms FROM base GROUP BY play_key)
           SELECT COUNT(*) AS plays,COALESCE(SUM(watch_ms),0) AS watch_ms FROM plays""",
        (int(vodum_user_id),),
    )
    row = dict(row) if row else {}
    periods["all_time"] = {"plays": int(row.get("plays") or 0), "watch_ms": int(row.get("watch_ms") or 0)}
    recent = db.query(
        """
        SELECT h.started_at,h.stopped_at,h.media_type,h.title,h.grandparent_title,
               h.client_name,h.client_product,h.device,h.watch_ms,s.name AS server_name,
               LOWER(COALESCE(s.type,'')) AS provider
        FROM media_session_history h
        JOIN media_users mu ON mu.id=h.media_user_id
        LEFT JOIN servers s ON s.id=h.server_id
        WHERE mu.vodum_user_id=?
        ORDER BY h.started_at DESC LIMIT 20
        """,
        (int(vodum_user_id),),
    ) or []
    media_types = db.query(
        """
        WITH base AS (
          SELECT (CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                 CASE WHEN TRIM(COALESCE(h.grandparent_title,''))<>'' OR LOWER(TRIM(COALESCE(h.media_type,''))) IN ('serie','series','episode','show','season') THEN 'serie'
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('movie','film','video') THEN 'movie'
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('music','audio','song','track','tracks') THEN 'music'
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('photo','photos','image','picture','pictures') THEN 'photo' ELSE 'other' END AS label,
                 CASE WHEN TRIM(COALESCE(h.grandparent_title,''))<>'' OR LOWER(TRIM(COALESCE(h.media_type,''))) IN ('serie','series','episode','show','season') THEN 400
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('movie','film','video') THEN 300
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('music','audio','song','track','tracks') THEN 200
                      WHEN LOWER(TRIM(COALESCE(h.media_type,''))) IN ('photo','photos','image','picture','pictures') THEN 100 ELSE 0 END AS kind_rank,
                 MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
          FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id
          WHERE mu.vodum_user_id=? AND h.stopped_at>=datetime('now','-30 days')
        ), plays AS (
          SELECT play_key,CASE MAX(kind_rank) WHEN 400 THEN 'serie' WHEN 300 THEN 'movie' WHEN 200 THEN 'music' WHEN 100 THEN 'photo' ELSE 'other' END AS label,MAX(watch_ms) AS watch_ms
          FROM base GROUP BY play_key
        )
        SELECT label,COUNT(*) AS plays,COALESCE(SUM(watch_ms),0) AS watch_ms FROM plays GROUP BY label
        ORDER BY plays DESC
        """,
        (int(vodum_user_id),),
    ) or []
    servers = db.query(
        """
        WITH base AS (
          SELECT h.server_id,(CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                 MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
          FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id
          WHERE mu.vodum_user_id=? AND h.stopped_at>=datetime('now','-30 days')
        ), plays AS (SELECT server_id,play_key,MAX(watch_ms) AS watch_ms FROM base GROUP BY server_id,play_key)
        SELECT COALESCE(NULLIF(s.name,''),'—') AS label,LOWER(COALESCE(s.type,'')) AS provider,COUNT(*) AS plays,COALESCE(SUM(p.watch_ms),0) AS watch_ms
        FROM plays p LEFT JOIN servers s ON s.id=p.server_id
        GROUP BY p.server_id,s.name,s.type
        ORDER BY plays DESC
        """,
        (int(vodum_user_id),),
    ) or []
    libraries = db.query(
        """
        SELECT COALESCE(NULLIF(l.name,''),'—') AS label,LOWER(COALESCE(l.type,'')) AS media_type,
               COUNT(*) AS plays
        FROM media_session_history h
        JOIN media_users mu ON mu.id=h.media_user_id
        LEFT JOIN libraries l ON l.server_id=h.server_id
                             AND CAST(l.section_id AS TEXT)=CAST(h.library_section_id AS TEXT)
        WHERE mu.vodum_user_id=? AND h.started_at>=datetime('now','-30 days')
        GROUP BY h.server_id,h.library_section_id,l.name,l.type
        ORDER BY plays DESC LIMIT 12
        """,
        (int(vodum_user_id),),
    ) or []
    daily = db.query(
        """
        WITH base AS (
          SELECT DATE(h.stopped_at) AS day,(CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key,
                 MIN(COALESCE(h.watch_ms,0),CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END) AS watch_ms
          FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id
          WHERE mu.vodum_user_id=? AND h.stopped_at>=datetime('now','-30 days')
        ), plays AS (SELECT day,play_key,MAX(watch_ms) AS watch_ms FROM base GROUP BY day,play_key)
        SELECT day,COUNT(*) AS plays,COALESCE(SUM(watch_ms),0) AS watch_ms FROM plays GROUP BY day ORDER BY day
        """,
        (int(vodum_user_id),),
    ) or []
    top_players = db.query(
        """
        WITH base AS (
          SELECT COALESCE(NULLIF(h.client_name,''),NULLIF(h.client_product,''),NULLIF(h.device,''),'Unknown') AS label,
                 (CAST(h.server_id AS TEXT)||'|'||CAST(h.media_user_id AS TEXT)||'|'||COALESCE(NULLIF(TRIM(h.media_key),''),'no_media')||'|'||strftime('%Y-%m-%d %H:%M',h.started_at)) AS play_key
          FROM media_session_history h JOIN media_users mu ON mu.id=h.media_user_id WHERE mu.vodum_user_id=?
        ), plays AS (SELECT play_key,MAX(label) AS label FROM base GROUP BY play_key)
        SELECT label,COUNT(*) AS plays FROM plays GROUP BY label ORDER BY plays DESC LIMIT 12
        """,
        (int(vodum_user_id),),
    ) or []
    ip_rows = db.query(
        """
        SELECT h.ip,MAX(h.stopped_at) AS last_seen,MIN(h.started_at) AS first_seen,
               COUNT(*) AS plays,COALESCE(SUM(MIN(COALESCE(h.watch_ms,0),
                 CASE WHEN COALESCE(h.duration_ms,0)>0 THEN h.duration_ms ELSE COALESCE(h.watch_ms,0) END)),0) AS watch_ms,
               MAX(COALESCE(NULLIF(h.client_name,''),NULLIF(h.client_product,''),NULLIF(h.device,''),'—')) AS player
        FROM media_session_history h
        JOIN media_users mu ON mu.id=h.media_user_id
        WHERE mu.vodum_user_id=? AND COALESCE(NULLIF(TRIM(h.ip),''),'')<>''
        GROUP BY h.ip ORDER BY last_seen DESC LIMIT 30
        """,
        (int(vodum_user_id),),
    ) or []

    def normalized(rows):
        return [dict(row) for row in rows]

    media_types = normalized(media_types)
    servers = normalized(servers)
    libraries = normalized(libraries)
    daily = normalized(daily)
    top_players = normalized(top_players)
    ip_rows = normalized(ip_rows)

    def masked_ip(value):
        value = str(value or "")
        if ":" in value:
            parts = value.split(":")
            return ":".join(parts[:3]) + ":…"
        parts = value.split(".")
        return ".".join(parts[:2] + ["×", "×"]) if len(parts) == 4 else "•••"

    for row in ip_rows:
        row["ip"] = masked_ip(row.get("ip"))
    max_daily = max((int(row.get("plays") or 0) for row in daily), default=0)
    max_server = max((int(row.get("plays") or 0) for row in servers), default=0)
    media_total = sum(int(row.get("plays") or 0) for row in media_types)
    for row in media_types:
        row["percent"] = round((int(row.get("plays") or 0) * 100 / media_total), 1) if media_total else 0
    for row in daily:
        row["percent"] = round((int(row.get("plays") or 0) * 100 / max_daily), 1) if max_daily else 0
    for row in servers:
        row["percent"] = round((int(row.get("plays") or 0) * 100 / max_server), 1) if max_server else 0
    return {
        "periods": periods,
        "recent": normalized(recent),
        "media_types": media_types,
        "servers": servers,
        "libraries": libraries,
        "daily": daily,
        "top_players": top_players,
        "ip_rows": ip_rows,
    }


def load_portal_support(db, vodum_user_id: int) -> dict | None:
    row = db.query_one(
        """
        SELECT vu.status AS user_status,pa.status AS portal_status,
               (SELECT contact_email FROM settings WHERE id=1) AS support_email,
               (SELECT portal_show_support_email FROM settings WHERE id=1) AS show_support_email,
               (SELECT portal_support_content FROM settings WHERE id=1) AS support_content,
               (SELECT portal_quick_messages_enabled FROM settings WHERE id=1) AS quick_messages_enabled,
               COUNT(DISTINCT mu.server_id) AS linked_servers
        FROM vodum_users vu
        JOIN portal_accounts pa ON pa.vodum_user_id=vu.id
        LEFT JOIN media_users mu ON mu.vodum_user_id=vu.id
        WHERE vu.id=?
        GROUP BY vu.id,vu.status,pa.status
        """,
        (int(vodum_user_id),),
    )
    return dict(row) if row else None
