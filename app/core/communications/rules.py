"""Shared communication rule helpers used by UI routes and services."""

from __future__ import annotations

from communications_engine import available_channels


def find_enabled_template_duplicate(
    db,
    *,
    trigger_event: str,
    trigger_provider: str,
    subscription_scope: str,
    subscription_template_id,
    days_before,
    days_after,
    expiration_change_direction: str = "all",
    exclude_id: int | None = None,
):
    """
    Detect only true logical duplicates among ENABLED templates.

    Allowed:
    - same trigger/provider/subscription target with different delay slots
      (ex: J-30 / J-7 / J-0 for expiration)
    - all + plex/jellyfin fallback combinations
    - disabled duplicates

    Blocked:
    - another ENABLED template with the exact same logical slot
    """
    normalized_sub_id = subscription_template_id if subscription_scope == "specific" else None
    normalized_exp_dir = expiration_change_direction if trigger_event == "expiration_change" else "all"

    sql = """
        SELECT id, name
        FROM comm_templates
        WHERE enabled = 1
          AND trigger_event = ?
          AND trigger_provider = ?
          AND COALESCE(subscription_scope, 'none') = ?
          AND COALESCE(subscription_template_id, 0) = COALESCE(?, 0)
          AND COALESCE(expiration_change_direction, 'all') = ?
          AND (
                (days_before IS NULL AND ? IS NULL)
                OR days_before = ?
              )
          AND (
                (days_after IS NULL AND ? IS NULL)
                OR days_after = ?
              )
    """
    params = [
        trigger_event,
        trigger_provider,
        subscription_scope,
        normalized_sub_id,
        normalized_exp_dir,
        days_before, days_before,
        days_after, days_after,
    ]

    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)

    sql += " LIMIT 1"

    row = db.query_one(sql, tuple(params))
    return dict(row) if row else None


def normalize_send_mode(settings: dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    return mode if mode in ("first", "all") else "first"


def normalize_campaign_targets(db, request_form) -> tuple[str, str, int | None]:
    trigger_provider = (request_form.get("trigger_provider") or "all").strip().lower()
    if trigger_provider not in ("all", "plex", "jellyfin"):
        trigger_provider = "all"

    subscription_scope_raw = (request_form.get("subscription_scope_value") or "none").strip()
    subscription_scope = "none"
    subscription_template_id = None

    if subscription_scope_raw == "all":
        subscription_scope = "all"

    elif subscription_scope_raw.startswith("subscription:"):
        sub_id_raw = subscription_scope_raw.split(":", 1)[1].strip()

        try:
            subscription_template_id = int(sub_id_raw)
        except Exception:
            subscription_template_id = None

        if subscription_template_id:
            sub_exists = db.query_one(
                """
                SELECT id
                FROM subscription_templates
                WHERE id = ?
                  AND COALESCE(is_enabled, 1) = 1
                """,
                (subscription_template_id,),
            )

            if sub_exists:
                subscription_scope = "specific"
            else:
                subscription_scope = "none"
                subscription_template_id = None

    return trigger_provider, subscription_scope, subscription_template_id


def campaign_attempts_satisfy_mode(db, settings: dict, user: dict, attempts: list) -> bool:
    """
    Campaign success rule:
    - FIRST: at least one successful channel
    - ALL  : all available channels for this user must succeed
    - skipped_only: treated as OK to stay aligned with unified comm engine behavior
    """
    mode = normalize_send_mode(settings)
    avail = available_channels(db, settings, user)
    attempts = attempts or []

    sent_channels = {a.channel for a in attempts if getattr(a, "status", None) == "sent"}
    skipped_only = bool(attempts) and all(getattr(a, "status", None) == "skipped" for a in attempts)

    if skipped_only:
        return True

    if mode == "all":
        required = []
        if avail.get("email"):
            required.append("email")
        if avail.get("discord"):
            required.append("discord")

        if not required:
            return False

        return all(ch in sent_channels for ch in required)

    return any(getattr(a, "status", None) == "sent" for a in attempts)
