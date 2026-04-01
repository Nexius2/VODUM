"""send_expiration_emails.py — unified communications

This task keeps the historical name for backward compatibility, but it now uses
Unified Communications:
- comm_templates (preavis / relance / fin)
- comm_history (real delivery history, channel used)

Legacy tables (sent_emails / sent_discord) are still updated to avoid duplicate
notifications across restarts and to keep older dashboards stable.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from logging_utils import get_logger
from web.helpers import get_db
from tasks_engine import task_logs
from notifications_utils import is_email_ready
from discord_utils import enrich_discord_settings, is_discord_ready

from communications_engine import (
    send_to_user,
    record_history,
    fetch_template_attachments,
    SendAttempt,
    available_channels,
    schedule_template_notification,
)
#from email_sender import send_email
from mailing_utils import build_user_context, render_mail

log = get_logger("send_expiration_emails")

def _row_value(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _json_dict_or_empty(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _user_has_pending_plex_invite(db, vodum_user_id: int) -> bool:
    """
    True si :
    - le user a au moins un media_user Plex
    - aucun media_user Plex n'est accepté
    - au moins un media_user Plex est encore pending
    """
    rows = db.query(
        """
        SELECT accepted_at, external_user_id, details_json, email, username
        FROM media_users
        WHERE vodum_user_id = ?
          AND type = 'plex'
        """,
        (vodum_user_id,),
    ) or []

    if not rows:
        return False

    any_accepted = False
    any_pending = False

    for row in rows:
        accepted_at = str(_row_value(row, "accepted_at") or "").strip()
        if accepted_at:
            any_accepted = True
            continue

        details = _json_dict_or_empty(_row_value(row, "details_json"))
        invite_state = details.get("plex_invite_state") or {}

        if isinstance(invite_state, dict) and bool(invite_state.get("is_pending")):
            any_pending = True
            continue

        external_user_id = str(_row_value(row, "external_user_id") or "").strip()
        email = str(_row_value(row, "email") or "").strip()
        username = str(_row_value(row, "username") or "").strip()

        if not external_user_id and (email or username):
            any_pending = True

    return any_pending and not any_accepted

def _parse_payload(payload_raw) -> dict:
    if not payload_raw:
        return {}
    try:
        data = json.loads(payload_raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _split_channels(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {x.strip() for x in str(raw).split(",") if x.strip()}


def _join_channels(values: set[str]) -> str | None:
    vals = sorted({x.strip() for x in values if x and x.strip()})
    return ",".join(vals) if vals else None


def _send_mode(settings: dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    return mode if mode in ("first", "all") else "first"


def _next_retry_modifier(next_attempt_number: int) -> str:
    if next_attempt_number <= 1:
        return "+15 minutes"
    if next_attempt_number == 2:
        return "+1 hour"
    if next_attempt_number == 3:
        return "+6 hours"
    return "+1 day"


def _required_channels_for_scheduled(db, settings: dict, user: dict, trigger_event: str) -> list[str]:
    if trigger_event in ("user_creation", "pending_invite_reminder"):
        return ["email"]

    avail = available_channels(db, settings, user)
    mode = _send_mode(settings)

    if mode == "all":
        channels = []
        if avail.get("email"):
            channels.append("email")
        if avail.get("discord"):
            channels.append("discord")
        return channels

    # mode == "first" -> one success is enough
    return []


def _flush_comm_scheduled(db, settings: dict, task_id: int | None):
    """
    Flush comm_scheduled queue with retry support.

    Status lifecycle:
    - pending -> first attempt when send_at <= now
    - error   -> retried when next_attempt_at <= now and attempt_count < max_attempts
    - sent    -> done
    """
    rows = db.query(
        """
        SELECT
          q.id AS scheduled_id,
          q.template_id,
          q.vodum_user_id,
          q.provider,
          q.server_id,
          q.send_at,
          q.status,
          q.last_error,
          q.attempt_count,
          q.max_attempts,
          q.next_attempt_at,
          q.last_attempt_at,
          q.payload_json,
          q.dedupe_key,
          q.channels_sent,
          t.key AS template_key,
          t.subject,
          t.body,
          t.trigger_event
        FROM comm_scheduled q
        JOIN comm_templates t ON t.id = q.template_id
        WHERE t.enabled = 1
          AND (
                (q.status = 'pending' AND datetime(q.send_at) <= datetime('now'))
             OR (q.status = 'error'
                 AND COALESCE(q.attempt_count, 0) < COALESCE(q.max_attempts, 10)
                 AND q.next_attempt_at IS NOT NULL
                 AND datetime(q.next_attempt_at) <= datetime('now'))
          )
        ORDER BY
            CASE WHEN q.status = 'pending' THEN 0 ELSE 1 END,
            q.send_at ASC,
            q.id ASC
        LIMIT 200
        """
    )
    due = [dict(r) for r in (rows or [])]
    if not due:
        return 0, 0

    sent = 0
    failed = 0

    for q in due:
        scheduled_id = int(q["scheduled_id"])
        tpl_id = int(q["template_id"])
        uid = int(q["vodum_user_id"])
        trigger_event = (q.get("trigger_event") or "expiration").lower()
        payload = _parse_payload(q.get("payload_json"))
        already_sent_channels = _split_channels(q.get("channels_sent"))

        user = db.query_one(
            """
            SELECT
              u.id,
              u.username,
              u.firstname,
              u.lastname,
              u.email,
              u.second_email,
              u.expiration_date,
              u.discord_user_id,
              u.notifications_order_override,
              u.subscription_template_id,
              st.name AS subscription_name,
              st.duration_days AS subscription_duration_days,
              st.subscription_value AS subscription_value
            FROM vodum_users u
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            WHERE u.id = ?
            """,
            (uid,),
        )
        user = dict(user) if user else None
        if not user:
            next_attempt = int(q.get("attempt_count") or 0) + 1
            max_attempts = int(q.get("max_attempts") or 10)

            if next_attempt >= max_attempts:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status='error',
                        attempt_count=?,
                        next_attempt_at=NULL,
                        last_attempt_at=CURRENT_TIMESTAMP,
                        last_error=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (next_attempt, "User not found", scheduled_id),
                )
            else:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status='error',
                        attempt_count=?,
                        next_attempt_at=datetime('now', ?),
                        last_attempt_at=CURRENT_TIMESTAMP,
                        last_error=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (next_attempt, _next_retry_modifier(next_attempt), "User not found", scheduled_id),
                )
            failed += 1
            continue

        exp_iso = (payload.get("expiration_date") or user.get("expiration_date") or "")[:10]
        extra_context = dict(payload or {})
        subject, body = _format_message(
            q.get("subject") or "",
            q.get("body") or "",
            user,
            exp_iso,
            extra_context=extra_context,
        )
        attachments = fetch_template_attachments(db, tpl_id)

        forced_channels = None
        required_channels = _required_channels_for_scheduled(db, settings, user, trigger_event)

        if required_channels:
            missing = [ch for ch in required_channels if ch not in already_sent_channels]
            forced_channels = missing
            if not forced_channels:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status='sent',
                        last_error=NULL,
                        next_attempt_at=NULL,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (scheduled_id,),
                )
                sent += 1
                continue

        elif trigger_event == "user_creation":
            forced_channels = ["email"]

        attempts = send_to_user(
            db=db,
            settings=settings,
            user=user,
            subject=subject,
            body=body,
            attachments=attachments,
            forced_channels=forced_channels,
            bypass_skip_never_used_accounts=(trigger_event in ("user_creation", "expiration_change", "pending_invite_reminder")),
        )

        updated_channels_sent = set(already_sent_channels)

        for att in attempts:
            record_history(
                db=db,
                kind="template",
                template_id=tpl_id,
                campaign_id=None,
                user_id=uid,
                attempt=att,
                meta={
                    "template_key": q.get("template_key"),
                    "trigger_event": trigger_event,
                    "provider": q.get("provider"),
                    "server_id": q.get("server_id"),
                    "scheduled_id": scheduled_id,
                    "send_at": q.get("send_at"),
                    "dedupe_key": q.get("dedupe_key"),
                    "payload": payload,
                    "attachments": [a.get("filename") for a in (attachments or [])],
                },
            )

            if att.status == "sent":
                updated_channels_sent.add(att.channel)

                # Legacy anti-dup markers for expiration notifications only
                template_key = (payload.get("template_key") or q.get("template_key") or "").strip()
                if trigger_event == "expiration" and template_key and exp_iso:
                    if att.channel == "email" and not _already_sent_email(db, uid, template_key, exp_iso):
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_emails(user_id, template_type, expiration_date, sent_at)
                            VALUES (?, ?, ?, datetime('now'))
                            """,
                            (uid, template_key, exp_iso),
                        )
                    elif att.channel == "discord" and not _already_sent_discord(db, uid, template_key, exp_iso):
                        db.execute(
                            """
                            INSERT OR IGNORE INTO sent_discord(user_id, template_type, expiration_date, sent_at)
                            VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
                            """,
                            (uid, template_key, exp_iso),
                        )

        mode = _send_mode(settings)
        skipped_only = bool(attempts) and all(a.status == "skipped" for a in attempts)

        if skipped_only:
            all_ok = True
        elif mode == "all":
            all_ok = bool(required_channels) and all(ch in updated_channels_sent for ch in required_channels)
        else:
            all_ok = any(a.status == "sent" for a in attempts)

        if all_ok:
            db.execute(
                """
                UPDATE comm_scheduled
                SET status='sent',
                    last_error=NULL,
                    next_attempt_at=NULL,
                    last_attempt_at=CURRENT_TIMESTAMP,
                    channels_sent=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (_join_channels(updated_channels_sent), scheduled_id),
            )

            # Referral: mark notification as really sent only here
            if trigger_event == "referral_reward" and payload.get("referral_id"):
                referral_id = int(payload["referral_id"])
                db.execute(
                    """
                    UPDATE user_referrals
                    SET notification_sent_at = CURRENT_TIMESTAMP,
                        notification_template_id = COALESCE(notification_template_id, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (tpl_id, referral_id),
                )
                db.execute(
                    """
                    INSERT INTO user_referral_events(
                        referral_id, event_type, actor,
                        old_referrer_user_id, new_referrer_user_id, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        referral_id,
                        "notification_sent",
                        "system",
                        None,
                        None,
                        json.dumps(
                            {
                                "template_id": tpl_id,
                                "scheduled_id": scheduled_id,
                                "channels_sent": sorted(updated_channels_sent),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

            sent += 1
        else:
            next_attempt = int(q.get("attempt_count") or 0) + 1
            max_attempts = int(q.get("max_attempts") or 10)
            err = "; ".join([a.error for a in attempts if a.error])[:1000] if attempts else "No channel available"

            if next_attempt >= max_attempts:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status='error',
                        attempt_count=?,
                        next_attempt_at=NULL,
                        last_attempt_at=CURRENT_TIMESTAMP,
                        last_error=?,
                        channels_sent=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (next_attempt, err, _join_channels(updated_channels_sent), scheduled_id),
                )
            else:
                db.execute(
                    """
                    UPDATE comm_scheduled
                    SET status='error',
                        attempt_count=?,
                        next_attempt_at=datetime('now', ?),
                        last_attempt_at=CURRENT_TIMESTAMP,
                        last_error=?,
                        channels_sent=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        next_attempt,
                        _next_retry_modifier(next_attempt),
                        err,
                        _join_channels(updated_channels_sent),
                        scheduled_id,
                    ),
                )
            failed += 1

    if task_id is not None:
        task_logs(task_id, "info", f"comm_scheduled flushed: sent={sent} failed={failed}")

    return sent, failed


