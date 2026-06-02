import hashlib
import json
import platform
import socket
import uuid
from pathlib import Path
import requests
from utils.platform_detection import detect_platform
from db_manager import DBManager
from logging_utils import get_logger
from datetime import datetime, timedelta

TELEMETRY_URL = "https://vodum-telemetry.vodum-project.workers.dev/api/ingest"

log = get_logger("telemetry")


def get_or_create_instance_id(db):
    row = db.query_one(
        "SELECT telemetry_instance_id FROM settings WHERE id = 1"
    )

    current = row["telemetry_instance_id"] if row else None

    if current:
        return current

    raw = f"{socket.gethostname()}-{uuid.getnode()}"

    instance_id = hashlib.sha256(raw.encode()).hexdigest()[:32]

    db.execute(
        "UPDATE settings SET telemetry_instance_id = ? WHERE id = 1",
        (instance_id,)
    )

    return instance_id


def run(task_id: int, db: DBManager):

    settings_row = db.query_one(
        """
        SELECT telemetry_last_sent_at, debug_mode
        FROM settings
        WHERE id = 1
        """
    )

    debug_mode_enabled = bool(
        settings_row
        and int(settings_row["debug_mode"] or 0) == 1
    )

    if debug_mode_enabled if "debug_mode_enabled" in locals() else False:
        log.info("Anonymous telemetry task started")


    if (
        not debug_mode_enabled
        and settings_row
        and settings_row["telemetry_last_sent_at"]
    ):

        try:

            from datetime import datetime, timedelta

            last_sent = datetime.fromisoformat(
                settings_row["telemetry_last_sent_at"]
            )

            next_allowed = last_sent + timedelta(days=7)

            if datetime.utcnow() < next_allowed:

                remaining = next_allowed - datetime.utcnow()

                log.info(
                    f"Telemetry skipped "
                    f"(next send in {remaining.days} days)"
                )

                return {
                    "success": True,
                    "skipped": True
                }

        except Exception:
            pass



    settings = db.query_one(
        "SELECT * FROM settings WHERE id = 1"
    )

    if not settings:
        log.warning("Telemetry aborted: settings row not found")
        return

    if int(settings["enable_anonymous_telemetry"] or 0) != 1:
        log.info("Anonymous telemetry disabled")
        return

    try:

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
        
        version = "unknown"
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

        try:

            info_path = Path("/app/INFO")

            if info_path.exists():

                for line in info_path.read_text().splitlines():

                    if line.startswith("VERSION="):
                        version = line.split("=", 1)[1].strip()
                        break

        except Exception:
            pass

        platform_info = detect_platform()

        payload = {
            "instance_id": get_or_create_instance_id(db),
            "version": version,
            "platform": platform.system().lower(),
            "platform_version": platform.version(),
            "os": platform_info["os"],
            "runtime_platform": platform_info["platform"],
            "container": platform_info["container"],
            "virtualized": platform_info["virtualized"],
            "python_version": platform.python_version(),
            "docker": True,
            "managed_users": users["total"] if users else 0,
            "plex_servers": plex_servers["total"] if plex_servers else 0,
            "jellyfin_servers": jellyfin_servers["total"] if jellyfin_servers else 0,
            "subscriptions_enabled": 1 if active_subscriptions and active_subscriptions["total"] > 0 else 0,
            "discord_enabled": 1 if settings["discord_enabled"] else 0,
            "mail_enabled": 1 if settings["mailing_enabled"] else 0,
            "policies_enabled": 1 if active_policies and active_policies["total"] > 0 else 0,
            "update_pending_days": update_pending_days,
        }
        log.info("Telemetry building payload")
        log.info(f"Telemetry payload prepared: {payload}")
        log.info("Telemetry sending HTTP request")

        response = requests.post(
            TELEMETRY_URL,
            json=payload,
            timeout=10
        )

        log.info(f"Telemetry HTTP response: {response.status_code}")
        log.info(f"Telemetry HTTP body: {response.text}")

        if response.status_code == 200:

            db.execute(
                "UPDATE settings SET telemetry_last_sent_at = CURRENT_TIMESTAMP WHERE id = 1"
            )

            log.info("Anonymous telemetry successfully sent")

        else:

            log.warning(
                f"Telemetry failed with HTTP {response.status_code}. "
                "If Vodum has no internet access, it is recommended to disable anonymous telemetry in Settings."
            )

    except Exception as e:
        log.exception(
            f"Telemetry fatal error: {e}. "
            "If Vodum has no internet access, it is recommended "
            "to disable anonymous telemetry in Settings."
        )