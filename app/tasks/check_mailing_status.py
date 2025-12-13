#!/usr/bin/env python3

from db_utils import open_db
from tasks_engine import safe_execute, task_logs
from logging_utils import get_logger
import traceback


log = get_logger("check_mailing_status")


def check_mailing_status(task_id=None, db=None):

    task_logs(task_id, "info", "Tâche check_mailing_status démarrée")

    log.info("=== CHECK MAILING STATUS : DÉBUT ===")

    # Toujours utiliser une DB locale pour éviter les locks du scheduler
    own_db = False
    if db is None:
        db = open_db()
        own_db = True

    cur = db.cursor()

    try:
        # --------------------------------------------------------
        # 1 - DIAGNOSTIC : lecture complète settings
        # --------------------------------------------------------
        log.debug("[DIAG] Lecture complète de la table settings…")

        safe_execute(cur, "SELECT * FROM settings")
        full_settings = cur.fetchone()

        log.debug("[DIAG] Contenu brut de settings : %s", dict(full_settings) if full_settings else "Aucun")

        # --------------------------------------------------------
        # 2 - Lecture de mailing_enabled
        # --------------------------------------------------------
        log.debug("Lecture du paramètre settings.mailing_enabled…")

        safe_execute(cur, "SELECT mailing_enabled FROM settings WHERE id = 1")
        row = cur.fetchone()

        raw_value = row["mailing_enabled"] if row else None
        mailing_enabled = (raw_value == 1)

        log.debug(
            "Valeur récupérée → raw = %s | interprété = %s",
            raw_value,
            mailing_enabled
        )

        # --------------------------------------------------------
        # 3 - Tâches dépendantes de mailing
        # --------------------------------------------------------
        mailing_tasks = ["send_expiration_emails", "send_mail_campaigns"]

        log.debug("Tâches dépendantes à mettre à jour : %s", mailing_tasks)

        updated = []

        for name in mailing_tasks:
            log.debug("[TASK] Lecture état de la tâche '%s'…", name)

            safe_execute(cur, "SELECT id, enabled FROM tasks WHERE name=?", (name,))
            trow = cur.fetchone()

            if not trow:
                log.warning("Tâche '%s' introuvable dans la table tasks.", name)
                continue

            old = trow["enabled"]
            new = 1 if mailing_enabled else 0

            log.debug(
                "[TASK] Mise à jour %s : old_enabled=%s → new_enabled=%s",
                name, old, new
            )

            safe_execute(cur, "UPDATE tasks SET enabled=? WHERE id=?", (new, trow["id"]))

            updated.append({
                "task": name,
                "old": old,
                "new": new
            })

        db.commit()

        # --------------------------------------------------------
        # 4 - Résultat
        # --------------------------------------------------------
        log.info("✔ Mailing %s", "activé" if mailing_enabled else "désactivé")
        log.debug("Tâches affectées : %s", updated)

        task_logs(task_id, "success", f"Mailing {'activé' if mailing_enabled else 'désactivé'}")

        log.info("=== CHECK MAILING STATUS : FIN ===")

    except Exception as e:
        tb = traceback.format_exc()

        log.error("❌ Exception pendant check_mailing_status : %s", e)
        log.error(tb)

        task_logs(task_id, "error", f"Erreur check_mailing_status : {e}")

    finally:
        if own_db:
            db.close()



def run(task_id=None, db=None):
    """
    Point d'entrée scheduler.
    ignore la DB du scheduler -> crée sa propre connexion
    """
    check_mailing_status(task_id)
    return "OK"


if __name__ == "__main__":
    check_mailing_status()
