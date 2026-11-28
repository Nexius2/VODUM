"""Compliance pages: overview, settings view, profiles, groups and deployment history.

Nothing in these routes writes to Plex or Jellyfin directly: every change goes
through a stored preview, the admin's confirmation, and the writer module.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from core import server_configuration_compliance as compliance_core
from core import server_configuration_deploy as deploy_core
from core import server_configuration_explorer as explorer_core
from core import server_configuration_profiles as profiles_core
from core import server_configuration_snapshots as snapshots_core
from core.auth_principal import admin_required
from core.error_reporting import log_handled_failure
from core.i18n import get_translator
from core.server_configuration import CATEGORIES, ServerConfigurationError, read_server_configuration
from web.helpers import add_log, get_db


def _media_servers(db):
    return [dict(row) for row in db.query(
        """SELECT id, name, LOWER(TRIM(type)) AS type, status FROM servers
           WHERE LOWER(TRIM(type)) IN ('plex','jellyfin') ORDER BY name COLLATE NOCASE, id"""
    ) or []]


def _flash_error(exc):
    flash(get_translator()(str(exc)), "error")


def register(app):
    @app.context_processor
    def _config_mode_context():
        """The operating mode badge shown on every Compliance page."""
        if not request.path.startswith("/server-configuration"):
            return {}
        try:
            return {"compliance_mode": deploy_core.get_mode(get_db())}
        except Exception:
            return {}

    def _safe_next(default_endpoint):
        target = str(request.form.get("next") or request.args.get("next") or "")
        if target.startswith("/server-configuration") and "//" not in target and "\\" not in target:
            return target
        return url_for(default_endpoint)

    @app.get("/server-configuration")
    @admin_required
    def server_configuration_page():
        """The old Servers tab: a server's settings now open in the Settings view."""
        server_id = request.args.get("server", type=int)
        if server_id:
            return redirect(url_for("server_configuration_settings_view", servers=server_id))
        return redirect(url_for("server_configuration_compliance"))

    # --------------------------------------------------------------- compliance
    @app.get("/server-configuration/compliance")
    @admin_required
    def server_configuration_compliance():
        db = get_db()
        return render_template(
            "server_configuration/compliance.html",
            active_page="server_configuration",
            config_tab="compliance",
            overview=explorer_core.overview(db),
            groups=profiles_core.list_groups(db),
            mode=deploy_core.get_mode(db),
        )

    @app.post("/server-configuration/compliance/check/<int:server_id>")
    @admin_required
    def server_configuration_compliance_check_one(server_id):
        """One server of a progressive check started from the page (JSON)."""
        try:
            summary = compliance_core.check_compliance(get_db(), [server_id])
        except Exception:
            log_handled_failure("server_configuration.compliance_manual", server_id=server_id)
            return jsonify({"ok": False, "error": "server_config_unexpected_answer"}), 200
        return jsonify({"ok": True, "summary": summary})

    @app.post("/server-configuration/snapshots/<int:server_id>/refresh")
    @admin_required
    def server_configuration_snapshot_refresh(server_id):
        """Read one server again for the Settings view (JSON); the page reads servers one by one."""
        try:
            outcome = snapshots_core.refresh(get_db(), server_id)
        except Exception:
            log_handled_failure("server_configuration.snapshot", server_id=server_id)
            outcome = {"ok": False, "error": "server_config_unexpected_answer"}
        return jsonify(outcome)

    @app.post("/server-configuration/compliance/check")
    @admin_required
    def server_configuration_compliance_check():
        """Read-only check started by the admin; Plex reads go ahead of background work."""
        try:
            summary = compliance_core.check_compliance(get_db())
        except Exception:
            log_handled_failure("server_configuration.compliance_manual")
            flash(get_translator()("server_config_unexpected_answer"), "error")
            return redirect(url_for("server_configuration_compliance"))
        add_log("info", "server_configuration", "Configuration compliance checked", summary)
        flash(get_translator()("config_compliance_checked").format(
            checked=summary["checked"], non_compliant=summary["non_compliant"],
            unreachable=summary["unreachable"]), "success")
        return redirect(url_for("server_configuration_compliance"))

    # ------------------------------------------------- deployments (steps 4-5)
    def _deploy_error(exc):
        flash(get_translator()(str(exc)), "error")

    @app.get("/server-configuration/deploy")
    @admin_required
    def server_configuration_deploy():
        db = get_db()
        return render_template(
            "server_configuration/deploy.html",
            active_page="server_configuration",
            config_tab="deploy",
            mode=deploy_core.get_mode(db),
            servers=_media_servers(db),
            profiles=profiles_core.list_profiles(db),
            groups=profiles_core.list_groups(db),
            deployments=deploy_core.list_deployments(db),
            max_servers=deploy_core.MAX_DEPLOY_SERVERS,
        )

    @app.post("/server-configuration/mode")
    @admin_required
    def server_configuration_mode():
        try:
            deploy_core.set_mode(get_db(), request.form.get("mode"))
            add_log("info", "server_configuration", "Configuration manager mode changed",
                    {"mode": request.form.get("mode")})
            flash(get_translator()("config_mode_saved"), "success")
        except deploy_core.DeployError as exc:
            _deploy_error(exc)
        if request.form.get("next") == "compliance":
            return redirect(url_for("server_configuration_compliance"))
        return redirect(_safe_next("server_configuration_deploy"))

    @app.post("/server-configuration/deploy/plan")
    @admin_required
    def server_configuration_deploy_plan():
        """Read-only preview: nothing is written until the admin confirms it."""
        try:
            deployment_id = deploy_core.plan_deployment(
                get_db(), request.form.get("source"), server_ids=request.form.getlist("server_ids"),
                group_ids=request.form.getlist("group_ids"), everyone=request.form.get("everyone") == "1",
                include_risky=request.form.get("include_risky") == "1")
        except (deploy_core.DeployError, profiles_core.ProfileError) as exc:
            _deploy_error(exc)
            return redirect(url_for("server_configuration_deploy"))
        return redirect(url_for("server_configuration_deployment", deployment_id=deployment_id))

    @app.post("/server-configuration/fix")
    @admin_required
    def server_configuration_fix():
        """Preview fixing deviations (one setting, selected servers or the whole fleet)."""
        server_ids = request.form.getlist("server_ids") or None
        keys = request.form.getlist("keys") or None
        try:
            deployment_id = deploy_core.plan_fix(get_db(), server_ids, keys)
        except deploy_core.DeployError as exc:
            _deploy_error(exc)
            return redirect(url_for("server_configuration_compliance"))
        return redirect(url_for("server_configuration_deployment", deployment_id=deployment_id))

    @app.get("/server-configuration/deploy/<int:deployment_id>")
    @admin_required
    def server_configuration_deployment(deployment_id):
        db = get_db()
        deployment = deploy_core.get_deployment(db, deployment_id)
        if not deployment:
            flash(get_translator()("config_deploy_not_found"), "error")
            return redirect(url_for("server_configuration_deploy"))
        return render_template(
            "server_configuration/deployment.html",
            active_page="server_configuration",
            config_tab="deploy",
            deployment=deployment,
            mode=deploy_core.get_mode(db),
        )

    @app.post("/server-configuration/deploy/<int:deployment_id>/confirm")
    @admin_required
    def server_configuration_deployment_confirm(deployment_id):
        try:
            deploy_core.confirm_deployment(get_db(), deployment_id, request.form.getlist("item_ids"))
            add_log("info", "server_configuration", "Configuration deployment confirmed",
                    {"deployment_id": deployment_id})
        except deploy_core.DeployError as exc:
            _deploy_error(exc)
        return redirect(url_for("server_configuration_deployment", deployment_id=deployment_id))

    @app.post("/server-configuration/deploy/<int:deployment_id>/discard")
    @admin_required
    def server_configuration_deployment_discard(deployment_id):
        deploy_core.discard_draft(get_db(), deployment_id)
        return redirect(url_for("server_configuration_deploy"))

    @app.post("/server-configuration/deploy/<int:deployment_id>/retry")
    @admin_required
    def server_configuration_deployment_retry(deployment_id):
        try:
            deploy_core.retry_failed(get_db(), deployment_id, request.form.get("server_id", type=int))
        except deploy_core.DeployError as exc:
            _deploy_error(exc)
        return redirect(url_for("server_configuration_deployment", deployment_id=deployment_id))

    @app.post("/server-configuration/deploy/<int:deployment_id>/servers/<int:server_id>/apply")
    @admin_required
    def server_configuration_deployment_apply(deployment_id, server_id):
        """Write and verify one server; returns its updated block for the page."""
        db = get_db()
        error = None
        try:
            summary = deploy_core.apply_server(db, deployment_id, server_id)
            add_log("info", "server_configuration", "Configuration deployed to a server",
                    {"deployment_id": deployment_id, "server_id": server_id, **summary})
        except deploy_core.DeployError as exc:
            error = str(exc)
        except Exception:
            log_handled_failure("server_configuration.deploy_apply", server_id=server_id)
            error = "server_config_unexpected_answer"
        deployment = deploy_core.get_deployment(db, deployment_id)
        group = next((g for g in (deployment or {}).get("servers", []) if g["id"] == server_id), None)
        if not group:
            abort(404)
        return render_template("server_configuration/_deploy_server.html", deployment=deployment, group=group,
                               apply_error=error)

    @app.post("/server-configuration/exceptions")
    @admin_required
    def server_configuration_exception():
        try:
            compliance_core.set_exception(get_db(), request.form.get("server_id", type=int) or 0,
                                          request.form.get("key"), request.form.get("label"),
                                          enabled=request.form.get("enabled") == "1")
            enabled = request.form.get("enabled") == "1"
            flash(get_translator()("config_exception_saved" if enabled else "config_exception_removed"), "success")
        except compliance_core.ExceptionError as exc:
            _deploy_error(exc)
        return redirect(_safe_next("server_configuration_compliance"))

    # ----------------------------------------------------------------- settings
    def _scope():
        return explorer_core.resolve_scope(
            get_db(), request.args.get("provider"), request.args.get("group"), request.args.getlist("servers"))

    def _scope_query(scope):
        params = [("provider", scope["provider"] or "")]
        if scope["group"]:
            params.append(("group", scope["group"]["id"]))
        elif scope["kind"] == "servers":
            params += [("servers", server["id"]) for server in scope["servers"]]
        return urlencode(params)

    @app.get("/server-configuration/settings")
    @admin_required
    def server_configuration_settings_view():
        db = get_db()
        scope = _scope()
        view = explorer_core.build(db, scope["servers"]) if scope["servers"] else None
        return render_template(
            "server_configuration/settings.html",
            active_page="server_configuration",
            config_tab="settings",
            scope=scope,
            view=view,
            mode=deploy_core.get_mode(db),
            show_filter=request.args.get("show") or "",
            scope_query=_scope_query(scope),
        )

    @app.get("/server-configuration/settings/detail")
    @admin_required
    def server_configuration_settings_detail():
        """Side panel of one setting: the servers grouped by value, and the editor."""
        db = get_db()
        scope = _scope()
        key = str(request.args.get("key") or "")
        view = explorer_core.build(db, scope["servers"], only_key=key) if scope["servers"] and key else None
        row = view["rows"][0] if view and view["rows"] else None
        return render_template("server_configuration/_setting_detail.html", row=row, scope=scope,
                               mode=deploy_core.get_mode(db), max_servers=deploy_core.MAX_DEPLOY_SERVERS,
                               back=str(request.args.get("back") or ""))

    @app.get("/server-configuration/compare")
    @admin_required
    def server_configuration_compare():
        """Compare is now the Settings view; old links keep their servers."""
        return redirect(url_for("server_configuration_settings_view", servers=request.args.getlist("servers")))

    @app.post("/server-configuration/settings/edit")
    @admin_required
    def server_configuration_settings_edit():
        """Changes chosen in the Settings view go to the usual preview; nothing is written here."""
        back_url = _safe_next("server_configuration_settings_view")
        try:
            edits = json.loads(request.form.get("edits") or "[]")
            deploy_core.require_manual(get_db())
            deployment_id = deploy_core.plan_edits(get_db(), edits if isinstance(edits, list) else None)
        except ValueError as exc:
            if isinstance(exc, (deploy_core.DeployError, profiles_core.ProfileError)):
                _deploy_error(exc)
            else:
                flash(get_translator()("config_edit_invalid"), "error")
            return redirect(back_url)
        return redirect(url_for("server_configuration_deployment", deployment_id=deployment_id))

    # ----------------------------------------------------------------- profiles
    @app.get("/server-configuration/profiles")
    @admin_required
    def server_configuration_profiles():
        db = get_db()
        return render_template(
            "server_configuration/profiles.html",
            active_page="server_configuration",
            config_tab="profiles",
            servers=_media_servers(db),
            profiles=profiles_core.list_profiles(db),
            resolution=profiles_core.server_profiles(db),
        )

    def _without_libraries(settings):
        """Profile settings without the options of libraries (they may not exist on every server)."""
        return {key: entry for key, entry in settings.items() if not entry.get("library")}

    @app.post("/server-configuration/profiles/create")
    @admin_required
    def server_configuration_profile_create():
        db = get_db()
        name = request.form.get("name")
        source = str(request.form.get("source") or "")
        server_id = int(source[7:]) if source.startswith("server:") and source[7:].isdigit() else None
        try:
            if server_id:
                result = read_server_configuration(db, server_id)
                settings, excluded = profiles_core.settings_from_read(result)
                settings = _without_libraries(settings) if request.form.get("skip_libraries") == "1" else settings
                profile_id = profiles_core.create_profile(db, result["provider"], name, request.form.get("description"),
                                                          settings, source_server_id=server_id)
                flash(get_translator()("config_profile_imported").format(count=len(settings), excluded=excluded),
                      "success")
            else:
                profile_id = profiles_core.create_profile(db, source.removeprefix("provider:"), name,
                                                          request.form.get("description"))
        except (profiles_core.ProfileError, ServerConfigurationError) as exc:
            _flash_error(exc)
            return redirect(url_for("server_configuration_profiles"))
        add_log("info", "server_configuration", "Configuration profile created", {"profile_id": profile_id})
        return redirect(url_for("server_configuration_profile", profile_id=profile_id))

    @app.get("/server-configuration/profiles/<int:profile_id>")
    @admin_required
    def server_configuration_profile(profile_id):
        db = get_db()
        profile = profiles_core.get_profile(db, profile_id)
        if not profile:
            flash(get_translator()("config_profile_not_found"), "error")
            return redirect(url_for("server_configuration_profiles"))
        order = {category: index for index, category in enumerate(CATEGORIES)}
        settings = sorted(profile["settings"].items(), key=lambda item: (
            order.get(item[1].get("category"), 99), str(item[1].get("library") or ""), str(item[1].get("label")).lower()))
        servers = _media_servers(db)
        return render_template(
            "server_configuration/profile.html",
            active_page="server_configuration",
            config_tab="profiles",
            profile=profile,
            settings=settings,
            compatible_servers=[server for server in servers if server["type"] == profile["provider"]],
            groups=profiles_core.list_groups(db),
            targets=profiles_core.profile_targets(db, profile_id),
        )

    @app.post("/server-configuration/profiles/<int:profile_id>/save")
    @admin_required
    def server_configuration_profile_save(profile_id):
        values = {key[6:]: value for key, value in request.form.items() if key.startswith("value:")}
        try:
            profiles_core.update_profile(get_db(), profile_id, name=request.form.get("name"),
                                         description=request.form.get("description"), values=values,
                                         removed=request.form.getlist("remove"))
            flash(get_translator()("config_profile_saved"), "success")
        except profiles_core.ProfileError as exc:
            _flash_error(exc)
        return redirect(url_for("server_configuration_profile", profile_id=profile_id))

    @app.post("/server-configuration/profiles/<int:profile_id>/import")
    @admin_required
    def server_configuration_profile_import(profile_id):
        db = get_db()
        profile = profiles_core.get_profile(db, profile_id)
        server_id = request.form.get("server_id", type=int)
        try:
            if not profile:
                raise profiles_core.ProfileError("config_profile_not_found")
            result = read_server_configuration(db, server_id or 0)
            if result["provider"] != profile["provider"]:
                raise profiles_core.ProfileError("config_profile_incompatible_server")
            settings, _ = profiles_core.settings_from_read(result)
            settings = _without_libraries(settings) if request.form.get("skip_libraries") == "1" else settings
            added = profiles_core.merge_profile_settings(
                db, profile_id, settings, replace_values=request.form.get("replace_values") == "1")
            flash(get_translator()("config_profile_merged").format(count=added), "success")
        except (profiles_core.ProfileError, ServerConfigurationError) as exc:
            _flash_error(exc)
        return redirect(url_for("server_configuration_profile", profile_id=profile_id))

    @app.post("/server-configuration/profiles/<int:profile_id>/targets")
    @admin_required
    def server_configuration_profile_targets(profile_id):
        try:
            profiles_core.set_profile_targets(get_db(), profile_id, request.form.getlist("server_ids"),
                                              request.form.getlist("group_ids"))
            flash(get_translator()("config_profile_targets_saved"), "success")
        except profiles_core.ProfileError as exc:
            _flash_error(exc)
        return redirect(url_for("server_configuration_profile", profile_id=profile_id))

    @app.post("/server-configuration/profiles/<int:profile_id>/duplicate")
    @admin_required
    def server_configuration_profile_duplicate(profile_id):
        try:
            new_id = profiles_core.duplicate_profile(get_db(), profile_id)
        except profiles_core.ProfileError as exc:
            _flash_error(exc)
            return redirect(url_for("server_configuration_profiles"))
        return redirect(url_for("server_configuration_profile", profile_id=new_id))

    @app.post("/server-configuration/profiles/<int:profile_id>/delete")
    @admin_required
    def server_configuration_profile_delete(profile_id):
        profiles_core.delete_profile(get_db(), profile_id)
        add_log("info", "server_configuration", "Configuration profile deleted", {"profile_id": profile_id})
        flash(get_translator()("config_profile_deleted"), "success")
        return redirect(url_for("server_configuration_profiles"))

    @app.post("/server-configuration/servers/<int:server_id>/profile")
    @admin_required
    def server_configuration_choose_profile(server_id):
        try:
            profiles_core.choose_server_profile(get_db(), server_id, request.form.get("profile_id", type=int) or 0)
            flash(get_translator()("config_profile_choice_saved"), "success")
        except profiles_core.ProfileError as exc:
            _flash_error(exc)
        return redirect(url_for("server_configuration_profiles"))

    # ------------------------------------------------------------------- groups
    @app.get("/server-configuration/groups")
    @admin_required
    def server_configuration_groups():
        db = get_db()
        return render_template(
            "server_configuration/groups.html",
            active_page="server_configuration",
            config_tab="groups",
            servers=_media_servers(db),
            groups=profiles_core.list_groups(db),
        )

    @app.post("/server-configuration/groups/save")
    @admin_required
    def server_configuration_group_save():
        try:
            profiles_core.save_group(get_db(), request.form.get("group_id", type=int), request.form.get("name"),
                                     request.form.get("description"), request.form.getlist("server_ids"))
            flash(get_translator()("config_group_saved"), "success")
        except profiles_core.ProfileError as exc:
            _flash_error(exc)
        return redirect(url_for("server_configuration_groups"))

    @app.post("/server-configuration/groups/<int:group_id>/delete")
    @admin_required
    def server_configuration_group_delete(group_id):
        profiles_core.delete_group(get_db(), group_id)
        flash(get_translator()("config_group_deleted"), "success")
        return redirect(url_for("server_configuration_groups"))
