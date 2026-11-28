"""Anonymous feature-usage and capacity counters for telemetry schema v5.

Every value is a flat, non-negative integer: a count, a 0/1 flag or a small
bucket index. Nothing here may read or export names, addresses, URLs, IPs,
titles, free text, identifiers or per-user rows. Each counter is computed on
its own and falls back to 0 when a table or column does not exist yet, so an
older or partially migrated database never prevents the report from being sent.
"""
import sqlite3

from core.server_page_queries import LIBRARY_TYPE_SQL
from logging_utils import get_logger

log = get_logger("telemetry")

# Append-only allow-list: the worker validates the same names.
TELEMETRY_TASKS = (
    "apply_jellyfin_access_updates", "apply_plex_access_updates", "auto_backup", "check_mailing_status",
    "check_servers", "check_update", "cleanup_artwork_cache", "cleanup_backups", "cleanup_data_consistency",
    "cleanup_data_retention", "cleanup_tautulli_imports", "cleanup_unfriended", "db_integrity_check",
    "delete_expired_users", "disable_expired_users", "expired_subscription_manager", "import_tautulli",
    "materialize_monitoring_daily_stats", "media_jobs_worker", "migration_worker", "monitor_collect_sessions",
    "monitor_enqueue_refresh", "process_referral_rewards", "referral_cleanup", "refresh_collection_inventory",
    "refresh_dashboard_quote_cache", "refresh_library_growth", "refresh_monitoring_statistics",
    "refresh_usage_risk_recommendations", "run_collections", "send_comm_campaigns",
    "send_expiration_emails", "send_pending_invite_reminders", "stream_enforcer", "sync_jellyfin", "sync_plex",
    "update_user_status", "usage_risk_notifications", "warmup_artwork_cache",
)

# Stream policy rule type -> telemetry suffix (field names avoid identifying tokens such as "ip").
POLICY_RULE_FIELDS = {
    "max_streams_per_user": "streams_per_user", "max_streams_per_ip": "streams_per_connection",
    "max_ips_per_user": "connections_per_user", "max_streams_per_server": "streams_per_server",
    "max_transcodes_global": "transcodes_global", "max_transcodes_per_server": "transcodes_per_server",
    "max_bitrate_kbps": "bitrate_limit", "device_allowlist": "device_allowlist",
}

# Library size buckets (sum of item counts): 0 none, 1 <1k, 2 <10k, 3 <50k, 4 <200k, 5 200k+.
LIBRARY_ITEM_BUCKETS = (1_000, 10_000, 50_000, 200_000)

