# Auto-split from app.py (keep URLs/endpoints intact)
import uuid
import threading
from flask import (
    render_template, request, redirect, url_for, flash, current_app,
)

from logging_utils import get_logger
from web.helpers import get_db
from web.pagination import normalize_page, pagination_links
from core.server_page_queries import (
    count_libraries,
    count_server_users,
    load_servers_list,
    load_libraries_page,
    count_server_libraries,
    load_server_libraries,
    load_server_detail,
    load_server_users,
    normalize_libraries_sort,
    snapshot_deleting_server_ids,
)
from core.library_bulk_access import (
    BulkAccessError,
    grant_libraries_to_active_users,
    remove_libraries_from_users,
    wake_bulk_access_worker,
)
from core.server_deletion import (
    claim_server_deletion,
    load_server_deletion_target,
    release_server_deletion,
    run_server_deletion_worker,
    start_server_deletion_thread,
)
from core.server_sync import (
    enqueue_plex_server_sync_jobs,
    load_plex_sync_user_ids,
    load_sync_server,
    plex_sync_result_flash,
    wake_plex_sync_worker,
)
from core.server_form import (
    is_supported_server_type,
    read_new_server_form,
    read_updated_server_form,
    server_base_url_error,
)
from core.server_admin import (
    ensure_new_server_tasks,
    commit_server_creation,
    decode_server_settings,
    insert_server,
    load_server_secrets,
    merge_updated_server_settings,
    prepare_new_server_secrets,
    prepare_updated_server_secrets,
    queue_server_discovery,
    server_creation_flash,
    update_server,
    wake_new_server_tasks,
    wake_updated_server_tasks,
)

server_delete_logger = get_logger("server_delete")
logger = get_logger("servers")

SERVER_DELETE_LOCK = threading.Lock()
SERVER_DELETE_IN_PROGRESS = set()

SERVER_TABLE_PAGE_SIZE = 20

def _page_arg(name: str = "page") -> int:
    return normalize_page(request.args.get(name, 1, type=int))


def _pagination(page: int, per_page: int, total_rows: int, endpoint: str, page_param: str = "page", unit_label: str | None = None, **kwargs):
    def page_url(value: int):
        args = dict(kwargs)
        args[page_param] = value
        return url_for(endpoint, **args)
    return pagination_links(page, per_page, total_rows, page_url, unit_label=unit_label)

def _background_delete_server(app, db_path, server_id, server_name):
    run_server_deletion_worker(
        db_path,
        server_id,
        server_name,
        server_delete_logger,
        SERVER_DELETE_LOCK,
        SERVER_DELETE_IN_PROGRESS,
    )

