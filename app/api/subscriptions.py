from flask import Blueprint, request, jsonify
from datetime import date, timedelta
import os
import json

from db_manager import DBManager
from logging_utils import get_logger
from tasks.update_user_status import compute_status
from tasks_engine import run_task_by_name
from communications_engine import select_comm_template_for_user, schedule_template_notification

log = get_logger("api.subscriptions")

subscriptions_api = Blueprint("subscriptions_api", __name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _remove_expired_subscription_policy_for_user(db, user_id: int) -> int:
    """
    Supprime toutes les stream_policies (scope=user) dont le rule_value_json contient system_tag=expired_subscription
    pour ce user.
    Retourne le nombre de policies supprimées.
    """
    rows = db.query(
        """
        SELECT id, rule_value_json
        FROM stream_policies
        WHERE scope_type = 'user' AND scope_id = ?
        """,
        (user_id,),
    ) or []

    removed = 0
    for r in rows:
        try:
            rule = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rule = {}

        if rule.get("system_tag") == "expired_subscription":
            db.execute("DELETE FROM stream_policies WHERE id = ?", (int(r["id"]),))
            removed += 1

    return removed


def update_user_expiration(user_id, new_expiration_date, reason="manual", db=None):
    """
    Met à jour la date d'expiration d'un utilisateur.
    Met aussi à jour immédiatement son statut contractuel
    (active / pre_expired / reminder / expired) sans attendre la tâche globale.
    """
    db = db or DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))

    row = db.query_one(
        "SELECT expiration_date, status FROM vodum_users WHERE id = ?",
        (user_id,)
    )

    if not row:
        return False, "User not found"

    old_status = row["status"]

    try:
        old_exp = date.fromisoformat(row["expiration_date"])
    except Exception:
        old_exp = date.today()

    new_exp = date.fromisoformat(new_expiration_date)

    # --------------------------------------------------
    # Recalcul immédiat du statut pour CE user uniquement
    # --------------------------------------------------
    new_status = None
    try:
        settings = db.query_one(
            "SELECT preavis_days, reminder_days FROM settings WHERE id = 1"
        )

        if settings:
            preavis_days = int(settings["preavis_days"])
            reminder_days = int(settings["reminder_days"])

            new_status = compute_status(
                new_expiration_date,
                date.today(),
                preavis_days,
                reminder_days,
            )
    except Exception:
        log.warning(
            f"[USER #{user_id}] Failed to recompute status during expiration update",
            exc_info=True
        )
        new_status = None

    # --------------------------------------------------
    # Mise à jour date + statut si recalcul disponible
    # --------------------------------------------------
    if new_status is not None and new_status != old_status:
        db.execute(
            """
            UPDATE vodum_users
            SET expiration_date = ?,
                status = ?,
                last_status = ?,
                status_changed_at = datetime('now')
            WHERE id = ?
            """,
            (new_expiration_date, new_status, old_status, user_id)
        )
        log.info(
            f"[USER #{user_id}] Expiration updated ({row['expiration_date']} -> {new_expiration_date}) "
            f"| status {old_status} -> {new_status} | reason={reason}"
        )
    else:
        db.execute(
            """
            UPDATE vodum_users
            SET expiration_date = ?
            WHERE id = ?
            """,
            (new_expiration_date, user_id)
        )
        log.info(
            f"[USER #{user_id}] Expiration updated ({row['expiration_date']} -> {new_expiration_date}) "
            f"| status unchanged ({old_status}) | reason={reason}"
        )

    # Si on renouvelle (date future), on supprime la policy système "expired_subscription"
    # (important si le mode a changé et que expired_subscription_manager ne tourne plus)
    if new_exp >= date.today():
        removed = _remove_expired_subscription_policy_for_user(db, int(user_id))
        if removed:
            log.info(f"[USER #{user_id}] Removed {removed} expired_subscription system policy(ies) after renewal")

    # Nouveau cycle détecté
    if new_exp > old_exp:
        log.info(f"[USER #{user_id}] Renewal detected ({old_exp} -> {new_exp}) | keeping email history")

    # --------------------------------------------------
    # Notification: expiration date changed
    # Covers:
    # - manual change from user_detail
    # - referral reward
    # - gifts
    # IMPORTANT:
    # this must NEVER block the expiration update itself
    # --------------------------------------------------
    if new_exp != old_exp:
        try:
            delta_days = (new_exp - old_exp).days

            if delta_days != 0:
                change_direction = "increase" if delta_days > 0 else "decrease"

                comm_contexts = db.query(
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

                normalized_contexts = []
                seen_contexts = set()

                for comm_ctx in comm_contexts:
                    comm_ctx = dict(comm_ctx)
                    provider = (comm_ctx.get("provider") or "").strip().lower()
                    server_id = comm_ctx.get("server_id")

                    if provider not in ("plex", "jellyfin"):
                        continue

                    key = (provider, server_id)
                    if key in seen_contexts:
                        continue
                    seen_contexts.add(key)

                    normalized_contexts.append({
                        "provider": provider,
                        "server_id": server_id,
                    })

                # Fallback important:
                # même sans media_users, on tente quand même de trouver
                # un template provider=all / plex / jellyfin
                if not normalized_contexts:
                    normalized_contexts = [
                        {"provider": "plex", "server_id": None},
                        {"provider": "jellyfin", "server_id": None},
                    ]

                selected_tpl = None
                selected_provider = None
                selected_server_id = None

                for comm_ctx in normalized_contexts:
                    provider = comm_ctx["provider"]
                    server_id = comm_ctx.get("server_id")

                    tpl = select_comm_template_for_user(
                        db=db,
                        trigger_event="expiration_change",
                        provider=provider,
                        user_id=int(user_id),
                        expiration_change_direction=change_direction,
                    )

                    if tpl:
                        selected_tpl = tpl
                        selected_provider = provider
                        selected_server_id = server_id
                        break

                if selected_tpl and selected_provider in ("plex", "jellyfin"):
                    old_exp_iso = old_exp.isoformat()
                    new_exp_iso = new_exp.isoformat()

                    reason_map = {
                        "manual": "manual",
                        "manual_update": "manual",
                        "ui_manual": "manual",
                        "gift": "gift",
                        "referral_reward": "referral",
                        "referral": "referral",
                    }

                    reason_label = reason_map.get(
                        (reason or "").strip().lower(),
                        (reason or "").strip().lower(),
                    )

                    payload = {
                        "event": "expiration_change",
                        "trigger_event": "expiration_change",
                        "reason": reason,
                        "expiration_change_reason": reason_label,
                        "old_expiration_date": old_exp_iso,
                        "new_expiration_date": new_exp_iso,
                        "expiration_date": new_exp_iso,
                        "expiration_change_days": abs(delta_days),
                        "expiration_change_signed_days": delta_days,
                        "expiration_change_direction": change_direction,
                    }

                    dedupe_key = (
                        f"expiration_change:template:{int(selected_tpl['id'])}:"
                        f"user:{int(user_id)}:old:{old_exp_iso}:new:{new_exp_iso}"
                    )

                    schedule_template_notification(
                        db=db,
                        template_id=int(selected_tpl["id"]),
                        user_id=int(user_id),
                        provider=selected_provider,
                        server_id=selected_server_id,
                        send_at_modifier=None,
                        payload=payload,
                        dedupe_key=dedupe_key,
                        max_attempts=10,
                    )

                    log.info(
                        f"[USER #{user_id}] expiration_change notification queued "
                        f"| {old_exp_iso} -> {new_exp_iso} | delta={delta_days} | reason={reason}"
                    )

                    queued_now = run_task_by_name("send_expiration_emails")
                    if queued_now:
                        log.info(
                            f"[USER #{user_id}] send_expiration_emails enqueued immediately "
                            f"after expiration change"
                        )
                    else:
                        log.warning(
                            f"[USER #{user_id}] expiration_change queued but send_expiration_emails "
                            f"could not be enqueued immediately (task disabled or cron disabled)"
                        )
                else:
                    log.info(
                        f"[USER #{user_id}] No enabled expiration_change template matched "
                        f"(direction={change_direction})"
                    )
        except Exception:
            log.error(
                f"[USER #{user_id}] expiration_change notification failed "
                f"but expiration update was kept",
                exc_info=True,
            )

    return True, "Expiration updated"


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

@subscriptions_api.route("/api/users/<int:user_id>/expiration", methods=["POST"])
def api_update_user_expiration(user_id):
    data = request.get_json(silent=True) or {}

    new_exp = data.get("expiration_date")
    reason = data.get("reason", "api")

    if not new_exp:
        return jsonify({"error": "Missing expiration_date"}), 400

    try:
        date.fromisoformat(new_exp)
    except ValueError:
        return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400

    ok, msg = update_user_expiration(user_id, new_exp, reason)

    if not ok:
        return jsonify({"error": msg}), 404

    return jsonify({
        "status": "ok",
        "message": msg,
        "user_id": user_id,
        "expiration_date": new_exp
    })


@subscriptions_api.route("/api/servers/<int:server_id>/gift", methods=["POST"])
def api_gift_time_to_server(server_id):
    data = request.get_json(silent=True) or {}
    days = data.get("days")
    target_type = "server"
    reason = (data.get("reason") or "manual gift").strip()


    if not isinstance(days, int) or days <= 0:
        return jsonify({"error": "days must be an integer > 0"}), 400

    db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))

    # ✅ users + user_servers -> vodum_users + media_users
    users = db.query(
        """
        SELECT DISTINCT vu.id, vu.expiration_date
        FROM vodum_users vu
        JOIN media_users mu ON mu.vodum_user_id = vu.id
        WHERE mu.server_id = ?
        """,
        (server_id,)
    )

    updated = 0

    for u in users:
        try:
            current_exp = date.fromisoformat(u["expiration_date"])
        except Exception:
            current_exp = date.today()

        new_exp = (current_exp + timedelta(days=days)).isoformat()

        ok, _ = update_user_expiration(
            u["id"],
            new_exp,
            reason=reason
        )

        if ok:
            updated += 1

            # ✅ Historiser le cadeau (1 ligne par user modifié)
            db.execute(
                """
                INSERT INTO subscription_gifts
                    (vodum_user_id, target_type, target_server_id, days_added, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    u["id"],
                    target_type,
                    int(server_id) if (target_type == "server" and server_id) else None,
                    days,
                    reason or None,
                )
            )


    return jsonify({
        "status": "ok",
        "server_id": server_id,
        "days_added": days,
        "users_updated": updated
    })


@subscriptions_api.route("/api/subscriptions/gift", methods=["POST"])
def api_gift_subscription():
    # --------------------------------------------------
    # Récupération des données
    # --------------------------------------------------
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()

    target_type = data.get("target_type")
    days_raw = data.get("days")
    reason = (data.get("reason") or "manual gift").strip()
    server_id = data.get("server_id")
    vodum_user_id = data.get("vodum_user_id")

    if not target_type:
        return jsonify({"error": "target_type missing"}), 400

    if not days_raw:
        return jsonify({"error": "days missing"}), 400

    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid days"}), 400

    if days <= 0:
        return jsonify({"error": "days must be > 0"}), 400

    db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))

    # --------------------------------------------------
    # Sélection des utilisateurs
    # --------------------------------------------------
    if target_type == "all":
        users = db.query(
            """
            SELECT u.id, u.expiration_date
            FROM vodum_users u
            WHERE u.status IN ('active', 'pre_expired', 'reminder')
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = u.id
              )
            """
        )

        target_server_id = None

    elif target_type == "server":
        if not server_id:
            return jsonify({"error": "server_id required"}), 400

        users = db.query(
            """
            SELECT DISTINCT vu.id, vu.expiration_date
            FROM vodum_users vu
            JOIN media_users mu ON mu.vodum_user_id = vu.id
            WHERE mu.server_id = ?
              AND vu.status IN ('active', 'pre_expired', 'reminder')
            """,
            (server_id,)
        )

        try:
            target_server_id = int(server_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid server_id"}), 400

    elif target_type == "user":
        if not vodum_user_id:
            return jsonify({"error": "vodum_user_id required"}), 400

        try:
            target_user_id = int(vodum_user_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid vodum_user_id"}), 400

        user = db.query_one(
            """
            SELECT u.id, u.expiration_date
            FROM vodum_users u
            WHERE u.id = ?
              AND u.status IN ('active', 'pre_expired', 'reminder')
              AND EXISTS (
                SELECT 1
                FROM media_users mu
                WHERE mu.vodum_user_id = u.id
              )
            """,
            (target_user_id,)
        )

        if not user:
            return jsonify({"error": "user not found"}), 404

        users = [user]
        target_server_id = None

    else:
        return jsonify({"error": "invalid target_type"}), 400

    # --------------------------------------------------
    # Historique : 1 ligne par gift (RUN)
    # --------------------------------------------------
    db.execute(
        """
        INSERT INTO subscription_gift_runs
            (target_type, target_server_id, days_added, reason, users_updated)
        VALUES (?, ?, ?, ?, 0)
        """,
        (target_type, target_server_id, days, reason or None)
    )

    # SQLite: récupère l'id du run créé
    run_id_row = db.query_one("SELECT last_insert_rowid() AS id")
    run_id = run_id_row["id"] if run_id_row else None

    if not run_id:
        return jsonify({"error": "failed to create gift run"}), 500

    # --------------------------------------------------
    # Mise à jour + détails du run (users)
    # --------------------------------------------------
    updated = 0

    for u in users:
        try:
            current_exp = date.fromisoformat(u["expiration_date"])
        except Exception:
            current_exp = date.today()

        new_exp = (current_exp + timedelta(days=days)).isoformat()

        ok, _msg = update_user_expiration(
            u["id"],
            new_exp,
            reason=reason
        )

        if ok:
            updated += 1

            # 1 ligne par user DANS LE DETAIL du run (pas dans l’historique principal)
            db.execute(
                """
                INSERT OR IGNORE INTO subscription_gift_run_users
                    (run_id, vodum_user_id)
                VALUES (?, ?)
                """,
                (run_id, u["id"])
            )

    # --------------------------------------------------
    # Update du compteur final sur le run
    # --------------------------------------------------
    db.execute(
        "UPDATE subscription_gift_runs SET users_updated = ? WHERE id = ?",
        (updated, run_id)
    )

    return jsonify({
        "status": "ok",
        "run_id": run_id,
        "users_updated": updated,
        "days_added": days,
        "target": target_type,
        "server_id": target_server_id
    }), 200


@subscriptions_api.route("/api/subscriptions/gifts/<int:run_id>", methods=["GET"])
def api_gift_history_detail(run_id):
    db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))

    run = db.query_one(
        """
        SELECT
            r.id,
            r.created_at,
            r.target_type,
            r.target_server_id,
            s.name AS server_name,
            r.days_added,
            r.reason,
            r.users_updated,
            (
                SELECT vu.username
                FROM subscription_gift_run_users ru
                JOIN vodum_users vu ON vu.id = ru.vodum_user_id
                WHERE ru.run_id = r.id
                ORDER BY vu.username COLLATE NOCASE
                LIMIT 1
            ) AS target_username
        FROM subscription_gift_runs r
        LEFT JOIN servers s ON s.id = r.target_server_id
        WHERE r.id = ?
        """,
        (run_id,)
    )

    if not run:
        return jsonify({"status": "error", "error": "not_found"}), 404

    users = db.query(
        """
        SELECT vu.id, vu.username
        FROM subscription_gift_run_users ru
        JOIN vodum_users vu ON vu.id = ru.vodum_user_id
        WHERE ru.run_id = ?
        ORDER BY vu.username COLLATE NOCASE
        """,
        (run_id,)
    )

    return jsonify({
        "status": "ok",
        "run": dict(run),
        "users": [dict(u) for u in users]
    }), 200



@subscriptions_api.route("/api/subscriptions/gifts", methods=["GET"])
def api_gift_history():
    db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
    rows = db.query(
        """
        SELECT
            r.id,
            r.created_at,
            r.target_type,
            r.target_server_id,
            s.name AS server_name,
            r.days_added,
            r.reason,
            r.users_updated,
            (
                SELECT vu.username
                FROM subscription_gift_run_users ru
                JOIN vodum_users vu ON vu.id = ru.vodum_user_id
                WHERE ru.run_id = r.id
                ORDER BY vu.username COLLATE NOCASE
                LIMIT 1
            ) AS target_username
        FROM subscription_gift_runs r
        LEFT JOIN servers s ON s.id = r.target_server_id
        ORDER BY r.created_at DESC
        LIMIT 100
        """
    )
    return jsonify({"status": "ok", "items": [dict(r) for r in rows]}), 200