FEATURE_TELEMETRY_FIELDS = (
    # Capacity and real usage
    "radarr_servers", "sonarr_servers", "seerr_servers",
    "libraries_movie", "libraries_shows", "libraries_music", "libraries_other", "library_items_bucket",
    "media_accounts", "peak_streams_30d", "peak_transcodes_30d", "viewers_30d", "watch_hours_30d",
    "transcoded_sessions_30d", "sessions_movie_30d", "sessions_episode_30d", "sessions_track_30d",
    # Media requests
    "requests_backend_arr", "requests_backend_seerr", "requests_portal_visible", "requests_libraries",
    "requests_arr_routes", "requests_arr_conditions", "requests_quota_enabled",
    "requests_30d", "requests_movie_30d", "requests_series_30d", "requests_4k_30d",
    # Subscriptions, referrals and payments
    "referrals_enabled", "referral_rewards_enabled", "referrals_30d", "referrals_rewarded_30d",
    "gift_runs_30d", "payment_links", "payment_links_enabled",
    # User portal
    "portal_roles_custom", "portal_monitoring_visible", "portal_support_visible",
    "support_conversations_30d", "support_posts_30d", "activations_30d", "turnstile_admin",
    # Migrations
    "migration_campaigns", "migrations_completed_30d",
    # Server configuration and compliance
    "config_profiles", "config_groups", "config_profile_targets", "config_servers_checked",
    "config_servers_compliant", "config_servers_drift", "config_servers_partial",
    "config_servers_unreachable", "config_drift_settings", "config_exceptions",
    "config_deployments_30d", "config_changes_30d",
    # Imports and API
    "tautulli_imports", "api_keys_active", "api_keys_used_30d",
    # Communications
    "discord_bots", "discord_campaigns_30d", "comm_templates", "comm_templates_enabled",
    "comm_template_languages", "comm_attachments", "comm_campaigns_30d", "comm_scheduled_30d",
    "welcome_templates", "mail_campaigns_30d", "expiry_reminders_enabled", "notify_all_channels",
    "user_notification_choice",
    # Usage risk and stream policies
    "usage_risk_recommendations_30d",
    *("policy_rule_" + suffix for suffix in POLICY_RULE_FIELDS.values()), "policy_rule_other",
    # Collections (in addition to the schema v3 collection counters)
    "collection_lists_official", "collection_lists_custom", "collection_lists_enabled",
    "franchise_lists", "franchise_lists_custom", "collections_tmdb_configured",
    "collections_myanimelist_configured", "collections_people_choices", "collections_spotlight_runs_30d",
    # Security, installation, monitoring and retention
    "admin_totp_enabled", "admin_login_plex", "admin_login_jellyfin", "reverse_proxy", "secure_cookies",
    "wizard_completed", "plex_import_all_users", "skip_unused_accounts", "arr_monitoring_active",
    "backup_retention_days", "backup_retention_count", "data_retention_years", "log_retention_days",
    # Scheduled tasks enabled, one flag per allow-listed task
    *("task_" + task for task in TELEMETRY_TASKS),
)

MAX_COUNTER = 10_000_000


class _Reader:
    """Read-only helper that turns any missing table or column into 0."""

    def __init__(self, db):
        self.db = db
        self._columns = {}

    def columns(self, table):
        if table not in self._columns:
            try:
                rows = self.db.query(f"PRAGMA table_info({table})") or []
                self._columns[table] = {row["name"] if hasattr(row, "keys") else row[1] for row in rows}
            except Exception:
                self._columns[table] = set()
        return self._columns[table]

    def has(self, table, *columns):
        available = self.columns(table)
        return bool(available) and all(column in available for column in columns)

    def row(self, sql, *tables):
        if not all(self.has(table) for table in tables):
            return {}
        try:
            row = self.db.query_one(sql)
            return dict(row) if row else {}
        except (sqlite3.Error, TypeError, ValueError) as exc:
            log.debug(f"Telemetry counter skipped: {type(exc).__name__}")
            return {}

    def value(self, sql, *tables):
        row = self.row(sql, *tables)
        return next(iter(row.values()), 0) if row else 0


