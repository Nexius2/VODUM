# Auto-split from app.py (keep URLs/endpoints intact)
from flask import (
    render_template, request, url_for, make_response,
)
from core.monitoring.overview_aggregates import build_monitoring_overview_aggregates
from core.monitoring.overview_servers import (
    load_monitoring_server_context,
    load_monitoring_servers_tab,
)
from core.monitoring.overview_live import load_monitoring_live_context
from core.monitoring.overview_activity import load_recent_monitoring_events
from core.monitoring.overview_history import load_monitoring_history
from core.monitoring.overview_libraries import (
    build_monitoring_library_options,
    build_monitoring_library_pagination,
    load_monitoring_library_top_cards,
    load_monitoring_library_table,
    load_monitoring_library_users,
)
from core.monitoring.overview_usage_risk import load_usage_risk_context
from core.monitoring.overview_users import (
    build_monitoring_users_options,
    build_monitoring_users_pagination,
    load_monitoring_users_rows,
    load_monitoring_users_total,
)
from core.monitoring.overview_policies import (
    load_policy_catalog,
    load_policy_breakdowns,
    load_policy_dashboard,
    load_policy_enforcement_pagination,
    load_grouped_policy_enforcements,
    load_policy_tracked_state,
    load_policy_hits_timeline,
    load_policy_top_users,
    load_recent_policy_enforcements,
)
from logging_utils import get_logger
from web.helpers import get_db
from .monitoring_enforcements import register as register_enforcement_routes

monitoring_logger = get_logger("monitoring_overview")

