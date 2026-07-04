import os
import json
from datetime import datetime, timezone
import requests
from logging_utils import get_logger
from core.app_paths import update_status_path
import re


logger = get_logger("task_check_update")

GITHUB_REPO = "Nexius2/VODUM"   
GITHUB_BRANCH = "main"       

LOCAL_INFO_PATH = "/app/INFO"


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

def _normalize_version_str(v: str) -> str:
    return (v or "").strip()


def _parse_version_tuple(v: str):
    s = _normalize_version_str(v)
    if not s or s.lower() == "dev":
        return None

    # enlève un éventuel "v" en début
    if s.lower().startswith("v"):
        s = s[1:].strip()

    # ex: "26.02.10 b1841"
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\s*[ -]?\s*b(\d+))?$", s, re.IGNORECASE)
    if not m:
        return None

    yy = int(m.group(1))
    mm = int(m.group(2))
    dd = int(m.group(3))
    build = int(m.group(4)) if m.group(4) else 0

    return (yy, mm, dd, build)


def _is_update_available(local_v: str, remote_v: str) -> bool:
    local_t = _parse_version_tuple(local_v)
    remote_t = _parse_version_tuple(remote_v)

    if local_t is not None and remote_t is not None:
        return remote_t > local_t

    # fallback (comportement historique)
    return bool(remote_v and _normalize_version_str(remote_v) != _normalize_version_str(local_v))


def _raw_info_url() -> str:
    repo = (GITHUB_REPO or "").strip().strip("/")
    branch = (GITHUB_BRANCH or "main").strip()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/INFO"


def _write_status(payload: dict):
    try:
        status_file = update_status_path()
        status_file.parent.mkdir(parents=True, exist_ok=True)
        with status_file.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed writing {update_status_path()}: {e}")


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
        "update_available_since": None,
        "update_pending_days": 0,
        "error": None,
        "source": url,
    }

    status_file = update_status_path()
    if status_file.exists():
        try:
            with status_file.open("r", encoding="utf-8") as f:
                previous = json.load(f) or {}

            payload["update_available_since"] = previous.get("update_available_since")
            payload["update_pending_days"] = int(previous.get("update_pending_days") or 0)

        except Exception:
            pass

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        latest = _read_version_from_info_text(r.text)
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
        payload["error"] = str(e)
        logger.warning(f"Update check unavailable: {e}")

    except Exception as e:
        payload["error"] = str(e)
        logger.error(f"Update check failed: {e}")

    _write_status(payload)
