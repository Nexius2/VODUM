import json


def update_user_referrer(
    db,
    *,
    user_id: int,
    requested_referrer_user_id: int | None,
    current_referral: dict | None,
    referral_settings: dict,
) -> str | None:
    current_referrer_user_id = (
        int(current_referral["referrer_user_id"])
        if current_referral and current_referral.get("referrer_user_id")
        else None
    )
    if requested_referrer_user_id == user_id:
        return "Referrer cannot be the same user"
    if requested_referrer_user_id == current_referrer_user_id:
        return None
    if current_referral and current_referral.get("status") in ("qualified", "rewarded"):
        return "Referrer cannot be changed after qualification/reward"
    if (
        current_referral
        and int(referral_settings.get("allow_referrer_change_before_qualification") or 0) != 1
    ):
        return "Referrer change is disabled"

    if requested_referrer_user_id is None:
        db.execute("UPDATE vodum_users SET referrer_user_id = NULL WHERE id = ?", (user_id,))
        if current_referral:
            referral_id = int(current_referral["id"])
            db.execute(
                """
                UPDATE user_referrals
                SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (referral_id,),
            )
            db.execute(
                """
                INSERT INTO user_referral_events(
                    referral_id, event_type, actor,
                    old_referrer_user_id, new_referrer_user_id, details_json
                )
                VALUES (?, 'cancelled', 'ui', ?, NULL, ?)
                """,
                (
                    referral_id,
                    current_referrer_user_id,
                    json.dumps({"source": "user_detail"}, ensure_ascii=False),
                ),
            )
        return None

    referrer = db.query_one(
        "SELECT id, status FROM vodum_users WHERE id = ?",
        (requested_referrer_user_id,),
    )
    if not referrer:
        return "Referrer not found"
    if (referrer["status"] or "").lower() != "active":
        return "Referrer must be active"

    db.execute(
        "UPDATE vodum_users SET referrer_user_id = ? WHERE id = ?",
        (requested_referrer_user_id, user_id),
    )
    qualification_days = int(referral_settings.get("qualification_days") or 60)
    reward_days = int(referral_settings.get("reward_days") or 60)
    if current_referral:
        referral_id = int(current_referral["id"])
        db.execute(
            """
            UPDATE user_referrals
            SET referrer_user_id = ?, status = 'pending',
                start_at = CURRENT_TIMESTAMP,
                qualification_due_at = datetime('now', ?),
                qualified_at = NULL, reward_granted_at = NULL,
                reward_expiration_before = NULL, reward_expiration_after = NULL,
                notification_sent_at = NULL, last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (requested_referrer_user_id, f"+{qualification_days} days", referral_id),
        )
        db.execute(
            """
            INSERT INTO user_referral_events(
                referral_id, event_type, actor,
                old_referrer_user_id, new_referrer_user_id, details_json
            )
            VALUES (?, 'referrer_changed', 'ui', ?, ?, ?)
            """,
            (
                referral_id,
                current_referrer_user_id,
                requested_referrer_user_id,
                json.dumps({"source": "user_detail"}, ensure_ascii=False),
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO user_referrals(
                referrer_user_id, referred_user_id, status, referral_source,
                start_at, qualification_due_at, qualification_days_snapshot,
                reward_days_snapshot, created_at, updated_at
            )
            VALUES(
                ?, ?, 'pending', 'manual', CURRENT_TIMESTAMP,
                datetime('now', ?), ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (
                requested_referrer_user_id,
                user_id,
                f"+{qualification_days} days",
                qualification_days,
                reward_days,
            ),
        )
    return None
