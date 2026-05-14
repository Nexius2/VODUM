"""Vodum smoke test (routes)

Usage:
  python tools/smoke_routes.py --db /appdata/database.db --no-auth
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="SQLite DB path (defaults to DATABASE_PATH env)")
    ap.add_argument("--no-auth", action="store_true", help="Disable auth_guard during the test")
    args = ap.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    if args.db:
        os.environ["DATABASE_PATH"] = args.db

    os.environ.setdefault("VODUM_IP_FILTER", "0")

    import app as appmod

    if hasattr(appmod, "app"):
        flask_app = appmod.app
    elif hasattr(appmod, "create_app"):
        flask_app = appmod.create_app()
    else:
        raise RuntimeError("Unable to find Flask app or create_app() in app module")

    client = flask_app.test_client()

    if args.no_auth:
        try:
            import sqlite3

            con = sqlite3.connect(flask_app.config["DATABASE"])
            con.execute("UPDATE settings SET auth_enabled=0 WHERE id=1")
            con.commit()
            con.close()
        except Exception:
            pass

    bad = []

    with flask_app.app_context():
        for rule in flask_app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue

            if rule.rule.startswith("/static"):
                continue

            if "<" in rule.rule and ">" in rule.rule:
                continue

            if rule.rule in ("/logout",):
                continue

            try:
                resp = client.get(rule.rule, follow_redirects=False)
            except Exception as e:
                bad.append((rule.rule, f"EXC: {e}"))
                continue

            if resp.status_code >= 500:
                bad.append((rule.rule, f"HTTP {resp.status_code}"))

    if bad:
        print("FAILED ROUTES:")
        for path, why in bad:
            print(f" - {path}: {why}")
        return 2

    print("OK: no 5xx on simple GET routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())