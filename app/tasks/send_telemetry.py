import hashlib
import json
import platform
import threading
import uuid
import requests
from utils.platform_detection import detect_platform
from db_manager import DBManager
from logging_utils import get_logger
from datetime import datetime, timedelta, timezone
from utils.version import load_app_version
from core.app_paths import update_status_path

TELEMETRY_URL = "https://vodum-telemetry.vodum-project.workers.dev/api/ingest"

log = get_logger("telemetry")
_SEND_LOCK = threading.Lock()

# Only aggregate numeric values, boolean feature flags and tightly allow-listed
# enums belong here. Never add names, addresses, URLs, IPs, tokens or free text.
TELEMETRY_PAYLOAD_KEYS = frozenset({
    "instance_id", "schema_version", "version", "platform", "runtime_platform",
    "container", "virtualized", "python_version", "docker", "managed_users",
    "total_users", "expired_users", "pending_users", "plex_servers",
    "jellyfin_servers", "libraries", "subscription_plans", "active_policies",
    "total_policies", "portal_accounts", "active_portal_accounts",
    "playback_sessions_30d", "communications_sent_30d", "policy_stops_30d",
    "enabled_tasks", "subscriptions_enabled", "discord_enabled", "mail_enabled",
    "policies_enabled", "debug_enabled", "automatic_backups_enabled",
    "usage_risk_enabled", "auth_enabled", "portal_enabled",
    "portal_local_auth_enabled", "portal_plex_auth_enabled",
    "portal_jellyfin_auth_enabled", "turnstile_enabled",
    "quick_messages_enabled", "cron_enabled",
    "maintenance_enabled", "default_language", "expiry_mode",
    "update_pending_days",
})

FORBIDDEN_TELEMETRY_KEY_TOKENS = frozenset({
    "email", "name", "url", "host", "ip", "token", "secret", "password",
    "title", "message", "body", "username", "domain",
})


def validate_anonymous_payload(payload):
    """Fail closed if a future change tries to export identifying data."""
    keys = set(payload)
    if not keys <= TELEMETRY_PAYLOAD_KEYS:
        raise ValueError(f"unsupported telemetry fields: {sorted(keys - TELEMETRY_PAYLOAD_KEYS)}")
    unsafe = [key for key in keys if set(key.lower().split("_")) & FORBIDDEN_TELEMETRY_KEY_TOKENS]
    if unsafe:
        raise ValueError(f"potentially identifying telemetry fields: {sorted(unsafe)}")
    if any(isinstance(value, (dict, list, tuple, set)) for value in payload.values()):
        raise ValueError("nested telemetry values are not allowed")
    return payload


def _aggregate(db, sql, params=()):
    row = db.query_one(sql, params)
    return dict(row) if row else {}


def get_or_create_instance_id(db):
    row = db.query_one(
        "SELECT telemetry_instance_id FROM settings WHERE id = 1"
    )

    current = row["telemetry_instance_id"] if row else None

    if current:
        return current

    instance_id = uuid.uuid4().hex

    db.execute(
        "UPDATE settings SET telemetry_instance_id = ? WHERE id = 1",
        (instance_id,)
    )

    return instance_id


def _parse_utc_timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


TELEMETRY_MIN_INTERVAL = timedelta(days=2)
TELEMETRY_MAX_INTERVAL = timedelta(days=7)


def _telemetry_random_interval(last_sent_at, instance_id):
    seed = f"{instance_id or ''}|{last_sent_at or ''}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()

    span_seconds = int((TELEMETRY_MAX_INTERVAL - TELEMETRY_MIN_INTERVAL).total_seconds())
    jitter_seconds = int.from_bytes(digest[:8], "big") % (span_seconds + 1)

    return TELEMETRY_MIN_INTERVAL + timedelta(seconds=jitter_seconds)


def _is_due(last_sent_at, instance_id=None, now=None):
    last_sent = _parse_utc_timestamp(last_sent_at)

    if not last_sent:
        return True

    now = now or datetime.now(timezone.utc)

    # Safety net: never wait more than 7 days.
    if now >= last_sent + TELEMETRY_MAX_INTERVAL:
        return True

    return now >= last_sent + _telemetry_random_interval(last_sent_at, instance_id)


def _task_enabled(db):
    row = db.query_one("SELECT enabled FROM tasks WHERE name='send_telemetry'")
    return bool(row and int(row["enabled"] or 0) == 1)


