import json

from communications_engine import (
    select_comm_template_for_user,
    schedule_template_notification,
    enqueue_named_task,
)
from core.usage_risk import build_usage_risk_report
from logging_utils import get_logger


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


def run(task_id=None, db=None):
    settings = dict(db.query_one("SELECT * FROM settings WHERE id = 1") or {})

    if _safe_int(settings.get("usage_risk_enabled"), 1) != 1:
        return {"status": "success", "message": "Usage risk disabled"}

    if _safe_int(settings.get("usage_risk_send_upgrade_suggestions"), 0) != 1:
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
        return {"status": "success", "message": "No enabled usage risk upgrade template"}

    min_kills = _safe_int(settings.get("usage_risk_min_kills_before_suggestion"), 3)
    cooldown_days = _safe_int(settings.get("usage_risk_suggestion_cooldown_days"), 30)
    analysis_window_days = _safe_int(settings.get("usage_risk_analysis_window_days"), 30)

    # Refresh recommendation history before sending.
    build_usage_risk_report(
        db,
        {"period_days": analysis_window_days},
        persist_history=True,
    )

    rows = db.query(
        """
        SELECT *
        FROM usage_risk_recommendations
        WHERE status IN ('detected', 'notified')
          AND suggested_subscription IS NOT NULL
          AND TRIM(suggested_subscription) <> ''
          AND datetime(last_detected_at) >= datetime('now', ?)
          AND (
                cooldown_until IS NULL
             OR datetime(cooldown_until) <= datetime('now')
          )
        ORDER BY risk_score DESC, last_detected_at DESC
        LIMIT 50
        """,
        (f"-{analysis_window_days} days",),
    ) or []

    queued = 0
    skipped = 0

    for rec in rows:
        rec = dict(rec)
        user_id = rec.get("vodum_user_id")

        if not user_id:
            skipped += 1
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
            continue

        user = _load_user(db, user_id)

        if not user:
            skipped += 1
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
            continue

        template_id = int(template["id"])
        values.update({
            "template_key": "usage_risk_upgrade_suggestion",
            "recommendation_id": int(rec["id"]),
            "suggestion_cooldown_days": cooldown_days,
        })
        delivery_cycle = rec.get("last_notification_at") or "initial"
        schedule_template_notification(
            db=db,
            template_id=template_id,
            user_id=int(user_id),
            provider="all",
            server_id=None,
            send_at_modifier=None,
            payload=values,
            dedupe_key=f"usage_risk_upgrade:{int(rec['id'])}:{delivery_cycle}",
            max_attempts=10,
        )
        queued += 1

    if queued:
        enqueue_named_task(db, "send_expiration_emails")

    return {
        "status": "success",
        "message": f"Usage risk upgrade suggestions queued={queued}, skipped={skipped}",
    }
