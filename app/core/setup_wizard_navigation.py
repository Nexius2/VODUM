from core.setup_wizard_state import TOTAL_SETUP_STEPS, load_setup_wizard_settings


def setup_communications_available(settings: dict, state: dict) -> bool:
    if state.get("communications") == "skipped":
        return False
    return bool(
        int(settings.get("mailing_enabled") or 0)
        or int(settings.get("discord_enabled") or 0)
    )


def setup_step_available(
    db,
    step: int,
    state: dict,
    settings: dict | None = None,
) -> bool:
    settings = settings or load_setup_wizard_settings(db)
    if step == 6:
        return setup_communications_available(settings, state)

    subscriptions = int(
        (
            db.query_one("SELECT COUNT(*) AS cnt FROM subscription_templates")
            or {"cnt": 0}
        )["cnt"]
        or 0
    )
    if step in (8, 9) and (
        subscriptions == 0 or state.get("subscriptions") == "skipped"
    ):
        return False
    if step == 9:
        users = int(
            (db.query_one("SELECT COUNT(*) AS cnt FROM vodum_users") or {"cnt": 0})[
                "cnt"
            ]
            or 0
        )
        return users > 0
    return True


def next_setup_step(
    db,
    current_step: int,
    state: dict,
    settings: dict | None = None,
) -> int:
    settings = settings or load_setup_wizard_settings(db)
    for candidate in range(current_step + 1, TOTAL_SETUP_STEPS + 1):
        if setup_step_available(db, candidate, state, settings):
            return candidate
        skipped_state_key = {6: "messages", 8: "subscription_settings", 9: "assignment"}.get(
            candidate
        )
        if skipped_state_key:
            state[skipped_state_key] = "skipped"
    return TOTAL_SETUP_STEPS


def previous_setup_step(
    db,
    current_step: int,
    state: dict,
    settings: dict | None = None,
) -> int:
    settings = settings or load_setup_wizard_settings(db)
    for candidate in range(current_step - 1, 0, -1):
        if setup_step_available(db, candidate, state, settings):
            return candidate
    return 1


def display_setup_step(db, settings: dict, state: dict) -> int:
    step = max(
        1,
        min(TOTAL_SETUP_STEPS, int(settings.get("wizard_step") or 1)),
    )
    if setup_step_available(db, step, state, settings):
        return step
    return next_setup_step(db, step, state, settings)
