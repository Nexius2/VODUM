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
def compute_status(expiration_date, today, preavis_days, reminder_days):
    """
    Calcul du statut VODUM (contractuel uniquement).
    """
    log.debug(f"[STATUS DEBUG] expiration_date='{expiration_date}'")

    # 1️⃣ Pas de date → pas de changement (on ne force pas "active")
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
        # Chargement des délais depuis SETTINGS (source unique)
        # ----------------------------------------------------
        settings = db.query_one(
            "SELECT preavis_days, reminder_days FROM settings WHERE id = 1"
        )

        if not settings:
            raise RuntimeError("Settings manquants (id=1)")

        preavis_days = int(settings["preavis_days"])
        reminder_days = int(settings["reminder_days"])

        log.info(
            f"Paramètres chargés → preavis={preavis_days}j | reminder={reminder_days}j"
        )

        # ----------------------------------------------------
        # Utilisateurs
        # ----------------------------------------------------
        users = db.query(
            "SELECT id, status, expiration_date FROM vodum_users"
        )

        log.info(f"{len(users)} utilisateurs chargés")

        updated = 0

        # ----------------------------------------------------
        # Boucle principale
        # ----------------------------------------------------
        for user in users:
            uid = user["id"]
            old_status = user["status"]
            expiration_date = user["expiration_date"]

            # ✅ correction : on appelle compute_status (existante) + on passe today
            new_status = compute_status(
                expiration_date,
                today,
                preavis_days,
                reminder_days,
            )

            # compute_status retourne None si on ne change rien
            if new_status is None:
                continue

            if new_status != old_status:
                log.info(f"[USER {uid}] statut {old_status} → {new_status}")

                db.execute(
                    """
                    UPDATE vodum_users
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
