from collections import OrderedDict
from ipaddress import ip_address
from threading import Lock
from time import monotonic

import requests


BATCH_SIZE = 100
CACHE_SIZE = 2048
LOCATION_TTL = 86400
MISS_TTL = 300

_cache = OrderedDict()
_lock = Lock()
_retry_at = 0.0


def parse_stream_ip(value):
    try:
        address = ip_address(str(value or "").strip())
    except ValueError:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def is_public_ip(address):
    return address.is_global and not address.is_multicast and not address.is_reserved


def format_ip_location(data):
    parts = (data.get(key) for key in ("city", "regionName", "country"))
    return ", ".join(dict.fromkeys(part.strip() for part in parts if isinstance(part, str) and part.strip()))


def _lookup_batch(addresses):
    global _retry_at
    try:
        response = requests.post(
            "http://ip-api.com/batch",
            params={"fields": "status,query,city,regionName,country"},
            json=addresses,
            timeout=(1, 2),
            allow_redirects=False,
        )
        if response.status_code == 429 or response.headers.get("X-Rl") == "0":
            delay = response.headers.get("X-Ttl", "")
            _retry_at = monotonic() + (max(1, int(delay)) if delay.isdecimal() else 60)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Unexpected IP geolocation response")
    except (requests.RequestException, ValueError):
        _retry_at = max(_retry_at, monotonic() + 30)
        return {}

    locations = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "success":
            continue
        address = parse_stream_ip(row.get("query"))
        if address is not None:
            locations[str(address)] = format_ip_location(row)
    return locations


def load_ip_locations(values):
    """Return approximate labels keyed by the original IP, with no network lookups for local IPs."""
    parsed = {value: parse_stream_ip(value) for value in values}
    public = {
        value: str(address)
        for value, address in parsed.items()
        if address is not None and is_public_ip(address)
    }
    now = monotonic()
    # Keep page refreshes responsive while another request fills the cache.
    if public and _lock.acquire(blocking=False):
        try:
            missing = [
                address for address in dict.fromkeys(public.values())
                if _cache.get(address, (0, ""))[0] <= now
            ]
            if missing and now >= _retry_at:
                batch = missing[:BATCH_SIZE]
                locations = _lookup_batch(batch)
                now = monotonic()
                for address in batch:
                    label = locations.get(address, "")
                    _cache[address] = (now + (LOCATION_TTL if label else MISS_TTL), label)
                    _cache.move_to_end(address)
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
        finally:
            _lock.release()

    labels = {}
    for value, address in parsed.items():
        if address is None:
            labels[value] = (False, "")
        elif value not in public:
            labels[value] = (True, "")
        else:
            expires, label = _cache.get(public[value], (0, ""))
            labels[value] = (False, label if expires > now else "")
    return labels
