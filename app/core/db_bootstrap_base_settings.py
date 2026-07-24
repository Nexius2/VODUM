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
