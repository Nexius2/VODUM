import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from core.server_cooldown import should_skip_unreachable_server
from core.http_security import server_http_session
from logging_utils import get_logger

logger = get_logger("apply_jellyfin_access_updates")


# ---------------------------------------------------------------------
# Jellyfin API helpers
# ---------------------------------------------------------------------
def _pick_server_base_url(server_row: Dict[str, Any]) -> str:
    """
    Pick best available base url for Jellyfin.
    """
    base = (
        (server_row.get("url") or "")
        or (server_row.get("local_url") or "")
        or (server_row.get("public_url") or "")
    ).strip().rstrip("/")
    if not base:
        raise RuntimeError("Jellyfin: missing server URL (url/local_url/public_url) defined.")
    return base


def _get_jellyfin_api_key(server_row: Dict[str, Any]) -> str:
    """
    In your DB, Jellyfin token is stored in servers.token.
    We use api_key query param (reliable across deployments).
    """
    token = (server_row.get("token") or "").strip()
    if not token:
        raise RuntimeError("Jellyfin: token missing (servers.token).")
    return token


def _jf_get_user(http, base_url: str, api_key: str, jf_user_id: str) -> Dict[str, Any]:
    url = f"{base_url}/Users/{jf_user_id}"
    r = http.get(url, headers={"X-Emby-Token": api_key}, timeout=20)
    r.raise_for_status()
    return r.json()


def _jf_set_policy(http, base_url: str, api_key: str, jf_user_id: str, policy: Dict[str, Any]) -> None:
    url = f"{base_url}/Users/{jf_user_id}/Policy"

    # IMPORTANT: envoyer du vrai JSON avec Content-Type: application/json
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Emby-Token": api_key,
    }

    # `json=` force requests à sérialiser en JSON + bon header
    r = http.post(url, json=policy, headers=headers, timeout=20)

    # Certains serveurs/versions acceptent PUT plutôt que POST.
    # Si POST n'est pas accepté, on tente PUT.
    if r.status_code in (405, 415):
        r = http.put(url, json=policy, headers=headers, timeout=20)

    r.raise_for_status()



def _apply_policy_enabled_folders(
    http,
    base_url: str,
    api_key: str,
    jf_user_id: str,
    enabled_folders: List[str],
) -> None:
    """
    Apply library restrictions by forcing:
      - EnableAllFolders = False
      - EnabledFolders = [folderIds]
    """
    user_obj = _jf_get_user(http, base_url, api_key, jf_user_id)
    policy = user_obj.get("Policy") or {}
    if not isinstance(policy, dict):
        policy = {}

    before_all = policy.get("EnableAllFolders")
    before_folders = policy.get("EnabledFolders")

    policy["EnableAllFolders"] = False
    policy["EnabledFolders"] = enabled_folders

    logger.info(
        f"Jellyfin policy update user={jf_user_id}: "
        f"EnableAllFolders {before_all} -> {policy['EnableAllFolders']}, "
        f"EnabledFolders {before_folders} -> {enabled_folders}"
    )

    _jf_set_policy(http, base_url, api_key, jf_user_id, policy)


# ---------------------------------------------------------------------
# DB helpers (DBManager from tasks_engine)
# ---------------------------------------------------------------------
def _fetch_pending_jobs(db, limit: int = 50):
    return db.query(
        """
        SELECT id, provider, action, vodum_user_id, server_id, library_id, payload_json, status, priority, run_after, locked_by, locked_until, attempts, max_attempts, last_error, processed, success, created_at, processed_at, executed_at, dedupe_key FROM media_jobs
        WHERE processed = 0
          AND provider = 'jellyfin'
          AND action IN ('grant','revoke','sync')
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (limit,),
    )


def _mark_attempt(db, job_id: int) -> None:
    db.execute(
        """
        UPDATE media_jobs
        SET attempts = attempts + 1,
            executed_at = CURRENT_TIMESTAMP,
            last_error = NULL
        WHERE id = ?
        """,
        (job_id,),
    )


def _mark_success(db, job_id: int) -> None:
    db.execute(
        """
        UPDATE media_jobs
        SET processed = 1,
            success = 1,
            last_error = NULL,
            processed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (job_id,),
    )


