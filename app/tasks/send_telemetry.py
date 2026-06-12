import hashlib
import json
import platform
import threading
import uuid
from pathlib import Path
import requests
from utils.platform_detection import detect_platform
from db_manager import DBManager
from logging_utils import get_logger
from datetime import datetime, timedelta, timezone
from utils.version import load_app_version

TELEMETRY_URL = "https://vodum-telemetry.vodum-project.workers.dev/api/ingest"

log = get_logger("telemetry")
_SEND_LOCK = threading.Lock()


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
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")

        if not settings:
            log.warning("Telemetry aborted: settings row not found")
            return {"success": False, "reason": "settings_missing"}

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
        
        version = load_app_version()
        update_pending_days = 0

        try:

            status_file = Path("/appdata/update_status.json")

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

        payload = {
            "instance_id": instance_id,
            "schema_version": 1,
            "version": version,
            "platform": platform.system().lower(),
            "runtime_platform": platform_info["platform"],
            "container": platform_info["container"],
            "virtualized": platform_info["virtualized"],
            "python_version": ".".join(platform.python_version_tuple()[:2]),
            "docker": True,
            "managed_users": users["total"] if users else 0,
            "plex_servers": plex_servers["total"] if plex_servers else 0,
            "jellyfin_servers": jellyfin_servers["total"] if jellyfin_servers else 0,
            "subscriptions_enabled": 1 if active_subscriptions and active_subscriptions["total"] > 0 else 0,
            "discord_enabled": 1 if settings["discord_enabled"] else 0,
            "mail_enabled": 1 if settings["mailing_enabled"] else 0,
            "policies_enabled": 1 if active_policies and active_policies["total"] > 0 else 0,
            "debug_enabled": 1 if debug_mode else 0,
            "automatic_backups_enabled": 1 if automatic_backups and automatic_backups["enabled"] else 0,
            "usage_risk_enabled": 1 if settings["usage_risk_enabled"] else 0,
            "auth_enabled": 1 if settings["auth_enabled"] else 0,
            "update_pending_days": update_pending_days,
        }
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