def _parse_date_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _get_expiration_templates(db):
    rows = db.query(
        """
        SELECT *
        FROM comm_templates
        WHERE enabled = 1
          AND trigger_event = 'expiration'
        ORDER BY id ASC
        """
    )
    return [dict(r) for r in (rows or [])]


def _get_days_before(template_row: dict | None, fallback: int | None) -> int | None:
    if not template_row:
        return fallback
    v = template_row.get("days_before")
    if v is None:
        return fallback
    try:
        return int(v)
    except Exception:
        return fallback

def _stable_template_marker(template_row: dict | None) -> str | None:
    if not template_row:
        return None

    key = (template_row.get("key") or "").strip().lower()
    if key:
        return key

    try:
        return f"tpl:{int(template_row['id'])}"
    except Exception:
        return None


def _template_markers_for_lookup(template_row: dict | None) -> list[str]:
    markers = []

    stable = _stable_template_marker(template_row)
    if stable:
        markers.append(stable)

    try:
        tpl_id = int(template_row["id"])
        legacy = f"tpl:{tpl_id}"
        if legacy not in markers:
            markers.append(legacy)
    except Exception:
        pass

    return markers

def _already_sent_email(db, user_id: int, template_keys: str | list[str], exp_iso: str) -> bool:
    if isinstance(template_keys, str):
        template_keys = [template_keys]

    keys = [k for k in (template_keys or []) if k]
    if not keys:
        return False

    placeholders = ",".join("?" for _ in keys)
    r = db.query_one(
        f"""
        SELECT 1
        FROM sent_emails
        WHERE user_id = ?
          AND expiration_date = ?
          AND template_type IN ({placeholders})
        LIMIT 1
        """,
        (user_id, exp_iso, *keys),
    )
    return bool(r)


