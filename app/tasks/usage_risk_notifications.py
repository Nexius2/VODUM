import json
from datetime import datetime

from communications_engine import (
    select_comm_template_for_user,
    schedule_template_notification,
    enqueue_named_task,
)
from core.usage_risk import build_usage_risk_report
from logging_utils import get_logger
from tasks_engine import task_logs


logger = get_logger("usage_risk_notifications")


DEFAULT_SUBJECT = "A more suitable subscription may be available"

DEFAULT_BODY = """Hello {username},

We noticed that your usage regularly reaches the limits of your current subscription.

Current subscription: {current_subscription}
Suggested subscription: {suggested_subscription}

This is only a recommendation to improve your experience and avoid blocked playback.

Best regards,
{brand_name}
"""


def _safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def _load_user(db, user_id):
    row = db.query_one(
        """
        SELECT
            u.id,
            u.username,
            u.firstname,
            u.lastname,
            u.email,
            u.second_email,
            u.expiration_date,
            u.discord_user_id,
            u.notifications_order_override,
            (
                SELECT mu.preferred_language
                FROM media_users mu
                WHERE mu.vodum_user_id = u.id
                  AND TRIM(COALESCE(mu.preferred_language, '')) <> ''
                ORDER BY mu.id ASC
                LIMIT 1
              ) AS preferred_language,
            u.subscription_template_id,
            st.name AS subscription_name,
            st.duration_days AS subscription_duration_days,
            st.subscription_value AS subscription_value
        FROM vodum_users u
        LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
        WHERE u.id = ?
        """,
        (user_id,),
    )

    return dict(row) if row else None


def _get_user_comm_contexts(db, user_id: int):
    rows = db.query(
        """
        SELECT
            LOWER(COALESCE(s.type, '')) AS provider,
            mu.server_id AS server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        ORDER BY
            CASE LOWER(COALESCE(s.type, ''))
                WHEN 'plex' THEN 0
                WHEN 'jellyfin' THEN 1
                ELSE 2
            END,
            mu.id ASC
        """,
        (user_id,),
    ) or []

    contexts = []
    seen = set()
    for row in rows:
        row = dict(row)
        provider = (row.get("provider") or "").strip().lower()
        server_id = row.get("server_id")
        if provider not in ("plex", "jellyfin"):
            continue
        key = (provider, server_id)
        if key in seen:
            continue
        seen.add(key)
        contexts.append({"provider": provider, "server_id": server_id})

    return contexts or [{"provider": "plex", "server_id": None}]


def _existing_scheduled(db, dedupe_key: str):
    row = db.query_one(
        """
        SELECT id, status, attempt_count, max_attempts
        FROM comm_scheduled
        WHERE dedupe_key = ?
        LIMIT 1
        """,
        (dedupe_key,),
    )
    return dict(row) if row else None


def _has_upgrade_delivery_history(db, recommendation_id: int):
    needle = f'"recommendation_id": {int(recommendation_id)}'
    row = db.query_one(
        """
        SELECT 1
        FROM comm_history h
        LEFT JOIN comm_templates t ON t.id = h.template_id
        WHERE (
                t.trigger_event = 'usage_risk_upgrade_suggestion'
             OR h.meta_json LIKE '%usage_risk_upgrade_suggestion%'
              )
          AND h.meta_json LIKE ?
        LIMIT 1
        """,
        (f"%{needle}%",),
    )
    return bool(row)


def _log_task(task_id, status, message, details=None):
    logger.info("%s | %s", message, details or {})
    if task_id is not None:
        task_logs(task_id, status, message, details=details)


