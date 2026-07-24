import ipaddress
from datetime import datetime

from logging_utils import get_logger, is_debug_mode_enabled


logger = get_logger("stream_enforcer")
HOUSEHOLD_TRANSITION_SECONDS = 90
HOUSEHOLD_DEVICE_MATCH_SCORE = 5


def safe_lower(value) -> str:
    return str(value or "").strip().lower()


def parse_datetime(value: str):
    if not value:
        return None
    value = str(value).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def seconds_between_sessions(a: dict, b: dict) -> int:
    a_ts = parse_datetime(a.get("last_seen_at") or a.get("started_at"))
    b_ts = parse_datetime(b.get("last_seen_at") or b.get("started_at"))
    return int(abs((a_ts - b_ts).total_seconds())) if a_ts and b_ts else 999999


def same_media_family(a: dict, b: dict) -> bool:
    a_parent = safe_lower(a.get("grandparent_title"))
    b_parent = safe_lower(b.get("grandparent_title"))
    if a_parent and b_parent and a_parent == b_parent:
        return True
    a_title = safe_lower(a.get("title"))
    b_title = safe_lower(b.get("title"))
    return bool(a_title and b_title and a_title == b_title)


def extract_machine_identifier(session: dict) -> str:
    try:
        raw = session.get("_parsed_raw_json") or {}
        for key in ("PlayerMachineIdentifier", "MachineIdentifier", "DeviceId", "ClientIdentifier", "clientIdentifier"):
            value = raw.get(key)
            if value:
                return str(value).strip().lower()
    except Exception as exc:
        if is_debug_mode_enabled():
            logger.debug("[smart_household] failed to extract machine identifier: %s", exc)
    return ""


def same_subnet(ip1: str, ip2: str) -> bool:
    try:
        first = ipaddress.ip_address(ip1)
        second = ipaddress.ip_address(ip2)
        if first.version != second.version:
            return False
        if first.version == 4:
            return str(ip1).split(".")[:3] == str(ip2).split(".")[:3]
        return str(ip1).split(":")[:4] == str(ip2).split(":")[:4]
    except Exception:
        return False


def household_match_score(a: dict, b: dict) -> int:
    score = 0
    a_ip, b_ip = safe_lower(a.get("ip")), safe_lower(b.get("ip"))
    if a_ip and b_ip and a_ip == b_ip:
        score += 10
    elif a_ip and b_ip and same_subnet(a_ip, b_ip):
        score += 4
    a_machine, b_machine = extract_machine_identifier(a), extract_machine_identifier(b)
    if a_machine and b_machine and a_machine == b_machine:
        score += 10
    if safe_lower(a.get("device")) and safe_lower(a.get("device")) == safe_lower(b.get("device")):
        score += 3
    if safe_lower(a.get("client_product")) and safe_lower(a.get("client_product")) == safe_lower(b.get("client_product")):
        score += 2
    if same_media_family(a, b):
        score += 2
    if seconds_between_sessions(a, b) <= HOUSEHOLD_TRANSITION_SECONDS:
        score += 3
    return score


def is_probable_same_household(a: dict, b: dict) -> bool:
    return household_match_score(a, b) >= HOUSEHOLD_DEVICE_MATCH_SCORE


def session_endpoint_identity(session: dict) -> tuple[str, bool]:
    machine = extract_machine_identifier(session)
    if machine:
        return f"machine:{machine}", True
    ip = safe_lower(session.get("ip"))
    descriptor = "|".join([
        safe_lower(session.get("client_product")),
        safe_lower(session.get("client_name")),
        safe_lower(session.get("device")),
    ]).strip("|")
    if not ip or ip == "unknown" or not descriptor:
        return "", False
    return f"client:{ip}|{descriptor}", False


def session_time_delta_seconds(first: dict, second: dict) -> int:
    first_time = parse_datetime(first.get("started_at") or first.get("last_seen_at"))
    second_time = parse_datetime(second.get("started_at") or second.get("last_seen_at"))
    return int(abs((first_time - second_time).total_seconds())) if first_time and second_time else 999999


def session_sort_key(session: dict) -> str:
    return str(session.get("last_seen_at") or session.get("started_at") or "")
