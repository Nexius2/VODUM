# Auto-split from app.py (keep URLs/endpoints intact)
import json

import requests
from flask import request, redirect, url_for, flash, jsonify

from logging_utils import get_logger
from tasks_engine import enable_and_run_task_by_name

from web.helpers import get_db
from core.plex_rate_limit import install_plex_rate_limit
from core.providers.jellyfin_users import jellyfin_list_users
from .users_list import merge_vodum_users
from core.media_jobs import insert_plex_media_job, insert_jellyfin_media_job


task_logger = get_logger("tasks_ui")

def _get_preferred_plex_media_user_id(db, user_id: int, server_id: int):
    row = db.query_one(
        """
        SELECT id
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
          AND type = 'plex'
        ORDER BY
            CASE WHEN LOWER(COALESCE(role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            id ASC
        LIMIT 1
        """,
        (user_id, server_id),
    )
    return int(row["id"]) if row and row["id"] is not None else None

def _queue_plex_share_settings_sync(db, user_id: int, server_id: int, reason: str):
    preferred_media_user_id = _get_preferred_plex_media_user_id(
        db,
        user_id,
        server_id,
    )

    dedupe_key = f"plex:sync:server={server_id}:user={user_id}:share_settings"

    payload = {
        "reason": reason,
        "preferred_media_user_id": preferred_media_user_id,
    }

    inserted = insert_plex_media_job(
        db,
        action="sync",
        vodum_user_id=user_id,
        server_id=server_id,
        library_id=None,
        dedupe_key=dedupe_key,
        payload=payload,
    )

    if inserted:
        task_logger.info(
            f"[MEDIA JOB CREATED] provider=plex action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"preferred_media_user_id={preferred_media_user_id} "
            f"reason={reason}"
        )

    try:
        enable_and_run_task_by_name("apply_plex_access_updates")
    except Exception:
        pass

    return inserted


def _force_queue_full_plex_sync_for_user(db, user_id: int, reason: str = "admin_force_resync"):
    """
    Recrée un job 'sync' complet par serveur Plex lié.

    Important :
    on passe par _insert_plex_media_job() pour annuler proprement
    les anciens jobs actifs du même user/server, au lieu de supprimer
    brutalement des jobs éventuellement en cours.
    """
    rows = db.query(
        """
        SELECT
            mu.server_id,
            mu.id AS preferred_media_user_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'plex'
          AND mu.type = 'plex'
        ORDER BY
            mu.server_id ASC,
            CASE WHEN LOWER(COALESCE(mu.role, '')) = 'owner' THEN 1 ELSE 0 END ASC,
            CASE WHEN TRIM(COALESCE(mu.accepted_at, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN TRIM(COALESCE(mu.external_user_id, '')) <> '' THEN 0 ELSE 1 END ASC,
            CASE WHEN LOWER(COALESCE(mu.role, '')) = 'unfriended' THEN 1 ELSE 0 END ASC,
            mu.id ASC
        """,
        (user_id,),
    ) or []

    queued = 0
    seen_servers = set()

    for row in rows:
        server_id = int(row["server_id"])
        if server_id in seen_servers:
            continue
        seen_servers.add(server_id)

        preferred_media_user_id = (
            int(row["preferred_media_user_id"])
            if row["preferred_media_user_id"] is not None
            else None
        )

        dedupe_key = (
            f"plex:sync:server={server_id}:"
            f"media_user={preferred_media_user_id or 'none'}:admin_force"
        )

        payload = {
            "reason": reason,
            "forced_by_admin": True,
            "preferred_media_user_id": preferred_media_user_id,
        }

        inserted = insert_plex_media_job(
            db,
            action="sync",
            vodum_user_id=user_id,
            server_id=server_id,
            library_id=None,
            dedupe_key=dedupe_key,
            payload=payload,
        )

        if inserted:
            queued += 1

        task_logger.info(
            f"[MEDIA JOB CREATED] provider=plex action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"preferred_media_user_id={preferred_media_user_id} "
            f"inserted={inserted} reason=admin_force"
        )

    return queued

