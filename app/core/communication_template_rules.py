VALID_TRIGGER_EVENTS = {
    "expiration", "user_creation", "pending_invite_reminder", "referral_reward",
    "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion",
}
IMMEDIATE_EVENTS = {"referral_reward", "expiration_change", "stream_blocked", "usage_risk_upgrade_suggestion"}


def _optional_int(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except Exception:
        return None


def normalize_template_rules(db, form) -> dict:
    trigger_event = str(form.get("trigger_event") or "expiration").strip().lower()
    if trigger_event not in VALID_TRIGGER_EVENTS:
        trigger_event = "expiration"
    trigger_provider = str(form.get("trigger_provider") or "all").strip().lower()
    if trigger_provider not in ("all", "plex", "jellyfin"):
        trigger_provider = "all"
    direction = str(form.get("expiration_change_direction") or "all").strip().lower()
    if direction not in ("all", "increase", "decrease") or trigger_event != "expiration_change":
        direction = "all"

    scope_raw = str(form.get("subscription_scope_value") or "none").strip()
    scope, subscription_template_id = "none", None
    if scope_raw == "all":
        scope = "all"
    elif scope_raw.startswith("subscription:"):
        subscription_template_id = _optional_int(scope_raw.split(":", 1)[1])
        if subscription_template_id and db.query_one("""
            SELECT id FROM subscription_templates
            WHERE id = ? AND COALESCE(is_enabled, 1) = 1
        """, (subscription_template_id,)):
            scope = "specific"
        else:
            subscription_template_id = None

    days_after = _optional_int(form.get("days_after"))
    days_before = _optional_int(form.get("days_before"))
    delay_direction = str(form.get("delay_direction") or "").strip().lower()
    if delay_direction not in ("before", "after"):
        delay_direction = "before"
    if isinstance(days_before, int) and days_before < 0:
        days_before = 0
    if isinstance(days_after, int) and days_after < 0:
        days_after = 0
    if trigger_event in ("user_creation", "pending_invite_reminder"):
        days_before = None
        days_after = 0 if days_after is None else days_after
        delay_direction = "after"
    elif trigger_event in IMMEDIATE_EVENTS:
        days_before, days_after, delay_direction = None, 0, "after"
    elif delay_direction == "after":
        days_after = days_after if days_after is not None else (days_before if days_before is not None else 0)
        days_before = None
    else:
        days_before = days_before if days_before is not None else (days_after if days_after is not None else 0)
        days_after = None
    return {
        "trigger_event": trigger_event, "trigger_provider": trigger_provider,
        "expiration_change_direction": direction, "subscription_scope": scope,
        "subscription_template_id": subscription_template_id,
        "days_before": days_before, "days_after": days_after,
    }
