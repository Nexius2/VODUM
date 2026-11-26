"""Durable portal submissions. A lost worker may replay checks, never an ARR POST."""

import json
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from core.portal_account_state import state_allows_portal
from core.portal_request_options import request_options
from core.portal_media_requests import MediaRequestError, submit_request
from core.portal_media_request_tracking import reconcile_uncertain_seerr_jobs, refresh_seerr_states
from core.portal_media_requests_tvdb import valid_tvdb_id
from core.portal_audit import record_portal_event
from core.tasks.worker_lease import WorkerLease
from core.tasks.database_restore_gate import database_restore_gate
from logging_utils import get_logger


JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_media_request_jobs (
    id TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES portal_accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('movie', 'series')),
    external_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'arr' CHECK(source IN ('arr', 'seerr')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'checking', 'submitting', 'done')),
    result TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    is_4k INTEGER,
    seasons TEXT,
    seerr_server_id INTEGER,
    seerr_request_id INTEGER,
    seerr_state TEXT,
    seerr_checked_at TEXT,
    tvdb_id INTEGER
)
"""
JOB_COLUMNS = {
    # Existing databases predate the Seerr backend; ARR stays the default.
    "source": "TEXT NOT NULL DEFAULT 'arr' CHECK(source IN ('arr', 'seerr'))",
    # Member choices (NULL = no choice made) and the Seerr request VODUM follows afterwards.
    "is_4k": "INTEGER",
    "seasons": "TEXT",
    "seerr_server_id": "INTEGER",
    "seerr_request_id": "INTEGER",
    "seerr_state": "TEXT",
    "seerr_checked_at": "TEXT",
    # TVDB series the member picked when Seerr has no TVDB id for the title.
    "tvdb_id": "INTEGER",
}
JOB_INDEXES = (
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_request_active
       ON portal_media_request_jobs(account_id, kind, external_id, source) WHERE status <> 'done'""",
    """CREATE INDEX IF NOT EXISTS idx_portal_request_queue
       ON portal_media_request_jobs(status, created_at)""",
)
_WAKE = Event()
_WORKER = WorkerLease()
_ALLOWED = """
    SELECT a.status AS account_status, u.status AS user_status
    FROM portal_accounts a JOIN vodum_users u ON u.id = a.vodum_user_id
    CROSS JOIN settings s
    WHERE a.id = ? AND a.vodum_user_id = ?
      AND s.id = 1 AND COALESCE(s.portal_show_media_requests, 1) = 1
      AND (s.portal_enabled = 1 OR s.portal_local_test_enabled = 1)
"""


def _can_submit(row):
    return row and state_allows_portal(row["account_status"], row["user_status"])


