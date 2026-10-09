"""Read-only connection checks for Sonarr/Radarr; credentials stay server-side."""
from core.http_security import server_http_session

ARR_TYPES = ("sonarr", "radarr")


def arr_get_status(server, base_url, token):
    if server.get("type") not in ARR_TYPES or not token:
        return ("down", None, None, "Missing API key")
    http = server_http_session(server)
    try:
        response = http.get(base_url.rstrip("/") + "/api/v3/system/status",
                            headers={"X-Api-Key": token, "Accept": "application/json"},
                            timeout=5, allow_redirects=False)
        if response.status_code != 200:
            return ("down", None, None, f"API returned HTTP {response.status_code}")
        info = response.json()
        expected = server["type"]
        if (not isinstance(info, dict) or not info.get("version")
                or str(info.get("appName") or "").lower() != expected):
            return ("down", None, None, "Invalid application status")
        name = server.get("name")
        if not name or name.endswith(" - pending"):
            name = info.get("instanceName") or expected.capitalize()
        return ("up", name, None, str(info["version"]))
    except Exception:
        return ("down", None, None, "API connection failed")
    finally:
        http.close()


def load_arr_servers(db):
    return [dict(row) for row in (db.query("""SELECT id, name, LOWER(TRIM(type)) AS type,
        COALESCE(url, local_url, public_url) AS url, status, last_checked, server_version
        FROM servers WHERE LOWER(TRIM(type)) IN ('sonarr','radarr') ORDER BY type, name
        """) or [])]
