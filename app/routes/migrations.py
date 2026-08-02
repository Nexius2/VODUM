import json
from datetime import datetime

from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from core.migrations.analysis import (
    analyze_migration,
    migration_pair_blocker,
    migration_workspace_blocker,
)
from core.migrations.drafts import create_migration_draft, delete_migration_draft, update_migration_draft
from core.migrations.execution import refresh_campaign_status
from core.migrations.lifecycle import (
    conflicting_active_users,
    pause_campaign,
    resume_campaign,
    retry_failed_users,
    set_user_excluded,
)
from core.migrations.phase4 import export_migration_plan, import_migration_plan
from core.migrations.phase3 import remove_validated_source_access, rollback_destination_access, rollback_source_access
from core.migrations.reporting import build_migration_report
from core.migrations.repository import get_campaign, load_report_users
from core.migrations.page_data import (
    enrich_campaign_users,
    load_campaign_detail_relations,
    mapping_overrides_from_form,
    migration_campaign_overview,
    normalize_campaign_detail,
    online_migration_servers,
    paginate_campaign_users,
)
from tasks_engine import enable_and_run_task_by_name
from secret_store import decrypt_secret
from web.helpers import add_log, get_db, table_exists
from logging_utils import get_logger


logger = get_logger("migrations")

def register(app):
    @app.get("/migrations")
    def migrations_page():
        db = get_db()
        servers = online_migration_servers(db)
        workspace_blocker = migration_workspace_blocker(db, servers)
        incompatible_servers = {
            str(server["id"]): [
                candidate["id"]
                for candidate in servers
                if migration_pair_blocker(db, server["id"], candidate["id"])
            ]
            for server in servers
        }

        source_id = request.args.get("source_server_id", type=int)
        destination_id = request.args.get("destination_server_id", type=int)
        analysis = None
        analysis_error = ""
        selection_blocker = ""
        if not workspace_blocker and source_id and destination_id:
            selection_blocker = migration_pair_blocker(db, source_id, destination_id)
            try:
                if selection_blocker:
                    raise ValueError(f"Migration pair is not allowed: {selection_blocker}.")
                analysis = analyze_migration(db, source_id, destination_id)
            except Exception as exc:
                if not selection_blocker:
                    analysis_error = str(exc)

        campaign_counts, campaigns = migration_campaign_overview(
            db,
            schema_available=table_exists(db, "migration_campaigns"),
        )

        return render_template(
            "migrations/migrations.html",
            active_page="migrations",
            servers=servers,
            source_id=source_id,
            destination_id=destination_id,
            analysis=analysis,
            analysis_error=analysis_error,
            workspace_blocker=workspace_blocker,
            selection_blocker=selection_blocker,
            incompatible_servers=incompatible_servers,
            campaign_counts=campaign_counts,
            campaigns=campaigns,
        )

    @app.post("/migrations/drafts")
    def migration_draft_create():
        db = get_db()
        servers = online_migration_servers(db)
        if migration_workspace_blocker(db, servers):
            flash("migration_not_available", "warning")
            return redirect(url_for("migrations_page"))

        source_id = request.form.get("source_server_id", type=int)
        destination_id = request.form.get("destination_server_id", type=int)
        if not source_id or not destination_id:
            flash("migration_servers_required", "error")
            return redirect(url_for("migrations_page"))
        pair_blocker = migration_pair_blocker(db, source_id, destination_id)
        if pair_blocker:
            flash(f"migration_blocker.{pair_blocker}", "error")
            return redirect(url_for("migrations_page"))

        mapping_overrides = mapping_overrides_from_form(request.form)

        try:
            analysis = analyze_migration(db, source_id, destination_id, mapping_overrides)
            if analysis.get("same_plex_owner"):
                flash("migration_shared_plex_not_needed", "warning")
                return redirect(url_for("migrations_page"))
            campaign_id = create_migration_draft(
                db,
                name=request.form.get("name") or "",
                source_server_id=source_id,
                destination_server_id=destination_id,
                mapping_overrides=mapping_overrides,
                safety_delay_days=(
                    request.form.get("safety_delay_days", type=int)
                    if request.form.get("safety_delay_days", type=int) is not None
                    else 7
                ),
                scheduled_at=request.form.get("scheduled_at") or "",
                batch_size=request.form.get("batch_size", type=int) or 10,
                intent=request.form.get("intent") or "copy",
                jellyfin_password_strategy=request.form.get("jellyfin_password_strategy") or "generated",
                jellyfin_temp_password=request.form.get("jellyfin_temp_password") or "",
                jellyfin_auto_deliver_credentials=bool(request.form.get("jellyfin_auto_deliver_credentials")),
            )
            add_log("info", "migrations", f"Migration draft created: campaign_id={campaign_id}")
            flash("migration_draft_created", "success")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        except Exception as exc:
            add_log("error", "migrations", f"Migration draft creation failed: {exc}")
            flash(str(exc), "error")

        return redirect(
            url_for(
                "migrations_page",
                source_server_id=source_id,
                destination_server_id=destination_id,
            )
        )

    @app.post("/migrations/plans/import")
    def migration_plan_import():
        db = get_db()
        upload = request.files.get("plan_file")
        if not upload or not upload.filename:
            flash("migration_plan_file_required", "error")
            return redirect(url_for("migrations_page"))
        raw = upload.stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            flash("migration_plan_too_large", "error")
            return redirect(url_for("migrations_page"))
        try:
            plan = json.loads(raw.decode("utf-8"))
            campaign_id = import_migration_plan(
                db,
                plan,
                name_override=request.form.get("name") or "",
            )
            add_log("info", "migrations", f"Migration plan imported: campaign_id={campaign_id}")
            flash("migration_plan_imported", "success")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        except Exception as exc:
            logger.exception("Migration plan import failed")
            add_log("error", "migrations", f"Migration plan import failed: {exc}")
            flash(str(exc), "error")
            return redirect(url_for("migrations_page"))

    @app.get("/migrations/<int:campaign_id>/plan")
    def migration_plan_export(campaign_id: int):
        db = get_db()
        try:
            plan = export_migration_plan(db, campaign_id)
        except Exception as exc:
            logger.exception("Migration plan export failed | campaign_id=%s", campaign_id)
            return jsonify({"ok": False, "error": str(exc)}), 404
        payload = json.dumps(plan, indent=2, sort_keys=True)
        return Response(
            payload,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="vodum-migration-plan-{campaign_id}.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/migrations/<int:campaign_id>")
    def migration_campaign_detail(campaign_id: int):
        db = get_db()
        requested_users_page = request.args.get("users_page", 1, type=int)
        requested_users_per_page = request.args.get("users_per_page", 20, type=int)
        campaign_row = get_campaign(db, campaign_id, with_server_details=True)
        if not campaign_row:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))

        campaign = normalize_campaign_detail(campaign_row)
        users, mapping_groups, destination_libraries = load_campaign_detail_relations(
            db,
            campaign_id,
            campaign["destination_server_id"],
        )
        summary = enrich_campaign_users(
            users,
            mapping_groups,
            safety_delay_days=campaign["safety_delay_days"],
        )

        (
            visible_users,
            users_page,
            users_per_page,
            users_total,
            users_total_pages,
        ) = paginate_campaign_users(
            users,
            requested_page=requested_users_page,
            requested_per_page=requested_users_per_page,
        )

        return render_template(
            "migrations/campaign_detail.html",
            active_page="migrations",
            campaign=campaign,
            users=visible_users,
            users_page=users_page,
            users_per_page=users_per_page,
            users_total=users_total,
            users_total_pages=users_total_pages,
            mappings=mapping_groups,
            destination_libraries=destination_libraries,
            summary=summary,
        )

    @app.post("/migrations/<int:campaign_id>/edit")
    def migration_draft_edit(campaign_id: int):
        db = get_db()
        try:
            update_migration_draft(
                db,
                campaign_id,
                name=request.form.get("name") or "",
                mapping_overrides=mapping_overrides_from_form(request.form),
                safety_delay_days=request.form.get("safety_delay_days", type=int) if request.form.get("safety_delay_days", type=int) is not None else 7,
                scheduled_at=request.form.get("scheduled_at") or "",
                batch_size=request.form.get("batch_size", type=int) or 10,
                intent=request.form.get("intent") or "copy",
                jellyfin_password_strategy=request.form.get("jellyfin_password_strategy") or "generated",
                jellyfin_temp_password=request.form.get("jellyfin_temp_password") or "",
                jellyfin_auto_deliver_credentials=bool(request.form.get("jellyfin_auto_deliver_credentials")),
            )
            add_log("info", "migrations", f"Migration draft edited: campaign_id={campaign_id}")
            flash("migration_draft_updated", "success")
        except Exception as exc:
            add_log("error", "migrations", f"Migration draft edit failed: campaign_id={campaign_id} error={exc}")
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/delete")
    def migration_draft_delete(campaign_id: int):
        db = get_db()
        campaign = db.query_one("SELECT name,status FROM migration_campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        if request.form.get("confirm_delete") != "1":
            flash("migration_delete_confirmation_required", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            delete_migration_draft(db, campaign_id)
            add_log("warning", "migrations", f"Migration draft deleted: campaign_id={campaign_id}")
            flash("migration_draft_deleted", "success")
            return redirect(url_for("migrations_page"))
        except Exception as exc:
            add_log("error", "migrations", f"Migration draft delete failed: campaign_id={campaign_id} error={exc}")
            flash(str(exc), "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/start")
    def migration_campaign_start(campaign_id: int):
        db = get_db()
        campaign = db.query_one(
            "SELECT id, status, source_server_id, destination_server_id, scheduled_at FROM migration_campaigns WHERE id = ?",
            (campaign_id,),
        )
        if not campaign:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        if campaign["status"] != "draft":
            flash("migration_campaign_cannot_start", "warning")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        pair_blocker = migration_pair_blocker(
            db,
            campaign["source_server_id"],
            campaign["destination_server_id"],
        )
        if pair_blocker:
            flash(f"migration_blocker.{pair_blocker}", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

        blocked = db.query_one(
            "SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=? AND eligibility='blocked'",
            (campaign_id,),
        )
        unmapped = db.query_one(
            "SELECT COUNT(*) AS total FROM migration_library_mappings WHERE campaign_id=? AND mapping_status='unmapped'",
            (campaign_id,),
        )
        if int(blocked["total"] or 0) > 0 or int(unmapped["total"] or 0) > 0:
            flash("migration_campaign_not_ready", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        actionable = db.query_one(
            "SELECT COUNT(*) AS total FROM migration_users WHERE campaign_id=? AND eligibility IN ('ready','already_present')",
            (campaign_id,),
        )
        if int(actionable["total"] or 0) == 0:
            flash("migration_campaign_no_users", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        if conflicting_active_users(db, campaign_id):
            flash("migration_campaign_conflict", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

        db.execute(
            """
            UPDATE migration_users
            SET status = 'pending',
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = ?
              AND eligibility IN ('ready','already_present')
              AND status IN ('pending','failed')
            """,
            (campaign_id,),
        )
        db.execute(
            """
            UPDATE migration_campaigns
            SET status=CASE
                  WHEN scheduled_at IS NOT NULL AND datetime(scheduled_at) > CURRENT_TIMESTAMP THEN 'scheduled'
                  ELSE 'running'
                END,
                started_at=CASE
                  WHEN scheduled_at IS NULL OR datetime(scheduled_at) <= CURRENT_TIMESTAMP
                    THEN COALESCE(started_at,CURRENT_TIMESTAMP)
                  ELSE started_at
                END,
                completed_at=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (campaign_id,),
        )
        refresh_campaign_status(db, campaign_id)
        enable_and_run_task_by_name("migration_worker")
        add_log("info", "migrations", f"Migration campaign started destination-only: campaign_id={campaign_id}")
        flash("migration_campaign_started", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/pause")
    def migration_campaign_pause(campaign_id: int):
        db = get_db()
        try:
            pause_campaign(db, campaign_id)
            add_log("warning", "migrations", f"Migration campaign paused: campaign_id={campaign_id}")
            flash("migration_campaign_paused", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/resume")
    def migration_campaign_resume(campaign_id: int):
        db = get_db()
        try:
            resume_campaign(db, campaign_id)
            enable_and_run_task_by_name("migration_worker")
            add_log("warning", "migrations", f"Migration campaign resumed: campaign_id={campaign_id}")
            flash("migration_campaign_resumed", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/retry-failed")
    def migration_campaign_retry_failed(campaign_id: int):
        db = get_db()
        try:
            count = retry_failed_users(db, campaign_id)
            if count:
                enable_and_run_task_by_name("migration_worker")
            add_log("warning", "migrations", f"Migration failed users retried: campaign_id={campaign_id} count={count}")
            flash("migration_failed_users_retried", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/users/<int:migration_user_id>/exclude")
    def migration_user_exclude(campaign_id: int, migration_user_id: int):
        db = get_db()
        try:
            set_user_excluded(db, campaign_id, migration_user_id, True)
            add_log("warning", "migrations", f"Migration user excluded: campaign_id={campaign_id} migration_user_id={migration_user_id}")
            flash("migration_user_excluded", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/users/<int:migration_user_id>/include")
    def migration_user_include(campaign_id: int, migration_user_id: int):
        db = get_db()
        try:
            set_user_excluded(db, campaign_id, migration_user_id, False)
            add_log("warning", "migrations", f"Migration user included: campaign_id={campaign_id} migration_user_id={migration_user_id}")
            flash("migration_user_included", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/users/<int:migration_user_id>/mapping-overrides")
    def migration_user_mapping_overrides(campaign_id: int, migration_user_id: int):
        db = get_db()
        row = db.query_one(
            """
            SELECT mu.id, mu.options_json, mc.status AS campaign_status
            FROM migration_users mu
            JOIN migration_campaigns mc ON mc.id = mu.campaign_id
            WHERE mu.id = ? AND mu.campaign_id = ?
            """,
            (migration_user_id, campaign_id),
        )
        if not row:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        if row["campaign_status"] != "draft":
            flash("migration_campaign_cannot_start", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            options = json.loads(row["options_json"] or "{}")
        except Exception:
            options = {}
        overrides = mapping_overrides_from_form(request.form, prefix="user_library_mapping_")
        options["library_mapping_overrides"] = {
            str(source_id): destination_ids
            for source_id, destination_ids in sorted(overrides.items())
        }
        db.execute(
            "UPDATE migration_users SET options_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(options), migration_user_id),
        )
        add_log("info", "migrations", f"Migration user mapping overrides saved: campaign_id={campaign_id} migration_user_id={migration_user_id}")
        flash("migration_user_mapping_overrides_saved", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/exclude-blocked")
    def migration_exclude_blocked_users(campaign_id: int):
        db = get_db()
        campaign = db.query_one("SELECT status FROM migration_campaigns WHERE id=?", (campaign_id,))
        if not campaign or campaign["status"] != "draft":
            flash("migration_campaign_cannot_start", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        rows = db.query(
            "SELECT id FROM migration_users WHERE campaign_id=? AND eligibility='blocked'",
            (campaign_id,),
        )
        excluded = 0
        for row in rows:
            try:
                set_user_excluded(db, campaign_id, int(row["id"]), True)
                excluded += 1
            except Exception:
                continue
        add_log("warning", "migrations", f"Blocked migration users excluded: campaign_id={campaign_id} count={excluded}")
        flash("migration_blocked_users_excluded", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/check-invitations")
    def migration_campaign_check_invitations(campaign_id: int):
        db = get_db()
        campaign = db.query_one(
            "SELECT id, status FROM migration_campaigns WHERE id=?",
            (campaign_id,),
        )
        if not campaign:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        db.execute(
            """
            UPDATE migration_users
            SET updated_at=datetime('now','-11 minutes')
            WHERE campaign_id=? AND status='waiting_acceptance'
            """,
            (campaign_id,),
        )
        enable_and_run_task_by_name("migration_worker")
        add_log("info", "migrations", f"Manual Plex invitation reconciliation requested: campaign_id={campaign_id}")
        flash("migration_invitation_check_started", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/users/<int:migration_user_id>/validate")
    def migration_user_validate(campaign_id: int, migration_user_id: int):
        db = get_db()
        row = db.query_one(
            "SELECT status,result_json FROM migration_users WHERE id=? AND campaign_id=?",
            (migration_user_id, campaign_id),
        )
        if not row or row["status"] != "waiting_validation":
            flash("migration_validation_not_available", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            result = json.loads(row["result_json"] or "{}")
        except Exception:
            result = {}
        result["destination_validated_at"] = result.get("destination_validated_at") or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        result["destination_validation_method"] = result.get("destination_validation_method") or "manual"
        db.execute(
            "UPDATE migration_users SET status='completed',result_json=?,completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result), migration_user_id),
        )
        refresh_campaign_status(db, campaign_id)
        add_log("warning", "migrations", f"Migration destination manually validated: campaign_id={campaign_id} migration_user_id={migration_user_id}")
        flash("migration_destination_validated", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    def _phase3_confirmed_campaign(db, campaign_id: int):
        campaign = db.query_one("SELECT id,name,source_server_id,destination_server_id,intent FROM migration_campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            return None
        if (request.form.get("confirmation") or "").strip() != (campaign["name"] or "").strip():
            return False
        return campaign

    @app.post("/migrations/<int:campaign_id>/remove-source-access")
    def migration_remove_source_access(campaign_id: int):
        db = get_db()
        campaign = _phase3_confirmed_campaign(db, campaign_id)
        if campaign is None:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        if campaign is False:
            flash("migration_confirmation_mismatch", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        if campaign["intent"] == "copy":
            flash("migration_copy_has_no_source_removal", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            result = remove_validated_source_access(db, campaign_id)
        except Exception as exc:
            add_log("error", "migrations", f"Migration source access removal failed: campaign_id={campaign_id} error={exc}")
            flash(str(exc), "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        source = db.query_one("SELECT type FROM servers WHERE id=?", (campaign["source_server_id"],))
        if result["queued"] and source:
            enable_and_run_task_by_name("apply_plex_access_updates" if source["type"] == "plex" else "apply_jellyfin_access_updates")
            enable_and_run_task_by_name("migration_worker")
        add_log("warning", "migrations", f"Migration source access removal requested: campaign_id={campaign_id} result={result}")
        flash("migration_source_removal_requested", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/rollback-source-access")
    def migration_rollback_source_access(campaign_id: int):
        db = get_db()
        campaign = _phase3_confirmed_campaign(db, campaign_id)
        if campaign is None:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        if campaign is False:
            flash("migration_confirmation_mismatch", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            result = rollback_source_access(db, campaign_id)
        except Exception as exc:
            add_log("error", "migrations", f"Migration source access rollback failed: campaign_id={campaign_id} error={exc}")
            flash(str(exc), "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        source = db.query_one("SELECT type FROM servers WHERE id=?", (campaign["source_server_id"],))
        if result["queued"] and source:
            enable_and_run_task_by_name("apply_plex_access_updates" if source["type"] == "plex" else "apply_jellyfin_access_updates")
            enable_and_run_task_by_name("migration_worker")
        add_log("warning", "migrations", f"Migration source access rollback requested: campaign_id={campaign_id} result={result}")
        flash("migration_source_rollback_requested", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.post("/migrations/<int:campaign_id>/rollback-destination-access")
    def migration_rollback_destination_access(campaign_id: int):
        db = get_db()
        campaign = _phase3_confirmed_campaign(db, campaign_id)
        if campaign is None:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))
        if campaign is False:
            flash("migration_confirmation_mismatch", "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        try:
            result = rollback_destination_access(db, campaign_id)
        except Exception as exc:
            add_log("error", "migrations", f"Migration destination access rollback failed: campaign_id={campaign_id} error={exc}")
            flash(str(exc), "error")
            return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))
        destination = db.query_one("SELECT type FROM servers WHERE id=?", (campaign["destination_server_id"],))
        if result["queued"] and destination:
            enable_and_run_task_by_name("apply_plex_access_updates" if destination["type"] == "plex" else "apply_jellyfin_access_updates")
            enable_and_run_task_by_name("migration_worker")
        add_log("warning", "migrations", f"Migration destination access rollback requested: campaign_id={campaign_id} result={result}")
        flash("migration_destination_rollback_requested", "success")
        return redirect(url_for("migration_campaign_detail", campaign_id=campaign_id))

    @app.get("/migrations/<int:campaign_id>/report")
    def migration_campaign_report(campaign_id: int):
        db = get_db()
        campaign = get_campaign(db, campaign_id)
        if not campaign:
            return jsonify({"ok": False, "error": "not_found"}), 404
        users = load_report_users(db, campaign_id)
        return jsonify(build_migration_report(campaign, users))

    @app.post("/migrations/<int:campaign_id>/users/<int:migration_user_id>/credentials")
    def migration_user_credentials(campaign_id: int, migration_user_id: int):
        db = get_db()
        row = db.query_one(
            """
            SELECT mu.result_json, vu.username
            FROM migration_users mu
            JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            WHERE mu.id = ? AND mu.campaign_id = ?
            """,
            (migration_user_id, campaign_id),
        )
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404
        try:
            result = json.loads(row["result_json"] or "{}")
        except Exception:
            result = {}
        encrypted = result.get("encrypted_generated_password")
        if not encrypted:
            return jsonify({"ok": False, "error": "credentials_unavailable"}), 404
        expires_at = str(result.get("credentials_expires_at") or "")
        if expires_at and expires_at <= datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"):
            result.pop("encrypted_generated_password", None)
            result["credentials_expired_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            result["credentials_pending_delivery"] = False
            db.execute("UPDATE migration_users SET result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(result), migration_user_id))
            return jsonify({"ok": False, "error": "credentials_expired"}), 410
        password = decrypt_secret(encrypted)
        result["credentials_revealed_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        result["credentials_pending_delivery"] = False
        db.execute("UPDATE migration_users SET result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(result), migration_user_id))
        add_log(
            "warning",
            "migrations",
            f"Generated Jellyfin migration password revealed: campaign_id={campaign_id} migration_user_id={migration_user_id}",
        )
        return jsonify({"ok": True, "username": row["username"] or "", "password": password})
