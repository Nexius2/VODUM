def seed_default_comm_templates(conn, cursor) -> None:
    # -------------------------------------------------
    # 3.2 Seed default COMM templates once
    # -------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comm_template_seed_state (
            seed_key TEXT PRIMARY KEY,
            seeded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    default_comm_templates = [
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
            "body": (
                "Hello {username},\n\n"
                "Your subscription expiration date has been updated.\n\n"
                "Previous expiration date: {old_expiration_date}\n"
                "New expiration date: {new_expiration_date}\n"
                "Change: {expiration_change_signed_days} day(s)\n"
                "Reason: {expiration_change_reason}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "Your subscription expired on {expiration_date}.\n"
                "Your access may now be suspended.\n\n"
                "If you wish to continue using the service, please renew your subscription.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "Your invitation is still waiting for acceptance.\n\n"
                "To start using your account:\n"
                "- Open Plex or Jellyfin\n"
                "- Sign in with your account\n"
                "- Accept the library share invitation if prompted\n\n"
                "Your subscription expiration is currently set to: {expiration_date}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "Your subscription will expire in {days_left} days.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Please renew it to avoid any service interruption.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "Good news: you earned {referral_reward_days} bonus day(s) thanks to {referred_username}.\n\n"
                "Previous expiration date: {referrer_old_expiration_date}\n"
                "New expiration date: {referrer_new_expiration_date}\n\n"
                "Thank you for your referral.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "This is a friendly reminder that your subscription will expire in {days_left} days.\n\n"
                "Expiration date: {expiration_date}\n\n"
                "Please renew it in time to avoid any service interruption.\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
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
            "body": (
                "Hello {username},\n\n"
                "Your account has been created successfully.\n\n"
                "Login email: {email}\n\n"
                "How to get started:\n"
                "- Open Plex or Jellyfin\n"
                "- Sign in with your account\n"
                "- Accept the library share invitation if prompted\n\n"
                "Subscription expiration date: {expiration_date}\n\n"
                "Best regards,\n"
                "{brand_name}\n"
            ),
        },
    ]

    cursor.execute(
        "SELECT seed_key FROM comm_template_seed_state WHERE seed_key = ?",
        ("default_comm_templates",),
    )
    default_comm_templates_already_seeded = cursor.fetchone() is not None

    if not default_comm_templates_already_seeded:
        print("🛠 Checking bundled default communication templates")

        inserted_defaults = 0

        for tpl in default_comm_templates:
            cursor.execute(
                "SELECT id FROM comm_templates WHERE key = ?",
                (tpl["key"],),
            )

            if cursor.fetchone():
                continue

            cursor.execute(
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
                    tpl["key"],
                    tpl["name"],
                    tpl["enabled"],
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
            inserted_defaults += 1

        cursor.execute(
            "INSERT OR IGNORE INTO comm_template_seed_state(seed_key) VALUES (?)",
            ("default_comm_templates",),
        )
        conn.commit()

        print(f"✔ Bundled default communication templates inserted: {inserted_defaults}")

