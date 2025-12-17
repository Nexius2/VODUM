from flask import Blueprint, request, jsonify
from datetime import date, timedelta

from db_manager import DBManager
from logging_utils import get_logger

log = get_logger("api.subscriptions")

subscriptions_api = Blueprint("subscriptions_api", __name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def update_user_expiration(user_id, new_expiration_date, reason="manual"):
    """
    Met à jour la date d'expiration d'un utilisateur.
    Reset les templates envoyés uniquement si on entre dans un nouveau cycle.
    """
    db = DBManager()

    row = db.query_one(
        "SELECT expiration_date FROM users WHERE id = ?",
        (user_id,)
    )

    if not row:
        return False, "Utilisateur introuvable"

    try:
        old_exp = date.fromisoformat(row["expiration_date"])
    except Exception:
        old_exp = date.today()

    new_exp = date.fromisoformat(new_expiration_date)

    # Mise à jour de la date
    db.execute(
        """
        UPDATE users
        SET expiration_date = ?
        WHERE id = ?
        """,
        (new_expiration_date, user_id)
    )

    # 🔁 Nouveau cycle → reset sent_emails
    if new_exp > old_exp:
        db.execute(
            """
            DELETE FROM sent_emails
            WHERE user_id = ?
              AND expiration_date = ?
            """,
            (user_id, old_exp)
        )

        log.info(
            f"[USER #{user_id}] Renouvellement détecté "
            f"({old_exp} → {new_exp}) | reset sent_emails"
        )

    return True, "Expiration mise à jour"


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

@subscriptions_api.route("/api/users/<int:user_id>/expiration", methods=["POST"])
def api_update_user_expiration(user_id):
    data = request.get_json(silent=True) or {}

    new_exp = data.get("expiration_date")
    reason = data.get("reason", "api")

    if not new_exp:
        return jsonify({"error": "expiration_date manquante"}), 400

    try:
        date.fromisoformat(new_exp)
    except ValueError:
        return jsonify({"error": "Format de date invalide (YYYY-MM-DD)"}), 400

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

    if not isinstance(days, int) or days <= 0:
        return jsonify({"error": "days doit être un entier > 0"}), 400

    db = DBManager()

    users = db.query(
        """
        SELECT DISTINCT u.id, u.expiration_date
        FROM users u
        JOIN user_servers us ON us.user_id = u.id
        WHERE us.server_id = ?
        """,
        (server_id,)
    )

    updated = 0

    for u in users:
        try:
            old_exp = date.fromisoformat(u["expiration_date"])
        except Exception:
            old_exp = date.today()

        new_exp = old_exp + timedelta(days=days)

        ok, _ = update_user_expiration(
            u["id"],
            new_exp.isoformat(),
            reason=f"gift_{days}_days"
        )

        if ok:
            updated += 1

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
    reason = data.get("reason") or "manual_gift"
    server_id = data.get("server_id")

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

    db = DBManager()

    # --------------------------------------------------
    # Sélection des utilisateurs
    # --------------------------------------------------
    if target_type == "all":
        users = db.query(
            """
            SELECT id, expiration_date
            FROM users
            WHERE status IN ('active', 'pre_expired', 'reminder')
            """
        )

    elif target_type == "server":
        if not server_id:
            return jsonify({"error": "server_id required"}), 400

        users = db.query(
            """
            SELECT u.id, u.expiration_date
            FROM users u
            JOIN user_servers us ON us.user_id = u.id
            WHERE us.server_id = ?
              AND u.status IN ('active', 'pre_expired', 'reminder')
            """,
            (server_id,)
        )

    else:
        return jsonify({"error": "invalid target_type"}), 400

    # --------------------------------------------------
    # Mise à jour
    # --------------------------------------------------
    updated = 0

    for u in users:
        try:
            current_exp = date.fromisoformat(u["expiration_date"])
        except Exception:
            current_exp = date.today()

        new_exp = (current_exp + timedelta(days=days)).isoformat()

        update_user_expiration(
            u["id"],
            new_exp,
            reason=reason
        )
        updated += 1

    return jsonify({
        "status": "ok",
        "users_updated": updated,
        "days_added": days,
        "target": target_type,
        "server_id": server_id
    }), 200
