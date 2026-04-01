from __future__ import annotations

from logging_utils import get_logger
from tasks_engine import task_logs
from communications_engine import (
    fetch_campaign_attachments,
    send_to_user,
    record_history,
    available_channels,
)

log = get_logger("send_comm_campaigns")


def _split_channels(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {x.strip() for x in str(raw).split(",") if x.strip()}


def _join_channels(values: set[str]) -> str | None:
    vals = sorted({x.strip() for x in values if x and x.strip()})
    return ",".join(vals) if vals else None


def _send_mode(settings: dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    return mode if mode in ("first", "all") else "first"


def _next_retry_modifier(next_attempt_number: int) -> str:
    if next_attempt_number <= 1:
        return "+15 minutes"
    if next_attempt_number == 2:
        return "+1 hour"
    if next_attempt_number == 3:
        return "+6 hours"
    return "+1 day"


def _required_channels(db, settings: dict, user: dict) -> list[str]:
    avail = available_channels(db, settings, user)
    channels = []
    if avail.get("email"):
        channels.append("email")
    if avail.get("discord"):
        channels.append("discord")
    return channels


def _apply_campaign_status(db, campaign_ids: set[int]) -> None:
    for campaign_id in campaign_ids:
        row = db.query_one(
            """
            SELECT
              COUNT(*) AS total_count,
              SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent_count,
              SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
              SUM(CASE WHEN status = 'error' AND COALESCE(next_attempt_at, '') <> '' AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 10) THEN 1 ELSE 0 END) AS retry_count,
              SUM(CASE WHEN status = 'error' AND (next_attempt_at IS NULL OR COALESCE(attempt_count, 0) >= COALESCE(max_attempts, 10)) THEN 1 ELSE 0 END) AS failed_final_count
            FROM comm_campaign_targets
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        )
        row = dict(row) if row else {}

        total_count = int(row.get("total_count") or 0)
        sent_count = int(row.get("sent_count") or 0)
        pending_count = int(row.get("pending_count") or 0)
        retry_count = int(row.get("retry_count") or 0)
        failed_final_count = int(row.get("failed_final_count") or 0)

        if total_count == 0:
            db.execute(
                "UPDATE comm_campaigns SET status='draft', sent_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (campaign_id,),
            )
            continue

        if pending_count > 0 or retry_count > 0:
            db.execute(
                "UPDATE comm_campaigns SET status='sending', sent_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (campaign_id,),
            )
            continue

        if failed_final_count > 0:
            final_status = "error"
        elif sent_count == total_count and total_count > 0:
            final_status = "finished"
        else:
            final_status = "error"

        db.execute(
            "UPDATE comm_campaigns SET status=?, sent_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (final_status, campaign_id),
        )


def run(task_id: int, db):
    task_logs(task_id, "info", "Task send_comm_campaigns started")
    log.info("=== SEND COMM CAMPAIGNS : START ===")

    try:
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}

        rows = db.query(
            """
            SELECT
              ct.id AS target_id,
              ct.campaign_id,
              ct.user_id,
              ct.status,
              ct.attempt_count,
              ct.max_attempts,
              ct.next_attempt_at,
              ct.last_attempt_at,
              ct.last_error,
              ct.channels_sent,
              c.name AS campaign_name,
              c.subject,
              c.body,
              c.server_id,
              c.status AS campaign_status
            FROM comm_campaign_targets ct
            JOIN comm_campaigns c ON c.id = ct.campaign_id
            WHERE c.is_test = 0
              AND (
                    ct.status = 'pending'
                 OR (
                        ct.status = 'error'
                    AND COALESCE(ct.attempt_count, 0) < COALESCE(ct.max_attempts, 10)
                    AND ct.next_attempt_at IS NOT NULL
                    AND datetime(ct.next_attempt_at) <= datetime('now')
                 )
              )
            ORDER BY
              CASE WHEN ct.status = 'pending' THEN 0 ELSE 1 END,
              ct.id ASC
            LIMIT 100
            """
        )
        due = [dict(r) for r in (rows or [])]
        if not due:
            task_logs(task_id, "info", "No queued communication campaigns")
            return {"status": "idle", "processed": 0}

        processed = 0
        success = 0
        failed = 0
        touched_campaign_ids: set[int] = set()

        for row in due:
            processed += 1
            target_id = int(row["target_id"])
            campaign_id = int(row["campaign_id"])
            user_id = int(row["user_id"])
            touched_campaign_ids.add(campaign_id)

            user = db.query_one(
                """
                SELECT id, username, firstname, lastname, email, second_email, discord_user_id, notifications_order_override, expiration_date
                FROM vodum_users
                WHERE id = ?
                """,
                (user_id,),
            )
            user = dict(user) if user else None
            if not user:
                next_attempt = int(row.get("attempt_count") or 0) + 1
                max_attempts = int(row.get("max_attempts") or 10)
                if next_attempt >= max_attempts:
                    db.execute(
                        """
                        UPDATE comm_campaign_targets
                        SET status='error',
                            attempt_count=?,
                            next_attempt_at=NULL,
                            last_attempt_at=CURRENT_TIMESTAMP,
                            last_error=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (next_attempt, "User not found", target_id),
                    )
                else:
                    db.execute(
                        """
                        UPDATE comm_campaign_targets
                        SET status='error',
                            attempt_count=?,
                            next_attempt_at=datetime('now', ?),
                            last_attempt_at=CURRENT_TIMESTAMP,
                            last_error=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (next_attempt, _next_retry_modifier(next_attempt), "User not found", target_id),
                    )
                failed += 1
                continue

            attachments = fetch_campaign_attachments(db, campaign_id)
            already_sent_channels = _split_channels(row.get("channels_sent"))
            mode = _send_mode(settings)
            required_channels = _required_channels(db, settings, user)

            if mode == "all":
                missing_channels = [ch for ch in required_channels if ch not in already_sent_channels]
                if not missing_channels and required_channels:
                    db.execute(
                        """
                        UPDATE comm_campaign_targets
                        SET status='sent',
                            last_error=NULL,
                            next_attempt_at=NULL,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (target_id,),
                    )
                    success += 1
                    continue
                forced_channels = missing_channels
            else:
                forced_channels = None

            attempts = send_to_user(
                db=db,
                settings=settings,
                user=user,
                subject=row.get("subject") or "",
                body=row.get("body") or "",
                attachments=attachments,
                forced_channels=forced_channels,
            )

            updated_channels_sent = set(already_sent_channels)
            for att in attempts:
                if att.status == "sent":
                    updated_channels_sent.add(att.channel)
                record_history(
                    db=db,
                    kind="campaign",
                    template_id=None,
                    campaign_id=campaign_id,
                    user_id=user_id,
                    attempt=att,
                    meta={
                        "campaign_id": campaign_id,
                        "campaign_name": row.get("campaign_name"),
                        "server_id": row.get("server_id"),
                        "target_id": target_id,
                        "attachments": [a.get("filename") for a in (attachments or [])],
                    },
                )

            skipped_only = bool(attempts) and all(a.status == "skipped" for a in attempts)

            if skipped_only:
                target_ok = True
            elif mode == "all":
                target_ok = bool(required_channels) and all(ch in updated_channels_sent for ch in required_channels)
            else:
                target_ok = any(a.status == "sent" for a in attempts)

            if target_ok:
                db.execute(
                    """
                    UPDATE comm_campaign_targets
                    SET status='sent',
                        last_error=NULL,
                        next_attempt_at=NULL,
                        last_attempt_at=CURRENT_TIMESTAMP,
                        channels_sent=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (_join_channels(updated_channels_sent), target_id),
                )
                success += 1
            else:
                next_attempt = int(row.get("attempt_count") or 0) + 1
                max_attempts = int(row.get("max_attempts") or 10)
                err = "; ".join([a.error for a in attempts if a.error])[:1000] if attempts else "No channel available"
                if next_attempt >= max_attempts:
                    db.execute(
                        """
                        UPDATE comm_campaign_targets
                        SET status='error',
                            attempt_count=?,
                            next_attempt_at=NULL,
                            last_attempt_at=CURRENT_TIMESTAMP,
                            last_error=?,
                            channels_sent=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (next_attempt, err, _join_channels(updated_channels_sent), target_id),
                    )
                else:
                    db.execute(
                        """
                        UPDATE comm_campaign_targets
                        SET status='error',
                            attempt_count=?,
                            next_attempt_at=datetime('now', ?),
                            last_attempt_at=CURRENT_TIMESTAMP,
                            last_error=?,
                            channels_sent=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (next_attempt, _next_retry_modifier(next_attempt), err, _join_channels(updated_channels_sent), target_id),
                    )
                failed += 1

        _apply_campaign_status(db, touched_campaign_ids)

        msg = f"send_comm_campaigns finished — processed={processed} success={success} failed={failed}"
        task_logs(task_id, "success" if success else "info", msg, details={"campaign_ids": sorted(touched_campaign_ids)})
        log.info(msg)
        return {"status": "ok", "processed": processed, "success": success, "failed": failed}

    except Exception as e:
        log.error("Error in send_comm_campaigns", exc_info=True)
        task_logs(task_id, "error", f"Error send_comm_campaigns: {e}")
        raise
    finally:
        log.info("=== SEND COMM CAMPAIGNS : END ===")