from __future__ import annotations

import hashlib
import json
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import requests

from core.http_security import ConfiguredHostSession, url_origin
from secret_store import decrypt_secret, encrypt_secret


PLEX_RESOURCES_URL = "https://plex.tv/api/resources"
DISCOVERY_TTL_SECONDS = 10 * 60
MAX_DISCOVERY_SERVERS = 100
MAX_CONNECTIONS_PER_SERVER = 10


class PlexDiscoveryError(RuntimeError):
    pass


def _safe_url(value: object) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or parsed.path not in {"", "/"}
        ):
            return None
    except ValueError:
        return None
    return raw


def _connection_rank(connection: dict) -> tuple:
    return (
        1 if connection["relay"] else 0,
        0 if connection["local"] else 1,
        0 if connection["protocol"] == "https" else 1,
        connection["uri"],
    )


def parse_plex_resources(payload: bytes, *, existing_identifiers=()) -> list[dict]:
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise PlexDiscoveryError("Plex returned an invalid resource list") from exc

    existing = {str(value or "").strip() for value in existing_identifiers if value}
    resources: dict[str, dict] = {}
    for device in root.findall(".//Device"):
        if str(device.get("provides") or "").lower().find("server") < 0:
            continue
        machine_id = str(
            device.get("clientIdentifier") or device.get("machineIdentifier") or ""
        ).strip()
        if not machine_id:
            continue
        connections = []
        seen_urls = set()
        for item in device.findall("./Connection")[:MAX_CONNECTIONS_PER_SERVER]:
            uri = _safe_url(item.get("uri"))
            if not uri or uri in seen_urls:
                continue
            seen_urls.add(uri)
            parsed = urlsplit(uri)
            connections.append(
                {
                    "uri": uri,
                    "local": str(item.get("local") or "0") == "1",
                    "relay": str(item.get("relay") or "0") == "1",
                    "protocol": parsed.scheme,
                }
            )
        connections.sort(key=_connection_rank)
        token = str(device.get("accessToken") or "").strip()
        candidate = {
            "machine_identifier": machine_id,
            "name": str(device.get("name") or "Plex Media Server").strip(),
            "owned": str(device.get("owned") or "0") == "1",
            "presence": str(device.get("presence") or "0") == "1",
            "access_token": token,
            "connections": connections,
            "already_added": machine_id in existing,
        }
        previous = resources.get(machine_id)
        if previous is None or (not previous["owned"] and candidate["owned"]):
            resources[machine_id] = candidate
        if len(resources) >= MAX_DISCOVERY_SERVERS:
            break
    return sorted(
        resources.values(),
        key=lambda item: (not item["owned"], not item["presence"], item["name"].casefold()),
    )