def run(task_id: int, db: DBManager):
    if not _SEND_LOCK.acquire(blocking=False):
        return {"success": True, "skipped": True, "reason": "already_running"}

    try:
        settings = db.query_one("SELECT id, mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass, smtp_auth_method, smtp_oauth_access_token, email_history_retention_years, disable_on_expiry, delete_after_expiry_days, send_reminders, preavis_days, reminder_days, default_language, timezone, admin_email, contact_email, admin_password_hash, auth_enabled, admin_totp_enabled, admin_totp_secret, wizard_active, wizard_completed, wizard_step, wizard_state_json, web_secure_cookies, web_cookie_samesite, web_trust_proxy, enable_cron_jobs, default_expiration_days, default_subscription_days, maintenance_mode, debug_mode, backup_retention_days, backup_retention_count, data_retention_years, brand_name, notifications_order, user_notifications_can_override, notifications_send_mode, expiry_mode, warn_then_disable_days, discord_enabled, discord_bot_token, discord_bot_id, mailing_enabled, skip_never_used_accounts, plex_user_import_mode, enable_anonymous_telemetry, telemetry_instance_id, telemetry_last_sent_at, task_defaults_version, stream_enforcer_boost_until, usage_risk_enabled, usage_risk_send_upgrade_suggestions, usage_risk_send_stream_blocked_message, usage_risk_min_kills_before_suggestion, usage_risk_analysis_window_days, usage_risk_suggestion_cooldown_days, usage_risk_medium_threshold, usage_risk_high_threshold FROM settings WHERE id = 1")

        if not settings:
            log.warning("Telemetry aborted: settings row not found")
            return {"success": False, "reason": "settings_missing"}
        settings = dict(settings)

        if int(settings["enable_anonymous_telemetry"] or 0) != 1:
            return {"success": True, "skipped": True, "reason": "disabled"}

        if not _task_enabled(db):
            return {"success": True, "skipped": True, "reason": "task_disabled"}

        debug_mode = int(settings["debug_mode"] or 0) == 1
        instance_id = get_or_create_instance_id(db)

        try:
            if not debug_mode and not _is_due(settings["telemetry_last_sent_at"], instance_id):
                return {"success": True, "skipped": True, "reason": "rate_limited"}
        except (TypeError, ValueError):
            log.warning("Invalid telemetry_last_sent_at ignored")

        users = db.query_one(
            "SELECT COUNT(*) AS total FROM vodum_users WHERE status NOT IN ('expired', 'pending_invite')"
        )

        plex_servers = db.query_one(
            "SELECT COUNT(*) AS total FROM servers WHERE type = 'plex'"
        )

        jellyfin_servers = db.query_one(
            "SELECT COUNT(*) AS total FROM servers WHERE type = 'jellyfin'"
        )

        active_subscriptions = db.query_one(
            """
            SELECT COUNT(*) AS total
            FROM subscription_templates
            WHERE is_enabled  = 1
            """
        )

        total_servers = (
            (plex_servers["total"] if plex_servers else 0)
            + (jellyfin_servers["total"] if jellyfin_servers else 0)
        )

        # IMPORTANT:
        # Do not send telemetry for fresh empty installs.
        # Wait until at least one media server is configured.
        #
        # This prevents sending empty statistics during first boot.
        if total_servers <= 0:

            log.info(
                "Telemetry skipped: no Plex or Jellyfin servers configured yet"
            )

            return {
                "success": True,
                "skipped": True,
                "reason": "no_servers"
            }

        active_policies = db.query_one(
            """
            SELECT COUNT(*) AS total
            FROM stream_policies
            WHERE is_enabled  = 1
            """
        )
        automatic_backups = db.query_one(
            "SELECT enabled FROM tasks WHERE name='auto_backup'"
        )

        user_stats = _aggregate(db, """
            SELECT COUNT(*) AS total_users,
                   SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) AS expired_users,
                   SUM(CASE WHEN status='pending_invite' THEN 1 ELSE 0 END) AS pending_users
            FROM vodum_users
        """)
        inventory = _aggregate(db, """
            SELECT (SELECT COUNT(*) FROM libraries) AS libraries,
                   (SELECT COUNT(*) FROM subscription_templates) AS subscription_plans,
                   (SELECT COUNT(*) FROM stream_policies) AS total_policies,
                   (SELECT COUNT(*) FROM portal_accounts) AS portal_accounts,
                   (SELECT COUNT(*) FROM portal_accounts WHERE status='active') AS active_portal_accounts,
                   (SELECT COUNT(*) FROM tasks WHERE enabled=1) AS enabled_tasks
        """)
        recent_usage = _aggregate(db, """
            SELECT (SELECT COUNT(*) FROM media_session_history WHERE started_at >= datetime('now','-30 day')) AS playback_sessions_30d,
                   (SELECT COUNT(*) FROM comm_history WHERE status='sent' AND sent_at >= datetime('now','-30 day')) AS communications_sent_30d,
                   (SELECT COUNT(*) FROM stream_enforcements WHERE created_at >= datetime('now','-30 day')) AS policy_stops_30d
        """)
        portal_settings = _aggregate(db, """
            SELECT portal_enabled,portal_local_auth_enabled,portal_plex_auth_enabled,
                   portal_jellyfin_auth_enabled,turnstile_enabled,
                   portal_quick_messages_enabled
            FROM settings WHERE id=1
        """)
        
        version = load_app_version()
        update_pending_days = 0

        try:

            status_file = update_status_path()

            if status_file.exists():

                status = json.loads(
                    status_file.read_text()
                )

                update_pending_days = int(
                    status.get("update_pending_days") or 0
                )

        except Exception:
            pass

        if not version:
            log.warning(
                "Telemetry skipped: no valid VODUM version could be read from "
                "VODUM_VERSION or an INFO file"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": "version_unavailable",
            }

        platform_info = detect_platform()

        payload = validate_anonymous_payload({
            "instance_id": instance_id,
            "schema_version": 2,
            "version": version,
            "platform": platform.system().lower(),
            "runtime_platform": platform_info["platform"],
            "container": platform_info["container"],
            "virtualized": platform_info["virtualized"],
            "python_version": ".".join(platform.python_version_tuple()[:2]),
            "docker": True,
            "managed_users": users["total"] if users else 0,
            "total_users": int(user_stats.get("total_users") or 0),
            "expired_users": int(user_stats.get("expired_users") or 0),
            "pending_users": int(user_stats.get("pending_users") or 0),
            "plex_servers": plex_servers["total"] if plex_servers else 0,
            "jellyfin_servers": jellyfin_servers["total"] if jellyfin_servers else 0,
            "libraries": int(inventory.get("libraries") or 0),
            "subscription_plans": int(inventory.get("subscription_plans") or 0),
            "active_policies": active_policies["total"] if active_policies else 0,
            "total_policies": int(inventory.get("total_policies") or 0),
            "portal_accounts": int(inventory.get("portal_accounts") or 0),
            "active_portal_accounts": int(inventory.get("active_portal_accounts") or 0),
            "playback_sessions_30d": int(recent_usage.get("playback_sessions_30d") or 0),
            "communications_sent_30d": int(recent_usage.get("communications_sent_30d") or 0),
            "policy_stops_30d": int(recent_usage.get("policy_stops_30d") or 0),
            "enabled_tasks": int(inventory.get("enabled_tasks") or 0),
            "subscriptions_enabled": 1 if active_subscriptions and active_subscriptions["total"] > 0 else 0,
            "discord_enabled": 1 if settings["discord_enabled"] else 0,
            "mail_enabled": 1 if settings["mailing_enabled"] else 0,
            "policies_enabled": 1 if active_policies and active_policies["total"] > 0 else 0,
            "debug_enabled": 1 if debug_mode else 0,
            "automatic_backups_enabled": 1 if automatic_backups and automatic_backups["enabled"] else 0,
            "usage_risk_enabled": 1 if settings["usage_risk_enabled"] else 0,
            "auth_enabled": 1 if settings["auth_enabled"] else 0,
            "portal_enabled": 1 if portal_settings.get("portal_enabled") else 0,
            "portal_local_auth_enabled": 1 if portal_settings.get("portal_local_auth_enabled") else 0,
            "portal_plex_auth_enabled": 1 if portal_settings.get("portal_plex_auth_enabled") else 0,
            "portal_jellyfin_auth_enabled": 1 if portal_settings.get("portal_jellyfin_auth_enabled") else 0,
            "turnstile_enabled": 1 if portal_settings.get("turnstile_enabled") else 0,
            "quick_messages_enabled": 1 if portal_settings.get("portal_quick_messages_enabled") else 0,
            "cron_enabled": 1 if settings.get("enable_cron_jobs") else 0,
            "maintenance_enabled": 1 if settings.get("maintenance_mode") else 0,
            "default_language": str(settings.get("default_language") or "unknown").lower() if str(settings.get("default_language") or "").lower() in {"en", "fr", "es", "de", "it"} else "unknown",
            "expiry_mode": str(settings.get("expiry_mode") or "none").lower() if str(settings.get("expiry_mode") or "").lower() in {"none", "warn_only", "warn_then_disable", "disable"} else "unknown",
            "update_pending_days": update_pending_days,
        })
        log.info(
            "Telemetry sending aggregate payload "
            f"(version={version}, fields={','.join(sorted(payload))})"
        )

        response = requests.post(
            TELEMETRY_URL,
            json=payload,
            timeout=(5, 10),
            headers={"User-Agent": f"VODUM/{version}"},
        )

        log.info(f"Telemetry HTTP response: {response.status_code}")

        if 200 <= response.status_code < 300:

            db.execute(
                "UPDATE settings SET telemetry_last_sent_at = CURRENT_TIMESTAMP WHERE id = 1"
            )

            log.info("Anonymous telemetry successfully sent")
            return {"success": True}

        log.warning(f"Telemetry failed with HTTP {response.status_code}")
        return {"success": False, "reason": "http_error", "status_code": response.status_code}

    except requests.RequestException as exc:
        log.warning(f"Telemetry network error: {type(exc).__name__}")
        return {"success": False, "reason": "network_error"}
    except Exception as exc:
        log.exception(
            f"Telemetry fatal error: {type(exc).__name__}"
        )
        return {"success": False, "reason": "internal_error"}
    finally:
        _SEND_LOCK.release()