def _force_queue_full_jellyfin_sync_for_user(db, user_id: int, reason: str = "admin_force_resync"):
    rows = db.query(
        """
        SELECT DISTINCT
            mu.server_id
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND s.type = 'jellyfin'
          AND mu.type = 'jellyfin'
        ORDER BY mu.server_id ASC
        """,
        (user_id,),
    ) or []

    queued = 0

    for row in rows:
        server_id = int(row["server_id"])

        dedupe_key = f"jellyfin:sync:server={server_id}:user={user_id}:admin_force"

        payload = {
            "reason": reason,
            "forced_by_admin": True,
        }

        inserted = insert_jellyfin_media_job(
            db,
            action="sync",
            vodum_user_id=user_id,
            server_id=server_id,
            library_id=None,
            dedupe_key=dedupe_key,
            payload=payload,
        )

        if inserted:
            queued += 1

        task_logger.info(
            f"[MEDIA JOB CREATED] provider=jellyfin action=sync "
            f"user_id={user_id} server_id={server_id} "
            f"inserted={inserted} reason=admin_force"
        )

    return queued

def _json_dict_or_empty(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _pick_server_base_url(server_row):
    for key in ("url", "local_url", "public_url"):
        value = str(server_row.get(key) or "").strip().rstrip("/")
        if value:
            return value
    return ""


def _pick_server_token(server_row):
    return str(server_row.get("token") or "").strip()


def _match_pending_invite(inv, *, email: str, username: str):
    candidates = [
        getattr(inv, "email", None),
        getattr(inv, "user", None),
        getattr(inv, "username", None),
        getattr(inv, "title", None),
    ]
    for val in candidates:
        sval = str(val or "").strip().lower()
        if not sval:
            continue
        if email and sval == email.lower():
            return True
        if username and sval == username.lower():
            return True
    return False


def _check_plex_media_user_presence(server_row, media_user_row):
    server_row = dict(server_row or {})
    media_user_row = dict(media_user_row or {})

    result = {
        "provider": "plex",
        "state": "unknown",               # friend / pending / missing / unknown
        "exists_on_platform": False,
        "can_return_on_sync": False,
        "detail": "",
    }

    base = _pick_server_base_url(server_row)
    token = _pick_server_token(server_row)

    if not base or not token:
        result["detail"] = "Plex server not fully configured"
        result["can_return_on_sync"] = True
        return result

    email = str(media_user_row.get("email") or "").strip()
    username = str(media_user_row.get("username") or "").strip()
    external_user_id = str(media_user_row.get("external_user_id") or "").strip()

    details = _json_dict_or_empty(media_user_row.get("details_json"))
    invite_state = details.get("plex_invite_state") or {}
    invite_is_pending_db = bool(invite_state.get("is_pending")) if isinstance(invite_state, dict) else False

    try:
        from plexapi.server import PlexServer

        session = requests.Session()
        install_plex_rate_limit(session, base)

        plex = PlexServer(base, token, session=session)
        account = plex.myPlexAccount()

        # 1) friends actuels
        try:
            users = account.users() or []
        except Exception:
            users = []

        for u in users:
            uid = str(getattr(u, "id", "") or "").strip()
            uemail = str(getattr(u, "email", "") or "").strip().lower()
            uname = str(getattr(u, "username", "") or getattr(u, "title", "") or "").strip().lower()

            if external_user_id and uid and uid == external_user_id:
                result["state"] = "friend"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Plex friend still exists on platform"
                return result

            if email and uemail and uemail == email.lower():
                result["state"] = "friend"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Plex friend still exists on platform"
                return result

            if username and uname and uname == username.lower():
                result["state"] = "friend"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Plex friend still exists on platform"
                return result

        # 2) pending invites actuelles
        try:
            pending_fn = getattr(account, "pendingInvites", None)
            if callable(pending_fn):
                pending = pending_fn() or []
            else:
                pending = []
        except Exception:
            pending = []

        for inv in pending:
            if _match_pending_invite(inv, email=email, username=username):
                result["state"] = "pending"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Pending Plex invite still exists on platform"
                return result

        # 3) fallback DB : si on sait déjà que c'est pending en base
        if invite_is_pending_db:
            result["state"] = "pending"
            result["exists_on_platform"] = True
            result["can_return_on_sync"] = True
            result["detail"] = "Pending Plex invite flagged in database"
            return result

        result["state"] = "missing"
        result["exists_on_platform"] = False
        result["can_return_on_sync"] = False
        result["detail"] = "Plex account/invite not found on platform"
        return result

    except Exception as e:
        result["state"] = "unknown"
        result["exists_on_platform"] = False
        result["can_return_on_sync"] = True
        result["detail"] = f"Unable to verify Plex account: {e}"
        return result


def _check_jellyfin_media_user_presence(server_row, media_user_row):
    server_row = dict(server_row or {})
    media_user_row = dict(media_user_row or {})

    result = {
        "provider": "jellyfin",
        "state": "unknown",               # present / missing / unknown
        "exists_on_platform": False,
        "can_return_on_sync": False,
        "detail": "",
    }

    base = _pick_server_base_url(server_row)
    token = _pick_server_token(server_row)

    if not base or not token:
        result["detail"] = "Jellyfin server not fully configured"
        result["can_return_on_sync"] = True
        return result

    external_user_id = str(media_user_row.get("external_user_id") or "").strip()
    username = str(media_user_row.get("username") or "").strip().lower()
    email = str(media_user_row.get("email") or "").strip().lower()

    try:
        users = jellyfin_list_users(server_row) or []

        for u in users:
            uid = str(u.get("Id") or "").strip()
            uname = str(u.get("Name") or "").strip().lower()

            if external_user_id and uid and uid == external_user_id:
                result["state"] = "present"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Jellyfin user still exists on platform"
                return result

            if username and uname and uname == username:
                result["state"] = "present"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Jellyfin user still exists on platform"
                return result

            # Best-effort supplémentaire si l'email a été copié dans Name
            if email and uname and uname == email:
                result["state"] = "present"
                result["exists_on_platform"] = True
                result["can_return_on_sync"] = True
                result["detail"] = "Jellyfin user still exists on platform"
                return result

        result["state"] = "missing"
        result["exists_on_platform"] = False
        result["can_return_on_sync"] = False
        result["detail"] = "Jellyfin user not found on platform"
        return result

    except Exception as e:
        result["state"] = "unknown"
        result["exists_on_platform"] = False
        result["can_return_on_sync"] = True
        result["detail"] = f"Unable to verify Jellyfin user: {e}"
        return result


def _build_user_delete_check(db, user_id: int):
    user = db.query_one(
        """
        SELECT id, username, email
        FROM vodum_users
        WHERE id = ?
        """,
        (user_id,),
    )
    if not user:
        return None

    rows = db.query(
        """
        SELECT
            mu.id,
            mu.server_id,
            mu.external_user_id,
            mu.username,
            mu.email,
            mu.type,
            mu.role,
            mu.joined_at,
            mu.accepted_at,
            mu.details_json,

            s.name AS server_name,
            s.type AS server_type,
            s.url,
            s.local_url,
            s.public_url,
            s.token
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        ORDER BY s.type ASC, s.name ASC, mu.id ASC
        """,
        (user_id,),
    ) or []

    items = []
    linked_accounts_total = 0
    still_exists_total = 0
    pending_total = 0
    unknown_total = 0
    will_return_on_sync = False

    for row in rows:
        linked_accounts_total += 1

        row_dict = dict(row)
        server_row = row_dict
        provider = (row_dict.get("type") or row_dict.get("server_type") or "").strip().lower()

        if provider == "plex":
            live = _check_plex_media_user_presence(server_row, row_dict)
        elif provider == "jellyfin":
            live = _check_jellyfin_media_user_presence(server_row, row_dict)
        else:
            live = {
                "provider": provider or "unknown",
                "state": "unknown",
                "exists_on_platform": False,
                "can_return_on_sync": True,
                "detail": f"Unsupported provider: {provider or 'unknown'}",
            }

        if live["exists_on_platform"]:
            still_exists_total += 1
        if live["state"] == "pending":
            pending_total += 1
        if live["state"] == "unknown":
            unknown_total += 1
        if live["can_return_on_sync"]:
            will_return_on_sync = True

        items.append({
            "media_user_id": int(row["id"]),
            "provider": provider or "unknown",
            "server_name": row["server_name"] or "",
            "username": row["username"] or "",
            "email": row["email"] or "",
            "external_user_id": row["external_user_id"] or "",
            "accepted_at": row["accepted_at"] or "",
            "state": live["state"],
            "exists_on_platform": bool(live["exists_on_platform"]),
            "can_return_on_sync": bool(live["can_return_on_sync"]),
            "detail": live["detail"],
        })

    return {
        "ok": True,
        "user_id": int(user["id"]),
        "username": user["username"] or "",
        "email": user["email"] or "",
        "linked_accounts_total": linked_accounts_total,
        "still_exists_total": still_exists_total,
        "pending_total": pending_total,
        "unknown_total": unknown_total,
        "will_return_on_sync": will_return_on_sync,
        "items": items,
    }


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
    @app.route("/users/<int:user_id>/plex/share/filter", methods=["POST"])
    def update_plex_share_filter(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        value = (form.get("value") or "").strip()

        allowed_fields = {"filterMovies", "filterTelevision", "filterMusic"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))

        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = value
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        _queue_plex_share_settings_sync(
            db,
            user_id=user_id,
            server_id=server_id,
            reason=f"plex_share_filter_{field}",
        )

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

        truthy = {"1", "true", "on", "yes"}
        new_val = 1 if str(v).strip().lower() in truthy else 0

        allowed_fields = {"allowSync", "allowCameraUpload", "allowChannels"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # sécurité: s'assurer que ce media_user appartient bien au user_id + server_id
        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # load json
        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = new_val
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        _queue_plex_share_settings_sync(
            db,
            user_id=user_id,
            server_id=server_id,
            reason=f"plex_share_option_{field}",
        )

        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id, tab="access"))

    @app.route("/users/<int:user_id>/delete/check", methods=["GET"])
    def user_delete_check(user_id):
        db = get_db()

        data = _build_user_delete_check(db, user_id)
        if not data:
            return jsonify({"ok": False, "error": "user_not_found"}), 404

        return jsonify(data)


    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    def user_delete(user_id):
        db = get_db()

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
        db = get_db()

        library_id = request.form.get("library_id", type=int)
        if not library_id:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        user_row = db.query_one(
            "SELECT id, status FROM vodum_users WHERE id = ?",
            (user_id,),
        )
        if not user_row:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        if (user_row["status"] or "").strip().lower() == "expired":
            task_logger.info(
                f"[ACCESS REQUEST BLOCKED] user_id={user_id} "
                f"library_id={library_id} reason=expired_user"
            )
            flash("expired", "error")
            return redirect(url_for("user_detail", user_id=user_id, tab="access"))

        # --------------------------------------------------
        # Récup library + server (pour savoir sur quel serveur on agit)
        # --------------------------------------------------
        lib = db.query_one(
            "SELECT id, server_id, name FROM libraries WHERE id = ?",
            (library_id,),
        )
        if not lib:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        server = db.query_one(
            "SELECT id, type, name FROM servers WHERE id = ?",
            (lib["server_id"],),
        )
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # IMPORTANT : on ne doit toggler QUE les media_users
        # de CE serveur (sinon tu peux lier une lib Plex à un compte Jellyfin)
        # --------------------------------------------------
        media_users = db.query(
            """
            SELECT id
            FROM media_users
            WHERE vodum_user_id = ?
              AND server_id = ?
            """,
            (user_id, lib["server_id"]),
        )
        if not media_users:
            flash("no_media_accounts_for_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        media_user_ids = [mu["id"] for mu in media_users]
        placeholders = ",".join("?" * len(media_user_ids))

        # --------------------------------------------------
        # Vérifier si l'accès existe déjà
        # --------------------------------------------------
        exists = db.query_one(
            f"""
            SELECT 1
            FROM media_user_libraries
            WHERE library_id = ?
              AND media_user_id IN ({placeholders})
            LIMIT 1
            """,
            (library_id, *media_user_ids),
        )

        removed = False

        # --------------------------------------------------
        # TOGGLE en DB
        # --------------------------------------------------
        if exists:
            db.execute(
                f"""
                DELETE FROM media_user_libraries
                WHERE library_id = ?
                  AND media_user_id IN ({placeholders})
                """,
                (library_id, *media_user_ids),
            )
            removed = True
            flash("library_access_removed", "success")
        else:
            for mid in media_user_ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (mid, library_id),
                )
            flash("library_access_added", "success")

        # --------------------------------------------------
        # Création d'un job pour apply_plex_access_updates
        # -> uniquement si serveur Plex (pour Jellyfin on fera plus tard)
        # --------------------------------------------------
        if server["type"] == "plex":
            preferred_media_user_id = _get_preferred_plex_media_user_id(
                db,
                user_id,
                lib["server_id"],
            )

            # Combien de libs restent pour CE user sur CE serveur ?
            remaining = db.query_one(
                f"""
                SELECT COUNT(DISTINCT mul.library_id) AS c
                FROM media_user_libraries mul
                JOIN libraries l ON l.id = mul.library_id
                WHERE mul.media_user_id IN ({placeholders})
                  AND l.server_id = ?
                """,
                (*media_user_ids, lib["server_id"]),
            )
            remaining_count = int(remaining["c"] or 0)

            # --------------------------------------------------
            # Choix de l'action:
            # - Ajout d'une bibliothèque => grant (équivalent plex_api_share.py --add --libraries X)
            # - Retrait d'une bibliothèque => sync (réapplique la liste DB), ou revoke si plus rien
            # --------------------------------------------------
            if removed and remaining_count == 0:
                action = "revoke"
                job_library_id = None
                dedupe_key = f"plex:revoke:server={lib['server_id']}:user={user_id}"
            elif removed:
                action = "sync"
                job_library_id = None
                dedupe_key = f"plex:sync:server={lib['server_id']}:user={user_id}"
            else:
                action = "grant"
                job_library_id = library_id
                dedupe_key = f"plex:grant:server={lib['server_id']}:user={user_id}:lib={library_id}"

            payload = {
                "reason": "library_toggle",
                "library_id": library_id,
                "library_name": lib["name"],
                "removed": removed,
                "remaining_count": remaining_count,
                "preferred_media_user_id": preferred_media_user_id,
            }

            inserted = insert_plex_media_job(
                db,
                action=action,
                vodum_user_id=user_id,
                server_id=lib["server_id"],
                library_id=job_library_id,
                dedupe_key=dedupe_key,
                payload=payload,
            )

            if inserted:
                task_logger.info(
                    f"[MEDIA JOB CREATED] provider=plex action={action} "
                    f"user_id={user_id} server_id={lib['server_id']} "
                    f"library_id={job_library_id} preferred_media_user_id={preferred_media_user_id}"
                )

            # Activer + queue la tâche apply_plex_access_updates
            try:
                enable_and_run_task_by_name("apply_plex_access_updates")
            except Exception:
                # pas bloquant si enqueue échoue, le scheduler le prendra plus tard
                pass

        elif server["type"] == "jellyfin":
            action = "sync"
            job_library_id = None
            dedupe_key = f"jellyfin:sync:server={lib['server_id']}:user={user_id}"

            payload = {
                "reason": "library_toggle",
                "toggled_library_id": library_id,
                "toggled_library_name": lib["name"],
                "removed": removed,
            }

            inserted = insert_jellyfin_media_job(
                db,
                action=action,
                vodum_user_id=user_id,
                server_id=lib["server_id"],
                library_id=job_library_id,
                dedupe_key=dedupe_key,
                payload=payload,
            )

            if inserted:
                task_logger.info(
                    f"[MEDIA JOB CREATED] provider=jellyfin action={action} "
                    f"user_id={user_id} server_id={lib['server_id']} "
                    f"library_id={job_library_id}"
                )

            try:
                enable_and_run_task_by_name("apply_jellyfin_access_updates")
            except Exception:
                pass







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

        queued_plex = _force_queue_full_plex_sync_for_user(
            db,
            user_id=user_id,
            reason="admin_force_resync",
        )

        queued_jellyfin = _force_queue_full_jellyfin_sync_for_user(
            db,
            user_id=user_id,
            reason="admin_force_resync",
        )

        if queued_plex:
            try:
                enable_and_run_task_by_name("apply_plex_access_updates")
            except Exception:
                pass

        if queued_jellyfin:
            try:
                enable_and_run_task_by_name("apply_jellyfin_access_updates")
            except Exception:
                pass

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


