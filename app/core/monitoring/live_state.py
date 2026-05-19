from threading import RLock
from copy import deepcopy
import time

LIVE_SESSIONS = {}
LIVE_LOCK = RLock()


def make_live_key(server_id, session_key):
    return f"{server_id}:{session_key}"


def update_live_session(server_id, session_key, payload):
    key = make_live_key(server_id, session_key)

    payload["last_live_update"] = int(time.time())

    with LIVE_LOCK:
        LIVE_SESSIONS[key] = payload


def remove_live_session(server_id, session_key):
    key = make_live_key(server_id, session_key)

    with LIVE_LOCK:
        LIVE_SESSIONS.pop(key, None)


def get_live_sessions(max_age=120):
    now = int(time.time())

    with LIVE_LOCK:

        expired = []

        for key, session in LIVE_SESSIONS.items():

            last_update = int(session.get("last_live_update") or 0)

            if now - last_update > max_age:
                expired.append(key)

        for key in expired:
            LIVE_SESSIONS.pop(key, None)

        return deepcopy(list(LIVE_SESSIONS.values()))