def _int(value):
    try:
        return max(0, min(MAX_COUNTER, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _bucket(total, limits):
    total = _int(total)
    if total <= 0:
        return 0
    return 1 + sum(1 for limit in limits if total >= limit)


def _capacity(r, m):
    if r.has("servers", "type"):
        row = r.row("""SELECT SUM(LOWER(type)='radarr') AS radarr_servers, SUM(LOWER(type)='sonarr') AS sonarr_servers,
            SUM(LOWER(type)='seerr') AS seerr_servers FROM servers""", "servers")
        m.update(row)
    if r.has("libraries", "type", "item_count"):
        row = r.row(f"""SELECT SUM(t='movie') AS libraries_movie, SUM(t='shows') AS libraries_shows,
            SUM(t='music') AS libraries_music, SUM(t NOT IN ('movie','shows','music')) AS libraries_other,
            SUM(items) AS items
            FROM (SELECT {LIBRARY_TYPE_SQL} AS t, COALESCE(l.item_count,0) AS items FROM libraries l)""", "libraries")
        m["library_items_bucket"] = _bucket(row.pop("items", 0), LIBRARY_ITEM_BUCKETS)
        m.update(row)
    m["media_accounts"] = r.value("SELECT COUNT(*) FROM media_users", "media_users")
    if r.has("monitoring_snapshots", "ts", "live_sessions", "transcodes"):
        m.update(r.row("""SELECT MAX(live_sessions) AS peak_streams_30d, MAX(transcodes) AS peak_transcodes_30d
            FROM monitoring_snapshots WHERE ts >= datetime('now','-30 day')""", "monitoring_snapshots"))
    if r.has("media_session_history", "started_at", "watch_ms", "was_transcode", "media_type",
             "media_user_id", "external_user_id", "server_id"):
        m.update(r.row("""SELECT
                COUNT(DISTINCT COALESCE(CAST(media_user_id AS TEXT), server_id || ':' || external_user_id)) AS viewers_30d,
                CAST(SUM(watch_ms) / 3600000 AS INTEGER) AS watch_hours_30d,
                SUM(was_transcode=1) AS transcoded_sessions_30d,
                SUM(media_type='movie') AS sessions_movie_30d,
                SUM(media_type='episode') AS sessions_episode_30d,
                SUM(media_type='track') AS sessions_track_30d
            FROM media_session_history WHERE started_at >= datetime('now','-30 day')""", "media_session_history"))


def _requests(r, m, settings):
    backend = str(settings.get("portal_request_backend") or "").lower()
    m["requests_backend_arr"] = int(backend == "arr")
    m["requests_backend_seerr"] = int(backend == "seerr")
    m["requests_portal_visible"] = int(bool(settings.get("portal_show_media_requests")))
    m["requests_quota_enabled"] = int(bool(settings.get("portal_request_quota_enabled")))
    if r.has("library_request_settings", "requests_enabled"):
        m["requests_libraries"] = r.value(
            "SELECT COUNT(*) FROM library_request_settings WHERE requests_enabled=1", "library_request_settings")
    if r.has("library_arr_routes", "enabled"):
        m["requests_arr_routes"] = r.value("SELECT COUNT(*) FROM library_arr_routes WHERE enabled=1", "library_arr_routes")
    m["requests_arr_conditions"] = r.value("SELECT COUNT(*) FROM library_arr_conditions", "library_arr_conditions")
    if r.has("portal_media_request_jobs", "created_at", "kind"):
        four_k = "SUM(is_4k=1)" if r.has("portal_media_request_jobs", "is_4k") else "0"
        m.update(r.row(f"""SELECT COUNT(*) AS requests_30d, SUM(kind='movie') AS requests_movie_30d,
                SUM(kind='series') AS requests_series_30d, {four_k} AS requests_4k_30d
            FROM portal_media_request_jobs WHERE created_at >= datetime('now','-30 day')""", "portal_media_request_jobs"))


def _subscriptions(r, m, settings):
    if r.has("user_referral_settings", "enabled", "reward_enabled"):
        row = r.row("SELECT enabled, reward_enabled FROM user_referral_settings WHERE id=1", "user_referral_settings")
        m["referrals_enabled"] = int(bool(row.get("enabled")))
        m["referral_rewards_enabled"] = int(bool(row.get("enabled")) and bool(row.get("reward_enabled")))
    if r.has("user_referrals", "created_at", "reward_granted_at"):
        m.update(r.row("""SELECT SUM(created_at >= datetime('now','-30 day')) AS referrals_30d,
                SUM(reward_granted_at >= datetime('now','-30 day')) AS referrals_rewarded_30d
            FROM user_referrals""", "user_referrals"))
    if r.has("subscription_gift_runs", "created_at"):
        m["gift_runs_30d"] = r.value(
            "SELECT COUNT(*) FROM subscription_gift_runs WHERE created_at >= datetime('now','-30 day')",
            "subscription_gift_runs")
    if r.has("portal_payment_links", "enabled"):
        m["payment_links"] = r.value("SELECT COUNT(*) FROM portal_payment_links WHERE enabled=1", "portal_payment_links")
    m["payment_links_enabled"] = int(bool(settings.get("portal_payment_links_enabled")))


def _portal(r, m, settings):
    if r.has("portal_roles", "is_system"):
        m["portal_roles_custom"] = r.value("SELECT COUNT(*) FROM portal_roles WHERE is_system=0", "portal_roles")
    m["portal_monitoring_visible"] = int(bool(settings.get("portal_show_monitoring")))
    m["portal_support_visible"] = int(bool(settings.get("portal_show_support")))
    m["turnstile_admin"] = int(bool(settings.get("turnstile_enabled")) and bool(settings.get("turnstile_protect_admin")))
    if r.has("portal_conversations", "created_at"):
        m["support_conversations_30d"] = r.value(
            "SELECT COUNT(*) FROM portal_conversations WHERE created_at >= datetime('now','-30 day')", "portal_conversations")
    if r.has("portal_messages", "created_at"):
        m["support_posts_30d"] = r.value(
            "SELECT COUNT(*) FROM portal_messages WHERE created_at >= datetime('now','-30 day')", "portal_messages")
    if r.has("user_activations", "completed_at"):
        m["activations_30d"] = r.value(
            "SELECT COUNT(*) FROM user_activations WHERE completed_at >= datetime('now','-30 day')", "user_activations")


def _configuration(r, m):
    if r.has("migration_campaigns", "status", "completed_at"):
        m.update(r.row("""SELECT COUNT(*) AS migration_campaigns,
                SUM(status='completed' AND completed_at >= datetime('now','-30 day')) AS migrations_completed_30d
            FROM migration_campaigns""", "migration_campaigns"))
    m["config_profiles"] = r.value("SELECT COUNT(*) FROM config_profiles", "config_profiles")
    m["config_groups"] = r.value("SELECT COUNT(*) FROM config_groups", "config_groups")
    m["config_profile_targets"] = r.value("SELECT COUNT(*) FROM config_profile_targets", "config_profile_targets")
    if r.has("config_compliance", "status", "drift_count"):
        m.update(r.row("""SELECT COUNT(*) AS config_servers_checked,
                SUM(status='compliant') AS config_servers_compliant,
                SUM(status='non_compliant') AS config_servers_drift,
                SUM(status='partial') AS config_servers_partial,
                SUM(status='unreachable') AS config_servers_unreachable,
                SUM(COALESCE(drift_count,0)) AS config_drift_settings
            FROM config_compliance""", "config_compliance"))
    m["config_exceptions"] = r.value("SELECT COUNT(*) FROM config_server_exceptions", "config_server_exceptions")
    if r.has("config_deployments", "created_at"):
        m["config_deployments_30d"] = r.value(
            "SELECT COUNT(*) FROM config_deployments WHERE created_at >= datetime('now','-30 day')", "config_deployments")
    if r.has("config_compliance_changes", "detected_at"):
        m["config_changes_30d"] = r.value(
            "SELECT COUNT(*) FROM config_compliance_changes WHERE detected_at >= datetime('now','-30 day')",
            "config_compliance_changes")
    if r.has("tautulli_import_jobs", "status"):
        m["tautulli_imports"] = r.value(
            "SELECT COUNT(*) FROM tautulli_import_jobs WHERE status IN ('done','completed','success')", "tautulli_import_jobs")
    if r.has("api_tokens", "revoked_at", "last_used_at"):
        m.update(r.row("""SELECT SUM(revoked_at IS NULL) AS api_keys_active,
                SUM(revoked_at IS NULL AND last_used_at >= datetime('now','-30 day')) AS api_keys_used_30d
            FROM api_tokens""", "api_tokens"))


def _communications(r, m, settings):
    m["discord_bots"] = r.value("SELECT COUNT(*) FROM discord_bots", "discord_bots")
    if r.has("discord_campaigns", "created_at", "is_test"):
        m["discord_campaigns_30d"] = r.value("""SELECT COUNT(*) FROM discord_campaigns
            WHERE is_test=0 AND created_at >= datetime('now','-30 day')""", "discord_campaigns")
    if r.has("comm_templates", "enabled"):
        m.update(r.row("SELECT COUNT(*) AS comm_templates, SUM(enabled=1) AS comm_templates_enabled FROM comm_templates",
                       "comm_templates"))
    if r.has("comm_template_translations", "language"):
        m["comm_template_languages"] = r.value(
            "SELECT COUNT(DISTINCT LOWER(language)) FROM comm_template_translations", "comm_template_translations")
    m["comm_attachments"] = (_int(r.value("SELECT COUNT(*) FROM comm_template_attachments", "comm_template_attachments"))
                             + _int(r.value("SELECT COUNT(*) FROM comm_campaign_attachments", "comm_campaign_attachments")))
    if r.has("comm_campaigns", "created_at", "is_test"):
        m["comm_campaigns_30d"] = r.value("""SELECT COUNT(*) FROM comm_campaigns
            WHERE is_test=0 AND created_at >= datetime('now','-30 day')""", "comm_campaigns")
    if r.has("comm_scheduled", "send_at", "status"):
        m["comm_scheduled_30d"] = r.value("""SELECT COUNT(*) FROM comm_scheduled
            WHERE status='sent' AND send_at >= datetime('now','-30 day')""", "comm_scheduled")
    m["welcome_templates"] = r.value("SELECT COUNT(*) FROM welcome_email_templates", "welcome_email_templates")
    if r.has("mail_campaigns", "created_at", "is_test"):
        m["mail_campaigns_30d"] = r.value("""SELECT COUNT(*) FROM mail_campaigns
            WHERE is_test=0 AND created_at >= datetime('now','-30 day')""", "mail_campaigns")
    m["expiry_reminders_enabled"] = int(bool(settings.get("send_reminders")))
    m["notify_all_channels"] = int(str(settings.get("notifications_send_mode") or "").lower() == "all")
    m["user_notification_choice"] = int(bool(settings.get("user_notifications_can_override")))


def _policies(r, m):
    if r.has("usage_risk_recommendations", "last_detected_at"):
        m["usage_risk_recommendations_30d"] = r.value("""SELECT COUNT(*) FROM usage_risk_recommendations
            WHERE last_detected_at >= datetime('now','-30 day')""", "usage_risk_recommendations")
    if r.has("stream_policies", "rule_type", "is_enabled"):
        try:
            rows = r.db.query("SELECT rule_type, COUNT(*) AS total FROM stream_policies WHERE is_enabled=1 GROUP BY rule_type") or []
        except sqlite3.Error:
            rows = []
        for row in rows:
            rule = str(row["rule_type"] or "").lower()
            key = "policy_rule_" + POLICY_RULE_FIELDS.get(rule, "other")
            m[key] = _int(m.get(key)) + _int(row["total"])


def _collections(r, m):
    if r.has("collection_lists", "origin", "enabled"):
        m.update(r.row("""SELECT SUM(origin='official') AS collection_lists_official,
                SUM(origin='custom') AS collection_lists_custom, SUM(enabled=1) AS collection_lists_enabled
            FROM collection_lists""", "collection_lists"))
    if r.has("franchise_lists", "enabled", "is_vodum"):
        m.update(r.row("""SELECT SUM(enabled=1) AS franchise_lists, SUM(enabled=1 AND is_vodum=0) AS franchise_lists_custom
            FROM franchise_lists""", "franchise_lists"))
    if r.has("collection_settings", "secret_tmdb"):
        has_mal = "secret_myanimelist" in r.columns("collection_settings")
        m.update(r.row(f"""SELECT MAX(COALESCE(secret_tmdb,'')<>'') AS collections_tmdb_configured,
                {"MAX(COALESCE(secret_myanimelist,'')<>'')" if has_mal else "0"} AS collections_myanimelist_configured
            FROM collection_settings""", "collection_settings"))
    if r.has("collection_person_choices", "manual", "excluded"):
        m["collections_people_choices"] = r.value(
            "SELECT COUNT(*) FROM collection_person_choices WHERE manual=1 OR excluded=1", "collection_person_choices")
    if r.has("collection_spotlight_runs", "started"):
        m["collections_spotlight_runs_30d"] = r.value(
            "SELECT COUNT(*) FROM collection_spotlight_runs WHERE started >= datetime('now','-30 day')",
            "collection_spotlight_runs")


def _installation(r, m, settings):
    m["admin_totp_enabled"] = int(bool(settings.get("admin_totp_enabled")))
    if r.has("admin_auth_identities", "provider", "is_active"):
        m.update(r.row("""SELECT MAX(provider='plex' AND is_active=1) AS admin_login_plex,
                MAX(provider='jellyfin' AND is_active=1) AS admin_login_jellyfin
            FROM admin_auth_identities""", "admin_auth_identities"))
    m["reverse_proxy"] = int(bool(settings.get("web_trust_proxy")))
    m["secure_cookies"] = int(bool(settings.get("web_secure_cookies")))
    m["wizard_completed"] = int(bool(settings.get("wizard_completed")))
    m["plex_import_all_users"] = int(str(settings.get("plex_user_import_mode") or "").lower() == "global")
    m["skip_unused_accounts"] = int(bool(settings.get("skip_never_used_accounts")))
    if r.has("arr_monitoring_samples", "checked_at"):
        m["arr_monitoring_active"] = int(bool(r.value(
            "SELECT 1 FROM arr_monitoring_samples WHERE checked_at >= datetime('now','-7 day') LIMIT 1",
            "arr_monitoring_samples")))
    for key in ("backup_retention_days", "backup_retention_count", "data_retention_years", "log_retention_days"):
        m[key] = settings.get(key)
    if r.has("tasks", "name", "enabled"):
        try:
            rows = r.db.query("SELECT name, enabled FROM tasks") or []
        except sqlite3.Error:
            rows = []
        for row in rows:
            name = str(row["name"] or "")
            if name in TELEMETRY_TASKS:
                m["task_" + name] = int(bool(row["enabled"]))


def _settings(r):
    wanted = ("portal_request_backend", "portal_show_media_requests", "portal_request_quota_enabled",
              "portal_payment_links_enabled", "portal_show_monitoring", "portal_show_support", "turnstile_enabled",
              "turnstile_protect_admin", "send_reminders", "notifications_send_mode", "user_notifications_can_override",
              "admin_totp_enabled", "web_trust_proxy", "web_secure_cookies", "wizard_completed", "plex_user_import_mode",
              "skip_never_used_accounts", "backup_retention_days", "backup_retention_count", "data_retention_years",
              "log_retention_days")
    columns = [column for column in wanted if column in r.columns("settings")]
    if not columns:
        return {}
    return r.row(f"SELECT {', '.join(columns)} FROM settings WHERE id=1", "settings")


def feature_telemetry(db):
    """Return every schema v5 counter as a bounded integer (0 when unavailable)."""
    reader = _Reader(db)
    metrics = dict.fromkeys(FEATURE_TELEMETRY_FIELDS, 0)
    settings = _settings(reader)
    for collect in (
        lambda: _capacity(reader, metrics),
        lambda: _requests(reader, metrics, settings),
        lambda: _subscriptions(reader, metrics, settings),
        lambda: _portal(reader, metrics, settings),
        lambda: _configuration(reader, metrics),
        lambda: _communications(reader, metrics, settings),
        lambda: _policies(reader, metrics),
        lambda: _collections(reader, metrics),
        lambda: _installation(reader, metrics, settings),
    ):
        try:
            collect()
        except Exception as exc:  # optional statistics must never block the report
            log.debug(f"Telemetry feature group skipped: {type(exc).__name__}")
    return {key: _int(metrics.get(key)) for key in FEATURE_TELEMETRY_FIELDS}