def discover_plex_resources(account_token: str, *, existing_identifiers=(), timeout=10.0, session=None) -> list[dict]:
    token = str(account_token or "").strip()
    if not token:
        raise PlexDiscoveryError("A recent Plex authorization is required")
    http = session or ConfiguredHostSession(
        {url_origin(PLEX_RESOURCES_URL)}, default_timeout=min(float(timeout), 15.0)
    )
    try:
        response = http.get(
            PLEX_RESOURCES_URL,
            params={"includeHttps": "1", "includeRelay": "1"},
            headers={"X-Plex-Token": token, "Accept": "application/xml"},
            timeout=min(float(timeout), 15.0),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PlexDiscoveryError("Plex server discovery is temporarily unavailable") from exc
    if len(response.content) > 2_000_000:
        raise PlexDiscoveryError("Plex returned an unexpectedly large resource list")
    return parse_plex_resources(response.content, existing_identifiers=existing_identifiers)


def _session_fingerprint(secret: str) -> str:
    return hashlib.sha256(str(secret or "").encode("utf-8")).hexdigest()


def store_discovery(db, *, session_secret: str, provider_subject: str, candidates: list[dict]) -> str:
    now = int(time.time())
    discovery_id = uuid.uuid4().hex
    db.execute("DELETE FROM plex_discovery_candidates WHERE expires_at < ?", (now,))
    for candidate in candidates:
        db.execute(
            """
            INSERT INTO plex_discovery_candidates(
              id,discovery_id,session_fingerprint,provider_subject,machine_identifier,
              name,is_owned,presence,connections_json,access_token_enc,expires_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                uuid.uuid4().hex,
                discovery_id,
                _session_fingerprint(session_secret),
                provider_subject,
                candidate["machine_identifier"],
                candidate["name"],
                1 if candidate["owned"] else 0,
                1 if candidate["presence"] else 0,
                json.dumps(candidate["connections"], separators=(",", ":")),
                encrypt_secret(candidate["access_token"]) if candidate["access_token"] else None,
                now + DISCOVERY_TTL_SECONDS,
            ),
        )
    return discovery_id


def load_discovery(db, *, discovery_id: str, session_secret: str) -> list[dict]:
    rows = db.query(
        """
        SELECT id,provider_subject,machine_identifier,name,is_owned,presence,connections_json,
               access_token_enc,expires_at
        FROM plex_discovery_candidates
        WHERE discovery_id=? AND session_fingerprint=? AND expires_at>=?
        ORDER BY is_owned DESC,presence DESC,name COLLATE NOCASE
        """,
        (discovery_id, _session_fingerprint(session_secret), int(time.time())),
    ) or []
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["connections"] = json.loads(item.pop("connections_json") or "[]")
        except (TypeError, ValueError):
            item["connections"] = []
        encrypted_token = item.pop("access_token_enc", None)
        item["access_token"] = decrypt_secret(encrypted_token) if encrypted_token else ""
        result.append(item)
    return result


def delete_discovery(db, discovery_id: str) -> None:
    db.execute("DELETE FROM plex_discovery_candidates WHERE discovery_id=?", (discovery_id,))


def automatic_plex_suggestions(
    db,
    *,
    provider_subject: str,
    account_token: str,
    context: dict | None,
    return_to: str,
) -> tuple[list[dict], dict]:
    """Load a short cache or discover suggestions for an already-linked account."""
    now = int(time.time())
    current = context if isinstance(context, dict) else {}
    existing_rows = db.query(
        "SELECT server_identifier FROM servers WHERE type='plex'"
    ) or []
    existing = {
        str(row["server_identifier"] or "").strip()
        for row in existing_rows
        if row["server_identifier"]
    }
    cached = (
        current.get("id")
        and current.get("nonce")
        and current.get("provider_subject") == provider_subject
        and int(current.get("expires_at") or 0) >= now
    )
    if cached:
        candidates = load_discovery(
            db,
            discovery_id=str(current["id"]),
            session_secret=str(current["nonce"]),
        )
        if candidates or int(current.get("result_count") or 0) == 0:
            refreshed_context = dict(current)
            refreshed_context["return_to"] = "wizard" if return_to == "wizard" else "servers"
            return _safe_suggestions(candidates, existing), refreshed_context

    if current.get("id"):
        delete_discovery(db, str(current["id"]))
    candidates = discover_plex_resources(
        account_token,
        existing_identifiers=existing,
    )
    nonce = uuid.uuid4().hex
    discovery_id = store_discovery(
        db,
        session_secret=nonce,
        provider_subject=provider_subject,
        candidates=candidates,
    )
    next_context = {
        "id": discovery_id,
        "nonce": nonce,
        "return_to": "wizard" if return_to == "wizard" else "servers",
        "provider_subject": provider_subject,
        "result_count": len(candidates),
        "expires_at": now + DISCOVERY_TTL_SECONDS,
    }
    return _safe_suggestions(candidates, existing), next_context


def _safe_suggestions(candidates: list[dict], existing: set[str]) -> list[dict]:
    suggestions = []
    for item in candidates:
        machine_id = str(item.get("machine_identifier") or "").strip()
        if not machine_id or machine_id in existing:
            continue
        safe = dict(item)
        safe.pop("access_token", None)
        safe["selectable"] = bool(item.get("access_token") and safe.get("connections"))
        suggestions.append(safe)
    return suggestions
