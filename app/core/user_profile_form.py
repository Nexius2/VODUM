from notifications_utils import parse_notifications_order


def normalize_user_profile_overrides(
    form,
    *,
    expiration_locked: bool,
    subscription_is_lifetime: bool,
    current_expiration_override,
    notifications_can_override: bool,
) -> dict:
    if expiration_locked:
        expiration_override = 1
    elif subscription_is_lifetime:
        expiration_override = int(current_expiration_override or 0)
    else:
        expiration_override = 1 if form.get("expiration_date_override") == "1" else 0

    max_streams_override = None
    raw_streams = form.get("max_streams_override")
    if raw_streams is not None:
        raw_streams = raw_streams.strip()
        if raw_streams:
            try:
                parsed_streams = int(raw_streams)
                max_streams_override = parsed_streams if parsed_streams > 0 else None
            except Exception:
                max_streams_override = None

    notifications_order_override = None
    if notifications_can_override and form.get("use_global_notifications_order") != "1":
        raw_order = (form.get("user_notifications_order") or "").strip()
        if raw_order:
            notifications_order_override = ",".join(parse_notifications_order(raw_order))

    return {
        "expiration_date_override": expiration_override,
        "max_streams_override": max_streams_override,
        "notifications_order_override": notifications_order_override,
    }