def _already_sent_discord(db, user_id: int, template_keys: str | list[str], exp_iso: str) -> bool:
    if isinstance(template_keys, str):
        template_keys = [template_keys]

    keys = [k for k in (template_keys or []) if k]
    if not keys:
        return False

    placeholders = ",".join("?" for _ in keys)
    r = db.query_one(
        f"""
        SELECT 1
        FROM sent_discord
        WHERE user_id = ?
          AND expiration_date = ?
          AND template_type IN ({placeholders})
        LIMIT 1
        """,
        (user_id, exp_iso, *keys),
    )
    return bool(r)


def _already_sent_any(db, user_id: int, template_keys: str | list[str], exp_iso: str) -> bool:
    return _already_sent_email(db, user_id, template_keys, exp_iso) or _already_sent_discord(db, user_id, template_keys, exp_iso)


def _already_sent_for_current_mode(db, settings: dict, user: dict, template_keys: str | list[str], exp_iso: str) -> bool:
    avail = available_channels(db, settings, user)
    mode = _send_mode(settings)

    email_sent = _already_sent_email(db, int(user["id"]), template_keys, exp_iso)
    discord_sent = _already_sent_discord(db, int(user["id"]), template_keys, exp_iso)

    if mode == "all":
        required = []
        if avail.get("email"):
            required.append(email_sent)
        if avail.get("discord"):
            required.append(discord_sent)
        return bool(required) and all(required)

    # FIRST
    return (avail.get("email") and email_sent) or (avail.get("discord") and discord_sent)

