ALLOWED_ACTIONS = {"archive", "restore"}


def normalize_referral_ids(values, limit=500):
    """Return unique, positive referral IDs while bounding the request size."""
    result = []
    seen = set()
    for value in values:
        try:
            referral_id = int(value)
        except (TypeError, ValueError):
            continue
        if referral_id <= 0 or referral_id in seen:
            continue
        seen.add(referral_id)
        result.append(referral_id)
        if len(result) >= limit:
            break
    return result


def bulk_update_referrals(db, referral_ids, action):
    """Archive or restore eligible referrals and return the affected row count."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported referral bulk action")

    ids = normalize_referral_ids(referral_ids)
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    if action == "archive":
        eligible_clause = "status IN ('pending', 'qualified', 'rewarded', 'expired')"
        update_sql = f"""
            UPDATE user_referrals
            SET status = 'archived',
                archived_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
              AND {eligible_clause}
        """
    else:
        eligible_clause = "status = 'archived'"
        update_sql = f"""
            UPDATE user_referrals
            SET status = CASE
                    WHEN reward_granted_at IS NOT NULL THEN 'rewarded'
                    WHEN qualified_at IS NOT NULL THEN 'qualified'
                    WHEN expired_at IS NOT NULL THEN 'expired'
                    ELSE 'pending'
                END,
                archived_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
              AND {eligible_clause}
        """

    row = db.query_one(
        f"SELECT COUNT(*) AS total FROM user_referrals "
        f"WHERE id IN ({placeholders}) AND {eligible_clause}",
        ids,
    )
    affected = int(row["total"] if row else 0)
    if affected:
        db.execute(update_sql, ids)
    return affected
