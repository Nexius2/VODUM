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

    task_logs(task_id, "info", "Tâche check_mailing_status démarrée")
    log.info("=== CHECK MAILING STATUS : DÉBUT ===")

    try:
        # --------------------------------------------------------
        # 1 - Lecture complète settings (diagnostic)
        # --------------------------------------------------------
        log.debug("[DIAG] Lecture complète de la table settings…")

        full_settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        log.debug(
            "[DIAG] Contenu brut de settings : %s",
            dict(full_settings) if full_settings else "Aucun"
        )

        if not full_settings:
            msg = "Settings manquants (id=1) : aucune modification des tâches mailing."
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
            "Valeur récupérée → raw=%s | interprété=%s",
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
                log.warning("Tâche '%s' introuvable dans la table tasks.", name)
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
        log.info("✔ Mailing %s", "activé" if mailing_enabled else "désactivé")
        log.debug("Tâches affectées : %s", updated)

        if changes:
            task_logs(
                task_id,
                "success",
                f"Mailing {'activé' if mailing_enabled else 'désactivé'} ({changes} tâche(s))"
            )
        else:
            task_logs(
                task_id,
                "info",
                "Aucun changement de statut des tâches mailing"
            )

        log.info("=== CHECK MAILING STATUS : FIN ===")

    except Exception as e:
        log.error("❌ Exception pendant check_mailing_status", exc_info=True)
        task_logs(task_id, "error", f"Erreur check_mailing_status : {e}")
        raise




