import json

TOTAL_SETUP_STEPS = 10

SETUP_WIZARD_SETTINGS_COLUMNS = """
    wizard_step,
    wizard_state_json,
    wizard_active,
    wizard_completed,
    admin_email,
    default_language,
    timezone,
    mailing_enabled,
    mail_from,
    smtp_host,
    smtp_port,
    smtp_tls,
    smtp_user,
    smtp_pass,
    smtp_auth_method,
    smtp_oauth_access_token,
    discord_enabled,
    discord_bot_token,
    notifications_send_mode,
    reminder_days,
    preavis_days,
    expiry_mode,
    usage_risk_enabled,
    usage_risk_send_upgrade_suggestions,
    usage_risk_min_kills_before_suggestion
"""


def load_setup_wizard_settings(db) -> dict:
    row = db.query_one(
        f"SELECT {SETUP_WIZARD_SETTINGS_COLUMNS} FROM settings WHERE id = 1"
    )
    return dict(row or {})


def should_resume_setup_wizard(db, settings: dict) -> bool:
    """Decide whether an authenticated admin still needs initial setup."""
    if int(settings.get("wizard_active") or 0) != 1:
        return False
    if int(settings.get("wizard_completed") or 0) == 1:
        db.execute("UPDATE settings SET wizard_active = 0 WHERE id = 1")
        settings["wizard_active"] = 0
        return False

    # A server is only step 4 for a fresh wizard. However, older configured
    # installations may have stale wizard flags and no wizard progress at all;
    # keep repairing that legacy state so they are not forced into onboarding.
    state = decode_setup_wizard_state(settings)
    has_fresh_progress = any(
        state.get(key)
        for key in ("instance", "administrator", "localization", "media_server")
    ) or bool(state.get("validated_server_ids"))
    if not has_fresh_progress:
        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) > 0:
            db.execute(
                "UPDATE settings SET wizard_active = 0, wizard_completed = 1 WHERE id = 1"
            )
            settings["wizard_active"] = 0
            settings["wizard_completed"] = 1
            return False
    return True


def decode_setup_wizard_state(settings: dict) -> dict:
    try:
        value = json.loads(settings.get("wizard_state_json") or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def save_setup_wizard_progress(
    db,
    *,
    step: int | None = None,
    state: dict | None = None,
    active: int | None = None,
    completed: int | None = None,
) -> None:
    current = load_setup_wizard_settings(db)
    next_step = int(step if step is not None else current.get("wizard_step") or 1)
    db.execute(
        """
        UPDATE settings SET
          wizard_step = ?,
          wizard_state_json = ?,
          wizard_active = ?,
          wizard_completed = ?
        WHERE id = 1
        """,
        (
            max(1, min(TOTAL_SETUP_STEPS, next_step)),
            json.dumps(
                state if state is not None else decode_setup_wizard_state(current)
            ),
            int(active if active is not None else current.get("wizard_active") or 0),
            int(
                completed
                if completed is not None
                else current.get("wizard_completed") or 0
            ),
        ),
    )