def run(task_id=None, db=None):
    settings = dict(db.query_one("SELECT id, mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass, smtp_auth_method, smtp_oauth_access_token, email_history_retention_years, disable_on_expiry, delete_after_expiry_days, send_reminders, preavis_days, reminder_days, default_language, communication_language, timezone, admin_email, contact_email, admin_password_hash, auth_enabled, admin_totp_enabled, admin_totp_secret, wizard_active, wizard_completed, wizard_step, wizard_state_json, web_secure_cookies, web_cookie_samesite, web_trust_proxy, enable_cron_jobs, default_expiration_days, default_subscription_days, maintenance_mode, debug_mode, backup_retention_days, backup_retention_count, data_retention_years, brand_name, notifications_order, user_notifications_can_override, notifications_send_mode, expiry_mode, warn_then_disable_days, discord_enabled, discord_bot_token, discord_bot_id, mailing_enabled, skip_never_used_accounts, plex_user_import_mode, enable_anonymous_telemetry, telemetry_instance_id, telemetry_last_sent_at, task_defaults_version, stream_enforcer_boost_until, usage_risk_enabled, usage_risk_send_upgrade_suggestions, usage_risk_send_stream_blocked_message, usage_risk_min_kills_before_suggestion, usage_risk_analysis_window_days, usage_risk_suggestion_cooldown_days, usage_risk_medium_threshold, usage_risk_high_threshold FROM settings WHERE id = 1") or {})

    if _safe_int(settings.get("usage_risk_enabled"), 1) != 1:
        _log_task(task_id, "info", "Usage risk detection is disabled")
        return {"status": "success", "message": "Usage risk disabled"}

    if _safe_int(settings.get("usage_risk_send_upgrade_suggestions"), 0) != 1:
        _log_task(task_id, "info", "Usage risk upgrade suggestions are disabled")
        return {"status": "success", "message": "Upgrade suggestions disabled"}

    template_available = db.query_one(
        """
        SELECT id
        FROM comm_templates
        WHERE enabled = 1
          AND trigger_event = 'usage_risk_upgrade_suggestion'
        LIMIT 1
        """
    )

    if not template_available:
        _log_task(task_id, "warning", "No enabled usage risk upgrade template")
        return {"status": "success", "message": "No enabled usage risk upgrade template"}

    min_kills = _safe_int(settings.get("usage_risk_min_kills_before_suggestion"), 3)
    cooldown_days = _safe_int(settings.get("usage_risk_suggestion_cooldown_days"), 30)
    analysis_window_days = _safe_int(settings.get("usage_risk_analysis_window_days"), 30)

    # Refresh recommendation history before sending.
    report = build_usage_risk_report(
        db,
        {"period_days": analysis_window_days},
        persist_history=True,
    )

    report_rows = report.get("rows") or []
    suggested_in_report = [r for r in report_rows if r.get("suggested_subscription")]
    current_suggestion_keys = {
        (int(row["vodum_user_id"]), str(row["suggested_subscription"]).strip())
        for row in suggested_in_report
        if row.get("vodum_user_id") and str(row.get("suggested_subscription") or "").strip()
    }

    rows = db.query(
        """
        SELECT
          id,
          vodum_user_id,
          risk_level,
          risk_score,
          current_subscription,
          suggested_subscription,
          first_detected_at,
          last_detected_at,
          last_notification_at,
          cooldown_until,
          CASE
            WHEN cooldown_until IS NOT NULL AND datetime(cooldown_until) > datetime('now') THEN 1
            ELSE 0
          END AS cooldown_active,
          status,
          meta_json
        FROM usage_risk_recommendations
        WHERE status IN ('detected', 'notified')
          AND suggested_subscription IS NOT NULL
          AND TRIM(suggested_subscription) <> ''
          AND datetime(last_detected_at) >= datetime('now', ?)
        ORDER BY risk_score DESC, last_detected_at DESC
        LIMIT 50
        """,
        (f"-{analysis_window_days} days",),
    ) or []

    queued = 0
    skipped = 0
    skip_reasons = {
        "no_user_id": 0,
        "below_min_kills": 0,
        "not_in_current_report": 0,
        "user_not_found": 0,
        "no_matching_template": 0,
        "cooldown_active": 0,
        "deduped_existing": 0,
    }

    for rec in rows:
        rec = dict(rec)
        user_id = rec.get("vodum_user_id")

        if not user_id:
            skipped += 1
            skip_reasons["no_user_id"] += 1
            continue

        suggestion_key = (int(user_id), str(rec.get("suggested_subscription") or "").strip())
        if suggestion_key not in current_suggestion_keys:
            skipped += 1
            skip_reasons["not_in_current_report"] += 1
            continue

        try:
            meta = json.loads(rec.get("meta_json") or "{}")
        except Exception:
            meta = {}

        if not isinstance(meta, dict):
            meta = {}

        kills_30d = _safe_int(meta.get("kills_30d"), 0)

        if kills_30d < min_kills:
            skipped += 1
            skip_reasons["below_min_kills"] += 1
            continue

        has_delivery_history = _has_upgrade_delivery_history(db, int(rec["id"]))
        if _safe_int(rec.get("cooldown_active"), 0) == 1 and has_delivery_history:
            skipped += 1
            skip_reasons["cooldown_active"] += 1
            continue

        user = _load_user(db, user_id)

        if not user:
            skipped += 1
            skip_reasons["user_not_found"] += 1
            continue

        values = {
            "brand_name": settings.get("brand_name") or "VODUM",
            "username": user.get("username") or "",
            "firstname": user.get("firstname") or "",
            "lastname": user.get("lastname") or "",
            "email": user.get("email") or "",
            "current_subscription": rec.get("current_subscription") or user.get("subscription_name") or "",
            "suggested_subscription": rec.get("suggested_subscription") or "",
            "usage_risk_level": rec.get("risk_level") or "",
            "usage_risk_score": rec.get("risk_score") or 0,
            "usage_risk_main_reason": meta.get("main_reason") or "",
            "usage_risk_reasons": ", ".join(meta.get("reasons") or []),
            "usage_risk_kills_7d": meta.get("kills_7d") or 0,
            "usage_risk_kills_30d": meta.get("kills_30d") or 0,
            "usage_risk_kills_90d": meta.get("kills_90d") or 0,
        }

        template = select_comm_template_for_user(
            db=db,
            trigger_event="usage_risk_upgrade_suggestion",
            provider="all",
            user_id=user_id,
        )

        if not template:
            skipped += 1
            skip_reasons["no_matching_template"] += 1
            continue

        template_id = int(template["id"])
        values.update({
            "template_key": "usage_risk_upgrade_suggestion",
            "recommendation_id": int(rec["id"]),
            "suggestion_cooldown_days": cooldown_days,
        })
        delivery_cycle = rec.get("last_notification_at") or "initial"
        dedupe_key = f"usage_risk_upgrade:{int(rec['id'])}:{delivery_cycle}"
        existing = _existing_scheduled(db, dedupe_key)

        # If an old scheduled row is marked sent but no delivery history exists,
        # do not let the dedupe key block the real email forever.
        if (
            existing
            and (existing.get("status") or "").strip().lower() == "sent"
            and not has_delivery_history
        ):
            dedupe_key = f"usage_risk_upgrade:{int(rec['id'])}:repair:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            existing = None

        contexts = _get_user_comm_contexts(db, int(user_id))
        scheduled_any = False
        for ctx in contexts[:1]:
            scheduled = schedule_template_notification(
                db=db,
                template_id=template_id,
                user_id=int(user_id),
                provider=ctx["provider"],
                server_id=ctx.get("server_id"),
                send_at_modifier=None,
                payload=values,
                dedupe_key=dedupe_key,
                max_attempts=10,
            )
            scheduled_any = scheduled_any or bool(scheduled)

        if scheduled_any:
            queued += 1
        else:
            skipped += 1
            skip_reasons["deduped_existing"] += 1

    if queued:
        enqueue_named_task(db, "send_expiration_emails")

    diagnostics = {
        "report_rows": len(report_rows),
        "suggested_in_report": len(suggested_in_report),
        "candidate_recommendations": len(rows),
        "queued": queued,
        "skipped": skipped,
        "skip_reasons": skip_reasons,
        "min_kills": min_kills,
        "analysis_window_days": analysis_window_days,
        "cooldown_days": cooldown_days,
        "summary": report.get("summary") or {},
    }
    status = "success" if queued else "info"
    _log_task(
        task_id,
        status,
        f"Usage risk upgrade suggestions queued={queued}, skipped={skipped}",
        details=diagnostics,
    )

    return {
        "status": "success",
        "message": f"Usage risk upgrade suggestions queued={queued}, skipped={skipped}",
        "details": diagnostics,
    }
