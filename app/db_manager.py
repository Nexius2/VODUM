import sqlite3
import threading
import logging
from typing import Any, Iterable, Optional
import os


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

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        self._configure_connection()

        self._initialized = True
        logging.getLogger(__name__).info(
            "DBManager initialized for %s",
            self.db_path,
        )

    def _configure_connection(self) -> None:
        cur = self.conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.execute("PRAGMA journal_mode = WAL;")
            cur.execute("PRAGMA synchronous = NORMAL;")
            cur.execute("PRAGMA busy_timeout = 5000;")
        finally:
            cur.close()

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
    ) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall()
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