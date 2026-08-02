from datetime import datetime, timedelta


def ensure_first_access_expiration(db, vodum_user_id: int, *, logger, today=None) -> bool:
    row = db.query_one(
        "SELECT expiration_date FROM vodum_users WHERE id = ?",
        (vodum_user_id,),
    )
    if not row or row["expiration_date"]:
        return False
    settings = db.query_one("SELECT default_subscription_days FROM settings WHERE id = 1")
    try:
        days = int(settings["default_subscription_days"]) if settings else 0
    except Exception:
        days = 0
    if days <= 0:
        return False
    base_date = today or datetime.utcnow().date()
    expiration = (base_date + timedelta(days=days)).isoformat()
    db.execute(
        "UPDATE vodum_users SET expiration_date = ? WHERE id = ?",
        (expiration, vodum_user_id),
    )
    logger.info(
        "[SUBSCRIPTION] expiration_date initialisée pour vodum_user_id=%s → %s",
        vodum_user_id,
        expiration,
    )
    return True
