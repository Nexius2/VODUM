"""Durable portal submissions. A lost worker may replay checks, never an ARR POST."""

from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from core.portal_account_state import state_allows_portal
from core.portal_media_requests import MediaRequestError, submit_request
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
    finished_at TEXT
)
"""
JOB_COLUMNS = {
    # Existing databases predate the Seerr backend; ARR stays the default.
    "source": "TEXT NOT NULL DEFAULT 'arr' CHECK(source IN ('arr', 'seerr'))",
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


def enqueue_media_request(db, account_id, kind, external_id, title, source="arr"):
    if kind not in ("movie", "series") or type(external_id) is not int or not 0 < external_id <= 2**63 - 1:
        raise MediaRequestError("portal_requests_invalid")
    if source not in ("arr", "seerr"):
        raise MediaRequestError("portal_requests_invalid")
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
            INSERT INTO portal_media_request_jobs(id, account_id, kind, external_id, title, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job_id, account_id, kind, external_id, str(title or "")[:200], source))
    _WAKE.set()
    return job_id


def media_request_jobs(db, account_id):
    return [dict(row) for row in db.query("""
        SELECT id, title, status, result FROM portal_media_request_jobs
        WHERE account_id = ? AND (status <> 'done' OR finished_at >= datetime('now', '-1 day'))
        ORDER BY (status = 'done'), created_at DESC, rowid DESC LIMIT 10
    """, (account_id,))]


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
            SELECT j.id, j.account_id, j.kind, j.external_id, j.title, j.source, a.vodum_user_id
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

    def before_post():
        nonlocal submitting
        with db.transaction() as cursor:
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
        if not _can_submit(db.query_one(_ALLOWED, account)):
            raise MediaRequestError("portal_requests_unavailable")
        result = submit_request(db, job["vodum_user_id"], None, job["kind"], job["external_id"],
                                before_post=before_post, source=job["source"] or "arr")
    except MediaRequestError as exc:
        result = str(exc)
        if submitting and result == "portal_requests_unavailable":
            result = "portal_requests_add_uncertain"
    except Exception:
        get_logger("portal_media_request_jobs").exception("Media request job failed | id=%s", job["id"])
        result = "portal_requests_add_uncertain" if submitting else "portal_requests_unavailable"
    updated = db.execute("""
        UPDATE portal_media_request_jobs SET status = 'done', result = ?,
            finished_at = CURRENT_TIMESTAMP, lease_id = NULL, lease_until = NULL
        WHERE id = ? AND lease_id = ?
    """, (result, *lease))
    if updated.rowcount:
        success = result in {"portal_requests_added", "portal_requests_pending", "portal_requests_present",
                             "portal_requests_seerr_awaiting_approval"}
        record_portal_event(db, "media_requested", "success" if success else "failure",
                            portal_account_id=job["account_id"],
                            details={"media_kind": job["kind"], "external_id": job["external_id"],
                                     "media_title": job["title"], "request_result": result,
                                     "request_source": job["source"] or "arr"})
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
