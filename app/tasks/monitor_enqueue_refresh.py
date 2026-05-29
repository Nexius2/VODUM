import json
from datetime import datetime, timezone
from core.server_cooldown import should_skip_unreachable_server

DEFAULT_INTERVAL_SEC = 60
MIN_INTERVAL_SEC = 15


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_sqlite_ts(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def run(task_id, db):
    """
    Toutes les minutes:
    - regarde les serveurs plex/jellyfin
    - si le dernier refresh monitoring est trop ancien => enfile un job refresh
    """
    servers = db.query("""
        SELECT id, type, settings_json, status, cooldown_until
        FROM servers
        WHERE LOWER(TRIM(type)) IN ('plex','jellyfin')
    """)

    now = _utcnow()
    enqueued = 0
    skipped_existing = 0
    due = 0

    for s in servers:
        server_id = int(s["id"])
        provider = (s["type"] or "").lower().strip()
        if should_skip_unreachable_server(s):
            continue

        interval = DEFAULT_INTERVAL_SEC
        settings_json = s["settings_json"]
        if settings_json:
            try:
                settings = json.loads(settings_json)
                interval = int(settings.get("monitoring_interval_sec", DEFAULT_INTERVAL_SEC))
            except Exception:
                interval = DEFAULT_INTERVAL_SEC

        if interval < MIN_INTERVAL_SEC:
            interval = MIN_INTERVAL_SEC

        last_refresh_row = db.query_one("""
            SELECT COALESCE(MAX(processed_at), MAX(created_at)) AS last_refresh
            FROM media_jobs
            WHERE action = 'refresh'
              AND server_id = ?
              AND status = 'success'
        """, (server_id,))

        last_refresh = _parse_sqlite_ts(last_refresh_row["last_refresh"]) if last_refresh_row else None

        is_due = (last_refresh is None) or ((now - last_refresh).total_seconds() >= interval)
        if not is_due:
            continue

        due += 1

        dedupe_key = f"monitor:refresh:server={server_id}"
        payload = json.dumps({"interval_sec": interval, "reason": "schedule"}, ensure_ascii=False)

        existing = db.query_one("""
            SELECT id, status, run_after, locked_until
            FROM media_jobs
            WHERE dedupe_key = ?
              AND status IN ('queued', 'running')
            LIMIT 1
        """, (dedupe_key,))

        if existing:
            status = (existing["status"] or "").strip().lower()

            # Cas important :
            # un ancien job monitoring peut être en queued mais repoussé par backoff.
            # Pour du live monitoring, on ne veut pas bloquer le refresh pendant 30 min / 1h / 2h.
            if status == "queued":
                db.execute("""
                    UPDATE media_jobs
                    SET run_after = NULL,
                        priority = 100,
                        payload_json = ?,
                        locked_by = NULL,
                        locked_until = NULL,
                        last_error = NULL
                    WHERE id = ?
                      AND status = 'queued'
                """, (payload, existing["id"]))

                enqueued += 1
                continue

            # Cas sécurité : job running bloqué avec lock expiré ou absent
            if status == "running":
                db.execute("""
                    UPDATE media_jobs
                    SET status = 'queued',
                        run_after = NULL,
                        locked_by = NULL,
                        locked_until = NULL,
                        last_error = 'Recovered stale monitoring job'
                    WHERE id = ?
                      AND status = 'running'
                      AND (
                            locked_until IS NULL
                         OR locked_until <= CURRENT_TIMESTAMP
                      )
                """, (existing["id"],))

                enqueued += 1
                continue

            skipped_existing += 1
            continue

        db.execute("""
            INSERT INTO media_jobs (
                provider, action, server_id,
                payload_json,
                status, priority, run_after,
                dedupe_key,
                created_at
            )
            VALUES (?, 'refresh', ?, ?, 'queued', 100, NULL, ?, CURRENT_TIMESTAMP)
        """, (provider, server_id, payload, dedupe_key))

        enqueued += 1

    return {
        "servers": len(servers),
        "due": due,
        "enqueued": enqueued,
        "skipped_existing": skipped_existing,
    }