import json
from datetime import datetime, timedelta

from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from core.migrations.analysis import (
    SUPPORTED_PROVIDERS,
    analyze_migration,
    is_server_online,
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
from core.migrations.phase3 import remove_validated_source_access, rollback_source_access
from tasks_engine import enable_and_run_task_by_name
from secret_store import decrypt_secret
from web.helpers import add_log, get_db, table_exists


def _online_migration_servers(db) -> list[dict]:
    return [
        dict(row)
        for row in db.query(
            """
            SELECT id, name, type, status, last_checked
            FROM servers
            ORDER BY lower(name), id
            """
        )
        if str(row["type"] or "").strip().lower() in SUPPORTED_PROVIDERS
        and is_server_online(row["status"])
    ]


def _mapping_overrides_from_form() -> dict[int, int | None]:
    overrides = {}
    prefix = "library_mapping_"
    for key, value in request.form.items():
        if not key.startswith(prefix):
            continue
        try:
            source_library_id = int(key[len(prefix):])
            overrides[source_library_id] = int(value) if str(value).strip() else None
        except (TypeError, ValueError):
            continue
    return overrides


def register(app):
    @app.get("/migrations")
    def migrations_page():
        db = get_db()
        servers = _online_migration_servers(db)
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

        campaign_counts = {
            "active": 0,
            "completed": 0,
            "needs_attention": 0,
            "waiting_users": 0,
            "blocked_users": 0,
        }
        campaign_rows = []
        campaigns = []
        if table_exists(db, "migration_campaigns"):
            campaign_rows = db.query(
                """
                SELECT status, COUNT(*) AS total
                FROM migration_campaigns
                GROUP BY status
                """
            )
            campaigns = [
                dict(row)
                for row in db.query(
                    """
                    SELECT
                      mc.id, mc.name, mc.migration_type, mc.migration_mode,
                      mc.status, mc.created_at,
                      source.name AS source_name,
                      destination.name AS destination_name,
                      COUNT(DISTINCT mu.id) AS users_count
                    FROM migration_campaigns mc
                    JOIN servers source ON source.id = mc.source_server_id
                    JOIN servers destination ON destination.id = mc.destination_server_id
                    LEFT JOIN migration_users mu ON mu.campaign_id = mc.id
                    GROUP BY mc.id
                    ORDER BY mc.updated_at DESC, mc.id DESC
                    LIMIT 20
                    """
                )
            ]
            user_counts = db.query_one(
                """
                SELECT
                  SUM(CASE WHEN status IN ('waiting_acceptance','waiting_validation') THEN 1 ELSE 0 END) AS waiting_users,
                  SUM(CASE WHEN eligibility='blocked' THEN 1 ELSE 0 END) AS blocked_users
                FROM migration_users
                """
            )
            if user_counts:
                campaign_counts["waiting_users"] = int(user_counts["waiting_users"] or 0)
                campaign_counts["blocked_users"] = int(user_counts["blocked_users"] or 0)
        for row in campaign_rows:
            status = str(row["status"] or "")
            total = int(row["total"] or 0)
            if status == "completed":
                campaign_counts["completed"] += total
            elif status in ("needs_attention", "failed"):
                campaign_counts["needs_attention"] += total
            elif status in ("scheduled", "running", "paused", "waiting_users"):
                campaign_counts["active"] += total

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
        servers = _online_migration_servers(db)
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

        mapping_overrides = _mapping_overrides_from_form()

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
            add_log("error", "migrations", f"Migration plan import failed: {exc}")
            flash(str(exc), "error")
            return redirect(url_for("migrations_page"))

    @app.get("/migrations/<int:campaign_id>/plan")
    def migration_plan_export(campaign_id: int):
        db = get_db()
        try:
            plan = export_migration_plan(db, campaign_id)
        except Exception as exc:
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
        campaign_row = db.query_one(
            """
            SELECT
              mc.*,
              source.name AS source_name,
              source.type AS source_type,
              destination.name AS destination_name,
              destination.type AS destination_type
            FROM migration_campaigns mc
            JOIN servers source ON source.id = mc.source_server_id
            JOIN servers destination ON destination.id = mc.destination_server_id
            WHERE mc.id = ?
            """,
            (campaign_id,),
        )
        if not campaign_row:
            flash("migration_campaign_not_found", "error")
            return redirect(url_for("migrations_page"))

        campaign = dict(campaign_row)
        try:
            campaign_options = json.loads(campaign.get("options_json") or "{}")
        except Exception:
            campaign_options = {}
        campaign["safety_delay_days"] = max(0, int(campaign_options.get("safety_delay_days", 7)))
        scheduled_raw = str(campaign.get("scheduled_at") or "")
        campaign["scheduled_at_input"] = (
            f"{scheduled_raw[:10]}T{scheduled_raw[11:16]}"
            if len(scheduled_raw) >= 16 and scheduled_raw[10:11] == " "
            else scheduled_raw[:16]
        )
        users = [
            dict(row)
            for row in db.query(
                """
                SELECT
                  mu.*, vu.username, vu.email, vu.status AS vodum_status
                FROM migration_users mu
                JOIN vodum_users vu ON vu.id = mu.vodum_user_id
                WHERE mu.campaign_id = ?
                ORDER BY
                  CASE mu.eligibility
                    WHEN 'blocked' THEN 0
                    WHEN 'ready' THEN 1
                    ELSE 2
                  END,
                  lower(COALESCE(vu.username, '')),
                  mu.id
                """,
                (campaign_id,),
            )
        ]
        mappings = [
            dict(row)
            for row in db.query(
                """
                SELECT
                  mlm.*,
                  source.name AS source_name,
                  source.type AS source_type,
                  destination.name AS destination_name,
                  destination.type AS destination_type
                FROM migration_library_mappings mlm
                JOIN libraries source ON source.id = mlm.source_library_id
                LEFT JOIN libraries destination ON destination.id = mlm.destination_library_id
                WHERE mlm.campaign_id = ?
                ORDER BY lower(source.name), mlm.id
                """,
                (campaign_id,),
            )
        ]
        destination_libraries = [
            dict(row)
            for row in db.query(
                "SELECT id,name,type,section_id FROM libraries WHERE server_id=? ORDER BY lower(name),id",
                (campaign["destination_server_id"],),
            )
        ]
        summary = {
            "total": len(users),
            "ready": sum(1 for user in users if user["eligibility"] == "ready"),
            "blocked": sum(1 for user in users if user["eligibility"] == "blocked"),
            "already_present": sum(1 for user in users if user["eligibility"] == "already_present"),
            "unmapped": sum(1 for mapping in mappings if mapping["mapping_status"] == "unmapped"),
            "failed": sum(1 for user in users if user["status"] == "failed"),
            "excluded": sum(1 for user in users if user["status"] == "excluded"),
        }
        for user in users:
            try:
                user["blockers"] = json.loads(user.get("blockers_json") or "[]")
            except Exception:
                user["blockers"] = []
            try:
                result = json.loads(user.get("result_json") or "{}")
            except Exception:
                result = {}
            user["has_credentials"] = bool(result.get("encrypted_generated_password"))
            user["plex_invited_at"] = result.get("plex_invited_at")
            user["plex_last_checked_at"] = result.get("plex_last_checked_at")
            user["plex_accepted_at"] = result.get("plex_accepted_at")
            user["plex_last_reminder_at"] = result.get("plex_last_reminder_at")
            user["plex_reminder_count"] = int(result.get("plex_reminder_count") or 0)
            user["destination_validated_at"] = result.get("destination_validated_at")
            user["source_removed_at"] = result.get("source_removed_at")
            user["source_removal_requested_at"] = result.get("source_removal_requested_at")
            user["source_restored_at"] = result.get("source_restored_at")
            user["source_restoration_requested_at"] = result.get("source_restoration_requested_at")
            user["source_removal_job_status"] = result.get("source_removal_job_status")
            user["source_removal_job_error"] = result.get("source_removal_job_error")
            user["source_restoration_job_status"] = result.get("source_restoration_job_status")
            user["source_restoration_job_error"] = result.get("source_restoration_job_error")
            user["destination_validation_method"] = result.get("destination_validation_method")
            user["source_removal_available_at"] = None
            if user["destination_validated_at"]:
                try:
                    user["source_removal_available_at"] = (
                        datetime.strptime(user["destination_validated_at"][:19], "%Y-%m-%d %H:%M:%S")
                        + timedelta(days=campaign["safety_delay_days"])
                    ).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
        summary["validated"] = sum(1 for user in users if user.get("destination_validated_at"))
        summary["source_removed"] = sum(1 for user in users if user.get("source_removed_at"))
        summary["source_removal_requested"] = sum(1 for user in users if user.get("source_removal_requested_at"))
        summary["removal_ready"] = sum(
            1 for user in users
            if user.get("source_removal_available_at")
            and user["source_removal_available_at"] <= datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            and not user.get("source_removed_at")
            and not (
                user.get("source_removal_requested_at")
                and user.get("source_removal_job_status") in ("queued", "running", "success")
            )
        )

        return render_template(
            "migrations/campaign_detail.html",
            active_page="migrations",
            campaign=campaign,
            users=users,
            mappings=mappings,
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
                mapping_overrides=_mapping_overrides_from_form(),
                safety_delay_days=request.form.get("safety_delay_days", type=int) if request.form.get("safety_delay_days", type=int) is not None else 7,
                scheduled_at=request.form.get("scheduled_at") or "",
                batch_size=request.form.get("batch_size", type=int) or 10,
                intent=request.form.get("intent") or "copy",
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
        campaign = db.query_one("SELECT id,name,source_server_id,intent FROM migration_campaigns WHERE id=?", (campaign_id,))
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

    @app.get("/migrations/<int:campaign_id>/report")
    def migration_campaign_report(campaign_id: int):
        db = get_db()
        campaign = db.query_one("SELECT * FROM migration_campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            return jsonify({"ok": False, "error": "not_found"}), 404
        users = [dict(row) for row in db.query(
            "SELECT id,vodum_user_id,status,eligibility,attempts,last_error,result_json,source_snapshot_json FROM migration_users WHERE campaign_id=? ORDER BY id",
            (campaign_id,),
        )]
        for user in users:
            try:
                result = json.loads(user.get("result_json") or "{}")
            except Exception:
                result = {}
            result.pop("encrypted_generated_password", None)
            user["result"] = result
            user.pop("result_json", None)
        status_counts = {}
        report_summary = {
            "users": len(users),
            "statuses": status_counts,
            "validated": 0,
            "source_removal_requested": 0,
            "source_removed": 0,
            "source_restored": 0,
            "provider_job_errors": 0,
        }
        for user in users:
            status_counts[user["status"]] = status_counts.get(user["status"], 0) + 1
            result = user.get("result") or {}
            report_summary["validated"] += int(bool(result.get("destination_validated_at")))
            report_summary["source_removal_requested"] += int(bool(result.get("source_removal_requested_at")))
            report_summary["source_removed"] += int(bool(result.get("source_removed_at")))
            report_summary["source_restored"] += int(bool(result.get("source_restored_at")))
            report_summary["provider_job_errors"] += int(
                bool(result.get("source_removal_job_error") or result.get("source_restoration_job_error"))
            )
        return jsonify({
            "ok": True,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "campaign": dict(campaign),
            "summary": report_summary,
            "users": users,
        })

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