def enqueue_media_request(db, account_id, kind, external_id, title, source="arr", *, is_4k=None, seasons=None,
                          tvdb_id=None):
    if kind not in ("movie", "series") or type(external_id) is not int or not 0 < external_id <= 2**63 - 1:
        raise MediaRequestError("portal_requests_invalid")
    if source not in ("arr", "seerr") or source != request_options(db)[0]:
        raise MediaRequestError("portal_requests_invalid")
    if source != "seerr" or kind != "series":
        tvdb_id = None
    if source != "seerr":
        is_4k, seasons = None, None
    if tvdb_id is not None and not valid_tvdb_id(tvdb_id):
        raise MediaRequestError("portal_requests_invalid")
    if is_4k is not None:
        is_4k = 1 if is_4k else 0
    if seasons is not None:
        if kind != "series" or not isinstance(seasons, (list, tuple)) or not seasons \
                or any(type(number) is not int or number <= 0 for number in seasons) or len(seasons) > 100:
            raise MediaRequestError("portal_requests_invalid")
        seasons = json.dumps(sorted(set(seasons)))
    with db.transaction() as cursor:
        cursor.execute("""
            SELECT id FROM portal_media_request_jobs
            WHERE account_id = ? AND kind = ? AND external_id = ? AND source = ? AND status <> 'done'
        """, (account_id, kind, external_id, source))
        existing = cursor.fetchone()
        if existing:
            return existing["id"]
        cursor.execute("""
            SELECT COUNT(*) AS total, SUM(account_id = ?) AS own
            FROM portal_media_request_jobs WHERE status <> 'done'
        """, (account_id,))
        counts = cursor.fetchone()
        if counts["total"] >= 32 or (counts["own"] or 0) >= 3:
            raise MediaRequestError("portal_requests_busy")
        job_id = uuid4().hex
        cursor.execute("""
            INSERT INTO portal_media_request_jobs(id, account_id, kind, external_id, title, source, is_4k, seasons, tvdb_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, account_id, kind, external_id, str(title or "")[:200], source, is_4k, seasons, tvdb_id))
    _WAKE.set()
    return job_id


def _job_seasons(value):
    try:
        seasons = json.loads(value) if value else None
    except (TypeError, ValueError):
        return None
    return seasons if isinstance(seasons, list) and all(type(n) is int for n in seasons) else None


def media_request_jobs(db, account_id, *, refresh=True):
    """The member's recent jobs; Seerr requests also carry the state Seerr reports for them.

    ``refresh`` asks Seerr for the current state of requests that are not final
    yet, at most once per minute per request and within a short overall deadline,
    so the request page and its poll stay responsive when Seerr is slow.
    """
    limit = request_options(db)[1]
    jobs = []
    for row in db.query("""
        SELECT id, title, status, result, source, kind, external_id, finished_at, is_4k, seasons, seerr_server_id,
               seerr_request_id, seerr_state,
               seerr_checked_at IS NULL OR seerr_checked_at <= datetime('now', '-60 seconds') AS stale
        FROM portal_media_request_jobs
        WHERE account_id = ?
        ORDER BY (status = 'done'), created_at DESC, rowid DESC LIMIT ?
    """, (account_id, limit)):
        job = dict(row)
        job["seasons"] = _job_seasons(job["seasons"])
        job["is_4k"] = None if job["is_4k"] is None else bool(job["is_4k"])
        jobs.append(job)
    if refresh:
        reconcile_uncertain_seerr_jobs(db, account_id, jobs)
        refresh_seerr_states(db, jobs)
    for job in jobs:
        # Seerr never answered clearly: say so in Seerr terms, not "Sonarr/Radarr".
        if job["source"] == "seerr" and job["result"] == "portal_requests_add_uncertain":
            job["result"] = "portal_requests_seerr_unconfirmed"
        for key in ("source", "seerr_server_id", "seerr_request_id", "stale", "external_id", "finished_at"):
            job.pop(key, None)
    return jobs


def _claim(db):
    if not db.query_one("""
        SELECT 1 FROM portal_media_request_jobs
        WHERE status = 'queued' OR (status IN ('checking', 'submitting') AND lease_until <= CURRENT_TIMESTAMP)
        LIMIT 1
    """):
        return None
    with db.transaction() as cursor:
        cursor.execute("""
            UPDATE portal_media_request_jobs
            SET status = CASE WHEN status = 'checking' AND attempts < 3 THEN 'queued' ELSE 'done' END,
                result = CASE WHEN status = 'submitting' THEN 'portal_requests_add_uncertain'
                              WHEN attempts >= 3 THEN 'portal_requests_unavailable' END,
                finished_at = CASE WHEN status = 'submitting' OR attempts >= 3 THEN CURRENT_TIMESTAMP END,
                lease_id = NULL, lease_until = NULL
            WHERE status IN ('checking', 'submitting') AND lease_until <= CURRENT_TIMESTAMP
        """)
        cursor.execute("""
            SELECT j.id, j.account_id, j.kind, j.external_id, j.title, j.source, j.is_4k, j.seasons, j.tvdb_id,
                   a.vodum_user_id
            FROM portal_media_request_jobs j JOIN portal_accounts a ON a.id = j.account_id
            WHERE j.status = 'queued' AND NOT EXISTS (
                SELECT 1 FROM portal_media_request_jobs WHERE status IN ('checking', 'submitting')
            )
            ORDER BY j.created_at, j.rowid LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None
        job = dict(row)
        job["lease_id"] = uuid4().hex
        cursor.execute("""
            UPDATE portal_media_request_jobs
            SET status = 'checking', attempts = attempts + 1, lease_id = ?,
                lease_until = datetime('now', '+5 minutes') WHERE id = ?
        """, (job["lease_id"], job["id"]))
        return job


def process_media_request_job(db):
    job = _claim(db)
    if not job:
        return False
    account = (job["account_id"], job["vodum_user_id"])
    lease = (job["id"], job["lease_id"])
    submitting = False
    tracking = {}

    def before_post():
        nonlocal submitting
        with db.transaction() as cursor:
            selected = cursor.execute("SELECT portal_request_backend FROM settings WHERE id=1").fetchone()
            if not selected or selected["portal_request_backend"] != job["source"]:
                raise MediaRequestError("portal_requests_invalid")
            cursor.execute(_ALLOWED, account)
            if not _can_submit(cursor.fetchone()):
                raise MediaRequestError("portal_requests_unavailable")
            cursor.execute("""
                UPDATE portal_media_request_jobs SET status = 'submitting',
                    lease_until = datetime('now', '+5 minutes')
                WHERE id = ? AND lease_id = ? AND status = 'checking'
                  AND lease_until > CURRENT_TIMESTAMP
            """, lease)
            if cursor.rowcount != 1:
                raise MediaRequestError("portal_requests_unavailable")
        submitting = True

    try:
        if job["source"] != request_options(db)[0] or not _can_submit(db.query_one(_ALLOWED, account)):
            raise MediaRequestError("portal_requests_unavailable")
        result = submit_request(db, job["vodum_user_id"], None, job["kind"], job["external_id"],
                                before_post=before_post, source=job["source"] or "arr",
                                is_4k=None if job["is_4k"] is None else bool(job["is_4k"]),
                                seasons=_job_seasons(job["seasons"]), on_submitted=tracking.update,
                                tvdb_choice=job["tvdb_id"])
    except MediaRequestError as exc:
        result = str(exc)
        if submitting and result == "portal_requests_unavailable":
            result = "portal_requests_add_uncertain"
    except Exception:
        get_logger("portal_media_request_jobs").exception("Media request job failed | id=%s", job["id"])
        result = "portal_requests_add_uncertain" if submitting else "portal_requests_unavailable"
    updated = db.execute("""
        UPDATE portal_media_request_jobs SET status = 'done', result = ?,
            finished_at = CURRENT_TIMESTAMP, lease_id = NULL, lease_until = NULL,
            is_4k = COALESCE(?, is_4k), seerr_server_id = ?, seerr_request_id = ?, seerr_state = ?,
            seerr_checked_at = CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END
        WHERE id = ? AND lease_id = ?
    """, (result, None if tracking.get("is_4k") is None else int(tracking["is_4k"]),
          tracking.get("seerr_server_id"), tracking.get("seerr_request_id"), tracking.get("seerr_state"),
          tracking.get("seerr_request_id"), *lease))
    if updated.rowcount:
        success = result in {"portal_requests_added", "portal_requests_pending", "portal_requests_present",
                             "portal_requests_seerr_awaiting_approval", "portal_requests_seerr_nothing_to_request"}
        details = {"media_kind": job["kind"], "external_id": job["external_id"],
                   "media_title": job["title"], "request_result": result,
                   "request_source": job["source"] or "arr"}
        if tracking.get("seerr_request_id") is not None:
            details.update({"seerr_request_id": tracking["seerr_request_id"], "is_4k": bool(tracking.get("is_4k")),
                            "seasons": tracking.get("seasons") or "all"})
        record_portal_event(db, "media_requested", "success" if success else "failure",
                            portal_account_id=job["account_id"], details=details)
    return True


def start_media_request_worker(db_provider):
    if not _WORKER.claim():
        return

    def run():
        cleanup_due = 0
        try:
            while True:
                _WAKE.clear()
                try:
                    with database_restore_gate.background() as allowed:
                        if allowed:
                            db = db_provider()
                            if process_media_request_job(db):
                                continue
                            if monotonic() >= cleanup_due:
                                db.execute("""
                                    DELETE FROM portal_media_request_jobs WHERE id IN (
                                        SELECT id FROM portal_media_request_jobs WHERE status = 'done'
                                        AND finished_at < datetime('now', '-7 days') LIMIT 100
                                    )
                                """)
                                cleanup_due = monotonic() + 60
                except Exception:
                    get_logger("portal_media_request_jobs").exception("Media request worker failed")
                    _WAKE.wait(10)
                _WAKE.wait(2)
        finally:
            _WORKER.release()

    try:
        Thread(target=run, name="vodum-portal-requests", daemon=True).start()
    except Exception:
        _WORKER.release()
        raise