def _format_message(subject: str, body: str, user: dict, exp_iso: str, extra_context: dict | None = None) -> tuple[str, str]:
    ctx_input = dict(user or {})
    ctx_input["expiration_date"] = exp_iso

    if extra_context:
        for k, v in extra_context.items():
            if k in ("expiration_date",):
                continue
            ctx_input[k] = v

    context = build_user_context(ctx_input)

    msg_subject = render_mail(subject or "", context)
    msg_body = render_mail(body or "", context)
    return msg_subject, msg_body

def _get_after(template_row: dict | None) -> int | None:
    if not template_row:
        return None
    v = template_row.get("days_after")
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None

def _safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _subscription_scope_rank(template_row: dict, user_subscription_template_id: int | None) -> int:
    scope = (template_row.get("subscription_scope") or "none").strip().lower()
    tpl_subscription_id = _safe_int(template_row.get("subscription_template_id"))

    if scope == "specific":
        if user_subscription_template_id is None:
            return -1
        return 3 if tpl_subscription_id == user_subscription_template_id else -1

    if scope == "all":
        return 2

    return 1


def _provider_rank(template_row: dict, providers: list[str]) -> int:
    tpl_provider = (template_row.get("trigger_provider") or "all").strip().lower()
    normalized = [p for p in (providers or []) if p in ("plex", "jellyfin")]

    # Best case: exact provider match for one of the user's real media providers
    if tpl_provider in normalized:
        return 3

    # Generic template
    if tpl_provider == "all":
        return 2

    # Fallback: allow a specific provider template even if the user has another
    # provider (or none), so expiration mail can still be sent.
    if tpl_provider in ("plex", "jellyfin"):
        return 1

    return -1


