import json
from datetime import datetime, timezone

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
    - si "dus" => enfile un job refresh (dedupe_key)
    """
    servers = db.query("""
        SELECT id, type, last_checked, settings_json
        FROM servers
        WHERE type IN ('plex','jellyfin')
    """)

    now = _utcnow()
    enqueued = 0
    due = 0

    for s in servers:
        server_id = int(s["id"])
        provider = (s["type"] or "").lower().strip()

        last_checked = _parse_sqlite_ts(s["last_checked"])

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

        is_due = (last_checked is None) or ((now - last_checked).total_seconds() >= interval)
        if not is_due:
            continue

        due += 1

        dedupe_key = f"monitor:refresh:server={server_id}"
        payload = json.dumps({"interval_sec": interval, "reason": "schedule"}, ensure_ascii=False)

        cur = db.execute("""
            INSERT OR IGNORE INTO media_jobs (
                provider, action, server_id,
                payload_json,
                status, priority, run_after,
                dedupe_key,
                created_at
            )
            VALUES (?, 'refresh', ?, ?, 'queued', 100, NULL, ?, CURRENT_TIMESTAMP)
        """, (provider, server_id, payload, dedupe_key))

        # db.execute peut retourner un cursor sqlite3, selon ton db_manager
        try:
            if cur and getattr(cur, "rowcount", 0) == 1:
                enqueued += 1
        except Exception:
            # si rowcount pas dispo, on ne casse pas la tâche
            pass

    return {"servers": len(servers), "due": due, "enqueued_attempted": enqueued}
