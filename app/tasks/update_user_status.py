#!/usr/bin/env python3
import json
from datetime import datetime, date, timedelta

from tasks_engine import task_logs
from logging_utils import get_logger


log = get_logger("update_user_status")


# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
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


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


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


def _compute_pending_invite_expiration(expiration_date, today, default_subscription_days):
    """
    Fait glisser l'expiration à today + default_subscription_days.
    Idempotent sur une même journée.
    """
    if int(default_subscription_days or 0) <= 0:
        return None

    target_date = today + timedelta(days=int(default_subscription_days))
    current_date = _parse_iso_date(expiration_date)

    if current_date is None or current_date < target_date:
        return target_date.isoformat()

    return None


def compute_status(expiration_date, today, preavis_days, reminder_days):
    """
    Calcul du statut VODUM
    """
    log.debug(f"[STATUS DEBUG] expiration_date='{expiration_date}'")

    # 1️⃣ Pas de date → pas de changement
    if not expiration_date:
        return None

    # 2️⃣ Parsing date
    try:
        exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
    except Exception:
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

    Cas spécial :
    - un user Plex encore invité reste en status='invited'
    - son expiration glisse chaque jour jusqu'à acceptation
    """

    task_logs(task_id, "info", "Task update_user_status started")
    log.info("=== UPDATE USER STATUS : START ===")

    today = date.today()

    try:
        # ----------------------------------------------------
        # Chargement des délais depuis SETTINGS
        # ----------------------------------------------------
        settings = db.query_one(
            """
            SELECT preavis_days, reminder_days, default_subscription_days
            FROM settings
            WHERE id = 1
            """
        )

        if not settings:
            raise RuntimeError("Missing settings (id=1)")

        preavis_days = int(settings["preavis_days"])
        reminder_days = int(settings["reminder_days"])
        default_subscription_days = int(settings["default_subscription_days"] or 0)

        log.info(
            f"Settings loaded → preavis={preavis_days}j | reminder={reminder_days}j | default_subscription_days={default_subscription_days}j"
        )

        # ----------------------------------------------------
        # Utilisateurs
        # ----------------------------------------------------
        users = db.query(
            "SELECT id, status, expiration_date FROM vodum_users"
        )

        log.info(f"{len(users)} users loaded chargés")

        updated = 0

        # ----------------------------------------------------
        # Utilisateurs orphelins : pas d'expiration + aucun serveur associé => expired
        # ----------------------------------------------------
        orphans = db.query(
            """
            SELECT u.id, u.status
            FROM vodum_users u
            LEFT JOIN media_users mu ON mu.vodum_user_id = u.id
            WHERE (u.expiration_date IS NULL OR u.expiration_date = '')
            GROUP BY u.id
            HAVING COUNT(mu.id) = 0
            """
        )

        orphan_updates = 0
        for o in orphans:
            uid = o["id"]
            old_status = o["status"] or "active"

            if old_status == "expired":
                continue

            db.execute(
                """
                UPDATE vodum_users
                SET status = ?,
                    last_status = ?,
                    status_changed_at = datetime('now')
                WHERE id = ?
                """,
                ("expired", old_status, uid),
            )
            orphan_updates += 1

        if orphan_updates:
            updated += orphan_updates
            log.info(f"{orphan_updates} orphan user(s) marked as expired")

        # ----------------------------------------------------
        # Boucle principale
        # ----------------------------------------------------
        for user in users:
            uid = user["id"]
            old_status = user["status"]
            expiration_date = user["expiration_date"]

            # ✅ Cas spécial : invitation Plex encore non acceptée
            if _user_has_pending_plex_invite(db, uid):
                new_expiration = _compute_pending_invite_expiration(
                    expiration_date=expiration_date,
                    today=today,
                    default_subscription_days=default_subscription_days,
                )

                if old_status != "invited" and new_expiration is not None:
                    db.execute(
                        """
                        UPDATE vodum_users
                        SET status = 'invited',
                            last_status = ?,
                            status_changed_at = datetime('now'),
                            expiration_date = ?
                        WHERE id = ?
                        """,
                        (old_status, new_expiration, uid),
                    )
                    log.info(f"[USER {uid}] status {old_status} → invited | expiration -> {new_expiration}")
                    updated += 1
                    continue

                if old_status != "invited":
                    db.execute(
                        """
                        UPDATE vodum_users
                        SET status = 'invited',
                            last_status = ?,
                            status_changed_at = datetime('now')
                        WHERE id = ?
                        """,
                        (old_status, uid),
                    )
                    log.info(f"[USER {uid}] status {old_status} → invited")
                    updated += 1
                    continue

                if new_expiration is not None:
                    db.execute(
                        """
                        UPDATE vodum_users
                        SET expiration_date = ?
                        WHERE id = ?
                        """,
                        (new_expiration, uid),
                    )
                    log.info(f"[USER {uid}] invited pending → expiration shifted to {new_expiration}")
                    updated += 1

                continue

            # ✅ Cas normal
            new_status = compute_status(
                expiration_date,
                today,
                preavis_days,
                reminder_days,
            )

            if new_status is None:
                continue

            if new_status != old_status:
                log.info(f"[USER {uid}] status {old_status} → {new_status}")

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

        msg = f"{updated} user(s) updated"
        log.info(msg)

        if updated > 0:
            task_logs(task_id, "success", msg)
        else:
            task_logs(task_id, "info", msg)

    except Exception as e:
        log.error("Global error in update_user_status", exc_info=True)
        task_logs(task_id, "error", f"Erreur update_user_status: {e}")
        raise

    finally:
        log.info("=== UPDATE USER STATUS : END ===")