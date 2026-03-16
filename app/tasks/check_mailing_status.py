#!/usr/bin/env python3
"""
check_mailing_status.py

But:
- Activer / désactiver automatiquement les tâches de communication en fonction
  de l'état réel de la configuration (SMTP / Discord bot).
- Nettoyer les statuts "error" quand on désactive (sinon ça pollue l'UI).
- Éviter que des tâches soient "enabled=1" si rien n'est prêt.

Règles:
- email_ok = mailing_enabled == 1 ET SMTP complet
- discord_ok = discord_enabled == 1 ET token bot dispo (via table bots ou legacy)

Tasks pilotées:
- send_expiration_emails : task "unifiée" (si email_ok OU discord_ok)
- send_mail_campaigns   : email only
- send_campaign_discord : discord only
- send_expiration_discord : deprecated -> toujours disabled
"""

from __future__ import annotations

from logging_utils import get_logger
from tasks_engine import task_logs
from notifications_utils import is_email_ready
from discord_utils import enrich_discord_settings, is_discord_ready

log = get_logger("check_mailing_status")


def _as_int(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _normalize_status(s: str | None) -> str:
    return (s or "").strip().lower()


def _set_task_state(db, task_name: str, enabled: int, status: str) -> dict | None:
    """
    Met à jour la tâche si elle existe.
    - Quand on disable: on remet status='disabled', on clear last_error/next_run/queued_count
    - Quand on enable: on remet status='idle', on clear last_error
    """
    row = db.query_one("SELECT id, enabled, status FROM tasks WHERE name = ?", (task_name,))
    if not row:
        return None

    old_enabled = _as_int(row["enabled"], 0)
    old_status = _normalize_status(row["status"])

    enabled = 1 if enabled else 0
    status = _normalize_status(status)

    # Rien à faire si déjà cohérent
    if old_enabled == enabled and old_status == status:
        return {
            "task": task_name,
            "changed": False,
            "old_enabled": old_enabled,
            "new_enabled": enabled,
            "old_status": old_status,
            "new_status": status,
        }

    if enabled == 0:
        db.execute(
            """
            UPDATE tasks
            SET enabled=?,
                status=?,
                last_error=NULL,
                next_run=NULL,
                queued_count=0,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (0, "disabled", row["id"]),
        )
        new_status = "disabled"
        new_enabled = 0
    else:
        db.execute(
            """
            UPDATE tasks
            SET enabled=?,
                status=?,
                last_error=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (1, "idle", row["id"]),
        )
        new_status = "idle"
        new_enabled = 1

    return {
        "task": task_name,
        "changed": True,
        "old_enabled": old_enabled,
        "new_enabled": new_enabled,
        "old_status": old_status,
        "new_status": new_status,
    }


def run(task_id: int, db):
    task_logs(task_id, "info", "Task check_mailing_status started")
    log.info("=== CHECK MAILING STATUS : START ===")

    try:
        # 1) Settings
        srow = db.query_one("SELECT * FROM settings WHERE id = 1")
        if not srow:
            msg = "Missing settings (id=1) → no comm task changes."
            log.error(msg)
            task_logs(task_id, "error", msg)
            return {"status": "error", "message": msg}

        settings = dict(srow)

        # 2) Readiness
        email_ok = is_email_ready(settings)

        s2 = enrich_discord_settings(db, settings)
        discord_ok = is_discord_ready(s2)

        log.info("Readiness: email_ok=%s discord_ok=%s", email_ok, discord_ok)

        # 3) Desired states
        desired = {
            # Unified expiration sender
            "send_expiration_emails": 1 if (email_ok or discord_ok) else 0,

            # Unified modern campaigns
            "send_comm_campaigns": 1 if (email_ok or discord_ok) else 0,

            # Legacy / deprecated
            "send_mail_campaigns": 0,
            "send_campaign_discord": 0,
            "send_expiration_discord": 0,
        }

        updated = []
        for tname, should_enable in desired.items():
            # enabled=1 => status idle, enabled=0 => status disabled
            info = _set_task_state(db, tname, should_enable, "idle" if should_enable else "disabled")
            if info is None:
                log.warning("Task '%s' not found in tasks table.", tname)
                continue
            if info.get("changed"):
                updated.append(info)

        if updated:
            task_logs(task_id, "success", f"Comms status applied ({len(updated)} task(s))", details=updated)
        else:
            task_logs(task_id, "info", "No comm task status changes")

        log.info("=== CHECK MAILING STATUS : END ===")
        return {"status": "ok", "email_ok": email_ok, "discord_ok": discord_ok, "updated": updated}

    except Exception as e:
        log.error("Exception during check_mailing_status", exc_info=True)
        task_logs(task_id, "error", f"Error check_mailing_status: {e}")
        raise