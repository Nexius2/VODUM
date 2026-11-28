#!/usr/bin/env python3
from datetime import datetime, date, timedelta

from tasks_engine import task_logs
from logging_utils import get_logger, is_debug_mode_enabled
from core.expiration_rules import only_pending_plex_accounts, parse_expiration_date, is_expired, load_expiration_accounts, user_is_exempt


log = get_logger("update_user_status")


# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _user_has_pending_plex_invite(db, vodum_user_id: int) -> bool:
    return only_pending_plex_accounts(db, vodum_user_id)


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
    if is_debug_mode_enabled():
        log.debug(f"[STATUS DEBUG] expiration_date='{expiration_date}'")

    # 1️⃣ Pas de date → pas de changement
    if not expiration_date:
        return None

    # 2️⃣ Parsing date
    try:
        exp_date = parse_expiration_date(expiration_date)
        if exp_date is None:
            return "active"
    except Exception:
        log.warning(f"Date expiration invalide ignorée: {expiration_date}")
        return "active"

    # 3️⃣ Expiré
    if is_expired(exp_date, today):
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

    task_logs(task_id, "start", "Task update_user_status started")
    log.debug("=== UPDATE USER STATUS : START ===")

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

        log.debug(
            f"Settings loaded → preavis={preavis_days}j | reminder={reminder_days}j | default_subscription_days={default_subscription_days}j"
        )

        # ----------------------------------------------------
        # Utilisateurs
        # ----------------------------------------------------
        users = db.query(
            """
            SELECT
                u.id,
                u.status,
                u.expiration_date,
                u.expiration_date_override,
                COALESCE(st.is_lifetime, 0) AS subscription_is_lifetime
            FROM vodum_users u
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            """
        )

        log.debug(f"{len(users)} users loaded")

        updated = 0

        # ----------------------------------------------------
        # Utilisateurs orphelins : pas d'expiration + aucun serveur associé => expired
        # ----------------------------------------------------
        orphans = db.query(
            """
            SELECT u.id, u.status
            FROM vodum_users u
            LEFT JOIN subscription_templates st ON st.id = u.subscription_template_id
            LEFT JOIN media_users mu ON mu.vodum_user_id = u.id
            WHERE (u.expiration_date IS NULL OR u.expiration_date = '')
              AND COALESCE(st.is_lifetime, 0) = 0
              AND COALESCE(u.expiration_date_override, 0) = 0
            GROUP BY u.id
            HAVING COUNT(mu.id) = 0
            """
        )

        orphan_updates = 0
        for o in orphans:
            uid = o["id"]
            old_status = o["status"] or "active"

            if old_status in ("expired", "suspended", "unfriended", "disabled", "removed"):
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
            subscription_is_lifetime = int(user["subscription_is_lifetime"] or 0) == 1
            expiration_override_enabled = user_is_exempt(user, load_expiration_accounts(db, uid))
            expiration_date = user["expiration_date"]

            # Statuts manuels / administratifs :
            # ne jamais les écraser automatiquement avec le calcul de date.
            if old_status in ("suspended", "unfriended", "disabled", "removed"):
                continue

            # ✅ Cas spécial : invitation Plex encore non acceptée
            if not expiration_override_enabled and _user_has_pending_plex_invite(db, uid):
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

            # ----------------------------------------------------
            # Automatic expiration override (+1 year)
            # ----------------------------------------------------

            if expiration_override_enabled:
                try:
                    exp_date = parse_expiration_date(expiration_date) or today

                    warning_date = exp_date - timedelta(days=preavis_days)

                    if today >= warning_date:
                        new_expiration_date = exp_date

                        while new_expiration_date - timedelta(days=preavis_days) <= today:
                            new_expiration_date = new_expiration_date + timedelta(days=365)

                        new_expiration = new_expiration_date.isoformat()

                        db.execute(
                            """
                            UPDATE vodum_users
                            SET expiration_date = ?,
                                status = 'active',
                                last_status = CASE
                                    WHEN status != 'active' THEN status
                                    ELSE last_status
                                END,
                                status_changed_at = CASE
                                    WHEN status != 'active' THEN datetime('now')
                                    ELSE status_changed_at
                                END
                            WHERE id = ?
                            """,
                            (new_expiration, uid),
                        )

                        source = "lifetime subscription" if subscription_is_lifetime else "expiration override"

                        log.info(
                            f"[USER {uid}] {source} applied "
                            f"{expiration_date or 'empty'} -> {new_expiration}"
                        )

                        updated += 1
                        continue

                except Exception:
                    log.warning(
                        f"[USER {uid}] invalid expiration date "
                        f"for override: {expiration_date}"
                    )

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
        if updated > 0:
            log.info(msg)
        else:
            log.debug(msg)

        if updated > 0:
            task_logs(task_id, "success", msg)
        else:
            task_logs(task_id, "debug", msg)

    except Exception as e:
        log.error("Global error in update_user_status", exc_info=True)
        task_logs(task_id, "error", f"Erreur update_user_status: {e}")
        raise

    finally:
        log.info("=== UPDATE USER STATUS : END ===")