"""Sonarr/Radarr quality profiles and root folders, fetched by check_servers.

The server page reads the stored lists instead of calling Sonarr/Radarr while
it renders. Adding media still asks the ARR server at submission time.
"""

import json

from core.error_reporting import log_handled_failure

SCHEMA = """CREATE TABLE IF NOT EXISTS arr_request_choices (
 server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
 profiles_json TEXT,
 roots_json TEXT,
 fetched_at TEXT,
 attempted_at TEXT,
 last_error TEXT
);
"""


def refresh_arr_request_choices(db, server):
    """Store the current choices of an online Sonarr/Radarr server; keep the last good ones on failure."""
    from core.portal_media_requests import MediaRequestError, arr_defaults
    db.execute("INSERT OR IGNORE INTO arr_request_choices(server_id) VALUES(?)", (server["id"],))
    try:
        choices = arr_defaults(dict(server))
    except MediaRequestError as exc:
        db.execute("UPDATE arr_request_choices SET attempted_at=CURRENT_TIMESTAMP,last_error=? WHERE server_id=?",
                   (str(exc)[:200], server["id"]))
        return False
    except Exception:
        log_handled_failure("arr.request_choices", server_id=server.get("id"))
        db.execute("UPDATE arr_request_choices SET attempted_at=CURRENT_TIMESTAMP,last_error='unexpected' WHERE server_id=?",
                   (server["id"],))
        return False
    db.execute("""UPDATE arr_request_choices SET profiles_json=?,roots_json=?,fetched_at=CURRENT_TIMESTAMP,
                  attempted_at=CURRENT_TIMESTAMP,last_error=NULL WHERE server_id=?""",
               (json.dumps(choices["profiles"]), json.dumps(choices["roots"]), server["id"]))
    return True


def store_arr_request_choices(db, server_id, choices):
    """Keep the lists that a successful save has just validated with the server."""
    db.execute("""INSERT INTO arr_request_choices(server_id,profiles_json,roots_json,fetched_at,attempted_at,last_error)
                  VALUES(?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL)
                  ON CONFLICT(server_id) DO UPDATE SET profiles_json=excluded.profiles_json,roots_json=excluded.roots_json,
                  fetched_at=excluded.fetched_at,attempted_at=excluded.attempted_at,last_error=NULL""",
               (server_id, json.dumps(choices["profiles"]), json.dumps(choices["roots"])))


def request_choices_refresh(db):
    """Queue check_servers once when a page finds no stored choices yet."""
    task = db.query_one("SELECT id,enabled,status,queued_count FROM tasks WHERE name='check_servers'")
    if not task or not task["enabled"] or task["status"] in ("running", "queued") or task["queued_count"]:
        return False
    from tasks_engine import enqueue_task
    return bool(enqueue_task(int(task["id"])))


def load_arr_request_choices(db, server_id):
    """Return (choices or None, metadata). Never contacts the ARR server."""
    row = db.query_one("SELECT profiles_json,roots_json,fetched_at,last_error FROM arr_request_choices WHERE server_id=?",
                       (server_id,))
    if not row or row["profiles_json"] is None or row["roots_json"] is None:
        return None, {"ready": False, "failed": bool(row and row["last_error"]), "fetched_at": None}
    choices = {"profiles": json.loads(row["profiles_json"]), "roots": json.loads(row["roots_json"])}
    return choices, {"ready": True, "failed": bool(row["last_error"]), "fetched_at": row["fetched_at"]}
