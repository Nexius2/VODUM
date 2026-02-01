import sqlite3
import threading
import logging
from typing import Any, Iterable, Optional
import os



class DBManager:
    """
    DBManager est l'autorité UNIQUE pour l'accès SQLite.
    - 1 seule connexion
    - 1 seul writer
    - WAL configuré une seule fois
    - Accès thread-safe
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, db_path: str | None = None):
        # Singleton strict
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str | None = None):
        if self._initialized:
            return

        if not db_path:
            db_path = os.environ.get("DATABASE_PATH", "/appdata/database.db")

        self.db_path = db_path
        self._lock = threading.Lock()

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row

        # PRAGMAs – exécutés UNE SEULE FOIS
        self._configure_connection()

        self._initialized = True
        logging.getLogger(__name__).info("DBManager initialized (single connection)")

    def _configure_connection(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("PRAGMA busy_timeout = 5000;")
        cur.close()

    # ----------------------------
    # API publique
    # ----------------------------

    def execute(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        commit: bool = True
    ) -> sqlite3.Cursor:
        """
        Exécute une requête WRITE (INSERT/UPDATE/DELETE).
        Accès sérialisé.
        """
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                if commit:
                    self.conn.commit()
                return cur
            except Exception:
                self.conn.rollback()
                raise

    def executemany(
        self,
        sql: str,
        seq_of_params: Iterable[Iterable[Any]],
        *,
        commit: bool = True
    ) -> None:
        """
        Exécute plusieurs requêtes WRITE en une transaction.
        """
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
        """
        Exécute une requête READ.
        Les lectures passent aussi par la même connexion
        (safe avec WAL).
        """
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            return rows

    def query_one(
        self,
        sql: str,
        params: Iterable[Any] = ()
    ) -> Optional[sqlite3.Row]:
        """
        Exécute une requête READ et retourne une seule ligne.
        """
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        """
        Fermeture explicite (rarement nécessaire).
        """
        with self._lock:
            self.conn.close()
            logging.getLogger(__name__).info("DBManager connection closed")
