from datetime import datetime, timedelta

from logging_utils import get_logger


logger = get_logger("stream_enforcer")
NORMAL_INTERVAL_SECONDS = 15
BOOST_INTERVAL_SECONDS = 5
BOOST_KILL_THRESHOLD = 1
BOOST_WINDOW_MINUTES = 10
BOOST_DURATION_MINUTES = 30


def _parse_sql_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def _set_interval(db, seconds: int):
    db.execute("""
        UPDATE tasks SET schedule_mode = 'interval', interval_seconds = ?,
        updated_at = CURRENT_TIMESTAMP WHERE name = 'stream_enforcer'
    """, (int(seconds),))


def _get_interval(db) -> int:
    row = db.query_one("SELECT interval_seconds FROM tasks WHERE name = 'stream_enforcer' LIMIT 1")
    try:
        return int(row["interval_seconds"] or NORMAL_INTERVAL_SECONDS) if row else NORMAL_INTERVAL_SECONDS
    except Exception:
        return NORMAL_INTERVAL_SECONDS


def _set_boost_until(db, until: datetime | None):
    value = until.strftime("%Y-%m-%d %H:%M:%S") if until else None
    db.execute("UPDATE settings SET stream_enforcer_boost_until = ? WHERE id = 1", (value,))


def _get_boost_until(db):
    row = db.query_one("SELECT stream_enforcer_boost_until FROM settings WHERE id = 1 LIMIT 1")
    return _parse_sql_datetime(row["stream_enforcer_boost_until"]) if row else None


def refresh_boost_state(db, task_id: int):
    boost_until = _get_boost_until(db)
    now = datetime.now()
    if boost_until and boost_until > now:
        if _get_interval(db) != BOOST_INTERVAL_SECONDS:
            _set_interval(db, BOOST_INTERVAL_SECONDS)
            logger.warning("[TASK %s] stream_enforcer boost active until %s -> interval=%ss", task_id, boost_until, BOOST_INTERVAL_SECONDS)
        return
    if boost_until and boost_until <= now:
        _set_boost_until(db, None)
    if _get_interval(db) != NORMAL_INTERVAL_SECONDS:
        _set_interval(db, NORMAL_INTERVAL_SECONDS)
        logger.warning("[TASK %s] stream_enforcer boost expired -> interval=%ss", task_id, NORMAL_INTERVAL_SECONDS)


def maybe_boost_after_expired_kill(db, task_id: int, policy_id: int, vodum_user_id):
    if vodum_user_id is None:
        return
    row = db.query_one("""
        SELECT COUNT(*) AS cnt FROM stream_enforcements
        WHERE policy_id = ? AND vodum_user_id = ? AND action = 'kill'
          AND datetime(created_at) >= datetime('now', ?)
    """, (int(policy_id), int(vodum_user_id), f"-{BOOST_WINDOW_MINUTES} minutes"))
    kill_count = int(row["cnt"] or 0) if row else 0
    if kill_count < BOOST_KILL_THRESHOLD:
        return
    boost_until = datetime.now() + timedelta(minutes=BOOST_DURATION_MINUTES)
    _set_boost_until(db, boost_until)
    _set_interval(db, BOOST_INTERVAL_SECONDS)
    logger.warning(
        "[TASK %s] stream_enforcer boost enabled: user=%s policy=%s kills=%s/%smin interval=%ss until=%s",
        task_id, vodum_user_id, policy_id, kill_count, BOOST_WINDOW_MINUTES,
        BOOST_INTERVAL_SECONDS, boost_until.strftime("%Y-%m-%d %H:%M:%S"),
    )