def register(app):
    @app.route("/servers/<int:server_id>/sync", methods=["POST"])
    def sync_server(server_id):
        db = get_db()

        # --------------------------------------------------
        # Vérifier que le serveur existe
        # --------------------------------------------------
        server = load_sync_server(db, server_id)

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
        vodum_users = load_plex_sync_user_ids(db, server_id)

        if not vodum_users:
            flash("no_users_to_sync_for_server", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Créer 1 job sync par vodum_user (dans media_jobs)
        # --------------------------------------------------
        created = enqueue_plex_server_sync_jobs(db, server_id, vodum_users)

        # --------------------------------------------------
        # Activer + queue apply_plex_access_updates
        # --------------------------------------------------
        wake_plex_sync_worker()

        message, category = plex_sync_result_flash(created)
        flash(message, category)

        return redirect(url_for("server_detail", server_id=server_id))





    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = load_servers_list(db)
        deleting_server_ids = snapshot_deleting_server_ids(
            SERVER_DELETE_LOCK,
            SERVER_DELETE_IN_PROGRESS,
        )

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
        sort, order, order_sql_clause = normalize_libraries_sort(sort, order)

        total_rows = count_libraries(db)
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

        libraries = load_libraries_page(
            db,
            per_page=per_page,
            offset=offset,
            order_clause=order_sql_clause,
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

        form_data = read_new_server_form(request.form)
        server_type = form_data["server_type"]

        if not is_supported_server_type(server_type):
            logger.error(
                f"[SERVER CREATE] Invalid server_type received: {server_type}"
            )
            flash("Invalid server type", "error")
            return redirect(url_for("servers"))
        name = f"{server_type.upper()} - pending"

        url = form_data["url"]

        # --------------------------------------------------
        # Basic validation
        # --------------------------------------------------
        url_error = server_base_url_error(url)
        if url_error == "protocol":
            flash("Server URL must start with http:// or https://", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Detect invalid Plex web UI URLs
        # --------------------------------------------------
        if url_error == "plex_web":
            flash(
                "Invalid Plex URL detected. Please use the server base URL without /web",
                "error",
            )
            return redirect(url_for("servers_list"))
        local_url = form_data["local_url"]
        public_url = form_data["public_url"]
        token = form_data["token"]

        # Options spécifiques (stockées dans settings_json)
        server_identifier = str(uuid.uuid4())

        # settings_json (clé/valeurs extensibles)
        settings = form_data["settings"]
        settings_json, token = prepare_new_server_secrets(settings, token)

        try:
            # --------------------------------------------------
            # 1) INSERT serveur
            # --------------------------------------------------
            insert_server(
                db,
                name=name,
                server_type=server_type,
                server_identifier=server_identifier,
                url=url,
                local_url=local_url,
                public_url=public_url,
                token=token,
                settings_json=settings_json,
            )
            # --------------------------------------------------
            # 2) Activation des tâches système
            # --------------------------------------------------
            ensure_new_server_tasks()

            # --------------------------------------------------
            # 3) Commit avant enqueue (évite des incohérences + locks)
            # --------------------------------------------------
            commit_server_creation(db)

            # --------------------------------------------------
            # Wakeup auto-enable system
            # --------------------------------------------------
            wake_new_server_tasks()

            # --------------------------------------------------
            # 4) Enchaîner check + sync (FIFO, jamais perdu)
            # --------------------------------------------------
            queue_server_discovery(server_type, app.logger)


        except Exception as e:
            # Si l'insert serveur ou l'update tasks a planté
            app.logger.exception(f"Server creation failed: {e}")
            flash("server_create_failed", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # 5) Message UI
        # --------------------------------------------------
        message, category = server_creation_flash(server_type)
        flash(message, category)

        return redirect(url_for("servers_list"))







    @app.route("/servers/<int:server_id>/delete", methods=["POST"])
    def server_delete(server_id):
        db = get_db()

        server = load_server_deletion_target(db, server_id)

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        delete_key = claim_server_deletion(
            SERVER_DELETE_LOCK,
            SERVER_DELETE_IN_PROGRESS,
            server_id,
        )
        if delete_key is None:
            flash("server_delete_already_running", "warning")
            return redirect(url_for("servers_list"))

        try:
            app_obj = current_app._get_current_object()
            db_path = current_app.config["DATABASE"]

            start_server_deletion_thread(
                _background_delete_server,
                app_obj,
                db_path,
                server_id,
                server["name"],
            )

            flash("server_delete_started", "success")

        except Exception as e:
            release_server_deletion(
                SERVER_DELETE_LOCK,
                SERVER_DELETE_IN_PROGRESS,
                delete_key,
            )

            flash(f"server_delete_failed ({e})", "error")

        return redirect(url_for("servers_list"))






    @app.route("/servers/<int:server_id>", methods=["GET"])
    def server_detail(server_id):
        db = get_db()

        server = load_server_detail(db, server_id)

        if not server:
            return "Serveur introuvable", 404

        per_page = SERVER_TABLE_PAGE_SIZE
        libraries_page = _page_arg("libraries_page")
        users_page = _page_arg("users_page")

        library_total = count_server_libraries(db, server_id)
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

        libraries = load_server_libraries(
            db, server_id, per_page=per_page, offset=libraries_offset,
        )

        user_total = count_server_users(db, server_id)
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

        users = load_server_users(
            db, server_id, per_page=per_page, offset=users_offset,
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

        form_data = read_updated_server_form(request.form)
        name = form_data["name"]
        server_type = form_data["server_type"]

        if not is_supported_server_type(server_type):
            logger.error(
                f"[SERVER SAVE] Invalid server_type received: {server_type}"
            )
            flash("Invalid server type", "error")
            return redirect(url_for("server_detail", server_id=server_id))
        url = form_data["url"]
        local_url = form_data["local_url"]
        public_url = form_data["public_url"]
        token = form_data["token"]
        status = form_data["status"]
        tautulli_url = form_data["tautulli_url"]
        tautulli_api_key = form_data["tautulli_api_key"]

        if not name:
            flash("Le nom du serveur est obligatoire", "error")
            return redirect(url_for("server_detail", server_id=server_id))

        row = load_server_secrets(db, server_id)

        settings = decode_server_settings(row)
        settings = merge_updated_server_settings(
            settings,
            tautulli_url=tautulli_url,
            tautulli_api_key=tautulli_api_key,
            verify_tls=form_data["verify_tls"],
        )

        settings_json, token = prepare_updated_server_secrets(
            settings,
            token,
            row["token"] if row else None,
        )

        update_server(
            db,
            server_id,
            name=name,
            server_type=server_type,
            url=url,
            local_url=local_url,
            public_url=public_url,
            token=token,
            settings_json=settings_json,
            status=status,
        )

        # --------------------------------------------------
        # Wakeup auto-enable system
        # --------------------------------------------------
        wake_updated_server_tasks()

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

        wake_bulk_access_worker(result, "grant", logger)

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

        wake_bulk_access_worker(result, "removal", logger)

        flash(result["message"], "success")
        return redirect(url_for("libraries_list"))


