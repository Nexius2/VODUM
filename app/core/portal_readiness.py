from __future__ import annotations

from urllib.parse import urlsplit
import ipaddress


def local_portal_test_request_allowed(settings: dict, remote_addr: str, host: str) -> bool:
    if int(settings.get("portal_local_test_enabled") or 0) != 1:
        return False
    try:
        address = ipaddress.ip_address(str(remote_addr or "").strip())
        host_name = (urlsplit(f"//{host}").hostname or "").strip()
    except ValueError:
        return False
    private_networks = (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("fc00::/7"),
    )
    address_is_local = address.is_loopback or any(address in network for network in private_networks)
    if host_name.lower() == "localhost":
        host_is_local = True
    else:
        try:
            host_address = ipaddress.ip_address(host_name)
            host_is_local = host_address.is_loopback or any(host_address in network for network in private_networks)
        except ValueError:
            host_is_local = False
    return bool(address_is_local and host_is_local)


def _proxy_configuration_safe(enabled, trusted_networks: str) -> bool:
    if int(enabled or 0) != 1:
        return True
    networks = []
    for raw in str(trusted_networks or "").split(","):
        if not raw.strip():
            continue
        try:
            networks.append(ipaddress.ip_network(raw.strip(), strict=False))
        except ValueError:
            return False
    return bool(networks) and all(network.prefixlen > 0 for network in networks)


def evaluate_portal_readiness(settings: dict, *, trusted_proxy_networks="") -> dict:
    public_url = str(settings.get("portal_public_url") or "").strip()
    parsed = urlsplit(public_url) if public_url else None
    local_auth_enabled = int(settings.get("portal_local_auth_enabled") or 0) == 1
    sign_in_enabled = local_auth_enabled or any(
        int(settings.get(key) or 0) == 1
        for key in ("portal_plex_auth_enabled", "portal_jellyfin_auth_enabled")
    )
    checks = {
        "sign_in_method": sign_in_enabled,
        "public_https": bool(parsed and parsed.scheme == "https" and parsed.netloc),
        "hostname": bool(
            parsed and parsed.hostname
        ),
        "support_email": bool(str(settings.get("contact_email") or "").strip()),
        "mailing": bool(
            int(settings.get("mailing_enabled") or 0) == 1
            and str(settings.get("smtp_host") or "").strip()
            and str(settings.get("mail_from") or settings.get("smtp_user") or "").strip()
        ),
        "secure_cookies": int(settings.get("web_secure_cookies") or 0) == 1,
        "proxy_trust": _proxy_configuration_safe(settings.get("web_trust_proxy"), trusted_proxy_networks),
        "provider_callbacks": True,
    }
    # Password recovery is relevant only when local email/password sign-in is in use.
    if local_auth_enabled:
        checks["recovery"] = True
    return {"ready": all(checks.values()), "checks": checks}