def _mark_jellyfin_account_removed(db, media_user_id: int, jf_user_id: str) -> None:
    row = db.query_one(
        "SELECT details_json FROM media_users WHERE id = ?",
        (media_user_id,),
    )
    details: Dict[str, Any] = {}
    if row and row["details_json"]:
        try:
            parsed = json.loads(row["details_json"])
            if isinstance(parsed, dict):
                details = parsed
        except (TypeError, ValueError):
            pass

    details.update(
        {
            "provider_presence": "removed",
            "provider_presence_external_user_id": jf_user_id,
            "provider_presence_checked_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
    )
    db.execute(
        "UPDATE media_users SET details_json = ? WHERE id = ?",
        (json.dumps(details, ensure_ascii=False), media_user_id),
    )


def _mark_failure(db, job_id: int, err: str) -> None:
    """
    IMPORTANT:
    - we DO NOT set processed=1 on failure
    - so the job remains pending and can be retried
    """
    db.execute(
        """
        UPDATE media_jobs
        SET success = 0,
            last_error = ?
        WHERE id = ?
        """,
        (err, job_id),
    )


def _get_server(db, server_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT id, name, server_identifier, type, url, local_url, public_url, token, settings_json, server_version, unavailable_since, cooldown_until, last_failure, last_checked, status FROM servers WHERE id = ?", (server_id,))
    return dict(row) if row else None


def _get_jellyfin_accounts(db, vodum_user_id: int, server_id: int) -> List[Dict[str, Any]]:
    rows = db.query(
        """
        SELECT id, external_user_id, username, details_json
        FROM media_users
        WHERE vodum_user_id = ?
          AND server_id = ?
          AND type = 'jellyfin'
        """,
        (vodum_user_id, server_id),
    )
    return [dict(r) for r in rows]


def _get_desired_enabled_folders(db, vodum_user_id: int, server_id: int) -> List[str]:
    """
    Source of truth:
      media_user_libraries + libraries.section_id
    restricted to THIS server + jellyfin media_users.

    NOTE:
    EnabledFolders will be set to these section_id values as strings.
    """
    rows = db.query(
        """
        SELECT DISTINCT l.section_id
        FROM media_user_libraries mul
        JOIN media_users mu ON mu.id = mul.media_user_id
        JOIN libraries l ON l.id = mul.library_id
        WHERE mu.vodum_user_id = ?
          AND mu.server_id = ?
          AND mu.type = 'jellyfin'
          AND l.server_id = ?
        ORDER BY l.section_id
        """,
        (vodum_user_id, server_id, server_id),
    )

    out: List[str] = []
    for r in rows:
        # r is sqlite3.Row -> use [] access (NOT .get)
        sid = r["section_id"]
        if sid is None:
            continue
        out.append(str(sid))
    return out


def _process_job(db, job: Dict[str, Any]) -> None:
    vodum_user_id = job.get("vodum_user_id")
    server_id = job.get("server_id")

    if vodum_user_id is None or server_id is None:
        raise RuntimeError("invalide job: vodum_user_id or server_id missing.")

    vodum_user_id = int(vodum_user_id)
    server_id = int(server_id)

    server = _get_server(db, server_id)
    if not server:
        raise RuntimeError(f"Server missing (id={server_id}).")

    base_url = _pick_server_base_url(server)
    api_key = _get_jellyfin_api_key(server)
    http = server_http_session(server)

    accounts = _get_jellyfin_accounts(db, vodum_user_id, server_id)
    if not accounts:
        logger.info(f"No Jellyfin account for vodum_user_id={vodum_user_id} on server_id={server_id}.")
        return

    enabled_folders = _get_desired_enabled_folders(db, vodum_user_id, server_id)

    logger.info(
        f"Apply Jellyfin access: vodum_user_id={vodum_user_id}, server_id={server_id}, "
        f"enabled_folders={enabled_folders}"
    )

    for acc in accounts:
        jf_user_id = (acc.get("external_user_id") or "").strip()
        if not jf_user_id:
            logger.warning(
                f"Jellyfin account without external_user_id (vodum_user_id={vodum_user_id}, server_id={server_id})."
            )
            continue

        try:
            account_details = json.loads(acc.get("details_json") or "{}")
        except (TypeError, ValueError):
            account_details = {}
        if isinstance(account_details, dict) and account_details.get("provider_presence") == "removed":
            logger.info(
                f"Skipping removed Jellyfin account media_user_id={acc['id']} "
                f"vodum_user_id={vodum_user_id} server_id={server_id}"
            )
            continue

        try:
            _apply_policy_enabled_folders(http, base_url, api_key, jf_user_id, enabled_folders)
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is None or response.status_code != 404:
                raise
            _mark_jellyfin_account_removed(db, int(acc["id"]), jf_user_id)
            logger.warning(
                f"Jellyfin account marked removed: media_user_id={acc['id']} "
                f"vodum_user_id={vodum_user_id} server_id={server_id} "
                f"external_user_id={jf_user_id}"
            )


# ---------------------------------------------------------------------
# Entry point expected by tasks_engine: run(task_id, db)
# ---------------------------------------------------------------------
def run(task_id: int, db) -> None:
    logger.debug("=== APPLY JELLYFIN ACCESS UPDATES : START ===")

    jobs = _fetch_pending_jobs(db, limit=50)
    if not jobs:
        logger.debug("No jobs to process.")
        logger.debug("=== APPLY JELLYFIN ACCESS UPDATES : END ===")
        return

    for job_row in jobs:
        # sqlite3.Row -> dict (so .get() works safely everywhere)
        job = dict(job_row)
        job_id = int(job["id"])
        server = _get_server(db, int(job["server_id"]))
        if server and should_skip_unreachable_server(server):
            logger.info(
                f"Skipping Jellyfin job id={job_id}: server_id={job['server_id']} is in cooldown"
            )
            continue
            
        # ✅ Sécurité: ne traite que grant/revoke/sync (jamais refresh monitoring)
        action = (job.get("action") or "").lower().strip()
        if action not in ("grant", "revoke", "sync"):
            logger.warning(
                f"Skipping Jellyfin job id={job_id}: unsupported action '{action}' "
                f"(expected grant/revoke/sync)"
            )
            continue

        try:
            _mark_attempt(db, job_id)
            logger.info(
                f"Traitement job Jellyfin id={job_id} action={action} "
                f"server_id={job.get('server_id')} vodum_user_id={job.get('vodum_user_id')}"
            )

            _process_job(db, job)

            _mark_success(db, job_id)

        except Exception as e:
            logger.error(f"Jellyfin job {job_id} failed: {e}", exc_info=True)
            _mark_failure(db, job_id, str(e))

    logger.debug("=== APPLY JELLYFIN ACCESS UPDATES : END ===")
