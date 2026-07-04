import ipaddress
import json
import re


FIXED_DEVICE_KEYWORDS = (
    "tv",
    "smart tv",
    "android tv",
    "apple tv",
    "shield",
    "playstation",
    "ps4",
    "ps5",
    "xbox",
    "console",
    "roku",
    "chromecast",
    "fire tv",
    "firetv",
    "nvidia",
    "bravia",
    "samsung",
    "lg",
    "hisense",
    "tizen",
    "webos",
)

MOBILE_DEVICE_KEYWORDS = (
    "iphone",
    "ipad",
    "android",
    "mobile",
    "phone",
    "tablet",
)

BROWSER_DEVICE_KEYWORDS = (
    "browser",
    "chrome",
    "safari",
    "firefox",
    "edge",
    "opera",
)

LOW_RISK_RULES = (
    "max_streams_per_ip",
)

HIGH_RISK_RULES = (
    "max_ips_per_user",
    "max_streams_per_user",
)


def _safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except Exception:
        return default


def _is_public_ip(value):
    value = (value or "").strip()
    if not value:
        return False

    try:
        ip = ipaddress.ip_address(value)
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        )
    except Exception:
        return False


def _normalize_text(value):
    return " ".join(str(value or "").split()).strip()


def _device_label(row):
    raw = " ".join(
        [
            str(row.get("device") or ""),
            str(row.get("client_product") or ""),
            str(row.get("client_name") or ""),
            str(row.get("player") or ""),
            str(row.get("platform") or ""),
        ]
    )
    return _normalize_text(raw) or "Unknown device"


def _is_fixed_device(label):
    label = (label or "").lower()
    return any(k in label for k in FIXED_DEVICE_KEYWORDS)


def _is_mobile_device(label):
    label = (label or "").lower()
    return any(k in label for k in MOBILE_DEVICE_KEYWORDS)


def _is_browser_device(label):
    label = (label or "").lower()
    return any(k in label for k in BROWSER_DEVICE_KEYWORDS)


def _is_mobile_or_browser(label):
    return _is_mobile_device(label) or _is_browser_device(label)


def _risk_level(score, medium_threshold, high_threshold):
    if score >= high_threshold:
        return "high"
    if score >= medium_threshold:
        return "medium"
    return "low"


def _risk_color(level):
    if level == "high":
        return "red"
    if level == "medium":
        return "orange"
    return "green"


def _suggest_subscription(db, current_template_id, current_value, needed_streams, needed_ips):
    templates = db.query(
        """
        SELECT id, name, subscription_value, policies_json
        FROM subscription_templates
        WHERE is_enabled = 1
        ORDER BY subscription_value ASC, name ASC
        """
    ) or []

    candidates = []

    for tpl in templates:
        tpl = dict(tpl)

        if current_template_id and int(tpl.get("id") or 0) == int(current_template_id):
            continue

        tpl_value = _safe_float(tpl.get("subscription_value"), 0)
        if current_value and tpl_value <= current_value:
            continue

        max_streams = 0
        max_ips = 0

        try:
            policies = json.loads(tpl.get("policies_json") or "[]")
        except Exception:
            policies = []

        for policy in policies:
            if not isinstance(policy, dict):
                continue

            if _safe_int(policy.get("is_enabled"), 1) != 1:
                continue

            rule_type = (policy.get("rule_type") or "").strip()
            rule = policy.get("rule") if isinstance(policy.get("rule"), dict) else {}

            if rule_type == "max_streams_per_user":
                max_streams = max(max_streams, _safe_int(rule.get("max"), 0))

            if rule_type == "max_ips_per_user":
                max_ips = max(max_ips, _safe_int(rule.get("max"), 0))

        streams_ok = max_streams >= needed_streams if needed_streams > 0 else True
        ips_ok = max_ips >= needed_ips if needed_ips > 0 else True

        if streams_ok and ips_ok:
            candidates.append(tpl)

    return candidates[0] if candidates else None


