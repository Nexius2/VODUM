"""Read-only connection checks for Seerr (Overseerr/Jellyseerr); the API key stays server-side."""
from core.error_reporting import log_handled_failure
from core.http_security import server_http_session

SEERR_TYPE = "seerr"
REQUEST_SERVER_TYPES = ("sonarr", "radarr", SEERR_TYPE)


def seerr_headers(token):
    return {"X-Api-Key": token or "", "Accept": "application/json"}


def seerr_identity(data):
    """Return the display name Seerr reports for the API key owner, or None."""
    if not isinstance(data, dict) or type(data.get("id")) is not int:
        return None
    return (data.get("displayName") or data.get("username") or data.get("email")
            or "Seerr")


def seerr_get_status(server, base_url, token):
    if server.get("type") != SEERR_TYPE or not token:
        return ("down", None, None, "Missing API key")
    http = server_http_session(server)
    base = base_url.rstrip("/")
    try:
        response = http.get(base + "/api/v1/auth/me", headers=seerr_headers(token),
                            timeout=5, allow_redirects=False)
        if response.status_code != 200:
            return ("down", None, None, f"API returned HTTP {response.status_code}")
        if seerr_identity(response.json()) is None:
            return ("down", None, None, "Invalid application status")
        version = None
        status = http.get(base + "/api/v1/status", headers=seerr_headers(token),
                          timeout=5, allow_redirects=False)
        if status.status_code == 200:
            info = status.json()
            if isinstance(info, dict) and info.get("version"):
                version = str(info["version"])
        name = server.get("name")
        if not name or name.endswith(" - pending"):
            name = "Seerr"
        return ("up", name, None, version or str(server.get("server_version") or ""))
    except Exception:
        log_handled_failure("seerr.test_connection")
        return ("down", None, None, "API connection failed")
    finally:
        http.close()
