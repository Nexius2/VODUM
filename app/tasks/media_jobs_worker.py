import json
import socket
from datetime import datetime, timezone, timedelta

WORKER_ID = socket.gethostname()

LEASE_SECONDS = 120          # durée du lock
MAX_BATCH = 20               # jobs max par run
TIME_BUDGET_SECONDS = 25     # temps max par run (évite chevauchements)


def _utcnow():
    return datetime.now(timezone.utc)


def _dt_sqlite(ts: datetime) -> str:
    # SQLite CURRENT_TIMESTAMP => "YYYY-MM-DD HH:MM:SS"
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _backoff_seconds(attempts: int) -> int:
    # 1->30s, 2->2m, 3->10m, 4->30m, 5->1h, sinon 2h
    return {1: 30, 2: 120, 3: 600, 4: 1800, 5: 3600}.get(attempts, 7200)


def _claim_one(db):
    """
    Claim d'UN job éligible:
    - status=queued
    - run_after <= now
    - lease expiré ou NULL
    - IMPORTANT: uniquement action='refresh' (monitoring)
    """
    now = _utcnow()
    locked_until = _dt_sqlite(now + timedelta(seconds=LEASE_SECONDS))

    job = db.query_one("""
        SELECT *
        FROM media_jobs
        WHERE status='queued'
          AND action='refresh'
          AND (run_after IS NULL OR run_after <= CURRENT_TIMESTAMP)
          AND (locked_until IS NULL OR locked_until <= CURRENT_TIMESTAMP)
        ORDER BY priority ASC, created_at ASC
        LIMIT 1
    """)
    if not job:
        return None

    db.execute("""
        UPDATE media_jobs
        SET status='running',
            locked_by=?,
            locked_until=?,
            executed_at=CURRENT_TIMESTAMP,
            attempts=attempts+1
        WHERE id=?
          AND status='queued'
          AND action='refresh'
          AND (locked_until IS NULL OR locked_until <= CURRENT_TIMESTAMP)
    """, (WORKER_ID, locked_until, job["id"]))

    claimed = db.query_one("SELECT * FROM media_jobs WHERE id=?", (job["id"],))
    if not claimed or claimed["status"] != "running" or claimed["locked_by"] != WORKER_ID:
        return None

    return claimed


def _mark_success(db, job_id: int):
    db.execute("""
        UPDATE media_jobs
        SET status='success',
            processed=1,
            success=1,
            processed_at=CURRENT_TIMESTAMP,
            locked_by=NULL,
            locked_until=NULL,
            last_error=NULL
        WHERE id=?
    """, (job_id,))


def _mark_retry_or_error(db, job, err: str):
    attempts = int(job["attempts"] or 0)
    max_attempts = int(job["max_attempts"] or 10)

    if attempts >= max_attempts:
        db.execute("""
            UPDATE media_jobs
            SET status='error',
                processed=1,
                success=0,
                processed_at=CURRENT_TIMESTAMP,
                locked_by=NULL,
                locked_until=NULL,
                last_error=?
            WHERE id=?
        """, (err[:2000], job["id"]))
        return

    delay = _backoff_seconds(attempts)
    run_after = _dt_sqlite(_utcnow() + timedelta(seconds=delay))

    db.execute("""
        UPDATE media_jobs
        SET status='queued',
            run_after=?,
            locked_by=NULL,
            locked_until=NULL,
            last_error=?
        WHERE id=?
    """, (run_after, err[:2000], job["id"]))


def _execute_job(db, job):
    """
    Exécute la collecte MONITORING pour 1 serveur.
    """
    provider = (job["provider"] or "").lower().strip()
    server_id = int(job["server_id"])

    payload = None
    payload_json = job["payload_json"]
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = None

    # Ton collector fait déjà:
    # - upsert media_sessions
    # - events
    # - history
    # - update servers.status up/down + last_checked
    from core.monitoring.collector import collect_sessions_for_server
    collect_sessions_for_server(db, server_id=server_id, provider=provider, payload=payload)


def run(task_id, db):
    start = _utcnow()
    processed = 0
    errors = 0

    while processed < MAX_BATCH:
        if (_utcnow() - start).total_seconds() >= TIME_BUDGET_SECONDS:
            break

        job = _claim_one(db)
        if not job:
            break

        try:
            _execute_job(db, job)
            _mark_success(db, job["id"])
            processed += 1

        except Exception as e:
            errors += 1
            _mark_retry_or_error(db, job, str(e))
            # on continue, pour ne pas bloquer la boucle

    return {"processed": processed, "errors": errors}
