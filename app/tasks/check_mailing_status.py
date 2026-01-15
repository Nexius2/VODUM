#!/usr/bin/env python3

from tasks_engine import task_logs
from logging_utils import get_logger
import traceback



log = get_logger("check_mailing_status")





def run(task_id: int, db):
    """
    Tâche scheduler : active / désactive les tâches de mailing
    selon settings.mailing_enabled
    """

    task_logs(task_id, "info", "Task check_mailing_status started")
    log.info("=== CHECK MAILING STATUS : START ===")

    try:
        # --------------------------------------------------------
        # 1 - Lecture complète settings (diagnostic)
        # --------------------------------------------------------
        log.debug("[DIAG] Full read of the settings table…")

        full_settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        log.debug(
            "[DIAG] Raw settings content : %s",
            dict(full_settings) if full_settings else "Aucun"
        )

        if not full_settings:
            msg = "Missing settings (id=1): no mailing task changes."
            log.error(msg)
            task_logs(task_id, "error", msg)
            return

        # --------------------------------------------------------
        # 2 - Lecture mailing_enabled
        # --------------------------------------------------------
        raw_value = full_settings["mailing_enabled"]
        try:
            mailing_enabled = int(raw_value or 0) == 1
        except Exception:
            mailing_enabled = False


        log.debug(
            "Retrieved value → raw=%s | interpreted=%s",
            raw_value,
            mailing_enabled
        )

        # --------------------------------------------------------
        # 3 - Mise à jour des tâches dépendantes
        # --------------------------------------------------------
        changes = 0

        mailing_tasks = ["send_expiration_emails", "send_mail_campaigns"]
        updated = []

        for name in mailing_tasks:
            trow = db.query_one(
                "SELECT id, enabled FROM tasks WHERE name = ?",
                (name,)
            )

            if not trow:
                log.warning("Task '%s' not found in the tasks table.", name)
                continue

            old = trow["enabled"]
            new = 1 if mailing_enabled else 0

            if old != new:
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new, trow["id"])
                )

                updated.append({
                    "task": name,
                    "old": old,
                    "new": new
                })

                changes += 1

                log.debug(
                    "[TASK] %s : enabled %s → %s",
                    name, old, new
                )

        # --------------------------------------------------------
        # 4 - Résultat
        # --------------------------------------------------------
        log.info("✔ Mailing %s", "Enabled" if mailing_enabled else "disabled")
        log.debug("Affected tasks : %s", updated)

        if changes:
            task_logs(
                task_id,
                "success",
                f"Mailing {'Enabled' if mailing_enabled else 'disabled'} ({changes} task(s))"
            )
        else:
            task_logs(
                task_id,
                "info",
                "No mailing task status changes"
            )

        log.info("=== CHECK MAILING STATUS : END ===")

    except Exception as e:
        log.error("❌ Exception during check_mailing_status", exc_info=True)
        task_logs(task_id, "error", f"Error check_mailing_status : {e}")
        raise




