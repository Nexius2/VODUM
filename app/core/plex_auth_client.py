from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from urllib.parse import urlencode, urlsplit

import requests

from core.http_security import ConfiguredHostSession, url_origin


PLEX_API_ORIGIN = "https://plex.tv"
PLEX_AUTH_URL = "https://app.plex.tv/auth#?"
PLEX_HTTP_ORIGINS = {
    url_origin("https://plex.tv"),
    url_origin("https://clients.plex.tv"),
}


class PlexAuthError(RuntimeError):
    """A safe-to-report Plex authentication failure."""


class PlexPinExpired(PlexAuthError):
    pass


class PlexServiceUnavailable(PlexAuthError):
    pass


class PlexAuthorizationIncomplete(PlexAuthError):
    pass


@dataclass(frozen=True)
class PlexPin:
    id: int
    code: str
    expires_in: int | None = None


@dataclass(frozen=True)
class PlexIdentity:
    subject: str
    username: str
    email: str
    display_name: str


def _json_object(response, operation: str) -> dict:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status = getattr(response, "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        if not status or int(status) >= 500:
            raise PlexServiceUnavailable(f"Plex {operation} unavailable{suffix}") from exc
        raise PlexAuthError(f"Plex {operation} failed{suffix}") from exc
    except ValueError as exc:
        raise PlexAuthError(f"Plex {operation} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PlexAuthError(f"Plex {operation} returned an invalid response")
    return payload


def _validate_forward_url(forward_url: str) -> str:
    value = str(forward_url or "").strip()
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("forward_url must be an absolute HTTP(S) URL without credentials or fragment")
    return value


class PlexAuthClient:
    """Plex account authentication only; never use for media server sync."""

    def __init__(
        self,
        client_identifier: str,
        *,
        product: str = "VODUM",
        version: str = "unknown",
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ):
        identifier = str(client_identifier or "").strip()
        if not identifier:
            raise ValueError("client_identifier is required")
        self.client_identifier = identifier
        self.product = str(product or "VODUM")
        self.timeout = max(1.0, min(float(timeout), 30.0))
        self.session = session or ConfiguredHostSession(
            PLEX_HTTP_ORIGINS,
            default_timeout=self.timeout,
        )
        self.headers = {
            "Accept": "application/json",
            "X-Plex-Client-Identifier": identifier,
            "X-Plex-Product": self.product,
            "X-Plex-Version": str(version or "unknown"),
        }

    def create_pin(self) -> PlexPin:
        response = self.session.post(
            f"{PLEX_API_ORIGIN}/api/v2/pins",
            params={"strong": "true"},
            headers=self.headers,
            timeout=self.timeout,
        )
        payload = _json_object(response, "PIN creation")
        try:
            pin_id = int(payload["id"])
            code = str(payload["code"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlexAuthError("Plex PIN creation returned an invalid response") from exc
        expires_in = payload.get("expiresIn")
        return PlexPin(
            id=pin_id,
            code=code,
            expires_in=int(expires_in) if expires_in is not None else None,
        )

    def build_authorization_url(self, pin: PlexPin, forward_url: str) -> str:
        query = urlencode(
            {
                "clientID": self.client_identifier,
                "code": pin.code,
                "context[device][product]": self.product,
                "forwardUrl": _validate_forward_url(forward_url),
            }
        )
        return PLEX_AUTH_URL + query

    def read_pin_token(self, pin_id: int) -> str | None:
        response = self.session.get(
            f"{PLEX_API_ORIGIN}/api/v2/pins/{int(pin_id)}",
            headers=self.headers,
            timeout=self.timeout,
        )
        if response.status_code in {404, 410}:
            raise PlexPinExpired("Plex PIN expired or no longer exists")
        payload = _json_object(response, "PIN check")
        token = payload.get("authToken")
        return str(token) if token else None

    def wait_for_token(
        self,
        pin_id: int,
        *,
        max_wait: float = 15.0,
        interval: float = 1.0,
    ) -> str | None:
        deadline = monotonic() + max(0.0, min(float(max_wait), 30.0))
        poll_interval = max(0.25, min(float(interval), 2.0))
        while True:
            token = self.read_pin_token(pin_id)
            if token:
                return token
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            sleep(min(poll_interval, remaining))

    def fetch_identity(self, token: str) -> PlexIdentity:
        secret = str(token or "").strip()
        if not secret:
            raise ValueError("token is required")
        headers = dict(self.headers)
        headers["X-Plex-Token"] = secret
        response = self.session.get(
            f"{PLEX_API_ORIGIN}/api/v2/user",
            headers=headers,
            timeout=self.timeout,
        )
        payload = _json_object(response, "identity verification")
        subject = payload.get("id") or payload.get("uuid")
        if subject is None:
            raise PlexAuthError("Plex identity verification returned no stable identifier")
        username = str(payload.get("username") or "")
        email = str(payload.get("email") or "")
        display_name = str(payload.get("friendlyName") or username or email)
        return PlexIdentity(str(subject), username, email, display_name)
