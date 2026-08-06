SUPPORTED_SERVER_TYPES = ("plex", "jellyfin")


def normalize_server_type(form) -> str:
    return (
        form.get("server_type")
        or form.get("type")
        or ""
    ).strip().lower()


def is_supported_server_type(server_type: str) -> bool:
    return server_type in SUPPORTED_SERVER_TYPES


def normalize_server_base_url(value) -> str:
    url = (value or "").strip().rstrip("/")
    if url.endswith("/web/index.html"):
        url = url[:-15]
    if url.endswith("/web"):
        url = url[:-4]
    return url.rstrip("/")


def server_base_url_error(url: str) -> str | None:
    if not url.startswith(("http://", "https://")):
        return "protocol"
    if "/web/" in url or url.endswith("/web"):
        return "plex_web"
    return None


def build_new_server_settings(form) -> dict:
    tautulli_url = form.get("tautulli_url") or None
    tautulli_api_key = form.get("tautulli_api_key") or None
    if not tautulli_url and not tautulli_api_key:
        return {}
    return {"tautulli": {"url": tautulli_url, "api_key": tautulli_api_key}}


def read_new_server_form(form) -> dict:
    return {
        "server_type": normalize_server_type(form),
        "url": normalize_server_base_url(form.get("url")),
        "local_url": form.get("local_url") or None,
        "public_url": form.get("public_url") or None,
        "token": form.get("token") or None,
        "settings": build_new_server_settings(form),
    }


def read_updated_server_form(form) -> dict:
    return {
        "name": form.get("name", "").strip(),
        "server_type": normalize_server_type(form),
        "url": form.get("url") or None,
        "local_url": form.get("local_url") or None,
        "public_url": form.get("public_url") or None,
        "token": form.get("token") or None,
        "status": form.get("status") or None,
        "tautulli_url": form.get("tautulli_url") or None,
        "tautulli_api_key": form.get("tautulli_api_key") or None,
        "verify_tls": form.get("verify_tls") == "1",
    }
