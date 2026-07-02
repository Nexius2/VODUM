import sqlite3
import threading
import logging
from typing import Any, Iterable, Optional
import os

from secret_store import decrypt_server_record


def open_sqlite_connection(
    db_path: str,
    *,
    uri: bool = False,
    check_same_thread: bool = True,
    timeout: float = 5.0,
    read_only: bool = False,
    row_factory=sqlite3.Row,
    busy_timeout_ms: int = 5000,
) -> sqlite3.Connection:
    """
    Open a consistently configured raw SQLite connection.

    Use this for bootstrap, maintenance and read-only validation paths where a
    shared DBManager instance would be too long-lived or unsafe.
    """
    connect_uri = uri
    target = db_path

    if read_only:
        target = f"file:{os.path.abspath(db_path)}?mode=ro"
        connect_uri = True

    conn = sqlite3.connect(
        target,
        uri=connect_uri,
        check_same_thread=check_same_thread,
        timeout=timeout,
    )
    conn.row_factory = row_factory

    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys = ON;")
        if not read_only:
            cur.execute("PRAGMA journal_mode = WAL;")
            cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)};")
    finally:
        cur.close()

    return conn


class DBManager:
    """
    DBManager = 1 instance par chemin de base.

    - même chemin DB => même instance
    - autre chemin DB => autre instance
    - connexion SQLite partagée par chemin
    - accès thread-safe
    """

    _instances: dict[str, "DBManager"] = {}
    _instance_lock = threading.Lock()

    @staticmethod
    def _resolve_db_path(db_path: str | None = None) -> str:
        raw_path = db_path or os.environ.get("DATABASE_PATH", "/appdata/database.db")
        return os.path.abspath(raw_path)

    def __new__(cls, db_path: str | None = None):
        resolved_path = cls._resolve_db_path(db_path)

        with cls._instance_lock:
            instance = cls._instances.get(resolved_path)
            if instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                instance._instance_key = resolved_path
                cls._instances[resolved_path] = instance

        return instance

    def __init__(self, db_path: str | None = None):
        resolved_path = self._resolve_db_path(db_path)

        if getattr(self, "_initialized", False):
            if getattr(self, "db_path", None) != resolved_path:
                raise ValueError(
                    f"DBManager already initialized for '{self.db_path}', "
                    f"cannot reuse same instance for '{resolved_path}'"
                )
            return

        self.db_path = resolved_path
        self._lock = threading.Lock()

        self.conn = open_sqlite_connection(
            self.db_path,
            check_same_thread=False,
        )

        self._initialized = True
        logging.getLogger(__name__).info(
            "DBManager initialized for %s",
            self.db_path,
        )


    def execute(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        commit: bool = True
    ) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                if commit:
                    self.conn.commit()
                return cur
            except Exception:
                self.conn.rollback()
                cur.close()
                raise

    def executemany(
        self,
        sql: str,
        seq_of_params: Iterable[Iterable[Any]],
        *,
        commit: bool = True
    ) -> None:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.executemany(sql, seq_of_params)
                if commit:
                    self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                cur.close()

    def query(
        self,
        sql: str,
        params: Iterable[Any] = ()
    ) -> list[sqlite3.Row | dict]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                rows = cur.fetchall()
                if "servers" in sql.lower():
                    return [
                        decrypt_server_record(row)
                        if "token" in row.keys() or "settings_json" in row.keys()
                        else row
                        for row in rows
                    ]
                return rows
            finally:
                cur.close()

    def query_one(
        self,
        sql: str,
        params: Iterable[Any] = ()
    ) -> Optional[sqlite3.Row]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        """
        Ferme la connexion associée à CETTE base uniquement
        puis enlève l'instance du cache.
        """
        with self._lock:
            try:
                if getattr(self, "conn", None) is not None:
                    self.conn.close()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "DBManager close warning for %s: %s",
                    getattr(self, "db_path", "<unknown>"),
                    e,
                    exc_info=True,
                )
            finally:
                self.conn = None
                self._initialized = False

        with type(self)._instance_lock:
            key = getattr(self, "_instance_key", None)
            if key and type(self)._instances.get(key) is self:
                del type(self)._instances[key]

        logging.getLogger(__name__).info(
            "DBManager connection closed + cache entry removed for %s",
            getattr(self, "db_path", "<unknown>"),
        )


