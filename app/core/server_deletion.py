import threading

from db_manager import open_sqlite_connection


DIRECT_SERVER_TABLES = (
    "media_sessions",
    "media_events",
    "media_session_history",
    "media_jobs",
    "stream_enforcement_state",
    "stream_enforcements",
    "user_identities",
    "tautulli_import_jobs",
    "welcome_email_templates",
)

DELETION_LOG_KEYS = DIRECT_SERVER_TABLES + (
    "media_user_libraries",
    "libraries",
    "media_users",
)


def open_server_deletion_connection(db_path: str):
    return open_sqlite_connection(
        db_path,
        check_same_thread=False,
        timeout=30,
        busy_timeout_ms=30000,
    )


def server_deletion_log_args(server_id: int, server_name: str, deleted: dict) -> tuple:
    return (
        server_id,
        server_name,
        *(deleted[key] for key in DELETION_LOG_KEYS),
    )


def log_server_deletion_success(logger, server_id: int, server_name: str, deleted: dict):
    logger.info(
        "[server_delete] Done for server_id=%s name=%s | "
        "media_sessions=%s media_events=%s media_session_history=%s media_jobs=%s "
        "stream_enforcement_state=%s stream_enforcements=%s user_identities=%s "
        "tautulli_import_jobs=%s welcome_email_templates=%s "
        "media_user_libraries=%s libraries=%s media_users=%s",
        *server_deletion_log_args(server_id, server_name, deleted),
    )


def run_server_deletion_worker(db_path, server_id, server_name, logger, lock, in_progress):
    delete_key = f"server:{server_id}"
    conn = None
    try:
        conn = open_server_deletion_connection(db_path)
        logger.info(
            f"[server_delete] Start background deletion for server_id={server_id} name={server_name}"
        )
        deleted = delete_server_data(conn, server_id)
        log_server_deletion_success(logger, server_id, server_name, deleted)
    except Exception as exc:
        logger.exception(
            f"[server_delete] Failed for server_id={server_id} name={server_name}: {exc}"
        )
    finally:
        close_connection_safely(conn)
        release_server_deletion(lock, in_progress, delete_key)


def load_server_deletion_target(db, server_id: int):
    return db.query_one(
        "SELECT id, name FROM servers WHERE id = ?",
        (server_id,),
    )


def start_server_deletion_thread(
    target, app, db_path: str, server_id: int, server_name: str,
):
    thread = threading.Thread(
        target=target,
        args=(app, db_path, int(server_id), server_name),
        daemon=True,
        name=f"delete-server-{server_id}",
    )
    thread.start()
    return thread


def delete_direct_server_rows(conn, server_id: int, *, batch_size: int = 1000) -> dict:
    deleted = {}
    for table in DIRECT_SERVER_TABLES:
        deleted[table] = delete_in_chunks(
            conn,
            f"""
            DELETE FROM {table}
            WHERE rowid IN (
                SELECT rowid FROM {table}
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
            batch_size=batch_size,
        )
    return deleted


def delete_server_relations(conn, server_id: int, *, batch_size: int = 1000) -> dict:
    deleted = {}
    deleted["media_user_libraries"] = delete_in_chunks(
        conn,
        """
        DELETE FROM media_user_libraries
        WHERE rowid IN (
            SELECT mul.rowid
            FROM media_user_libraries mul
            JOIN libraries l ON l.id = mul.library_id
            WHERE l.server_id = ?
            LIMIT ?
        )
        """,
        (server_id,),
        batch_size=batch_size,
    )
    for table in ("libraries", "media_users"):
        deleted[table] = delete_in_chunks(
            conn,
            f"""
            DELETE FROM {table}
            WHERE rowid IN (
                SELECT rowid FROM {table}
                WHERE server_id = ?
                LIMIT ?
            )
            """,
            (server_id,),
            batch_size=batch_size,
        )
    conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    conn.commit()
    return deleted


def delete_server_data(conn, server_id: int, *, batch_size: int = 1000) -> dict:
    deleted = delete_direct_server_rows(
        conn, server_id, batch_size=batch_size,
    )
    deleted.update(
        delete_server_relations(conn, server_id, batch_size=batch_size)
    )
    return deleted


def close_connection_safely(conn) -> bool:
    if conn is None:
        return False
    try:
        conn.close()
    except Exception:
        return False
    return True


def claim_server_deletion(lock, in_progress: set, server_id: int) -> str | None:
    delete_key = f"server:{server_id}"
    with lock:
        if delete_key in in_progress:
            return None
        in_progress.add(delete_key)
    return delete_key


def release_server_deletion(lock, in_progress: set, delete_key: str):
    with lock:
        in_progress.discard(delete_key)


def delete_in_chunks(conn, sql: str, params=(), *, batch_size: int = 1000) -> int:
    total = 0
    while True:
        cursor = conn.execute(sql, tuple(params) + (batch_size,))
        deleted = cursor.rowcount if cursor.rowcount is not None else 0
        conn.commit()
        if deleted <= 0:
            break
        total += deleted
        if deleted < batch_size:
            break
    return total
