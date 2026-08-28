from __future__ import annotations

import ipaddress
import requests

from secret_store import decrypt_secret

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_config(settings) -> dict:
    source = dict(settings or {})
    return {
        "enabled": int(source.get("turnstile_enabled") or 0) == 1,
        "site_key": str(source.get("turnstile_site_key") or "").strip(),
        "secret_key": decrypt_secret(source.get("turnstile_secret_key")) or "",
        "mode": source.get("turnstile_mode") if source.get("turnstile_mode") in {"compact", "invisible"} else "compact",
        "protect_portal": int(source.get("turnstile_protect_portal") or 0) == 1,
        "protect_admin": int(source.get("turnstile_protect_admin") or 0) == 1,
    }


def local_recovery_allowed(remote_addr: str | None) -> bool:
    try:
        return ipaddress.ip_address(str(remote_addr or "")).is_loopback
    except ValueError:
        return False


def verify_turnstile(settings, token: str, *, remote_ip="", hostname="", http_post=requests.post) -> dict:
    config = turnstile_config(settings)
    if not config["enabled"] or not config["protect_portal"]:
        return {"ok": True, "reason": "disabled"}
    if not config["site_key"] or not config["secret_key"]:
        return {"ok": False, "reason": "incomplete_configuration"}
    if not str(token or "").strip():
        return {"ok": False, "reason": "missing_token"}
    try:
        response = http_post(VERIFY_URL, data={"secret": config["secret_key"], "response": token, "remoteip": remote_ip}, timeout=4)
        payload = response.json() if response.ok else {}
    except (requests.RequestException, ValueError):
        return {"ok": local_recovery_allowed(remote_ip), "reason": "provider_unavailable"}
    returned_host = str(payload.get("hostname") or "").lower()
    expected_host = str(hostname or "").split(":", 1)[0].lower()
    if not payload.get("success"):
        return {"ok": False, "reason": "challenge_failed"}
    if expected_host and returned_host != expected_host:
        return {"ok": False, "reason": "hostname_mismatch"}
    return {"ok": True, "reason": "verified"}
