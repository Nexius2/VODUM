"""Activate deferred subscriptions when a user starts their first playback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def activate_subscription_on_playback(db, media_user_id: int) -> bool:
    row = db.query_one(
        """
        SELECT vu.id AS vodum_user_id, vu.expiration_date, s.default_subscription_days
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        CROSS JOIN settings s
        WHERE mu.id = ? AND s.id = 1
        LIMIT 1
        """,
        (int(media_user_id),),
    )
    if not row or row["expiration_date"]:
        return False
    try:
        days = int(row["default_subscription_days"] or 0)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return False

    expiration = (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()
    cursor = db.execute(
        "UPDATE vodum_users SET expiration_date=? WHERE id=? AND expiration_date IS NULL",
        (expiration, int(row["vodum_user_id"])),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0
