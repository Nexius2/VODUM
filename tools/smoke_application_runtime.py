"""Start the real Flask application against a temporary bootstrapped database."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vodum-runtime-smoke-") as temp_dir:
        data_dir = Path(temp_dir)
        database = data_dir / "database.db"
        connection = sqlite3.connect(database)
        try:
            connection.executescript((ROOT / "tables.sql").read_text(encoding="utf-8"))
            connection.commit()
        finally:
            connection.close()

        env = os.environ.copy()
        env.update(
            DATABASE_PATH=str(database),
            PYTHONPATH=str(APP_DIR),
            VODUM_LOG_DIR=str(data_dir / "logs"),
            VODUM_ENCRYPTION_KEY="runtime-smoke-fixed-key-not-for-production",
            VODUM_SECRET_KEY="runtime-smoke-secret-key",
        )
        subprocess.run(
            [sys.executable, str(APP_DIR / "db_bootstrap.py")],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        smoke_code = """
from app import create_app

application = create_app()
client = application.test_client()
health = client.get('/health', base_url='https://vodum.example.test')
assert health.status_code == 200, health.status_code
assert health.get_json() == {'status': 'ok'}, health.get_data(as_text=True)
assert health.headers.get('Strict-Transport-Security')
assert health.headers.get('X-Content-Type-Options') == 'nosniff'
assert client.post('/health').status_code == 403
route_count = len(list(application.url_map.iter_rules()))
assert route_count >= 150, route_count
print(f'OK - Flask runtime started with {route_count} routes.')
"""
        subprocess.run(
            [sys.executable, "-c", smoke_code],
            cwd=ROOT,
            env=env,
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
