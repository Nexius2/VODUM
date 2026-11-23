"""Explicit manual Jellyfin suspension, scoped to one linked native account."""
import json
import re

from core.http_security import server_http_session
from core.providers.jellyfin_users import _pick_base_url, _headers, _api_key


class JellyfinAccountStateError(RuntimeError):
    pass


def set_jellyfin_account_disabled(db, user_id, media_user_id, disabled):
    if type(disabled) is not bool:
        raise JellyfinAccountStateError("jellyfin_state_failed")
    row = db.query_one("""SELECT mu.external_user_id, mu.role, s.*
        FROM media_users mu JOIN servers s ON s.id=mu.server_id
        WHERE mu.id=? AND mu.vodum_user_id=?
          AND LOWER(TRIM(mu.type))='jellyfin' AND LOWER(TRIM(s.type))='jellyfin'
        """, (media_user_id, user_id))
    if not row:
        raise JellyfinAccountStateError("jellyfin_state_failed")
    server = dict(row)
    native_id = str(server.get("external_user_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9-]+", native_id) or native_id == "0":
        raise JellyfinAccountStateError("jellyfin_state_failed")
    if str(server.get("role") or "").lower() in ("admin", "owner"):
        raise JellyfinAccountStateError("jellyfin_state_protected")
    http = server_http_session(server)
    try:
        base, headers = _pick_base_url(server), _headers(_api_key(server))
        url = f"{base}/Users/{native_id}"

        def read():
            response = http.get(url, headers=headers, timeout=20, allow_redirects=False)
            if response.status_code != 200:
                raise JellyfinAccountStateError("jellyfin_state_failed")
            data = response.json()
            policy = data.get("Policy") if isinstance(data, dict) else None
            if (not isinstance(policy, dict) or str(data.get("Id")) != native_id
                    or type(policy.get("IsDisabled")) is not bool
                    or type(policy.get("IsAdministrator")) is not bool):
                raise JellyfinAccountStateError("jellyfin_state_failed")
            if policy["IsAdministrator"]:
                raise JellyfinAccountStateError("jellyfin_state_protected")
            return data

        data = read()
        if data["Policy"]["IsDisabled"] != disabled:
            policy = dict(data["Policy"])
            policy["IsDisabled"] = disabled
            response = http.post(url + "/Policy", json=policy, headers=headers,
                                 timeout=20, allow_redirects=False)
            if response.status_code not in (200, 204):
                raise JellyfinAccountStateError("jellyfin_state_failed")
            data = read()
            if data["Policy"]["IsDisabled"] != disabled:
                raise JellyfinAccountStateError("jellyfin_state_failed")
        db.execute("""UPDATE media_users SET raw_json=?
            WHERE id=? AND vodum_user_id=? AND external_user_id=?""",
            (json.dumps(data), media_user_id, user_id, native_id))
    except JellyfinAccountStateError:
        raise
    except Exception:
        raise JellyfinAccountStateError("jellyfin_state_failed") from None
    finally:
        http.close()