def _pick_expiration_template(
    days_left: int,
    templates: list[dict],
    providers: list[str],
    user_subscription_template_id: int | None,
) -> tuple[dict, str, int | None] | None:
    applicable = []
    normalized_providers = [p for p in (providers or []) if p in ("plex", "jellyfin")]

    for tpl in templates:
        sub_rank = _subscription_scope_rank(tpl, user_subscription_template_id)
        if sub_rank < 0:
            continue

        prov_rank = _provider_rank(tpl, normalized_providers)
        if prov_rank < 0:
            continue

        applicable.append({
            **tpl,
            "_sub_rank": sub_rank,
            "_prov_rank": prov_rank,
        })

    if not applicable:
        return None

    before_values = []
    after_values = []

    for tpl in applicable:
        before_v = _get_days_before(tpl, None)
        after_v = _get_after(tpl)

        if before_v is not None:
            before_values.append(before_v)
        if after_v is not None:
            after_values.append(after_v)

    matches = []

    for tpl in applicable:
        before_v = _get_days_before(tpl, None)
        after_v = _get_after(tpl)

        matched = False
        if before_v is not None and _match_before_window(days_left, before_v, before_values, after_values):
            matched = True
        elif after_v is not None and _match_after_window(days_left, after_v, after_values):
            matched = True

        if matched:
            matches.append(tpl)

    if not matches:
        return None

    matches.sort(key=lambda x: (-int(x["_sub_rank"]), -int(x["_prov_rank"]), int(x["id"])))
    best = matches[0]

    tpl_provider = (best.get("trigger_provider") or "all").strip().lower()

    # Queue context:
    # - exact match => use that real provider
    # - otherwise, if user has at least one provider, use the first real one
    # - otherwise, use the template provider if specific
    # - final technical fallback: plex (required by comm_scheduled schema)
    queue_provider = None
    queue_server_id = None

    if tpl_provider in normalized_providers:
        queue_provider = tpl_provider
    elif normalized_providers:
        queue_provider = normalized_providers[0]
    elif tpl_provider in ("plex", "jellyfin"):
        queue_provider = tpl_provider
    else:
        queue_provider = "plex"

    best.pop("_sub_rank", None)
    best.pop("_prov_rank", None)

    return best, queue_provider, queue_server_id

