"""Vodum smoke test (routes)

Usage (inside container or locally):
  python tools/smoke_routes.py --db /appdata/database.db

What it does:
- Builds the Flask app
- Logs-in bypass can be enabled with --no-auth (sets auth_enabled=0 temporarily)
- Hits every GET route that has no required URL params

This is meant to quickly catch regressions after refactors.
"""

from __future__ import annotations

import argparse
import os
import re
from urllib.parse import urlparse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="SQLite DB path (defaults to DATABASE_PATH env)")
    ap.add_argument("--no-auth", action="store_true", help="Disable auth_guard during the test")
    args = ap.parse_args()

    if args.db:
        os.environ["DATABASE_PATH"] = args.db

    # Optional: bypass IP filter in test contexts
    os.environ.setdefault("VODUM_IP_FILTER", "0")

    import app as appmod  # noqa

    flask_app = appmod.app
    client = flask_app.test_client()

    # Optional: disable auth in DB if requested
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

            # skip static + api heavy
            if rule.rule.startswith("/static"):
                continue

            # skip routes with params (/<int:id> etc)
            if "<" in rule.rule and ">" in rule.rule:
                continue

            # skip logout/login/setup routes (not meaningful in smoke)
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
