import json
import os
import socket
import uuid
from datetime import datetime, timezone, timedelta
from core.monitoring.collector import collect_sessions_for_server

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _new_lock_owner() -> str:
    return f"{WORKER_ID}:{uuid.uuid4().hex[:12]}"

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

def _recover_expired_running_refresh_jobs(db):
    """
    Remet en file les jobs monitoring restés bloqués en running.

    Cas typique:
    - Vodum démarre un job refresh
    - le process redémarre/crash avant _mark_success() ou _mark_retry_or_error()
    - le job reste en running
    - le dedupe_key empêche tout nouveau job pour ce serveur

    On ne récupère que les jobs dont le lease est expiré.
    """
    db.execute("""
        UPDATE media_jobs
        SET status='queued',
            locked_by=NULL,
            locked_until=NULL,
            last_error='Recovered expired running monitoring job'
        WHERE status='running'
          AND action='refresh'
          AND locked_until IS NOT NULL
          AND locked_until <= CURRENT_TIMESTAMP
    """)

def _cleanup_finished_refresh_jobs(db):
    """
    Nettoie les anciens jobs monitoring terminés.

    Sans ça, media_jobs grossit en continu.
    On garde un historique récent pour debug, mais on évite que la table devienne
    un cimetière de jobs success/error.
    """
    db.execute("""
        DELETE FROM media_jobs
        WHERE action='refresh'
          AND status='success'
          AND processed_at IS NOT NULL
          AND processed_at < datetime('now', '-2 days')
    """)

    db.execute("""
        DELETE FROM media_jobs
        WHERE action='refresh'
          AND status IN ('error', 'canceled')
          AND processed_at IS NOT NULL
          AND processed_at < datetime('now', '-7 days')
    """)

def _claim_one(db):
    """
    Claim d'UN job monitoring.

    Le locked_by est unique à chaque claim, pas seulement au hostname.
    Ça évite qu'une double exécution du worker sur la même machine traite
    le même job deux fois.
    """
    now = _utcnow()
    locked_until = _dt_sqlite(now + timedelta(seconds=LEASE_SECONDS))
    lock_owner = _new_lock_owner()

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

    cur = db.execute("""
        UPDATE media_jobs
        SET status='running',
            locked_by=?,
            locked_until=?,
            executed_at=CURRENT_TIMESTAMP,
            attempts=attempts+1
        WHERE id=?
          AND status='queued'
          AND action='refresh'
          AND (run_after IS NULL OR run_after <= CURRENT_TIMESTAMP)
          AND (locked_until IS NULL OR locked_until <= CURRENT_TIMESTAMP)
    """, (lock_owner, locked_until, job["id"]))

    if int(getattr(cur, "rowcount", 0) or 0) != 1:
        return None

    claimed = db.query_one("SELECT * FROM media_jobs WHERE id=?", (job["id"],))
    if not claimed:
        return None

    if claimed["status"] != "running" or claimed["locked_by"] != lock_owner:
        return None

    return claimed


def _mark_success(db, job):
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
          AND status='running'
          AND locked_by=?
    """, (job["id"], job["locked_by"]))


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
              AND status='running'
              AND locked_by=?
        """, (err[:2000], job["id"], job["locked_by"]))
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
          AND status='running'
          AND locked_by=?
    """, (run_after, err[:2000], job["id"], job["locked_by"]))


def _execute_job(db, job):
    """
    Exécute la collecte MONITORING pour 1 serveur.

    Retourne le report du collector pour que le worker affiche un vrai résumé
    exploitable dans les logs de tâche.
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

    return collect_sessions_for_server(
        db,
        server_id=server_id,
        provider=provider,
        payload=payload,
    )


def run(task_id, db):
    start = _utcnow()
    processed = 0
    errors = 0
    recovered = 0
    sessions_seen = 0
    events = 0
    warnings = []
    processed_servers = []

    before_recovery = db.query_one("""
        SELECT COUNT(*) AS c
        FROM media_jobs
        WHERE status='running'
          AND action='refresh'
          AND locked_until IS NOT NULL
          AND locked_until <= CURRENT_TIMESTAMP
    """)
    recovered = int(before_recovery["c"] or 0) if before_recovery else 0

    _recover_expired_running_refresh_jobs(db)
    _cleanup_finished_refresh_jobs(db)

    while processed < MAX_BATCH:
        if (_utcnow() - start).total_seconds() >= TIME_BUDGET_SECONDS:
            break

        job = _claim_one(db)
        if not job:
            break

        try:
            result = _execute_job(db, job) or {}

            _mark_success(db, job)
            processed += 1

            sessions_seen += int(result.get("sessions_seen") or 0)
            events += int(result.get("events") or 0)

            processed_servers.append({
                "server_id": int(job["server_id"]),
                "provider": (job["provider"] or "").lower().strip(),
                "sessions_seen": int(result.get("sessions_seen") or 0),
                "events": int(result.get("events") or 0),
                "status": result.get("status"),
                "stale_sessions_kept": int(result.get("stale_sessions_kept") or 0),
            })

            if result.get("warning"):
                warnings.append({
                    "server_id": int(job["server_id"]),
                    "provider": (job["provider"] or "").lower().strip(),
                    "warning": str(result.get("warning"))[:500],
                })

        except Exception as e:
            errors += 1
            _mark_retry_or_error(db, job, str(e))
            # on continue, pour ne pas bloquer la boucle

    try:
        from core.monitoring.collector import write_monitoring_snapshot
        snapshot = write_monitoring_snapshot(db)
    except Exception as e:
        snapshot = {"error": str(e)}

    queued_left_row = db.query_one("""
        SELECT COUNT(*) AS c
        FROM media_jobs
        WHERE action='refresh'
          AND status='queued'
          AND (run_after IS NULL OR run_after <= CURRENT_TIMESTAMP)
    """)
    queued_left = int(queued_left_row["c"] or 0) if queued_left_row else 0

    running_left_row = db.query_one("""
        SELECT COUNT(*) AS c
        FROM media_jobs
        WHERE action='refresh'
          AND status='running'
    """)
    running_left = int(running_left_row["c"] or 0) if running_left_row else 0

    return {
        "processed": processed,
        "errors": errors,
        "recovered": recovered,
        "sessions_seen": sessions_seen,
        "events": events,
        "warnings": warnings,
        "processed_servers": processed_servers,
        "queued_left": queued_left,
        "running_left": running_left,
        "snapshot": snapshot,
    }