def _match_before_window(
    days_left: int,
    current_value: int | None,
    all_values: list[int],
    after_values: list[int] | None = None,
) -> bool:
    if current_value is None:
        return False

    # Cas spécial J0 "before":
    # si l'app était arrêtée, on autorise le rattrapage après expiration
    # jusqu'au prochain palier "after" s'il existe.
    if days_left < 0:
        if current_value != 0:
            return False

        overdue_days = -days_left
        future_after_values = sorted(
            [v for v in (after_values or []) if v is not None and int(v) >= 0]
        )
        next_after = future_after_values[0] if future_after_values else None

        if next_after is None:
            return True

        return overdue_days < next_after

    lower_values = sorted([v for v in all_values if v < current_value], reverse=True)
    lower_bound = lower_values[0] if lower_values else -1
    return lower_bound < days_left <= current_value


def _match_after_window(days_left: int, current_value: int | None, all_values: list[int]) -> bool:
    if current_value is None or days_left >= 0:
        return False

    overdue_days = -days_left
    higher_values = sorted([v for v in all_values if v > current_value])
    upper_bound = higher_values[0] if higher_values else None

    if upper_bound is None:
        return overdue_days >= current_value
    return current_value <= overdue_days < upper_bound


def _pick_expiration_template_key(days_left: int, templates: dict) -> str | None:
    preavis_tpl = templates.get("preavis")
    relance_tpl = templates.get("relance")
    fin_tpl = templates.get("fin")

    preavis_before = _get_days_before(preavis_tpl, None)
    relance_before = _get_days_before(relance_tpl, None)
    fin_before = _get_days_before(fin_tpl, None)

    preavis_after = _get_after(preavis_tpl)
    relance_after = _get_after(relance_tpl)
    fin_after = _get_after(fin_tpl)

    before_values = [v for v in (preavis_before, relance_before, fin_before) if v is not None]
    after_values = [v for v in (preavis_after, relance_after, fin_after) if v is not None]

    if _match_before_window(days_left, preavis_before, before_values, after_values):
        return "preavis"
    if _match_before_window(days_left, relance_before, before_values, after_values):
        return "relance"
    if _match_before_window(days_left, fin_before, before_values, after_values):
        return "fin"

    if _match_after_window(days_left, preavis_after, after_values):
        return "preavis"
    if _match_after_window(days_left, relance_after, after_values):
        return "relance"
    if _match_after_window(days_left, fin_after, after_values):
        return "fin"

    # legacy fallback
    if fin_before is None and fin_after is None and days_left < 0:
        return "fin"

    return None


def _get_user_comm_contexts(db, user_id: int) -> list[dict]:
    rows = db.query(
        """
        SELECT
            LOWER(COALESCE(s.type, '')) AS provider,
            mu.server_id AS server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        ORDER BY
            CASE LOWER(COALESCE(s.type, ''))
                WHEN 'plex' THEN 0
                WHEN 'jellyfin' THEN 1
                ELSE 2
            END,
            mu.id ASC
        """,
        (user_id,),
    ) or []

    contexts = []
    seen = set()

    for row in rows:
        row = dict(row)
        provider = (row.get("provider") or "").strip().lower()
        server_id = row.get("server_id")

        if provider not in ("plex", "jellyfin"):
            continue

        key = (provider, server_id)
        if key in seen:
            continue
        seen.add(key)

        contexts.append({
            "provider": provider,
            "server_id": server_id,
        })

    return contexts

