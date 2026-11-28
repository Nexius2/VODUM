from __future__ import annotations

from core.plex_access_identity import row_get
from logging_utils import get_logger


logger = get_logger("plex_access_runtime")


def redact_headers(headers: dict):
    if not headers:
        return headers
    redacted = dict(headers)
    for key in list(redacted):
        if key.lower() in {"x-plex-token", "authorization"}:
            redacted[key] = "***REDACTED***"
    return redacted


def install_plex_http_logger(session, label: str):
    if not session or not hasattr(session, "request"):
        logger.warning("[%s] invalid session, unable to install HTTP logger", label)
        return
    if getattr(session, "_vodum_http_logger_installed", False):
        return
    original_request = session.request

    def wrapped_request(method, url, **kwargs):
        logger.warning(
            "[%s] >>> REQUEST %s %s\n[%s] headers=%s\n[%s] params=%s\n"
            "[%s] data=%s\n[%s] json=%s",
            label,
            method,
            url,
            label,
            redact_headers(kwargs.get("headers") or {}),
            label,
            kwargs.get("params"),
            label,
            kwargs.get("data"),
            label,
            kwargs.get("json"),
        )
        response = original_request(method, url, **kwargs)
        try:
            text = response.text if hasattr(response, "text") else None
            logger.warning(
                "[%s] <<< RESPONSE status=%s len=%s text_preview=%s",
                label,
                getattr(response, "status_code", None),
                len(text) if text else 0,
                text[:800] if text else None,
            )
        except Exception:
            logger.exception("[%s] failed to log HTTP response", label)
        return response

    session.request = wrapped_request
    session._vodum_http_logger_installed = True
    logger.warning("[%s] HTTP logger installed", label)


def log_updatefriend_payload(
    action,
    server_row,
    user_row,
    plex_obj,
    plex_user_obj,
    sections,
    allowSync,
    allowCameraUpload,
    allowChannels,
    filterMovies,
    filterTelevision,
    filterMusic,
):
    logger.warning(
        "### PLEX updateFriend() PAYLOAD ###\n"
        "action=%s\n"
        "db_server_id=%s\n"
        "db_server_name=%s\n"
        "db_server_url=%s\n"
        "db_server_local_url=%s\n"
        "db_server_public_url=%s\n"
        "plex_friendlyName=%s\n"
        "db_username=%s\n"
        "plex_username=%s\n"
        "sections=%s\n"
        "allowSync=%s (%s)\n"
        "allowCameraUpload=%s (%s)\n"
        "allowChannels=%s (%s)\n"
        "filterMovies=%s\n"
        "filterTelevision=%s\n"
        "filterMusic=%s\n"
        "################################",
        action,
        row_get(server_row, "id"),
        row_get(server_row, "name"),
        row_get(server_row, "url"),
        row_get(server_row, "local_url"),
        row_get(server_row, "public_url"),
        getattr(plex_obj, "friendlyName", None),
        row_get(user_row, "username"),
        getattr(plex_user_obj, "username", None),
        sections,
        allowSync,
        type(allowSync).__name__,
        allowCameraUpload,
        type(allowCameraUpload).__name__,
        allowChannels,
        type(allowChannels).__name__,
        filterMovies,
        filterTelevision,
        filterMusic,
    )