def _extract_session_identity(sess):
    label = _device_label(sess)
    ip = str(sess.get("ip") or "").strip()

    machine_id = (
        sess.get("machine_id")
        or sess.get("client_identifier")
        or sess.get("player_uuid")
        or sess.get("session_id")
        or label
    )

    return {
        "label": label,
        "ip": ip,
        "device_key": _normalize_text(machine_id) or label,
        "is_fixed": _is_fixed_device(label),
        "is_mobile": _is_mobile_device(label),
        "is_browser": _is_browser_device(label),
    }


def _score_usage_item(item, min_kills):
    distinct_ips = len(item["ips"])
    fixed_devices = len(item["fixed_devices"])
    mobile_devices = len(item["mobile_devices"])
    browser_devices = len(item["browser_devices"])
    kills_7d = item["kills_7d"]
    kills_30d = item["kills_30d"] or item["kills"]
    kills_90d = item["kills_90d"]

    repeated_max_ips = _safe_int(item["rules"].get("max_ips_per_user"), 0)
    repeated_max_streams_user = _safe_int(item["rules"].get("max_streams_per_user"), 0)
    repeated_high_rules = repeated_max_ips + repeated_max_streams_user

    score = 0
    reasons = []
    reason_items = []

    def add_reason(text, code, **params):
        reasons.append(text)
        reason_items.append({"code": code, **params})

    if distinct_ips >= 2:
        pts = min(30, 8 + (distinct_ips * 7))
        score += pts
        add_reason(f"{distinct_ips} public IPs", "public_ips", count=distinct_ips)

    if fixed_devices >= 1:
        pts = min(24, fixed_devices * 10)
        score += pts
        add_reason(
            f"{fixed_devices} fixed device{'s' if fixed_devices > 1 else ''}",
            "fixed_devices",
            count=fixed_devices,
        )

    if fixed_devices >= 2:
        score += 20
        add_reason("multiple fixed devices", "multiple_fixed_devices")

    fixed_ip_pairs = item["fixed_device_ip_pairs"]
    if len(fixed_ip_pairs) >= 2:
        unique_pair_ips = {pair.split(" @ ", 1)[1] for pair in fixed_ip_pairs if " @ " in pair}
        unique_pair_devices = {pair.split(" @ ", 1)[0] for pair in fixed_ip_pairs if " @ " in pair}

        if len(unique_pair_ips) >= 2 and len(unique_pair_devices) >= 2:
            score += 40
            add_reason(
                "fixed devices linked to different public IPs",
                "fixed_devices_different_ips",
            )

    if distinct_ips >= 2 and fixed_devices >= 2:
        score += 22
        add_reason("multi-household pattern likely", "multi_household")

    if kills_7d >= 2:
        pts = min(20, kills_7d * 4)
        score += pts
        add_reason(f"{kills_7d} kills in 7 days", "stops_7d", count=kills_7d)

    if kills_30d >= min_kills:
        pts = min(24, kills_30d * 3)
        score += pts
        add_reason(f"{kills_30d} kills in 30 days", "stops_30d", count=kills_30d)

    if kills_90d >= max(min_kills * 2, 6):
        pts = min(16, kills_90d)
        score += pts
        add_reason(f"{kills_90d} kills in 90 days", "stops_90d", count=kills_90d)

    for rule_type, count in item["rules"].items():
        if count < 2:
            continue

        if rule_type in HIGH_RISK_RULES:
            pts = min(40, 12 + (count * 2))
            score += pts
            add_reason(f"repeated {rule_type}", "repeated_rule", rule=rule_type)
        elif rule_type in LOW_RISK_RULES:
            pts = min(10, count * 2)
            score += pts
            add_reason(f"repeated {rule_type}", "repeated_rule", rule=rule_type)
        else:
            pts = min(14, count * 3)
            score += pts
            add_reason(f"repeated {rule_type}", "repeated_rule", rule=rule_type)

    normal_tv_mobile_pattern = (
        distinct_ips <= 2
        and fixed_devices <= 1
        and (mobile_devices or browser_devices)
    )

    normal_mobile_browser_pattern = (
        distinct_ips <= 2
        and fixed_devices == 0
        and (mobile_devices or browser_devices)
    )

    has_repeated_blocks = (
        kills_7d >= 6
        or kills_30d >= max(min_kills * 3, 9)
        or repeated_high_rules >= max(min_kills * 3, 9)
    )

    # Usage normal : TV fixe + téléphone/tablette/navigateur sur 1 ou 2 IP.
    # On plafonne seulement si l'utilisateur n'a PAS beaucoup de blocages.
    if normal_tv_mobile_pattern:
        if not has_repeated_blocks:
            score = min(score, 35)
            add_reason("TV/mobile usage pattern reduces risk", "tv_mobile_reduces")
        else:
            score = max(0, score - 15)
            add_reason("TV/mobile usage pattern softens risk", "tv_mobile_softens")

    # Usage mobile/browser sans appareil fixe.
    # Même logique : réduction forte seulement si les blocages restent faibles.
    if normal_mobile_browser_pattern:
        if not has_repeated_blocks:
            score = min(score, 28)
            add_reason("mobile/browser usage reduces risk", "mobile_browser_reduces")
        else:
            score = max(0, score - 15)
            add_reason("mobile/browser usage softens risk", "mobile_browser_softens")

    # Usage très simple : 1 IP, 1 appareil fixe max, peu de blocages.
    if distinct_ips <= 1 and fixed_devices <= 1 and kills_30d < min_kills:
        score = max(0, score - 25)

    return score, reasons, reason_items

