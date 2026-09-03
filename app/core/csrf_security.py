from __future__ import annotations

from flask import abort, request, session

from web.security import csrf_tokens_match


STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def csrf_request_guard() -> None:
    """Reject every state-changing request without a session-bound CSRF token."""
    if request.method not in STATE_CHANGING_METHODS:
        return

    sent_token = (
        request.form.get("_csrf_token")
        or request.headers.get("X-CSRF-Token")
        or ""
    ).strip()
    session_token = (session.get("_csrf_token") or "").strip()

    if not csrf_tokens_match(sent_token, session_token):
        abort(403)
