import os
import json
from datetime import datetime, timezone
import requests
from logging_utils import get_logger

logger = get_logger("task_check_update")

GITHUB_REPO = "Nexius2/VODUM"   
GITHUB_BRANCH = "main"       

LOCAL_INFO_PATH = "/app/INFO"
STATUS_FILE = "/appdata/update_status.json"


def _read_version_from_info_text(text: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith("VERSION="):
            return line.split("=", 1)[1].strip()
    return ""


def _read_local_version() -> str:
    if not os.path.exists(LOCAL_INFO_PATH):
        return "dev"
    try:
        with open(LOCAL_INFO_PATH, "r", encoding="utf-8", errors="ignore") as f:
            return _read_version_from_info_text(f.read()) or "dev"
    except Exception:
        return "dev"


def _raw_info_url() -> str:
    repo = (GITHUB_REPO or "").strip().strip("/")
    branch = (GITHUB_BRANCH or "main").strip()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/INFO"


def _write_status(payload: dict):
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed writing {STATUS_FILE}: {e}")


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
        return

    url = _raw_info_url()

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "local_version": local_version,
        "latest_version": None,
        "update_available": False,
        "error": None,
        "source": url,
    }

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        latest = _read_version_from_info_text(r.text)
        payload["latest_version"] = latest or None
        payload["update_available"] = bool(latest and latest != local_version)

        if payload["update_available"]:
            logger.info(f"Update available: local={local_version} remote={latest}")
        else:
            logger.info(f"No update: local={local_version} remote={latest}")

    except Exception as e:
        payload["error"] = str(e)
        logger.error(f"Update check failed: {e}")

    _write_status(payload)
