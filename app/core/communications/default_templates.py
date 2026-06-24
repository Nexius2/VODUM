"""Default communication templates and template-safety helpers."""

from __future__ import annotations


DEFAULT_COMM_TEMPLATES = [
    {
        "key": "stream_blocked",
        "name": "Stream blocked",
        "enabled": 0,
        "trigger_event": "stream_blocked",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Playback blocked",
        "body": "Hello {firstusername},\n\nYour playback has been stopped by VODUM.\n\nReason: {policy_reason}\nStream killed: {stream_killed}\nRule usage: {policy_observed} / {policy_limit}\nOther active streams ({other_streams_count}):\n{other_streams}\nTime: {blocked_at}\n\nIf you think this is a mistake, please contact the administrator.\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_expiration_date_change",
        "name": "Expiration date change",
        "enabled": 0,
        "trigger_event": "expiration_change",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Your subscription date has been updated",
        "body": "Hello {username},\n\nYour subscription expiration date has been updated.\n\nPrevious expiration date: {old_expiration_date}\nNew expiration date: {new_expiration_date}\nChange: {expiration_change_signed_days} day(s)\nReason: {expiration_change_reason}\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_fin",
        "name": "Expired subscription",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 0,
        "days_after": None,
        "subject": "Your subscription has expired",
        "body": "Hello {username},\n\nYour subscription expired on {expiration_date}.\nYour access may now be suspended.\n\nIf you wish to continue using the service, please renew your subscription.\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_pending_invite_reminder",
        "name": "Pending invite reminder",
        "enabled": 0,
        "trigger_event": "pending_invite_reminder",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 3,
        "subject": "Reminder - please accept your invitation",
        "body": "Hello {username},\n\nYour invitation is still waiting for acceptance.\n\nTo start using your account:\n- Open Plex or Jellyfin\n- Sign in with your account\n- Accept the library share invitation if prompted\n\nYour subscription expiration is currently set to: {expiration_date}\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_preavis",
        "name": "Expiration notice",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 30,
        "days_after": None,
        "subject": "Your subscription will expire in {days_left} days",
        "body": "Hello {username},\n\nYour subscription will expire in {days_left} days.\n\nExpiration date: {expiration_date}\n\nPlease renew it to avoid any service interruption.\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_parrainage",
        "name": "Referral reward",
        "enabled": 0,
        "trigger_event": "referral_reward",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Referral reward granted",
        "body": "Hello {username},\n\nGood news: you earned {referral_reward_days} bonus day(s) thanks to {referred_username}.\n\nPrevious expiration date: {referrer_old_expiration_date}\nNew expiration date: {referrer_new_expiration_date}\n\nThank you for your referral.\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_relance",
        "name": "Expiration reminder",
        "enabled": 0,
        "trigger_event": "expiration",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": 7,
        "days_after": None,
        "subject": "Reminder - your subscription will expire soon",
        "body": "Hello {username},\n\nThis is a friendly reminder that your subscription will expire in {days_left} days.\n\nExpiration date: {expiration_date}\n\nPlease renew it in time to avoid any service interruption.\n\nBest regards,\n{brand_name}\n",
    },
    {
        "key": "default_user_creation",
        "name": "User creation",
        "enabled": 0,
        "trigger_event": "user_creation",
        "trigger_provider": "all",
        "subscription_scope": "all",
        "subscription_template_id": None,
        "expiration_change_direction": "all",
        "days_before": None,
        "days_after": 0,
        "subject": "Welcome - your account is ready",
        "body": "Hello {username},\n\nYour account has been created successfully.\n\nLogin email: {email}\n\nHow to get started:\n- Open Plex or Jellyfin\n- Sign in with your account\n- Accept the library share invitation if prompted\n\nSubscription expiration date: {expiration_date}\n\nBest regards,\n{brand_name}\n",
    },
]


def restore_default_comm_templates(db) -> int:
    restored = 0

    for tpl in DEFAULT_COMM_TEMPLATES:
        restore_key = f"{tpl['key']}_restore_default"
        restore_name = f"{tpl['name']} - Default"

        existing = db.query_one(
            "SELECT id FROM comm_templates WHERE key = ?",
            (restore_key,),
        )

        if existing:
            continue

        db.execute(
            """
            INSERT INTO comm_templates(
                key,
                name,
                enabled,
                trigger_event,
                trigger_provider,
                expiration_change_direction,
                subscription_scope,
                subscription_template_id,
                days_before,
                days_after,
                subject,
                body,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                restore_key,
                restore_name,
                0,
                tpl["trigger_event"],
                tpl["trigger_provider"],
                tpl["expiration_change_direction"],
                tpl["subscription_scope"],
                tpl["subscription_template_id"],
                tpl["days_before"],
                tpl["days_after"],
                tpl["subject"],
                tpl["body"],
            ),
        )

        restored += 1

    return restored


def is_stream_blocked_template(row: dict | None) -> bool:
    if not row:
        return False

    return (row.get("key") or "").strip().lower() == "stream_blocked"


def subscription_expired_warning_requires_stream_blocked(settings: dict | None) -> bool:
    mode = ((settings or {}).get("expiry_mode") or "none").strip().lower()
    return mode in ("warn_only", "warn_then_disable")


def force_stream_blocked_template_values(template: dict, *, enabled: int | None = None) -> dict:
    forced = dict(template or {})
    forced["key"] = "stream_blocked"
    forced["trigger_event"] = "stream_blocked"
    forced["trigger_provider"] = "all"
    forced["subscription_scope"] = "all"
    forced["subscription_template_id"] = None
    forced["expiration_change_direction"] = "all"
    forced["days_before"] = None
    forced["days_after"] = 0

    if enabled is not None:
        forced["enabled"] = int(enabled)

    return forced
