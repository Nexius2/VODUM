from __future__ import annotations

import json
from datetime import datetime, date

from logging_utils import get_logger
from tasks_engine import task_logs
from communications_engine import (
    select_comm_templates_for_user,
    schedule_template_notification,
    enqueue_named_task,
)

log = get_logger("send_pending_invite_reminders")


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


def _parse_dt(value):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None

    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(s[:19] if "H" in fmt else s[:10], fmt)
        except Exception:
            pass
    return None


def _pending_plex_rows_for_user(db, vodum_user_id: int):
    rows = db.query(
        """
        SELECT
            mu.id,
            mu.server_id,
            mu.username,
            mu.email,
            mu.external_user_id,
            mu.accepted_at,
            mu.details_json,
            vu.created_at,
            vu.expiration_date
        FROM media_users mu
        JOIN vodum_users vu ON vu.id = mu.vodum_user_id
        WHERE mu.vodum_user_id = ?
          AND mu.type = 'plex'
        ORDER BY mu.id ASC
        """,
        (vodum_user_id,),
    ) or []

    out = []
    for row in rows:
        accepted_at = str(_row_value(row, "accepted_at") or "").strip()
        if accepted_at:
            continue

        details = _json_dict_or_empty(_row_value(row, "details_json"))
        invite_state = details.get("plex_invite_state") or {}

        is_pending = False
        if isinstance(invite_state, dict) and bool(invite_state.get("is_pending")):
            is_pending = True
        else:
            ext_id = str(_row_value(row, "external_user_id") or "").strip()
            email = str(_row_value(row, "email") or "").strip()
            username = str(_row_value(row, "username") or "").strip()
            if not ext_id and (email or username):
                is_pending = True

        if is_pending:
            out.append(dict(row))

    return out


def _user_has_accepted_plex_invite(db, vodum_user_id: int) -> bool:
    row = db.query_one(
        """
        SELECT 1
        FROM media_users
        WHERE vodum_user_id = ?
          AND type = 'plex'
          AND accepted_at IS NOT NULL
          AND TRIM(accepted_at) <> ''
        LIMIT 1
        """,
        (vodum_user_id,),
    )
    return bool(row)


def _pick_primary_pending_server_id(pending_rows):
    if not pending_rows:
        return None

    for row in pending_rows:
        details = _json_dict_or_empty(row.get("details_json"))
        invite_state = details.get("plex_invite_state") or {}
        try:
            primary_server_id = int(invite_state.get("primary_server_id"))
            if primary_server_id > 0:
                return primary_server_id
        except Exception:
            pass

    try:
        return int(pending_rows[0]["server_id"])
    except Exception:
        return None


def _created_days_ago(created_at_raw) -> int | None:
    dt = _parse_dt(created_at_raw)
    if not dt:
        return None
    return (date.today() - dt.date()).days


def _safe_days_after(tpl) -> int:
    try:
        v = int(tpl.get("days_after") or 0)
        return v if v >= 0 else 0
    except Exception:
        return 0


def run(task_id: int, db):
    task_logs(task_id, "info", "Task send_pending_invite_reminders started")
    log.info("=== SEND PENDING INVITE REMINDERS : START ===")

    try:
        tpl_exists = db.query_one(
            """
            SELECT 1
            FROM comm_templates
            WHERE enabled = 1
              AND trigger_event = 'pending_invite_reminder'
            LIMIT 1
            """
        )
        if not tpl_exists:
            msg = "No enabled pending_invite_reminder template."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return {"status": "idle", "queued": 0, "users": 0}

        users = db.query(
            """
            SELECT id, username, email, created_at, expiration_date, status
            FROM vodum_users
            WHERE status = 'invited'
            ORDER BY id ASC
            """
        ) or []

        queued = 0
        pending_users = 0

        for u in users:
            user = dict(u)
            uid = int(user["id"])

            if _user_has_accepted_plex_invite(db, uid):
                continue

            pending_rows = _pending_plex_rows_for_user(db, uid)
            if not pending_rows:
                continue

            pending_users += 1

            created_days = _created_days_ago(user.get("created_at"))
            if created_days is None:
                log.info(f"[USER {uid}] pending invite but created_at missing/unparseable -> skipped")
                continue

            server_id = _pick_primary_pending_server_id(pending_rows)
            provider = "plex"

            templates = select_comm_templates_for_user(
                db=db,
                trigger_event="pending_invite_reminder",
                provider=provider,
                user_id=uid,
            )

            if not templates:
                continue

            for tpl in templates:
                delay_days = _safe_days_after(tpl)
                if created_days < delay_days:
                    continue

                tpl_id = int(tpl["id"])
                dedupe_key = (
                    f"pending_invite_reminder:template:{tpl_id}:"
                    f"user:{uid}:provider:{provider}:server:{server_id}:day:{delay_days}"
                )

                payload = {
                    "trigger_event": "pending_invite_reminder",
                    "username": user.get("username") or "",
                    "email": user.get("email") or "",
                    "expiration_date": (user.get("expiration_date") or "")[:10],
                    "invited_since": (str(user.get("created_at") or "")[:10]),
                    "pending_invite_days": created_days,
                }

                schedule_template_notification(
                    db=db,
                    template_id=tpl_id,
                    user_id=uid,
                    provider=provider,
                    server_id=server_id,
                    send_at_modifier=None,
                    payload=payload,
                    dedupe_key=dedupe_key,
                    max_attempts=10,
                )
                queued += 1

        if queued > 0:
            enqueue_named_task(db, "send_expiration_emails")

        msg = (
            f"send_pending_invite_reminders finished — "
            f"pending_users={pending_users}, queued={queued}"
        )
        log.info(msg)
        task_logs(task_id, "success" if queued else "info", msg)
        return {"status": "ok", "queued": queued, "users": pending_users}

    except Exception as e:
        log.error("Error in send_pending_invite_reminders", exc_info=True)
        task_logs(task_id, "error", f"Error send_pending_invite_reminders: {e}")
        raise

    finally:
        log.info("=== SEND PENDING INVITE REMINDERS : END ===")