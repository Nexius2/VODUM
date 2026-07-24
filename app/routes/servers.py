# Auto-split from app.py (keep URLs/endpoints intact)
import json
import uuid
import threading
from tasks_engine import mark_auto_enable_dirty, force_task_run
from flask import (
    render_template, request, redirect, url_for, flash, current_app,
)

from logging_utils import get_logger
from tasks_engine import enqueue_server_discovery_sequence, enable_and_run_task_by_name, ensure_tasks_enabled
from web.helpers import get_db
from web.pagination import normalize_page, pagination_links
from core.media_jobs import insert_plex_media_job
from core.user_sync_jobs import get_preferred_plex_media_user_id
from core.server_page_queries import (
    LIBRARIES_LIST_COLUMNS,
    SERVER_DETAIL_COLUMNS,
    SERVER_DETAIL_LIBRARY_COLUMNS,
    SERVERS_LIST_COLUMNS,
)
from core.library_bulk_access import (
    BulkAccessError,
    grant_libraries_to_active_users,
    remove_libraries_from_users,
)
from secret_store import encrypt_secret, encrypt_server_settings_json, keep_existing_secret
from db_manager import open_sqlite_connection

server_delete_logger = get_logger("server_delete")
logger = get_logger("servers")

SERVER_DELETE_LOCK = threading.Lock()
SERVER_DELETE_IN_PROGRESS = set()

DELETE_BATCH_SIZE = 1000
SERVER_TABLE_PAGE_SIZE = 20

def _page_arg(name: str = "page") -> int:
    return normalize_page(request.args.get(name, 1, type=int))


def _pagination(page: int, per_page: int, total_rows: int, endpoint: str, page_param: str = "page", unit_label: str | None = None, **kwargs):
    def page_url(value: int):
        args = dict(kwargs)
        args[page_param] = value
        return url_for(endpoint, **args)
    return pagination_links(page, per_page, total_rows, page_url, unit_label=unit_label)

def _delete_in_chunks(conn, sql, params=(), batch_size=DELETE_BATCH_SIZE):
    total = 0
    while True:
        cur = conn.execute(sql, tuple(params) + (batch_size,))
        deleted = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()

        if deleted <= 0:
            break

        total += deleted

        if deleted < batch_size:
            break

    return total


