from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from typing import MutableMapping


PLEX_FLOW_SESSION_KEY = "vodum_plex_auth_flow"
PLEX_FLOW_MAX_AGE_SECONDS = 10 * 60
_ALLOWED_PURPOSES = {"login", "link", "replace", "reauthenticate", "wizard-link", "discover"}


class PlexFlowRejected(ValueError):
    pass


class PlexFlowMissing(PlexFlowRejected):
    pass


class PlexFlowInvalid(PlexFlowRejected):
    pass


class PlexFlowExpired(PlexFlowRejected):
    pass


@dataclass(frozen=True)
class PlexFlow:
    state: str
    pin_id: int
    purpose: str
    started_at: int


def begin_plex_flow(
    session: MutableMapping,
    *,
    pin_id: int,
    purpose: str,
    now: int | None = None,
) -> PlexFlow:
    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_purpose not in _ALLOWED_PURPOSES:
        raise ValueError("unsupported Plex authentication purpose")
    flow = PlexFlow(
        state=secrets.token_urlsafe(32),
        pin_id=int(pin_id),
        purpose=normalized_purpose,
        started_at=int(time.time() if now is None else now),
    )
    session[PLEX_FLOW_SESSION_KEY] = {
        "state": flow.state,
        "pin_id": flow.pin_id,
        "purpose": flow.purpose,
        "started_at": flow.started_at,
    }
    return flow


def consume_plex_flow(
    session: MutableMapping,
    *,
    returned_state: str,
    expected_purpose: str | None = None,
    now: int | None = None,
    max_age: int = PLEX_FLOW_MAX_AGE_SECONDS,
) -> PlexFlow:
    # Pop first: success, invalid state, and expired state are all one-shot.
    stored = session.pop(PLEX_FLOW_SESSION_KEY, None)
    if not isinstance(stored, dict):
        raise PlexFlowMissing("Plex authentication session is missing")

    stored_state = str(stored.get("state") or "")
    candidate_state = str(returned_state or "")
    if not stored_state or not hmac.compare_digest(stored_state, candidate_state):
        raise PlexFlowInvalid("Plex authentication state is invalid")

    try:
        flow = PlexFlow(
            state=stored_state,
            pin_id=int(stored["pin_id"]),
            purpose=str(stored["purpose"]),
            started_at=int(stored["started_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlexFlowInvalid("Plex authentication session is invalid") from exc

    current_time = int(time.time() if now is None else now)
    bounded_max_age = max(1, min(int(max_age), PLEX_FLOW_MAX_AGE_SECONDS))
    age = current_time - flow.started_at
    if age < 0 or age > bounded_max_age:
        raise PlexFlowExpired("Plex authentication session has expired")

    if expected_purpose and flow.purpose != expected_purpose:
        raise PlexFlowInvalid("Plex authentication purpose does not match")
    return flow
