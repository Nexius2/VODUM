"""Boot Vodum on a fresh temporary database and smoke every registered route."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"


def _route_path(rule) -> str:
    def replace(match):
        raw = match.group(1)
        converter, _, name = raw.partition(":")
        if not name:
            name = converter
            converter = "string"
        if converter in {"int", "float"} or name.endswith("_id"):
            return "999999"
        if name == "section":
            return "general"
        if name == "filename":
            return "missing-file"
        return "missing"

    return re.sub(r"<([^>]+)>", replace, rule.rule)


def _assert_no_server_errors(client, app) -> tuple[int, list[tuple[str, int]]]:
    checked = 0
    failures = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        if "GET" not in rule.methods or rule.endpoint == "static":
            continue
        path = _route_path(rule)
        response = client.get(path, follow_redirects=False)
        checked += 1
        if response.status_code >= 500:
            failures.append((path, response.status_code))
    return checked, failures


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vodum-runtime-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db_path = root / "database.db"
        log_dir = root / "logs"
        backup_dir = root / "backups"
        log_dir.mkdir()
        backup_dir.mkdir()

        os.environ.update({
            "DATABASE_PATH": str(db_path),
            "VODUM_LOG_DIR": str(log_dir),
            "VODUM_BACKUP_DIR": str(backup_dir),
            "VODUM_SECRET_KEY_FILE": str(root / "vodum.secret_key"),
            "VODUM_SECRET_KEY": "runtime-smoke-secret",
            "VODUM_IP_FILTER": "0",
            "PYTHONUTF8": "1",
        })

        connection = sqlite3.connect(db_path)
        connection.executescript((ROOT / "tables.sql").read_text(encoding="utf-8"))
        connection.commit()
        connection.close()

        for attempt in range(2):
            result = subprocess.run(
                [sys.executable, str(APP_DIR / "db_bootstrap.py")],
                cwd=ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode:
                raise AssertionError(
                    f"db_bootstrap attempt {attempt + 1} failed:\n{result.stdout}\n{result.stderr}"
                )

        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            UPDATE settings
            SET admin_email = ?, admin_password_hash = ?, auth_enabled = 1,
                wizard_active = 0, maintenance_mode = 0
            WHERE id = 1
            """,
            ("admin@example.test", generate_password_hash("Audit-password-1")),
        )
        connection.execute(
            """
            INSERT INTO servers(name, server_identifier, type, url, status)
            VALUES ('Audit Jellyfin', 'audit-jellyfin', 'jellyfin', 'http://127.0.0.1:9', 'offline')
            """
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.commit()
        connection.close()

        sys.path.insert(0, str(APP_DIR))
        from app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        templates = app.jinja_env.list_templates()
        for template_name in templates:
            app.jinja_env.get_template(template_name)

        anonymous = app.test_client()
        public_paths = {"/login", "/setup-admin"}
        protected_checked = 0
        for rule in app.url_map.iter_rules():
            if "GET" not in rule.methods or rule.endpoint == "static":
                continue
            path = _route_path(rule)
            if path in public_paths or path.startswith("/static"):
                continue
            response = anonymous.get(path, follow_redirects=False)
            protected_checked += 1
            assert response.status_code == 302 and "/login" in response.headers.get("Location", ""), (
                f"Unauthenticated GET was exposed: {rule.rule} -> {response.status_code}"
            )

        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302 and "/login" in response.headers["Location"]

        response = client.get("/login")
        assert response.status_code == 200
        with client.session_transaction() as session:
            csrf_token = session["_csrf_token"]

        response = client.post(
            "/login/submit",
            data={
                "email": "admin@example.test",
                "password": "Audit-password-1",
                "_csrf_token": csrf_token,
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        cookie = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
        with client.session_transaction() as session:
            assert session.get("vodum_logged_in") is True

        checked, failures = _assert_no_server_errors(client, app)
        assert not failures, f"GET routes returned 5xx: {failures}"

        post_checked = 0
        for rule in app.url_map.iter_rules():
            if "POST" not in rule.methods:
                continue
            response = anonymous.post(_route_path(rule), follow_redirects=False)
            post_checked += 1
            assert response.status_code == 403, (
                f"POST without CSRF was not rejected: {rule.rule} -> {response.status_code}"
            )

        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE settings SET maintenance_mode=1 WHERE id=1")
        connection.commit()
        connection.close()
        assert client.get("/").status_code == 503
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE settings SET maintenance_mode=0 WHERE id=1")
        connection.commit()
        connection.close()

        locked_client = app.test_client()
        locked_client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.10"})
        with locked_client.session_transaction() as session:
            locked_csrf = session["_csrf_token"]
        for _ in range(5):
            response = locked_client.post(
                "/login/submit",
                data={
                    "email": "admin@example.test",
                    "password": "wrong-password",
                    "_csrf_token": locked_csrf,
                },
                environ_base={"REMOTE_ADDR": "203.0.113.10"},
            )
            assert response.status_code == 302
        connection = sqlite3.connect(db_path)
        locked_until = connection.execute(
            "SELECT locked_until FROM auth_login_attempts WHERE scope='ip' AND scope_value=?",
            ("203.0.113.10",),
        ).fetchone()[0]
        connection.close()
        assert locked_until

        redirect_client = app.test_client()
        redirect_client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.11"})
        with redirect_client.session_transaction() as session:
            redirect_csrf = session["_csrf_token"]
        response = redirect_client.post(
            "/login/submit?next=https://evil.example/steal",
            data={
                "email": "admin@example.test",
                "password": "Audit-password-1",
                "_csrf_token": redirect_csrf,
            },
            environ_base={"REMOTE_ADDR": "203.0.113.11"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "evil.example" not in response.headers.get("Location", "")

        print(
            "OK - fresh DB bootstrap, integrity/FK, authentication, "
            f"{len(templates)} templates, {protected_checked} protected GET routes, "
            f"{checked} authenticated GET routes, {post_checked} CSRF-protected POST routes, "
            "maintenance mode, brute-force locking and safe redirects validated."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
