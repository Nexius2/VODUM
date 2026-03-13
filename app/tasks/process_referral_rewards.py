import json
import os
from datetime import date, datetime, timedelta

from db_manager import DBManager
from logging_utils import get_logger
from api.subscriptions import update_user_expiration
from mailing_utils import build_user_context, render_mail
from communications_engine import send_to_user, record_history

log = get_logger("task.process_referral_rewards")


def _get_db():
    return DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _today_iso():
    return date.today().isoformat()


def _get_settings(db):
    row = db.query_one("SELECT * FROM user_referral_settings WHERE id = 1")
    return dict(row) if row else {
        "enabled": 0,
        "reward_enabled": 1,
        "qualification_days": 60,
        "reward_days": 60,
        "allow_referrer_change_before_qualification": 1,
        "auto_notify_reward": 1,
        "eligible_statuses": "active",
    }


def _eligible_statuses(raw):
    return [x.strip() for x in (raw or "active").split(",") if x.strip()]


def _log_event(db, referral_id, event_type, actor="system", old_referrer_user_id=None, new_referrer_user_id=None, details=None):
    db.execute(
        """
        INSERT INTO user_referral_events(
            referral_id, event_type, actor,
            old_referrer_user_id, new_referrer_user_id, details_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            referral_id,
            event_type,
            actor,
            old_referrer_user_id,
            new_referrer_user_id,
            json.dumps(details or {}, ensure_ascii=False) if details is not None else None,
        ),
    )


def _find_reward_template(db):
    row = db.query_one(
        """
        SELECT *
        FROM comm_templates
        WHERE enabled = 1
          AND trigger_event = 'referral_reward'
        ORDER BY id ASC
        LIMIT 1
        """
    )
    if row:
        return dict(row)

    row = db.query_one(
        """
        SELECT *
        FROM comm_templates
        WHERE key = 'referral_reward_default'
          AND enabled = 1
        LIMIT 1
        """
    )
    return dict(row) if row else None


def run(task_id=None, db=None):
    if db is None:
        db = _get_db()

    settings = _get_settings(db)
    if _safe_int(settings.get("enabled"), 0) != 1:
        log.info("Referral program disabled")
        return

    if _safe_int(settings.get("reward_enabled"), 1) != 1:
        log.info("Referral reward disabled")
        return

    statuses = _eligible_statuses(settings.get("eligible_statuses"))
    today = _today_iso()
    rewarded = 0
    skipped = 0
    failed = 0

    rows = db.query(
        """
        SELECT
            r.*,
            referred.username AS referred_username,
            referred.status AS referred_status,
            referred.expiration_date AS referred_expiration_date,
            referrer.username AS referrer_username,
            referrer.expiration_date AS referrer_expiration_date
        FROM user_referrals r
        JOIN vodum_users referred ON referred.id = r.referred_user_id
        JOIN vodum_users referrer ON referrer.id = r.referrer_user_id
        WHERE r.status = 'pending'
          AND r.reward_granted_at IS NULL
          AND r.qualification_due_at IS NOT NULL
          AND date(r.qualification_due_at) <= date(?)
        ORDER BY r.qualification_due_at ASC, r.id ASC
        """,
        (today,),
    ) or []

    tpl = _find_reward_template(db)
    global_settings = db.query_one("SELECT * FROM settings WHERE id = 1")
    global_settings = dict(global_settings) if global_settings else {}

    for row in rows:
        r = dict(row)
        referral_id = int(r["id"])
        referred_status = (r.get("referred_status") or "").strip().lower()

        if referred_status not in statuses:
            skipped += 1
            db.execute(
                """
                UPDATE user_referrals
                SET last_error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (f"Referred user status not eligible: {referred_status}", referral_id),
            )
            continue

        reward_days = _safe_int(r.get("reward_days_snapshot"), _safe_int(settings.get("reward_days"), 60))
        referrer_user_id = int(r["referrer_user_id"])

        referrer = db.query_one(
            "SELECT id, username, email, second_email, discord_user_id, expiration_date, notifications_order_override FROM vodum_users WHERE id = ?",
            (referrer_user_id,),
        )
        if not referrer:
            failed += 1
            db.execute(
                "UPDATE user_referrals SET last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("Referrer not found", referral_id),
            )
            continue

        referrer = dict(referrer)
        before_exp = (referrer.get("expiration_date") or "").strip()

        if before_exp:
            try:
                base_date = date.fromisoformat(before_exp[:10])
            except Exception:
                base_date = date.today()
        else:
            base_date = date.today()

        if base_date < date.today():
            base_date = date.today()

        after_exp = (base_date + timedelta(days=reward_days)).isoformat()

        ok, msg = update_user_expiration(referrer_user_id, after_exp, reason="referral_reward")
        if not ok:
            failed += 1
            db.execute(
                "UPDATE user_referrals SET last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (msg or "Failed to update referrer expiration", referral_id),
            )
            continue

        db.execute(
            """
            UPDATE user_referrals
            SET status = 'rewarded',
                qualified_at = COALESCE(qualified_at, CURRENT_TIMESTAMP),
                reward_granted_at = CURRENT_TIMESTAMP,
                reward_expiration_before = ?,
                reward_expiration_after = ?,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (before_exp or None, after_exp, referral_id),
        )

        _log_event(
            db,
            referral_id,
            "reward_granted",
            actor="system",
            details={
                "reward_days": reward_days,
                "referred_username": r.get("referred_username"),
                "referrer_old_expiration_date": before_exp,
                "referrer_new_expiration_date": after_exp,
            },
        )

        if tpl and _safe_int(settings.get("auto_notify_reward"), 1) == 1:
            ctx = build_user_context({
                **referrer,
                "expiration_date": after_exp,
            })
            ctx["referred_username"] = r.get("referred_username") or ""
            ctx["referral_reward_days"] = reward_days
            ctx["referrer_old_expiration_date"] = before_exp or ""
            ctx["referrer_new_expiration_date"] = after_exp

            subject = render_mail(tpl.get("subject") or "", ctx)
            body = render_mail(tpl.get("body") or "", ctx)

            attempts = send_to_user(
                db=db,
                settings=global_settings,
                user=referrer,
                subject=subject,
                body=body,
                attachments=[],
            )

            any_ok = any(a.status == "sent" for a in attempts)
            for att in attempts:
                record_history(
                    db=db,
                    kind="template",
                    template_id=int(tpl["id"]),
                    campaign_id=None,
                    user_id=referrer_user_id,
                    attempt=att,
                    meta={
                        "event": "referral_reward",
                        "referral_id": referral_id,
                        "referred_user_id": int(r["referred_user_id"]),
                        "referred_username": r.get("referred_username"),
                        "reward_days": reward_days,
                    },
                )

            if any_ok:
                db.execute(
                    """
                    UPDATE user_referrals
                    SET notification_sent_at = CURRENT_TIMESTAMP,
                        notification_template_id = ?
                    WHERE id = ?
                    """,
                    (int(tpl["id"]), referral_id),
                )
                _log_event(
                    db,
                    referral_id,
                    "notification_sent",
                    actor="system",
                    details={
                        "template_id": int(tpl["id"]),
                        "reward_days": reward_days,
                    },
                )

        rewarded += 1

    log.info(
        f"Referral rewards processed: rewarded={rewarded} skipped={skipped} failed={failed}"
    )