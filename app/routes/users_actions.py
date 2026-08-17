# Auto-split from app.py (keep URLs/endpoints intact)
from flask import request, redirect, url_for, flash, jsonify

from logging_utils import get_logger
from tasks_engine import enable_and_run_task_by_name

from web.helpers import get_db
from core.user_merge import merge_vodum_users
from core.user_sync_jobs import (
    force_queue_full_jellyfin_sync_for_user,
    force_queue_full_plex_sync_for_user,
)
from core.provider_presence import (
    build_user_delete_check,
    delete_removed_media_account,
    get_user_deletion_protection,
)
from core.user_library_access import toggle_user_library_access
from core.user_plex_options import update_single_plex_share_option


task_logger = get_logger("tasks_ui")

def _delete_vodum_user_everywhere(db, user_id: int) -> bool:
    """
    Suppression LOCALE uniquement.
    Si le compte existe encore sur une plateforme active,
    un prochain sync peut le recréer.
    """
    with db._lock:
        cur = db.conn.cursor()
        try:
            cur.execute(
                "SELECT id FROM vodum_users WHERE id = ?",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False

            # Tables sans FK utile / nettoyage manuel
            cur.execute(
                "DELETE FROM stream_policies WHERE scope_type = 'user' AND scope_id = ?",
                (user_id,),
            )
            cur.execute(
                "DELETE FROM subscription_gift_run_users WHERE vodum_user_id = ?",
                (user_id,),
            )
            cur.execute(
                "DELETE FROM stream_enforcement_state WHERE vodum_user_id = ?",
                (user_id,),
            )
            cur.execute(
                "DELETE FROM stream_enforcements WHERE vodum_user_id = ?",
                (user_id,),
            )

            # media_users doit être supprimé avant vodum_users
            cur.execute(
                "DELETE FROM media_users WHERE vodum_user_id = ?",
                (user_id,),
            )

            cur.execute(
                "DELETE FROM vodum_users WHERE id = ?",
                (user_id,),
            )

            db.conn.commit()
            return True
        except Exception:
            db.conn.rollback()
            raise
        finally:
            cur.close()

def register(app):
    @app.route("/users/<int:user_id>/media-accounts/<int:media_user_id>/delete-removed", methods=["POST"])
    def delete_removed_provider_account(user_id, media_user_id):
        db = get_db()
        result = delete_removed_media_account(db, user_id, media_user_id)
        if result.get("deleted"):
            task_logger.warning(
                "[MEDIA ACCOUNT DELETE] user_id=%s media_user_id=%s provider=%s",
                user_id,
                media_user_id,
                result.get("provider"),
            )
            flash("provider_removed_deleted_local", "success")
        else:
            flash(result.get("reason") or "delete_user_failed", "error")
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))

    @app.route("/users/<int:user_id>/plex/share/filter", methods=["POST"])
    def update_plex_share_filter(user_id):
        db = get_db()
        form = request.form
        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        value = (form.get("value") or "").strip()
        result = update_single_plex_share_option(
            db,
            vodum_user_id=user_id,
            server_id=server_id,
            media_user_id=media_user_id,
            field=field,
            value=value,
            option_type="filter",
            wake_task=enable_and_run_task_by_name,
        )
        if not result["ok"]:
            flash(result["reason"], "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))
        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))



    @app.route("/users/<int:user_id>/plex/share/toggle", methods=["POST"])
    def toggle_plex_share_option(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        vals = form.getlist("value")
        v = vals[-1] if vals else "0"

        result = update_single_plex_share_option(
            db,
            vodum_user_id=user_id,
            server_id=server_id,
            media_user_id=media_user_id,
            field=field,
            value=v,
            option_type="toggle",
            wake_task=enable_and_run_task_by_name,
        )
        if not result["ok"]:
            flash(result["reason"], "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))
        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))

    @app.route("/users/<int:user_id>/delete/check", methods=["GET"])
    def user_delete_check(user_id):
        db = get_db()

        data = build_user_delete_check(db, user_id)
        if not data:
            return jsonify({"ok": False, "error": "user_not_found"}), 404

        return jsonify(data)


    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    def user_delete(user_id):
        db = get_db()

        protection = get_user_deletion_protection(db, user_id)
        if not protection.get("can_delete", True):
            flash(protection.get("blocked_reason") or "delete_user_failed", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="general"))

        user = db.query_one(
            "SELECT id, username, email FROM vodum_users WHERE id = ?",
            (user_id,),
        )
        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list", tab="users"))

        try:
            deleted = _delete_vodum_user_everywhere(db, user_id)
            if not deleted:
                flash("user_not_found", "error")
                return redirect(url_for("users_list", tab="users"))

            task_logger.info(
                f"[USER DELETE] user_id={user_id} username={user['username']} email={user['email']}"
            )
            flash("user_deleted", "success")
            return redirect(url_for("users_list", tab="users"))
        except Exception as e:
            task_logger.error(f"[USER DELETE] error user_id={user_id}: {e}", exc_info=True)
            flash("delete_user_failed", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="general"))

    @app.route("/users/<int:user_id>/merge", methods=["POST"])
    def user_merge(user_id):
        db = get_db()

        other_id = request.form.get("other_id", type=int)
        if not other_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        if other_id == user_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            merge_vodum_users(db, master_id=user_id, other_id=other_id)
            flash("user_merged", "success")
        except Exception as e:
            task_logger.error(f"[MERGE] error master={user_id} other={other_id}: {e}", exc_info=True)
            flash("merge_failed", "error")

        return redirect(url_for("user_detail", user_id=user_id))






    @app.route("/users/<int:user_id>/toggle_library", methods=["POST"])
    def user_toggle_library(user_id):
        library_id = request.form.get("library_id", type=int)
        if not library_id:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        result = toggle_user_library_access(
            get_db(),
            user_id=user_id,
            library_id=library_id,
            wake_task=enable_and_run_task_by_name,
            logger=task_logger,
        )
        flash(
            result.get("message") if result["ok"] else result["reason"],
            "success" if result["ok"] else "error",
        )
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))
    @app.route("/users/<int:user_id>/force_resync_access", methods=["POST"])
    def force_resync_access(user_id):
        db = get_db()

        user_row = db.query_one(
            "SELECT id, username FROM vodum_users WHERE id = ?",
            (user_id,),
        )
        if not user_row:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))

        media_count_row = db.query_one(
            """
            SELECT
                COUNT(DISTINCT CASE WHEN mu.type = 'plex' AND s.type = 'plex' THEN mu.server_id END) AS plex_count,
                COUNT(DISTINCT CASE WHEN mu.type = 'jellyfin' AND s.type = 'jellyfin' THEN mu.server_id END) AS jellyfin_count
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
            """,
            (user_id,),
        )

        plex_server_count = int(media_count_row["plex_count"] or 0) if media_count_row else 0
        jellyfin_server_count = int(media_count_row["jellyfin_count"] or 0) if media_count_row else 0

        if plex_server_count == 0 and jellyfin_server_count == 0:
            flash("no_media_accounts_for_user", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))

        queued_plex = force_queue_full_plex_sync_for_user(
            db,
            user_id=user_id,
            reason="admin_force_resync",
        )

        queued_jellyfin = force_queue_full_jellyfin_sync_for_user(
            db,
            user_id=user_id,
            reason="admin_force_resync",
        )

        if queued_plex:
            try:
                enable_and_run_task_by_name("apply_plex_access_updates")
            except Exception:
                task_logger.exception(
                    "Forced Plex resync jobs persisted but worker startup failed | user_id=%s | jobs=%s",
                    user_id,
                    queued_plex,
                )

        if queued_jellyfin:
            try:
                enable_and_run_task_by_name("apply_jellyfin_access_updates")
            except Exception:
                task_logger.exception(
                    "Forced Jellyfin resync jobs persisted but worker startup failed | user_id=%s | jobs=%s",
                    user_id,
                    queued_jellyfin,
                )

        queued = queued_plex + queued_jellyfin

        task_logger.warning(
            f"[ACCESS REPAIR REQUEST] user_id={user_id} "
            f"plex_servers={plex_server_count} jellyfin_servers={jellyfin_server_count} "
            f"queued_sync_jobs={queued}"
        )

        flash("task_run_success", "success")
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))


    # -----------------------------
    # SERVEURS & BIBLIO
    # -----------------------------
