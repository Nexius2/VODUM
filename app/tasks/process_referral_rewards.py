import json
import os
from datetime import date, datetime, timedelta

from db_manager import DBManager
from logging_utils import get_logger
from api.subscriptions import update_user_expiration
from communications_engine import schedule_template_notification, select_comm_template_for_user

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




def _get_user_comm_context(db, user_id: int):
    row = db.query_one(
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
        LIMIT 1
        """,
        (user_id,),
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

    tpl = None
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

        if _safe_int(settings.get("auto_notify_reward"), 1) == 1:
            comm_ctx = _get_user_comm_context(db, referrer_user_id)

            if not comm_ctx:
                db.execute(
                    """
                    UPDATE user_referrals
                    SET last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    ("Reward granted but notification queue failed: no media/server context found", referral_id),
                )
                log.warning(
                    "Referral reward notification not queued: no media/server context for referrer_user_id=%s",
                    referrer_user_id,
                )
            else:
                provider = (comm_ctx.get("provider") or "").strip().lower()
                server_id = comm_ctx.get("server_id")

                tpl = select_comm_template_for_user(
                    db=db,
                    trigger_event="referral_reward",
                    provider=provider,
                    user_id=referrer_user_id,
                )

                if not tpl:
                    db.execute(
                        """
                        UPDATE user_referrals
                        SET last_error = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        ("Reward granted but notification queue skipped: no matching referral template", referral_id),
                    )
                    log.warning(
                        "Referral reward notification skipped: no matching template for referrer_user_id=%s provider=%s",
                        referrer_user_id,
                        provider,
                    )
                    rewarded += 1
                    continue

                payload = {
                    "event": "referral_reward",
                    "trigger_event": "referral_reward",
                    "referral_id": referral_id,
                    "referred_user_id": int(r["referred_user_id"]),
                    "referred_username": r.get("referred_username") or "",
                    "reward_days": reward_days,
                    "referral_reward_days": reward_days,
                    "referrer_old_expiration_date": before_exp or "",
                    "referrer_new_expiration_date": after_exp,
                    "expiration_date": after_exp,
                }

                dedupe_key = f"referral_reward:{referral_id}:template:{int(tpl['id'])}:user:{referrer_user_id}"

                schedule_template_notification(
                    db=db,
                    template_id=int(tpl["id"]),
                    user_id=referrer_user_id,
                    provider=provider,
                    server_id=server_id,
                    send_at_modifier=None,
                    payload=payload,
                    dedupe_key=dedupe_key,
                    max_attempts=10,
                )

                _log_event(
                    db,
                    referral_id,
                    "notification_queued",
                    actor="system",
                    details={
                        "template_id": int(tpl["id"]),
                        "reward_days": reward_days,
                        "dedupe_key": dedupe_key,
                    },
                )

        rewarded += 1

    log.info(
        f"Referral rewards processed: rewarded={rewarded} skipped={skipped} failed={failed}"
    )