from core.error_reporting import log_handled_failure
import os
import json
from datetime import datetime, timezone
import requests
from logging_utils import get_logger
from core.app_paths import update_status_path
import tempfile
import time
from utils.version import load_app_version, is_valid_app_version, app_version_tuple


logger = get_logger("task_check_update")

GITHUB_REPO = "Nexius2/VODUM"   
GITHUB_BRANCH = "main"       



def _read_version_from_info_text(text: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith("VERSION="):
            return line.split("=", 1)[1].strip()
    return ""


def _read_local_version() -> str:
    return load_app_version(fallback="dev")

def _parse_version_tuple(v: str):
    return app_version_tuple(v)


def _is_update_available(local_v: str, remote_v: str) -> bool:
    local_t = _parse_version_tuple(local_v)
    remote_t = _parse_version_tuple(remote_v)

    if local_t is not None and remote_t is not None:
        return remote_t > local_t

    # Unknown versions cannot establish that the remote build is newer.
    return False


def _raw_info_url() -> str:
    repo = (GITHUB_REPO or "").strip().strip("/")
    branch = (GITHUB_BRANCH or "main").strip()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/INFO"


def _write_status(payload: dict):
    temporary = None
    try:
        status_file = update_status_path()
        status_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=status_file.parent,
                                         prefix=".update-status-", suffix=".tmp", delete=False) as f:
            temporary = f.name
            json.dump(payload, f, ensure_ascii=False, indent=2)
        for attempt in range(5):
            try:
                os.replace(temporary, status_file)
                break
            except PermissionError:
                # Windows can deny replacement while another process reads.
                if os.name != 'nt' or attempt == 4:
                    raise
                time.sleep(0.01 * (2 ** attempt))
    except Exception as e:
        logger.error(f"Failed writing {update_status_path()}: {e}")
        raise RuntimeError('Unable to publish update status') from e
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


# ✅ IMPORTANT : le moteur appelle run(task_id, db) => il faut accepter 2 args
def run(task_id: int = None, db=None):
    local_version = _read_local_version()

    # Si repo pas rempli => on écrit un status propre et on sort
    if not (GITHUB_REPO or "").strip():
        payload = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "local_version": local_version,
            "latest_version": None,
            "update_available": False,
            "error": "GITHUB_REPO not configured",
            "source": None,
        }
        _write_status(payload)
        logger.warning("check_update: GITHUB_REPO not configured")
        raise RuntimeError('Update source is not configured')

    url = _raw_info_url()

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "local_version": local_version,
        "latest_version": None,
        "update_available": False,
        "update_available_since": None,
        "update_pending_days": 0,
        "error": None,
        "source": url,
    }

    previous = {}
    status_file = update_status_path()
    if status_file.exists():
        try:
            with status_file.open("r", encoding="utf-8") as f:
                previous = json.load(f) or {}
            if not isinstance(previous, dict):
                previous = {}

            if (previous.get('source') == url
                    and _is_update_available(local_version, previous.get('latest_version'))
                    and previous.get('update_available') is True):
                payload["update_available_since"] = previous.get("update_available_since")
                payload["update_pending_days"] = max(0, int(previous.get("update_pending_days") or 0))

        except Exception:
            log_handled_failure("updates.read_previous_status")
            pass

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        latest = _read_version_from_info_text(r.text)
        if not is_valid_app_version(latest):
            raise ValueError("Remote INFO contains no valid VERSION")
        if not is_valid_app_version(local_version):
            raise ValueError("Local version is unknown")
        payload["latest_version"] = latest or None
        payload["update_available"] = _is_update_available(local_version, latest)

        now = datetime.now(timezone.utc)

        if payload["update_available"]:

            if not payload["update_available_since"]:
                payload["update_available_since"] = now.isoformat()

            try:
                first_seen = datetime.fromisoformat(
                    payload["update_available_since"]
                )

                payload["update_pending_days"] = max(
                    0,
                    (now - first_seen).days
                )

            except Exception:
                log_handled_failure("updates.read_first_seen_date")
                payload["update_available_since"] = now.isoformat()
                payload["update_pending_days"] = 0

            logger.info(
                f"Update available: local={local_version} remote={latest} "
                f"pending_days={payload['update_pending_days']}"
            )

        else:

            payload["update_available_since"] = None
            payload["update_pending_days"] = 0

            logger.info(f"No update: local={local_version} remote={latest}")

    except requests.exceptions.RequestException as e:
        payload["error"] = str(e) or type(e).__name__
        logger.warning(f"Update check unavailable: {e}")

    except Exception as e:
        payload["error"] = str(e) or type(e).__name__
        logger.error(f"Update check failed: {e}")

    if payload['error']:
        # A temporary outage does not cancel an already confirmed update.
        # Recompare against this installation so upgrades clear obsolete badges.
        latest = previous.get('latest_version')
        if previous.get('source') == url and is_valid_app_version(latest):
            payload['latest_version'] = latest
            payload['update_available'] = _is_update_available(local_version, latest)
        if not payload['update_available']:
            payload['update_available_since'] = None
            payload['update_pending_days'] = 0

    _write_status(payload)
    if payload['error']:
        raise RuntimeError('Update check unavailable; see update status')
