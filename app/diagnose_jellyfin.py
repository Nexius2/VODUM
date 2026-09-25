"""Read-only Jellyfin timing probe. Run in VODUM: python -m diagnose_jellyfin 7."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from core.http_security import server_http_session
from core.jellyfin_auth import jellyfin_headers
from secret_store import decrypt_secret


def probe(session, base, path, headers):
    started = time.monotonic()
    try:
        with session.get(base + path, headers=headers, timeout=(5, 30), allow_redirects=False) as response:
            result = {"status": response.status_code, "seconds": round(time.monotonic() - started, 2)}
            if response.status_code == 200:
                try:
                    payload = response.json()
                    if isinstance(payload, list):
                        result["records"] = len(payload)
                    elif isinstance(payload, dict) and "TotalRecordCount" in payload:
                        result["records"] = payload["TotalRecordCount"]
                except ValueError:
                    result["error"] = "InvalidJSON"
            return result
    except Exception as exc:
        # Exception text and response bodies may contain addresses or secrets.
        return {"error": type(exc).__name__, "seconds": round(time.monotonic() - started, 2)}


def auth_variants(token, compare=False):
    current = jellyfin_headers(token)
    if not compare:
        return [("current", current)]
    # Reuse validation/decryption, but reproduce the previous header exactly.
    legacy = {"Accept": "application/json", "X-Emby-Token": (decrypt_secret(token) or "").strip()}
    modern = {"Accept": "application/json", "Authorization": 'MediaBrowser Client="VODUM", Device="Server", DeviceId="vodum", Version="1", Token="' + legacy["X-Emby-Token"] + '"'}
    return [("legacy", legacy), ("modern", modern)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server_id", type=int)
    parser.add_argument("--compare-auth", action="store_true", help="Compare previous and current authentication on identical requests")
    args = parser.parse_args()
    path = Path(os.environ.get("DATABASE_PATH", "/appdata/database.db")).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM servers WHERE id=? AND type='jellyfin'", (args.server_id,)).fetchone()
        if row is None:
            raise ValueError("Jellyfin server ID not found")
        server = dict(row)
        library = conn.execute("SELECT section_id FROM libraries WHERE server_id=? ORDER BY id LIMIT 1", (args.server_id,)).fetchone()
    variants = auth_variants(server.get("token"), args.compare_auth)
    endpoints = [("health", "/System/Info/Public"), ("users", "/Users"),
                 ("sessions", "/Sessions?EnableRemoteIP=true"), ("libraries", "/Library/VirtualFolders")]
    if library and library[0]:
        endpoints.append(("library_count", "/Items?ParentId=" + quote(str(library[0]), safe="") + "&Recursive=true&StartIndex=0&Limit=1&EnableTotalRecordCount=true"))
    if args.compare_auth:
        endpoints = [(label, endpoint) for label, endpoint in endpoints if label in ("users", "library_count")]
    seen = set()
    for field in ("url", "local_url", "public_url"):
        base = str(server.get(field) or "").strip().rstrip("/")
        if not base or base in seen:
            continue
        seen.add(base)
        for label, endpoint in endpoints:
            for auth, headers in variants:
                # Separate sessions prevent connection state from leaking across methods.
                with server_http_session(server) as attempt:
                    print(json.dumps({"server_id": args.server_id, "address": field, "endpoint": label,
                                      "auth": auth, **probe(attempt, base, endpoint, headers)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "stage": "configuration"}))
        raise SystemExit(1)