def _upsert_recommendation_history(db, item_out, cooldown_days):
    vodum_user_id = item_out.get("vodum_user_id")
    suggested_subscription = item_out.get("suggested_subscription")

    if not vodum_user_id or not suggested_subscription:
        return

    current_subscription = item_out.get("subscription_name") or ""
    risk_level = item_out.get("risk_level") or "low"
    risk_score = _safe_int(item_out.get("risk_score"), 0)

    meta_json = json.dumps(
        {
            "main_reason": item_out.get("main_reason"),
            "reasons": item_out.get("reasons") or [],
            "evidence": item_out.get("evidence") or {},
            "kills_7d": item_out.get("kills_7d") or 0,
            "kills_30d": item_out.get("kills_30d") or 0,
            "kills_90d": item_out.get("kills_90d") or 0,
        },
        ensure_ascii=False,
    )

    existing = db.query_one(
        """
        SELECT id
        FROM usage_risk_recommendations
        WHERE vodum_user_id = ?
          AND suggested_subscription = ?
          AND status IN ('detected','notified')
        ORDER BY id DESC
        LIMIT 1
        """,
        (vodum_user_id, suggested_subscription),
    )

    if existing:
        db.execute(
            """
            UPDATE usage_risk_recommendations
            SET risk_level = ?,
                risk_score = ?,
                current_subscription = ?,
                last_detected_at = CURRENT_TIMESTAMP,
                meta_json = ?
            WHERE id = ?
            """,
            (
                risk_level,
                risk_score,
                current_subscription,
                meta_json,
                dict(existing).get("id"),
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO usage_risk_recommendations (
                vodum_user_id,
                risk_level,
                risk_score,
                current_subscription,
                suggested_subscription,
                cooldown_until,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                vodum_user_id,
                risk_level,
                risk_score,
                current_subscription,
                suggested_subscription,
                meta_json,
            ),
        )

def build_usage_risk_report(db, filters=None, persist_history=True):
    filters = filters or {}

    settings = dict(db.query_one("SELECT id, mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass, smtp_auth_method, smtp_oauth_access_token, email_history_retention_years, disable_on_expiry, delete_after_expiry_days, send_reminders, preavis_days, reminder_days, default_language, timezone, admin_email, contact_email, admin_password_hash, auth_enabled, admin_totp_enabled, admin_totp_secret, wizard_active, wizard_completed, wizard_step, wizard_state_json, web_secure_cookies, web_cookie_samesite, web_trust_proxy, enable_cron_jobs, default_expiration_days, default_subscription_days, maintenance_mode, debug_mode, backup_retention_days, backup_retention_count, data_retention_years, brand_name, notifications_order, user_notifications_can_override, notifications_send_mode, expiry_mode, warn_then_disable_days, discord_enabled, discord_bot_token, discord_bot_id, mailing_enabled, skip_never_used_accounts, plex_user_import_mode, enable_anonymous_telemetry, telemetry_instance_id, telemetry_last_sent_at, task_defaults_version, stream_enforcer_boost_until, usage_risk_enabled, usage_risk_send_upgrade_suggestions, usage_risk_send_stream_blocked_message, usage_risk_min_kills_before_suggestion, usage_risk_analysis_window_days, usage_risk_suggestion_cooldown_days, usage_risk_medium_threshold, usage_risk_high_threshold FROM settings WHERE id = 1") or {})

    enabled = _safe_int(settings.get("usage_risk_enabled"), 1) == 1
    window_days = _safe_int(settings.get("usage_risk_analysis_window_days"), 30)
    min_kills = _safe_int(settings.get("usage_risk_min_kills_before_suggestion"), 3)
    medium_threshold = _safe_int(settings.get("usage_risk_medium_threshold"), 40)
    high_threshold = _safe_int(settings.get("usage_risk_high_threshold"), 75)
    suggestion_cooldown_days = _safe_int(settings.get("usage_risk_suggestion_cooldown_days"), 30)

    if not enabled:
        return {
            "enabled": False,
            "summary": {"high": 0, "medium": 0, "low": 0, "suggested": 0},
            "rows": [],
            "filters": filters,
        }

    q = " ".join((filters.get("q") or "").split()).strip().lower()
    risk_level = (filters.get("risk_level") or "").strip().lower()
    subscription_id = _safe_int(filters.get("subscription_id"), 0)
    server_id = _safe_int(filters.get("server_id"), 0)
    policy = (filters.get("policy") or "").strip()
    period_days = _safe_int(filters.get("period_days"), window_days)

    if period_days <= 0:
        period_days = window_days

    where = ["datetime(e.created_at) >= datetime('now', ?)"]
    params = [f"-{period_days} days"]

    if server_id > 0:
        where.append("e.server_id = ?")
        params.append(server_id)

    if policy:
        where.append("p.rule_type = ?")
        params.append(policy)

    if subscription_id > 0:
        where.append("vu.subscription_template_id = ?")
        params.append(subscription_id)

    rows = db.query(
        f"""
        SELECT
          e.id,
          e.created_at,
          e.action,
          e.reason,
          e.vodum_user_id,
          e.external_user_id,
          e.account_username,
          e.ips_json,
          e.details_json,
          e.server_id,
          p.rule_type,
          s.name AS server_name,
          vu.username,
          vu.email,
          vu.subscription_template_id,
          st.name AS subscription_name,
          st.subscription_value
        FROM stream_enforcements e
        LEFT JOIN stream_policies p ON p.id = e.policy_id
        LEFT JOIN servers s ON s.id = e.server_id
        LEFT JOIN vodum_users vu ON vu.id = e.vodum_user_id
        LEFT JOIN subscription_templates st ON st.id = vu.subscription_template_id
        WHERE {" AND ".join(where)}
        ORDER BY datetime(e.created_at) DESC
        LIMIT 5000
        """,
        tuple(params),
    ) or []

    by_user = {}

    for row in rows:
        row = dict(row)

        actor_key = (
            f"vodum:{row.get('vodum_user_id')}"
            if row.get("vodum_user_id")
            else f"ext:{row.get('external_user_id') or row.get('account_username') or 'unknown'}"
        )

        item = by_user.setdefault(
            actor_key,
            {
                "actor_key": actor_key,
                "vodum_user_id": row.get("vodum_user_id"),
                "username": row.get("username") or row.get("account_username") or row.get("external_user_id") or "Unknown user",
                "email": row.get("email") or "",
                "subscription_template_id": row.get("subscription_template_id"),
                "subscription_name": row.get("subscription_name") or "—",
                "subscription_value": _safe_float(row.get("subscription_value"), 0),
                "last_activity": row.get("created_at"),
                "kills_7d": 0,
                "kills_30d": 0,
                "kills_90d": 0,
                "warns": 0,
                "kills": 0,
                "ips": set(),
                "fixed_devices": set(),
                "mobile_devices": set(),
                "browser_devices": set(),
                "fixed_device_ip_pairs": set(),
                "rules": {},
                "servers": set(),
            },
        )

        if row.get("created_at") and row.get("created_at") > (item.get("last_activity") or ""):
            item["last_activity"] = row.get("created_at")

        action = (row.get("action") or "").strip().lower()
        if action == "kill":
            item["kills"] += 1
        elif action == "warn":
            item["warns"] += 1

        rule_type = row.get("rule_type") or "unknown"
        item["rules"][rule_type] = item["rules"].get(rule_type, 0) + 1

        if row.get("server_name"):
            item["servers"].add(row.get("server_name"))

        try:
            ips = json.loads(row.get("ips_json") or "[]")
            if isinstance(ips, list):
                for ip in ips:
                    ip = str(ip or "").strip()
                    if _is_public_ip(ip):
                        item["ips"].add(ip)
        except Exception:
            pass

        try:
            details = json.loads(row.get("details_json") or "{}")
        except Exception:
            details = {}

        if isinstance(details, dict):
            sessions = details.get("sessions") or details.get("all_sessions") or []
            target_session = details.get("target_session")

            if isinstance(target_session, dict):
                sessions.append(target_session)

            if isinstance(sessions, list):
                for sess in sessions:
                    if not isinstance(sess, dict):
                        continue

                    session_identity = _extract_session_identity(sess)
                    ip = session_identity["ip"]
                    label = session_identity["label"]

                    if _is_public_ip(ip):
                        item["ips"].add(ip)

                    if session_identity["is_fixed"]:
                        item["fixed_devices"].add(label)
                        if _is_public_ip(ip):
                            item["fixed_device_ip_pairs"].add(f"{label} @ {ip}")
                    elif session_identity["is_mobile"]:
                        item["mobile_devices"].add(label)
                    elif session_identity["is_browser"]:
                        item["browser_devices"].add(label)

    kill_windows = db.query(
        """
        SELECT
          COALESCE(e.vodum_user_id, 0) AS vodum_user_id,
          COALESCE(e.external_user_id, '') AS external_user_id,
          SUM(CASE WHEN e.action = 'kill' AND datetime(e.created_at) >= datetime('now', '-7 days') THEN 1 ELSE 0 END) AS kills_7d,
          SUM(CASE WHEN e.action = 'kill' AND datetime(e.created_at) >= datetime('now', '-30 days') THEN 1 ELSE 0 END) AS kills_30d,
          SUM(CASE WHEN e.action = 'kill' AND datetime(e.created_at) >= datetime('now', '-90 days') THEN 1 ELSE 0 END) AS kills_90d
        FROM stream_enforcements e
        WHERE datetime(e.created_at) >= datetime('now', '-90 days')
        GROUP BY COALESCE(e.vodum_user_id, 0), COALESCE(e.external_user_id, '')
        """
    ) or []

    for row in kill_windows:
        row = dict(row)
        actor_key = (
            f"vodum:{row.get('vodum_user_id')}"
            if _safe_int(row.get("vodum_user_id"), 0) > 0
            else f"ext:{row.get('external_user_id') or 'unknown'}"
        )

        if actor_key not in by_user:
            continue

        by_user[actor_key]["kills_7d"] = _safe_int(row.get("kills_7d"), 0)
        by_user[actor_key]["kills_30d"] = _safe_int(row.get("kills_30d"), 0)
        by_user[actor_key]["kills_90d"] = _safe_int(row.get("kills_90d"), 0)

    output = []

    for item in by_user.values():
        distinct_ips = len(item["ips"])
        fixed_devices = len(item["fixed_devices"])
        kills_30d = item["kills_30d"] or item["kills"]

        score, reasons, reason_items = _score_usage_item(item, min_kills)

        # Hide false positives neutralized by scoring.
        if score <= 0 and not risk_level:
            continue

        level = _risk_level(score, medium_threshold, high_threshold)

        needed_streams = max(1, fixed_devices)
        needed_ips = max(1, distinct_ips)

        suggestion = None
        if kills_30d >= min_kills:
            suggestion = _suggest_subscription(
                db,
                item.get("subscription_template_id"),
                item.get("subscription_value"),
                needed_streams,
                needed_ips,
            )

        main_reason = reasons[0] if reasons else "No suspicious usage detected"

        item_out = {
            "actor_key": item["actor_key"],
            "vodum_user_id": item["vodum_user_id"],
            "username": item["username"],
            "email": item["email"],
            "subscription_name": item["subscription_name"],
            "risk_level": level,
            "risk_color": _risk_color(level),
            "risk_score": score,
            "main_reason": main_reason,
            "reasons": reasons,
            "reason_items": reason_items,
            "evidence": {
                "ips": sorted(item["ips"]),
                "fixed_devices": sorted(item["fixed_devices"]),
                "mobile_devices": sorted(item["mobile_devices"]),
                "browser_devices": sorted(item["browser_devices"]),
                "fixed_device_ip_pairs": sorted(item["fixed_device_ip_pairs"]),
                "rules": item["rules"],
                "servers": sorted(item["servers"]),
            },
            "kills": item["kills"],
            "kills_7d": item["kills_7d"],
            "kills_30d": item["kills_30d"],
            "kills_90d": item["kills_90d"],
            "suggested_subscription": suggestion.get("name") if suggestion else "",
            "last_activity": item["last_activity"],
        }

        searchable = " ".join(
            [
                item_out["username"],
                item_out["email"],
                item_out["subscription_name"],
                item_out["main_reason"],
                " ".join(item_out["reasons"]),
                " ".join(item_out["evidence"]["ips"]),
                " ".join(item_out["evidence"]["fixed_devices"]),
                " ".join(item_out["evidence"]["mobile_devices"]),
                " ".join(item_out["evidence"]["browser_devices"]),
                " ".join(item_out["evidence"]["rules"].keys()),
            ]
        ).lower()

        if q and q not in searchable:
            continue

        if risk_level and item_out["risk_level"] != risk_level:
            continue

        if persist_history and item_out.get("suggested_subscription"):
            _upsert_recommendation_history(db, item_out, suggestion_cooldown_days)

        output.append(item_out)

    output.sort(key=lambda r: (r["risk_score"], r["kills_30d"], r["last_activity"] or ""), reverse=True)

    summary = {
        "high": sum(1 for r in output if r["risk_level"] == "high"),
        "medium": sum(1 for r in output if r["risk_level"] == "medium"),
        "low": sum(1 for r in output if r["risk_level"] == "low"),
        "suggested": sum(1 for r in output if r["suggested_subscription"]),
    }

    return {
        "enabled": True,
        "summary": summary,
        "rows": output,
        "filters": filters,
    }


def build_usage_risk_for_user(db, vodum_user_id):
    report = build_usage_risk_report(
        db,
        {
            "period_days": 90,
        },
    )

    actor_key = f"vodum:{int(vodum_user_id)}"

    for row in report.get("rows") or []:
        if row.get("actor_key") == actor_key:
            return row

    return {
        "actor_key": actor_key,
        "vodum_user_id": vodum_user_id,
        "risk_level": "low",
        "risk_color": "green",
        "risk_score": 0,
        "main_reason": "No suspicious usage detected",
        "reasons": [],
        "reason_items": [],
        "evidence": {
            "ips": [],
            "fixed_devices": [],
            "mobile_devices": [],
            "browser_devices": [],
            "fixed_device_ip_pairs": [],
            "rules": {},
            "servers": [],
        },
        "kills": 0,
        "kills_7d": 0,
        "kills_30d": 0,
        "kills_90d": 0,
        "suggested_subscription": "",
        "last_activity": None,
    }
