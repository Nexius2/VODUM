from datetime import datetime, timezone, timedelta


DEFAULT_COOLDOWN_SECONDS = 300


def _dt_sqlite(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_get(row, key, default=None):
    if not row:
        return default

    if isinstance(row, dict):
        return row.get(key, default)

    try:
        return row[key]
    except Exception:
        return default


def _parse_sqlite_utc(value):
    if not value:
        return None

    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def get_server_cooldown_remaining_seconds(server_row) -> int:
    cooldown_until = _row_get(server_row, "cooldown_until")
    until = _parse_sqlite_utc(cooldown_until)

    if not until:
        return 0

    remaining = int((until - datetime.now(timezone.utc)).total_seconds())
    return max(0, remaining)


def is_server_in_cooldown(server_row) -> bool:
    return get_server_cooldown_remaining_seconds(server_row) > 0


def should_skip_unreachable_server(server_row) -> bool:
    status = str(_row_get(server_row, "status") or "").lower().strip()
    return status == "down" or is_server_in_cooldown(server_row)



def mark_server_unreachable(db, server_id: int, reason: str, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
    now = datetime.now(timezone.utc)
    cooldown_until = _dt_sqlite(now + timedelta(seconds=cooldown_seconds))

    db.execute(
        """
        UPDATE servers
        SET status = 'down',
            last_checked = CURRENT_TIMESTAMP,
            unavailable_since = COALESCE(unavailable_since, CURRENT_TIMESTAMP),
            cooldown_until = ?,
            last_failure = ?
        WHERE id = ?
        """,
        (cooldown_until, str(reason or "")[:1000], int(server_id)),
    )


def clear_server_cooldown(db, server_id: int) -> None:
    db.execute(
        """
        UPDATE servers
        SET cooldown_until = NULL,
            unavailable_since = NULL,
            last_failure = NULL
        WHERE id = ?
        """,
        (int(server_id),),
    )