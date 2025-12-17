#!/usr/bin/env python3
"""
update_user_status.py — VODUM CONTRACT STATUS (DBManager)
--------------------------------------------------------
✓ Statut purement contractuel
✓ Aucune dépendance Plex / Jellyfin
✓ DBManager (connexion unique, sérialisée)
✓ ZÉRO open_db / close / commit / rollback manuel
✓ finally propre (log uniquement)
✓ Compatible tasks_engine / scheduler
"""

from datetime import datetime, date

from tasks_engine import task_logs
from logging_utils import get_logger


log = get_logger("update_user_status")


# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
def get_days_before(db, tpl_type, default_value):
    """
    Récupère days_before depuis email_templates.
    Fallback propre si absent ou invalide.
    """
    try:
        row = db.query_one(
            "SELECT days_before FROM email_templates WHERE type=?",
            (tpl_type,),
        )

        val = row["days_before"] if row else None
        log.debug(f"Template '{tpl_type}' → days_before = {val}")

        return int(val) if val is not None else default_value

    except Exception as e:
        log.error(f"Erreur get_days_before({tpl_type}): {e}", exc_info=True)
        return default_value


def compute_status(expiration_date, today, preavis_days, reminder_days):
    """
    Calcul du statut VODUM (contractuel uniquement).
    """
    log.debug(f"[STATUS DEBUG] expiration_date='{expiration_date}'")

    # 1️⃣ Pas de date → actif
    if not expiration_date:
        return None

    # 2️⃣ Parsing date
    try:
        exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
    except Exception:
        # Donnée invalide = actif (on ne bloque pas)
        log.warning(f"Date expiration invalide ignorée: {expiration_date}")
        return "active"

    # 3️⃣ Expiré
    if exp_date <= today:
        return "expired"

    delta = (exp_date - today).days

    # 4️⃣ Reminder
    if delta <= reminder_days:
        return "reminder"

    # 5️⃣ Préavis
    if delta <= preavis_days:
        return "pre_expired"

    # 6️⃣ Sinon actif
    return "active"


# ----------------------------------------------------
# Tâche principale
# ----------------------------------------------------
def run(task_id: int, db):
    """
    Mise à jour du statut contractuel des utilisateurs
    (active / pre_expired / reminder / expired)
    """

    task_logs(task_id, "info", "Tâche update_user_status démarrée")
    log.info("=== UPDATE USER STATUS : START ===")

    today = date.today()

    try:
        # ----------------------------------------------------
        # Paramètres mail (préavis / relance)
        # ----------------------------------------------------
        preavis_days = get_days_before(db, "preavis", 30)
        reminder_days = get_days_before(db, "relance", 7)

        log.info(
            f"Paramètres chargés → preavis={preavis_days}j | reminder={reminder_days}j"
        )

        # ----------------------------------------------------
        # Utilisateurs
        # ----------------------------------------------------
        users = db.query(
            "SELECT id, status, expiration_date FROM users"
        )

        log.info(f"{len(users)} utilisateurs chargés")

        updated = 0

        # ----------------------------------------------------
        # Boucle principale
        # ----------------------------------------------------
        for user in users:
            uid = user["id"]
            old_status = user["status"]

            new_status = compute_status(
                user["expiration_date"],
                today,
                preavis_days,
                reminder_days,
            )

            if new_status != old_status:
                log.info(
                    f"[USER {uid}] statut {old_status} → {new_status}"
                )

                db.execute(
                    """
                    UPDATE users
                    SET status = ?,
                        last_status = ?,
                        status_changed_at = datetime('now')
                    WHERE id = ?
                    """,
                    (new_status, old_status, uid),
                )

                updated += 1

        # ----------------------------------------------------
        # Fin normale
        # ----------------------------------------------------
        msg = f"{updated} utilisateur(s) mis à jour"
        log.info(msg)

        if updated > 0:
            task_logs(task_id, "success", msg)
        else:
            task_logs(task_id, "info", msg)

    except Exception as e:
        log.error("Erreur globale update_user_status", exc_info=True)
        task_logs(task_id, "error", f"Erreur update_user_status: {e}")
        raise

    finally:
        log.info("=== UPDATE USER STATUS : END ===")
