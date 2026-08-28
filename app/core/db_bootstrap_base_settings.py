def ensure_base_settings(conn, cursor, *, ensure_row) -> None:
    ensure_row(cursor, "settings", "id = :id", {
        "id": 1,
        "mail_from": "noreply@example.com",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_tls": 1,
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_auth_method": "password",
        "smtp_oauth_access_token": None,
        "skip_never_used_accounts": 0,
        "default_language": None,
        "timezone": "Europe/Paris",
        "admin_email": "",
        "contact_email": "",
        "enable_cron_jobs": 1,
        "default_expiration_days": 90,
        "subscription_currency": "EUR",
        "maintenance_mode": 0,
        "brand_name": None,
        "debug_mode": 0,
        "admin_password_hash": None,
        "auth_enabled": 1,
        "admin_totp_enabled": 0,
        "admin_totp_secret": None,
        "wizard_active": 1,
        "wizard_completed": 0,
        "wizard_step": 1,
        "wizard_state_json": "{}",
        "web_secure_cookies": 0,
        "web_cookie_samesite": "Lax",
        "web_trust_proxy": 0,
        "portal_enabled": 0,
        "portal_public_url": None,
        "portal_support_email": None,
        "portal_support_content": None,
        "portal_show_support_email": 1,
        "portal_quick_messages_enabled": 0,
        "portal_allowed_hostname": None,
        "portal_brand_name": None,
        "portal_logo_url": None,
        "portal_terms_url": None,
        "portal_privacy_url": None,
        "portal_show_subscription": 1,
        "portal_show_media_access": 1,
        "portal_show_monitoring": 1,
        "portal_show_support": 1,
        "portal_show_payment": 0,
        "portal_payment_url": None,
        "portal_payment_label": None,
        "portal_local_auth_enabled": 0,
        "portal_plex_auth_enabled": 0,
        "portal_jellyfin_auth_enabled": 0,
        "portal_local_test_enabled": 0,
        "portal_password_min_length": 8,
        "portal_password_require_upper": 0,
        "portal_password_require_lower": 0,
        "portal_password_require_digit": 0,
        "portal_password_require_symbol": 0,
        "turnstile_enabled": 0,
        "turnstile_site_key": None,
        "turnstile_secret_key": None,
        "turnstile_mode": "compact",
        "turnstile_protect_portal": 0,
        "turnstile_protect_admin": 0,
    })
    cursor.execute("""
        UPDATE settings SET contact_email = admin_email
        WHERE TRIM(COALESCE(contact_email, '')) = ''
          AND TRIM(COALESCE(admin_email, '')) <> ''
    """)
    cursor.execute("""
        UPDATE settings
        SET wizard_completed = CASE
                WHEN TRIM(COALESCE(admin_password_hash, '')) <> ''
                 AND EXISTS (SELECT 1 FROM servers) THEN 1 ELSE 0 END,
            wizard_active = CASE
                WHEN TRIM(COALESCE(admin_password_hash, '')) <> ''
                 AND EXISTS (SELECT 1 FROM servers) THEN 0 ELSE 1 END
        WHERE id = 1 AND (wizard_completed IS NULL OR wizard_active IS NULL)
    """)
    conn.commit()