def _background_delete_server(app, db_path, server_id, server_name):
    delete_key = f"server:{server_id}"
    conn = None

    try:
        conn = open_sqlite_connection(
            db_path,
            check_same_thread=False,
            timeout=30,
            busy_timeout_ms=30000,
        )
        server_delete_logger.info(
            f"[server_delete] Start background deletion for server_id={server_id} name={server_name}"
        )

        # 1) Très grosses tables monitoring / jobs
        deleted_sessions = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_sessions
            WHERE rowid IN (
                SELECT rowid
                FROM media_sessions
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_events = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_events
            WHERE rowid IN (
                SELECT rowid
                FROM media_events
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_history = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_session_history
            WHERE rowid IN (
                SELECT rowid
                FROM media_session_history
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_jobs = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_jobs
            WHERE rowid IN (
                SELECT rowid
                FROM media_jobs
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 2) Tables enforcement / identities / imports
        deleted_state = _delete_in_chunks(
            conn,
            """
            DELETE FROM stream_enforcement_state
            WHERE rowid IN (
                SELECT rowid
                FROM stream_enforcement_state
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_enforcements = _delete_in_chunks(
            conn,
            """
            DELETE FROM stream_enforcements
            WHERE rowid IN (
                SELECT rowid
                FROM stream_enforcements
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_identities = _delete_in_chunks(
            conn,
            """
            DELETE FROM user_identities
            WHERE rowid IN (
                SELECT rowid
                FROM user_identities
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_import_jobs = _delete_in_chunks(
            conn,
            """
            DELETE FROM tautulli_import_jobs
            WHERE rowid IN (
                SELECT rowid
                FROM tautulli_import_jobs
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_welcome_templates = _delete_in_chunks(
            conn,
            """
            DELETE FROM welcome_email_templates
            WHERE rowid IN (
                SELECT rowid
                FROM welcome_email_templates
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 3) Liaison libraries -> media_user_libraries
        deleted_mul = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_user_libraries
            WHERE rowid IN (
                SELECT mul.rowid
                FROM media_user_libraries mul
                JOIN libraries l ON l.id = mul.library_id
                WHERE l.server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 4) Libraries puis media_users
        deleted_libraries = _delete_in_chunks(
            conn,
            """
            DELETE FROM libraries
            WHERE rowid IN (
                SELECT rowid
                FROM libraries
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        deleted_media_users = _delete_in_chunks(
            conn,
            """
            DELETE FROM media_users
            WHERE rowid IN (
                SELECT rowid
                FROM media_users
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
        )

        # 5) Final : supprimer le serveur
        conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        conn.commit()

        server_delete_logger.info(
            "[server_delete] Done for server_id=%s name=%s | "
            "media_sessions=%s media_events=%s media_session_history=%s media_jobs=%s "
            "stream_enforcement_state=%s stream_enforcements=%s user_identities=%s "
            "tautulli_import_jobs=%s welcome_email_templates=%s "
            "media_user_libraries=%s libraries=%s media_users=%s",
            server_id,
            server_name,
            deleted_sessions,
            deleted_events,
            deleted_history,
            deleted_jobs,
            deleted_state,
            deleted_enforcements,
            deleted_identities,
            deleted_import_jobs,
            deleted_welcome_templates,
            deleted_mul,
            deleted_libraries,
            deleted_media_users,
        )

    except Exception as e:
        server_delete_logger.exception(
            f"[server_delete] Failed for server_id={server_id} name={server_name}: {e}"
        )
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

        with SERVER_DELETE_LOCK:
            SERVER_DELETE_IN_PROGRESS.discard(delete_key)

def register(app):
    @app.route("/servers/<int:server_id>/sync", methods=["POST"])
    def sync_server(server_id):
        db = get_db()

        # --------------------------------------------------
        # Vérifier que le serveur existe
        # --------------------------------------------------
        server = db.query_one(
            "SELECT id, type FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Si ce n'est pas un serveur Plex, ne pas créer de job Plex
        # --------------------------------------------------
        if server["type"] != "plex":
            flash("sync_not_supported_for_server_type", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Cibler les vodum_users qui ont AU MOINS 1 accès sur ce serveur
        # (évite le cas où apply_sync_job bloque quand sections == [])
        # --------------------------------------------------
        vodum_users = db.query(
            """
            SELECT DISTINCT vu.id AS vodum_user_id
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
            JOIN libraries l
                ON l.id = mul.library_id
            WHERE mu.server_id = ?
              AND l.server_id = ?
              AND mu.type = 'plex'
            """,
            (server_id, server_id),
        )

        if not vodum_users:
            flash("no_users_to_sync_for_server", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Créer 1 job sync par vodum_user (dans media_jobs)
        # --------------------------------------------------
        created = 0
        for r in vodum_users:
            vodum_user_id = int(r["vodum_user_id"])
            preferred_media_user_id = get_preferred_plex_media_user_id(db, vodum_user_id, server_id)

            dedupe_key = (
                f"plex:sync:server={server_id}:"
                f"media_user={preferred_media_user_id or 'none'}:server_sync"
            )

            payload = {
                "reason": "server_sync",
                "preferred_media_user_id": preferred_media_user_id,
            }

            inserted = insert_plex_media_job(
                db,
                action="sync",
                vodum_user_id=vodum_user_id,
                server_id=server_id,
                dedupe_key=dedupe_key,
                payload=payload,
            )

            if inserted:
                created += 1

        # --------------------------------------------------
        # Activer + queue apply_plex_access_updates
        # --------------------------------------------------
        try:
            enable_and_run_task_by_name("apply_plex_access_updates")
        except Exception:
            # pas bloquant, le scheduler la prendra
            pass

        if created > 0:
            flash("sync_jobs_created", "success")
        else:
            flash("sync_jobs_already_pending", "info")

        return redirect(url_for("server_detail", server_id=server_id))





    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = db.query(
            f"""
            SELECT
{SERVERS_LIST_COLUMNS},

                -- nb bibliothèques
                COUNT(DISTINCT l.id) AS libraries_count,

                -- nb d'utilisateurs Vodum ayant au moins un compte sur ce serveur
                COUNT(DISTINCT mu.vodum_user_id) AS users_count

            FROM servers s
            LEFT JOIN libraries l
                   ON l.server_id = s.id

            LEFT JOIN media_users mu
                   ON mu.server_id = s.id

            GROUP BY s.id
            ORDER BY s.name
            """
        )

        with SERVER_DELETE_LOCK:
            deleting_server_ids = {
                int(str(x).split(":", 1)[1])
                for x in SERVER_DELETE_IN_PROGRESS
                if str(x).startswith("server:")
            }

        with SERVER_DELETE_LOCK:
            deleting_server_ids = {
                int(str(x).split(":", 1)[1])
                for x in SERVER_DELETE_IN_PROGRESS
                if str(x).startswith("server:")
            }

        return render_template(
            "servers/servers.html",
            servers=servers,
            deleting_server_ids=deleting_server_ids,
            active_page="servers",
            active_tab="servers",
        )




    @app.route("/libraries", methods=["GET"])
    def libraries_list():
        db = get_db()

        page = _page_arg("page")
        per_page = SERVER_TABLE_PAGE_SIZE
        sort = (request.args.get("sort") or "server").strip().lower()
        order = (request.args.get("order") or "asc").strip().lower()
        if order not in ("asc", "desc"):
            order = "asc"

        sort_map = {
            "server": "LOWER(s.name)",
            "name": "LOWER(l.name)",
            "type": "type",
            "section_id": "LOWER(COALESCE(l.section_id, ''))",
            "users": "users_count",
        }
        if sort not in sort_map:
            sort = "server"
        order_sql = "DESC" if order == "desc" else "ASC"
        order_sql_clause = f"{sort_map[sort]} {order_sql}, LOWER(s.name) ASC, LOWER(l.name) ASC, l.id ASC"

        total_row = db.query_one("SELECT COUNT(*) AS total FROM libraries")
        total_rows = int(total_row["total"] if total_row and total_row["total"] is not None else 0)
        pagination = _pagination(
            page,
            per_page,
            total_rows,
            "libraries_list",
            sort=sort,
            order=order,
            unit_label="libraries",
        )
        page = pagination["page"]
        offset = (page - 1) * per_page

        libraries = db.query(
            f"""
            SELECT
{LIBRARIES_LIST_COLUMNS},
                s.name AS server_name,
                COUNT(DISTINCT mu.vodum_user_id) AS users_count
            FROM libraries l
            JOIN servers s
                ON s.id = l.server_id
            LEFT JOIN media_user_libraries mul
                ON mul.library_id = l.id
            LEFT JOIN media_users mu
                ON mu.id = mul.media_user_id
            GROUP BY l.id
            ORDER BY {order_sql_clause}
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )

        return render_template(
            "servers/libraries.html",
            libraries=libraries,
            pagination=pagination,
            sort=sort,
            order=order,
            active_page="servers",
            active_tab="libraries",
        )








    @app.route("/servers/new", methods=["POST"])
    def server_create():
        db = get_db()

        server_type = (
            request.form.get("server_type")
            or request.form.get("type")
            or ""
        ).strip().lower()

        if server_type not in ("plex", "jellyfin"):
            logger.error(
                f"[SERVER CREATE] Invalid server_type received: {server_type}"
            )
            flash("Invalid server type", "error")
            return redirect(url_for("servers"))
        name = f"{server_type.upper()} - pending"

        url = (request.form.get("url") or "").strip()

        # --------------------------------------------------
        # Normalize Plex/Jellyfin URLs
        # --------------------------------------------------
        url = url.rstrip("/")

        if url.endswith("/web/index.html"):
            url = url[:-15]

        if url.endswith("/web"):
            url = url[:-4]

        url = url.rstrip("/")

        # --------------------------------------------------
        # Basic validation
        # --------------------------------------------------
        if not url.startswith(("http://", "https://")):
            flash("Server URL must start with http:// or https://", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Detect invalid Plex web UI URLs
        # --------------------------------------------------
        if "/web/" in url or url.endswith("/web"):
            flash(
                "Invalid Plex URL detected. Please use the server base URL without /web",
                "error",
            )
            return redirect(url_for("servers_list"))
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None

        # Options spécifiques (stockées dans settings_json)
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None

        server_identifier = str(uuid.uuid4())

        # settings_json (clé/valeurs extensibles)
        settings = {}
        if tautulli_url or tautulli_api_key:
            settings["tautulli"] = {"url": tautulli_url, "api_key": tautulli_api_key}
        settings_json = encrypt_server_settings_json(
            json.dumps(settings) if settings else None
        )
        token = encrypt_secret(token)

        try:
            # --------------------------------------------------
            # 1) INSERT serveur
            # --------------------------------------------------
            cur = db.execute(
                """
                INSERT INTO servers (
                    name,
                    type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    server_type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    "unknown",
                ),
            )
            server_id = getattr(cur, "lastrowid", None)

            # --------------------------------------------------
            # 2) Activation des tâches système
            # --------------------------------------------------
            ensure_tasks_enabled(["check_servers", "update_user_status"])


            # --------------------------------------------------
            # 3) Commit avant enqueue (évite des incohérences + locks)
            # --------------------------------------------------
            try:
                db.commit()
            except Exception:
                # Si ton get_db() auto-commit déjà, ce commit peut ne pas exister
                # ou lever selon ton wrapper. Dans ce cas, on ignore.
                pass

            # --------------------------------------------------
            # Wakeup auto-enable system
            # --------------------------------------------------
            mark_auto_enable_dirty()

            # --------------------------------------------------
            # Wakeup monitoring / access workers
            # --------------------------------------------------
            force_task_run("check_servers")

            # --------------------------------------------------
            # 4) Enchaîner check + sync (FIFO, jamais perdu)
            # --------------------------------------------------
            try:
                enqueue_server_discovery_sequence(server_type)
            except Exception as e:
                app.logger.warning(f"Failed to queue sequence after server creation: {e}")


        except Exception as e:
            # Si l'insert serveur ou l'update tasks a planté
            app.logger.exception(f"Server creation failed: {e}")
            flash("server_create_failed", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # 5) Message UI
        # --------------------------------------------------
        if server_type == "plex":
            flash("plex_server_created_sync_planned", "success")
        elif server_type == "jellyfin":
            flash("jellyfin_server_created_sync_planned", "success")
        else:
            flash("server_created_no_sync", "success")

        return redirect(url_for("servers_list"))







    @app.route("/servers/<int:server_id>/delete", methods=["POST"])
    def server_delete(server_id):
        db = get_db()

        server = db.query_one(
            "SELECT id, name FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        delete_key = f"server:{server_id}"

        with SERVER_DELETE_LOCK:
            if delete_key in SERVER_DELETE_IN_PROGRESS:
                flash("server_delete_already_running", "warning")
                return redirect(url_for("servers_list"))

            SERVER_DELETE_IN_PROGRESS.add(delete_key)

        try:
            app_obj = current_app._get_current_object()
            db_path = current_app.config["DATABASE"]

            threading.Thread(
                target=_background_delete_server,
                args=(app_obj, db_path, int(server_id), server["name"]),
                daemon=True,
                name=f"delete-server-{server_id}",
            ).start()

            flash("server_delete_started", "success")

        except Exception as e:
            with SERVER_DELETE_LOCK:
                SERVER_DELETE_IN_PROGRESS.discard(delete_key)

            flash(f"server_delete_failed ({e})", "error")

        return redirect(url_for("servers_list"))






    @app.route("/servers/<int:server_id>", methods=["GET"])
    def server_detail(server_id):
        db = get_db()

        server = db.query_one(
            f"SELECT {SERVER_DETAIL_COLUMNS} FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            return "Serveur introuvable", 404

        per_page = SERVER_TABLE_PAGE_SIZE
        libraries_page = _page_arg("libraries_page")
        users_page = _page_arg("users_page")

        library_total_row = db.query_one(
            "SELECT COUNT(*) AS total FROM libraries WHERE server_id = ?",
            (server_id,),
        )
        library_total = int(library_total_row["total"] if library_total_row and library_total_row["total"] is not None else 0)
        libraries_pagination = _pagination(
            libraries_page,
            per_page,
            library_total,
            "server_detail",
            page_param="libraries_page",
            server_id=server_id,
            users_page=users_page,
            unit_label="libraries",
        )
        libraries_page = libraries_pagination["page"]
        libraries_offset = (libraries_page - 1) * per_page

        libraries = db.query(
            f"""
            SELECT
{SERVER_DETAIL_LIBRARY_COLUMNS},
                COUNT(DISTINCT mu.vodum_user_id) AS users_count
            FROM libraries l
            LEFT JOIN media_user_libraries mul
                   ON mul.library_id = l.id
            LEFT JOIN media_users mu
                   ON mu.id = mul.media_user_id
            WHERE l.server_id = ?
            GROUP BY l.id
            ORDER BY LOWER(l.name), l.id
            LIMIT ? OFFSET ?
            """,
            (server_id, per_page, libraries_offset),
        )

        user_total_row = db.query_one(
            """
            SELECT COUNT(DISTINCT vu.id) AS total
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            WHERE mu.server_id = ?
            """,
            (server_id,),
        )
        user_total = int(user_total_row["total"] if user_total_row and user_total_row["total"] is not None else 0)
        users_pagination = _pagination(
            users_page,
            per_page,
            user_total,
            "server_detail",
            page_param="users_page",
            server_id=server_id,
            libraries_page=libraries_page,
            unit_label="users",
        )
        users_page = users_pagination["page"]
        users_offset = (users_page - 1) * per_page

        users = db.query(
            """
            SELECT
                vu.id,
                vu.username,
                vu.email
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            WHERE mu.server_id = ?
            GROUP BY vu.id
            ORDER BY LOWER(vu.username), vu.id
            LIMIT ? OFFSET ?
            """,
            (server_id, per_page, users_offset),
        )

        return render_template(
            "servers/server_detail.html",
            server=server,
            libraries=libraries,
            libraries_pagination=libraries_pagination,
            users=users,
            users_pagination=users_pagination,
            active_page="servers",
        )

    @app.route("/servers/<int:server_id>/save", methods=["POST"])
    def server_detail_save(server_id):
        db = get_db()

        name = request.form.get("name", "").strip()
        server_type = (
            request.form.get("server_type")
            or request.form.get("type")
            or ""
        ).strip().lower()

        if server_type not in ("plex", "jellyfin"):
            logger.error(
                f"[SERVER SAVE] Invalid server_type received: {server_type}"
            )
            flash("Invalid server type", "error")
            return redirect(url_for("server_detail", server_id=server_id))
        url = request.form.get("url") or None
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None
        status = request.form.get("status") or None

        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None

        if not name:
            flash("Le nom du serveur est obligatoire", "error")
            return redirect(url_for("server_detail", server_id=server_id))

        row = db.query_one(
            "SELECT token, settings_json FROM servers WHERE id = ?",
            (server_id,),
        )

        settings = {}
        if row and row["settings_json"]:
            try:
                settings = json.loads(row["settings_json"])
            except Exception:
                settings = {}

        existing_tautulli = settings.get("tautulli")
        if not isinstance(existing_tautulli, dict):
            existing_tautulli = {}

        if tautulli_url is not None or tautulli_api_key is not None:
            settings["tautulli"] = {
                "url": tautulli_url or existing_tautulli.get("url"),
                "api_key": keep_existing_secret(
                    tautulli_api_key,
                    existing_tautulli.get("api_key"),
                ),
            }

        settings["verify_tls"] = request.form.get("verify_tls") == "1"

        settings_json = encrypt_server_settings_json(
            json.dumps(settings) if settings else None
        )
        token = encrypt_secret(
            keep_existing_secret(token, row["token"] if row else None)
        )

        db.execute(
            """
            UPDATE servers
            SET name = ?,
                type = ?,
                url = ?,
                local_url = ?,
                public_url = ?,
                token = ?,
                settings_json = ?,
                status = ?
            WHERE id = ?
            """,
            (
                name,
                server_type,
                url,
                local_url,
                public_url,
                token,
                settings_json,
                status,
                server_id,
            ),
        )

        # --------------------------------------------------
        # Wakeup auto-enable system
        # --------------------------------------------------
        mark_auto_enable_dirty()

        # --------------------------------------------------
        # Wakeup server checks
        # --------------------------------------------------
        force_task_run("check_servers")

        flash("server_updated", "success")
        return redirect(url_for("server_detail", server_id=server_id))




    @app.route("/servers/bulk_grant", methods=["POST"])
    def bulk_grant_libraries():
        db = get_db()

        try:
            result = grant_libraries_to_active_users(
                db,
                server_id=request.form.get("server_id", type=int),
                library_ids=request.form.getlist("library_ids"),
            )
        except BulkAccessError as exc:
            flash(exc.flash_key, exc.category)
            return redirect(url_for("libraries_list"))

        try:
            enable_and_run_task_by_name("apply_plex_access_updates")
        except Exception:
            logger.exception(
                "Bulk library grant persisted but Plex worker startup failed | server_id=%s | changed_users=%s",
                result.get("server_id"),
                result.get("changed_users"),
            )
        mark_auto_enable_dirty()
        force_task_run("apply_plex_access_updates")

        flash(result["message"], "success")
        return redirect(url_for("libraries_list"))


    @app.route("/servers/bulk_remove", methods=["POST"])
    def bulk_remove_libraries():
        db = get_db()

        try:
            result = remove_libraries_from_users(
                db,
                server_id=request.form.get("server_id", type=int),
                library_ids=request.form.getlist("library_ids"),
            )
        except BulkAccessError as exc:
            flash(exc.flash_key, exc.category)
            return redirect(url_for("libraries_list"))

        try:
            enable_and_run_task_by_name("apply_plex_access_updates")
        except Exception:
            logger.exception(
                "Bulk library removal persisted but Plex worker startup failed | server_id=%s | changed_users=%s",
                result.get("server_id"),
                result.get("changed_users"),
            )
        mark_auto_enable_dirty()
        force_task_run("apply_plex_access_updates")

        flash(result["message"], "success")
        return redirect(url_for("libraries_list"))


