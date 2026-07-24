from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from logging_utils import get_logger, is_debug_mode_enabled


logger = get_logger("monitoring.resource_stats")


def empty_server_resource_stats(note=None):
    return {
        "server_cpu_pct": None,
        "server_ram_pct": None,
        "server_resource_available": False,
        "server_resource_note": note,
    }


def load_server_resource_stats(db, server_ids, max_age_seconds=600):
    normalized_ids = []
    for server_id in server_ids or []:
        try:
            server_id = int(server_id or 0)
        except (TypeError, ValueError):
            server_id = 0
        if server_id > 0:
            normalized_ids.append(server_id)
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    rows = db.query(
        f"""
        SELECT server_id, cpu_pct, ram_pct, is_available, note, fetched_at
        FROM monitoring_server_resources
        WHERE server_id IN ({placeholders})
          AND datetime(fetched_at) >= datetime('now', ?)
        """,
        tuple(normalized_ids) + (f"-{int(max_age_seconds)} seconds",),
    )
    return {
        int(row["server_id"]): {
            "server_cpu_pct": row["cpu_pct"],
            "server_ram_pct": row["ram_pct"],
            "server_resource_available": bool(row["is_available"]),
            "server_resource_note": row["note"],
        }
        for row in rows or []
    }


def apply_server_resource_stats(
    rows,
    resource_by_server,
    server_id_key="server_id",
):
    for row in rows or []:
        try:
            server_id = int(row.get(server_id_key) or 0)
        except (TypeError, ValueError):
            server_id = 0
        resource = resource_by_server.get(server_id) or empty_server_resource_stats(
            note="unavailable"
        )
        row["server_cpu_pct"] = resource.get("server_cpu_pct")
        row["server_ram_pct"] = resource.get("server_ram_pct")
        row["server_resource_available"] = bool(
            resource.get("server_resource_available")
        )
        row["server_resource_note"] = resource.get("server_resource_note")


def normalize_pct(value) -> Optional[float]:
    if value is None:
        return None
    try:
        normalized = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return round(min(normalized, 100.0), 1)


def extract_plex_resource_percentages(xml_text: str) -> Dict[str, Any]:
    """Extract the best available CPU and RAM percentages from Plex XML."""
    root = ET.fromstring(xml_text)
    cpu_keys = ("processCpuUtilization", "cpuUtilization", "cpuPercent", "cpu", "hostCpuUtilization")
    ram_keys = ("processMemoryUtilization", "memoryUtilization", "memoryPercent", "memory", "hostMemoryUtilization")
    best = None

    for elem in root.iter():
        attrs = getattr(elem, "attrib", {}) or {}
        cpu = next((value for key in cpu_keys if attrs.get(key) not in (None, "") and (value := normalize_pct(attrs.get(key))) is not None), None)
        ram = next((value for key in ram_keys if attrs.get(key) not in (None, "") and (value := normalize_pct(attrs.get(key))) is not None), None)
        if cpu is None and ram is None:
            continue
        tag = (getattr(elem, "tag", "") or "").lower()
        title = (attrs.get("title") or attrs.get("name") or attrs.get("process") or "").lower()
        score = (10 if "plex media server" in title else 0) + (5 if tag == "process" else 0) + (2 if cpu is not None else 0) + (2 if ram is not None else 0)
        candidate = {"cpu_pct": cpu, "ram_pct": ram, "score": score}
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if not best:
        for elem in root.iter():
            attrs = getattr(elem, "attrib", {}) or {}
            try:
                cpu = float(attrs["cpu"]) if attrs.get("cpu") else None
                ram = float(attrs["memory"]) if attrs.get("memory") else None
            except (TypeError, ValueError):
                cpu = ram = None
            if cpu is not None or ram is not None:
                return {"cpu_pct": None, "ram_pct": None, "is_available": 1, "note": "raw_values_only"}
        return {"cpu_pct": None, "ram_pct": None, "is_available": 0, "note": "unavailable"}

    return {
        "cpu_pct": best.get("cpu_pct"),
        "ram_pct": best.get("ram_pct"),
        "is_available": int(best.get("cpu_pct") is not None or best.get("ram_pct") is not None),
        "note": None,
    }


def candidate_bases(server_row) -> list[str]:
    bases = []
    for key in ("url", "local_url", "public_url"):
        raw = server_row.get(key)
        if not raw:
            continue
        base = str(raw).strip().rstrip("/")
        if base.lower() in {"", "none", "null", "undefined"}:
            continue
        if not base.startswith(("http://", "https://")):
            continue
        if base not in bases:
            bases.append(base)
    return bases


def collect_plex_server_resources(srv: Dict[str, Any], timeout: int = 4) -> Dict[str, Any]:
    token = (srv.get("token") or "").strip()
    bases = candidate_bases(srv)
    if not token or not bases:
        return {"cpu_pct": None, "ram_pct": None, "is_available": 0, "note": "missing_config"}

    from core.http_security import server_http_session

    last_error = None
    http = server_http_session(srv)
    for base in bases:
        try:
            response = http.get(
                f"{base}/statistics/resources",
                params={"timespan": 6},
                headers={"Accept": "application/xml", "X-Plex-Token": token},
                timeout=timeout,
            )
            response.raise_for_status()
            parsed = extract_plex_resource_percentages(response.text)
            parsed["note"] = None if parsed.get("is_available") else "unavailable"
            return parsed
        except Exception as exc:
            last_error = exc

    if is_debug_mode_enabled():
        logger.debug("Plex resource stats fetch failed for server_id=%s: %s", srv.get("id"), str(last_error) if last_error else "unknown")
    return {"cpu_pct": None, "ram_pct": None, "is_available": 0, "note": "unreachable"}


def collect_server_resource_stats(srv: Dict[str, Any], provider_name: str) -> Dict[str, Any]:
    if (provider_name or "").lower().strip() == "plex":
        return collect_plex_server_resources(srv)
    return {"cpu_pct": None, "ram_pct": None, "is_available": 0, "note": "unsupported"}


def store_server_resource_stats(db, server_id: int, provider_name: str, stats: Dict[str, Any]) -> None:
    db.execute(
        """
        INSERT INTO monitoring_server_resources (
          server_id, provider, cpu_pct, ram_pct, is_available, note, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server_id) DO UPDATE SET
          provider = excluded.provider,
          cpu_pct = excluded.cpu_pct,
          ram_pct = excluded.ram_pct,
          is_available = excluded.is_available,
          note = excluded.note,
          fetched_at = CURRENT_TIMESTAMP
        """,
        (server_id, provider_name, stats.get("cpu_pct"), stats.get("ram_pct"), int(bool(stats.get("is_available"))), stats.get("note")),
    )
