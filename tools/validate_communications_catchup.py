import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from core.communications_recovery import (  # noqa: E402
    recover_missed_scheduled_emails,
    retry_failed_scheduled_communications,
)


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)


db = DB()
db.conn.executescript(
    """
    CREATE TABLE comm_templates(id INTEGER PRIMARY KEY, enabled INTEGER);
    CREATE TABLE vodum_users(id INTEGER PRIMARY KEY, email TEXT, second_email TEXT);
    CREATE TABLE comm_scheduled(
      id INTEGER PRIMARY KEY, template_id INTEGER, vodum_user_id INTEGER,
      send_at TEXT, status TEXT, attempt_count INTEGER, max_attempts INTEGER,
      next_attempt_at TEXT, last_attempt_at TEXT, last_error TEXT,
      channels_sent TEXT, catchup_count INTEGER, last_catchup_at TEXT,
      updated_at TEXT
    );
    INSERT INTO comm_templates VALUES(1, 1);
    INSERT INTO vodum_users VALUES(10, 'user@example.com', '');
    INSERT INTO comm_scheduled VALUES(
      100, 1, 10, CURRENT_TIMESTAMP, 'error', 10, 10,
      NULL, CURRENT_TIMESTAMP, 'smtp down',
      NULL, 0, NULL, CURRENT_TIMESTAMP
    );
    """
)

settings = {
    "mailing_enabled": 1,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "vodum@example.com",
    "smtp_pass": "configured-secret",
    "mail_from": "vodum@example.com",
}
result = recover_missed_scheduled_emails(db, settings)
row = db.conn.execute("SELECT * FROM comm_scheduled WHERE id=100").fetchone()
assert result["requeued"] == 1
assert row["status"] == "pending"
assert row["attempt_count"] == 0
assert row["catchup_count"] == 1

second = recover_missed_scheduled_emails(db, settings)
assert second["requeued"] == 0

db.conn.execute(
    """
    UPDATE comm_scheduled
    SET status='error', attempt_count=10, next_attempt_at=CURRENT_TIMESTAMP,
        last_attempt_at=CURRENT_TIMESTAMP, last_error='still failed'
    WHERE id=100
    """
)
assert retry_failed_scheduled_communications(db) == 1
manual = db.conn.execute("SELECT * FROM comm_scheduled WHERE id=100").fetchone()
assert manual["status"] == "pending"
assert manual["attempt_count"] == 0
assert manual["next_attempt_at"] is None
assert manual["last_attempt_at"] is None

source = (ROOT / "app" / "tasks" / "send_expiration_emails.py").read_text(encoding="utf-8")
assert "recover_missed_scheduled_emails(db, settings)" in source
route = (ROOT / "app" / "routes" / "communications.py").read_text(encoding="utf-8")
assert "retry_failed_scheduled_communications(db)" in route
bootstrap = (ROOT / "app" / "db_bootstrap.py").read_text(encoding="utf-8")
schema = (ROOT / "tables.sql").read_text(encoding="utf-8")
assert "idx_comm_scheduled_catchup" in bootstrap
assert "catchup_count INTEGER NOT NULL DEFAULT 0" in schema
assert "idx_comm_scheduled_catchup" in schema

print("OK - final scheduled email failures receive a bounded automatic catch-up.")