def run(task_id: int | None = None, db=None):
    if db is None:
        db = get_db()

    try:
        task_logs(task_id, "info", "Task send_expiration_emails (unified) started")

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(settings) if settings else {}
        
        # If no channel is ready, do nothing (avoid pointless DB work and errors)
        s2 = enrich_discord_settings(db, settings)
        email_ok = is_email_ready(settings)
        discord_ok = is_discord_ready(s2)

        if not email_ok and not discord_ok:
            msg = "Mailing + Discord disabled or not configured → no action."
            task_logs(task_id, "info", msg)
            log.warning(msg)
            return
        
        # Flush scheduled notifications (user_creation days_after etc.)
        _flush_comm_scheduled(db, settings, task_id)

        # Templates (unified)
        templates = _get_expiration_templates(db)

        preavis_tpl = next((t for t in templates if (t.get("key") or "").strip().lower() == "preavis"), None)
        relance_tpl = next((t for t in templates if (t.get("key") or "").strip().lower() == "relance"), None)

        # Backward-compat: legacy global delays can still be used as fallback
        try:
            legacy_preavis = int(settings.get("preavis_days") or 0)
        except Exception:
            legacy_preavis = 0
        try:
            legacy_relance = int(settings.get("reminder_days") or 0)
        except Exception:
            legacy_relance = 0

        preavis_days = _get_days_before(preavis_tpl, legacy_preavis) or None
        relance_days = _get_days_before(relance_tpl, legacy_relance) or None

        log.info(f"Unified delays → preavis={preavis_days} | relance={relance_days}")

        # Users concerned
        users = db.query(
            """
            SELECT
              u.id,
              u.username,
              u.firstname,
              u.lastname,
              u.email,
              u.second_email,
              u.expiration_date,
              u.discord_user_id,
              u.notifications_order_override,
              u.subscription_template_id
            FROM vodum_users u
            WHERE u.expiration_date IS NOT NULL
            """
        )

        today = date.today()
        sent_users_ok = 0
        sent_users_failed = 0

        task_logs(task_id, "info", f"{len(users)} Users analyzed")

        for u in users or []:
            u = dict(u)
            uid = int(u["id"])

            # Ne jamais envoyer de mails d'expiration tant que l'invitation Plex
            # n'est pas réellement acceptée.
            if _user_has_pending_plex_invite(db, uid):
                log.info(f"[USER {uid}] pending Plex invite → expiration notifications skipped")
                continue

            exp = _parse_date_iso(u.get("expiration_date"))
            if not exp:
                continue

            exp_iso = exp.isoformat()
            days_left = (exp - today).days

            comm_contexts = _get_user_comm_contexts(db, uid)
            providers = [ctx["provider"] for ctx in comm_contexts]

            user_subscription_template_id = _safe_int(u.get("subscription_template_id"))
            picked = _pick_expiration_template(days_left, templates, providers, user_subscription_template_id)

            if not picked:
                continue

            tpl, provider, server_id = picked

            # If the queued provider matches a real media server for this user,
            # keep its real server_id. Otherwise leave server_id as None.
            if server_id is None and comm_contexts:
                for ctx in comm_contexts:
                    if ctx["provider"] == provider:
                        server_id = ctx.get("server_id")
                        break

            template_marker = _stable_template_marker(tpl)
            lookup_markers = _template_markers_for_lookup(tpl)

            if not template_marker:
                continue

            # In FIRST mode: one successful channel is enough
            # In ALL mode  : all available channels must have succeeded
            if _already_sent_for_current_mode(db, settings, u, lookup_markers, exp_iso):
                continue

            dedupe_key = f"expiration:template:{template_marker}:user:{uid}:exp:{exp_iso}"
            payload = {
                "trigger_event": "expiration",
                "template_key": template_marker,
                "expiration_date": exp_iso,
                "days_left": days_left,
            }

            schedule_template_notification(
                db=db,
                template_id=int(tpl["id"]),
                user_id=uid,
                provider=provider,
                server_id=server_id,
                send_at_modifier=None,
                payload=payload,
                dedupe_key=dedupe_key,
                max_attempts=10,
            )

        # Flush again so newly queued expiration notifications can go out immediately
        queued_sent, queued_failed = _flush_comm_scheduled(db, settings, task_id)

        msg = (
            f"send_expiration_emails finished — "
            f"queued_ok={queued_sent} queued_failed={queued_failed} "
            f"users_flagged_failed={sent_users_failed}"
        )
        log.info(msg)
        task_logs(task_id, "info", msg)

    except Exception as e:
        log.error("Error in send_expiration_emails", exc_info=True)
        task_logs(task_id, "error", f"Error send_expiration_emails : {e}")
        raise