def register(app):
    register_enforcement_routes(app)

    @app.route("/monitoring")
    def monitoring_page():
        db = get_db()
        tab = request.args.get("tab", "overview")

        # Une session est consideree "live" si vue dans les 120 dernieres secondes
        live_window_seconds = 300
        live_window_sql = f"-{live_window_seconds} seconds"

        server_context = load_monitoring_server_context(db, tab)
        servers = server_context["servers"]
        configured_server_count = server_context["configured_server_count"]
        server_resource_stats = server_context["server_resource_stats"]
        server_stats = server_context["server_stats"]
        live_context = load_monitoring_live_context(
            db,
            tab,
            server_resource_stats,
            live_window_seconds=live_window_seconds,
        )
        sessions_stats = live_context["sessions_stats"]
        live_servers = live_context["live_servers"]
        sessions = live_context["sessions"]
        events = load_recent_monitoring_events(db, tab)
        stats_7d = {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
        top_users_30d = []
        top_content_30d = []
        top_movies_30d = []
        concurrent_7d = {"peak_streams": 0}
        # --------------------------
        # Donnees overview uniquement
        # --------------------------
        if tab == "overview":
            overview_aggregates = build_monitoring_overview_aggregates(db, sessions_stats)
            stats_7d = overview_aggregates["stats_7d"]
            top_users_30d = overview_aggregates["top_users_30d"]
            top_content_30d = overview_aggregates["top_content_30d"]
            top_movies_30d = overview_aggregates["top_movies_30d"]
            concurrent_7d = overview_aggregates["concurrent_7d"]

        sort_key = None
        sort_dir = None


        # --------------------------
        # Tabs data
        # --------------------------
        policies = []
        rows = []
        filters = {}
        pagination = None
        library_top_cards = []
        library_users = []
        library_range = "30d"
        library_user = "all"
        hidden_libraries_count = 0

        policy_dashboard = {}
        policy_hits_30d = []
        policy_rule_breakdown_30d = []
        policy_provider_breakdown_30d = []
        policy_scope_breakdown = {}
        policy_top_users_30d = []
        policy_recent_enforcements = []
        policy_enforcement_page = 1
        policy_enforcement_per_page = 20
        policy_enforcement_total_pages = 1
        policy_enforcement_total = 0
        policy_grouped_enforcements = []
        policy_tracked_state = {}

        usage_risk_report = {
            "enabled": True,
            "summary": {"high": 0, "medium": 0, "low": 0, "suggested": 0},
            "rows": [],
            "filters": {},
        }
        usage_risk_filters = {}
        subscription_templates = []
        stream_policy_types = []
        

        if tab == "history":
            def build_url(p):
                args = dict(request.args)
                args["tab"] = "history"
                args["page"] = p
                return url_for("monitoring_page", **args)

            history_context = load_monitoring_history(
                db,
                request.args,
                request.cookies,
                build_url,
            )
            rows = history_context["rows"]
            filters = history_context["filters"]
            pagination = history_context["pagination"]
            sort_key = history_context["sort_key"]
            sort_dir = history_context["sort_dir"]

        elif tab == "usage_risk":
            usage_risk_context = load_usage_risk_context(db, request.args)
            usage_risk_filters = usage_risk_context["usage_risk_filters"]
            usage_risk_report = usage_risk_context["usage_risk_report"]
            subscription_templates = usage_risk_context["subscription_templates"]
            stream_policy_types = usage_risk_context["stream_policy_types"]
        elif tab == "users":
            user_options = build_monitoring_users_options(request.args, request.cookies)
            q = user_options["q"]
            sort_key = user_options["sort_key"]
            sort_dir = user_options["sort_dir"]

            total_rows = load_monitoring_users_total(db, q)

            rows = load_monitoring_users_rows(db, user_options)

            # Pagination
            def build_url(p):
                args = dict(request.args)
                args["tab"] = "users"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = build_monitoring_users_pagination(
                total_rows,
                user_options,
                build_url,
            )

        elif tab == "policies":
            enforcement_pagination = load_policy_enforcement_pagination(
                db,
                request.args,
            )
            policy_enforcement_page = enforcement_pagination["page"]
            policy_enforcement_per_page = enforcement_pagination["per_page"]
            policy_enforcement_total = enforcement_pagination["total"]
            policy_enforcement_total_pages = enforcement_pagination["total_pages"]

            edit_policy_id = request.args.get("edit_policy_id", type=int)
            policy_catalog = load_policy_catalog(db, edit_policy_id)
            policies = policy_catalog["policies"]
            edit_policy = policy_catalog["edit_policy"]

            policy_dashboard = load_policy_dashboard(db, policy_catalog)

            policy_breakdowns = load_policy_breakdowns(db)
            policy_scope_breakdown = policy_breakdowns[
                "policy_scope_breakdown"
            ]
            policy_provider_breakdown_30d = policy_breakdowns[
                "policy_provider_breakdown_30d"
            ]
            policy_rule_breakdown_30d = policy_breakdowns[
                "policy_rule_breakdown_30d"
            ]

            policy_top_users_30d = load_policy_top_users(db)

            policy_recent_enforcements = load_recent_policy_enforcements(
                db,
                enforcement_pagination,
            )
            policy_grouped_enforcements = load_grouped_policy_enforcements(db)
            policy_tracked_state = load_policy_tracked_state(db)

            policy_hits_30d = load_policy_hits_timeline(db)



        elif tab == "libraries":
            library_options = build_monitoring_library_options(
                request.args,
                request.cookies,
            )
            library_range = library_options["library_range"]
            library_user = library_options["library_user"]
            library_user_id = library_options["library_user_id"]
            sort_key = library_options["sort_key"]
            sort_dir = library_options["sort_dir"]

            library_table = load_monitoring_library_table(db, library_options)
            rows = library_table["rows"]
            total_rows = library_table["total_rows"]
            hidden_libraries_count = library_table["hidden_libraries_count"]
            def build_url(p):
                args = dict(request.args)
                args["tab"] = "libraries"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = build_monitoring_library_pagination(
                total_rows,
                library_options,
                build_url,
            )

            library_users = load_monitoring_library_users(db)

            library_top_cards = load_monitoring_library_top_cards(
                db,
                library_options,
            )

        server_range = request.args.get("range", "7d")
        servers_combined = None
        servers_details = None
        servers_sessions_day = None
        servers_media_types = None
        servers_clients = None
        servers_top_users = None
        servers_top_titles = None
        servers_unique_ips = None

        if tab == "servers":
            servers_tab = load_monitoring_servers_tab(
                db,
                request.args,
                live_window_sql,
                server_resource_stats,
            )
            server_range = servers_tab["server_range"]
            servers_combined = servers_tab["servers_combined"]
            servers_details = servers_tab["servers_details"]
            servers_sessions_day = servers_tab["servers_sessions_day"]
            servers_media_types = servers_tab["servers_media_types"]
            servers_clients = servers_tab["servers_clients"]
            servers_top_users = servers_tab["servers_top_users"]
            servers_top_titles = servers_tab["servers_top_titles"]
            servers_unique_ips = servers_tab["servers_unique_ips"]


        # ------------------------------------------------------------------
        # HTMX: une requete dynamique renvoie uniquement le contenu de l'onglet
        # ------------------------------------------------------------------
        is_hx = bool(request.headers.get("HX-Request"))
        if is_hx:
            tab_tpl = {
                "overview": "monitoring/overview_body.html",
                "now_playing": "monitoring/tabs/now_playing.html",
                "policies": "monitoring/tabs/policies.html",
                "usage_risk": "monitoring/tabs/usage_risk.html",
                "activity": "monitoring/tabs/activity.html",
                "history": "monitoring/tabs/history.html",
                "libraries": "monitoring/tabs/libraries.html",
                "users": "monitoring/tabs/users.html",
                "servers": "monitoring/tabs/servers.html",
            }.get(tab, "monitoring/overview_body.html")

            resp = make_response(render_template(
                tab_tpl,
                active_page="monitoring",
                tab=tab,
                servers=servers,
                configured_server_count=configured_server_count,
                server_stats=server_stats,
                sessions_stats=sessions_stats,
                live_servers=live_servers,
                sessions=sessions,
                events=events,
                live_window_seconds=live_window_seconds,
                stats_7d=stats_7d,
                top_users_30d=top_users_30d,
                top_content_30d=top_content_30d,
                top_movies_30d=top_movies_30d,
                concurrent_7d=concurrent_7d,
                rows=rows,
                filters=filters,
                pagination=pagination,
                sort_key=sort_key,
                sort_dir=sort_dir,
                policies=policies,
                edit_policy=locals().get('edit_policy'),
                server_range=server_range,
                servers_combined=servers_combined,
                servers_details=servers_details,
                servers_sessions_day=servers_sessions_day,
                servers_media_types=servers_media_types,
                servers_clients=servers_clients,
                servers_top_users=servers_top_users,
                servers_top_titles=servers_top_titles,
                servers_unique_ips=servers_unique_ips,
                library_top_cards=library_top_cards,
                library_users=library_users,
                library_range=library_range,
                library_user=library_user,
                hidden_libraries_count=hidden_libraries_count,
                policy_dashboard=policy_dashboard,
                policy_hits_30d=policy_hits_30d,
                policy_rule_breakdown_30d=policy_rule_breakdown_30d,
                policy_provider_breakdown_30d=policy_provider_breakdown_30d,
                policy_scope_breakdown=policy_scope_breakdown,
                policy_top_users_30d=policy_top_users_30d,
                policy_recent_enforcements=policy_recent_enforcements,
                policy_enforcement_page=policy_enforcement_page,
                policy_enforcement_per_page=policy_enforcement_per_page,
                policy_enforcement_total_pages=policy_enforcement_total_pages,
                policy_enforcement_total=policy_enforcement_total,
                policy_grouped_enforcements=policy_grouped_enforcements,
                policy_tracked_state=policy_tracked_state,
                usage_risk_report=usage_risk_report,
                usage_risk_filters=usage_risk_filters,
                subscription_templates=subscription_templates,
                stream_policy_types=stream_policy_types,
            ))
            if sort_key and sort_dir:
                resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
                resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)

            return resp

        # Page complete (chargement normal)
        resp = make_response(render_template(
            "monitoring/monitoring.html",
            active_page="monitoring",
            tab=tab,
            servers=servers,
            configured_server_count=configured_server_count,
            server_stats=server_stats,
            sessions_stats=sessions_stats,
            live_servers=live_servers,
            sessions=sessions,
            events=events,
            live_window_seconds=live_window_seconds,
            stats_7d=stats_7d,
            top_users_30d=top_users_30d,
            top_content_30d=top_content_30d,
            top_movies_30d=top_movies_30d,
            concurrent_7d=concurrent_7d,
            rows=rows,
            filters=filters,
            pagination=pagination,
            sort_key=sort_key,
            sort_dir=sort_dir,
            policies=policies,
            edit_policy=locals().get('edit_policy'),
            server_range=server_range,
            servers_combined=servers_combined,
            servers_details=servers_details,
            servers_sessions_day=servers_sessions_day,
            servers_media_types=servers_media_types,
            servers_clients=servers_clients,
            servers_top_users=servers_top_users,
            servers_top_titles=servers_top_titles,
            servers_unique_ips=servers_unique_ips,
            library_top_cards=library_top_cards,
            library_users=library_users,
            library_range=library_range,
            library_user=library_user,
            hidden_libraries_count=hidden_libraries_count,
            policy_dashboard=policy_dashboard,
            policy_hits_30d=policy_hits_30d,
            policy_rule_breakdown_30d=policy_rule_breakdown_30d,
            policy_provider_breakdown_30d=policy_provider_breakdown_30d,
            policy_scope_breakdown=policy_scope_breakdown,
            policy_top_users_30d=policy_top_users_30d,
            policy_recent_enforcements=policy_recent_enforcements,
            policy_enforcement_page=policy_enforcement_page,
            policy_enforcement_per_page=policy_enforcement_per_page,
            policy_enforcement_total_pages=policy_enforcement_total_pages,
            policy_enforcement_total=policy_enforcement_total,
            policy_grouped_enforcements=policy_grouped_enforcements,
            policy_tracked_state=policy_tracked_state,
            usage_risk_report=usage_risk_report,
            usage_risk_filters=usage_risk_filters,
            subscription_templates=subscription_templates,
            stream_policy_types=stream_policy_types,
        ))
        
        if sort_key and sort_dir:
            resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
            resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)
        return resp
