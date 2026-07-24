from __future__ import annotations

import json
import re
from datetime import datetime


REFERRAL_DISPLAY_COLUMNS = """
    r.id,
    r.referrer_user_id,
    r.referred_user_id,
    r.status,
    r.qualification_due_at,
    r.reward_days_snapshot
"""

EMPTY_REFERRAL_STATS = {
    "total_referrals": 0,
    "pending_referrals": 0,
    "qualified_referrals": 0,
    "rewarded_referrals": 0,
}


def normalize_profile_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, date_format).date().isoformat()
        except Exception:
            pass
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if match:
        year, month, day = (
            match.group(1),
            match.group(2).zfill(2),
            match.group(3).zfill(2),
        )
        try:
            return datetime.strptime(
                f"{year}-{month}-{day}", "%Y-%m-%d"
            ).date().isoformat()
        except Exception:
            return None
    try:
        date_part = raw.split("T", 1)[0].split(" ", 1)[0]
        return datetime.fromisoformat(date_part).date().isoformat()
    except Exception:
        return None


def enrich_media_servers(rows):
    servers = []
    for row in rows:
        server = dict(row)
        server.update(
            {
                "allow_sync": 0,
                "allow_camera_upload": 0,
                "allow_channels": 0,
                "filter_movies": "",
                "filter_television": "",
                "filter_music": "",
            }
        )
        try:
            details = json.loads(server.get("details_json") or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        if server.get("media_type") == "plex":
            plex_share = details.get("plex_share", {})
            if not isinstance(plex_share, dict):
                plex_share = {}
            server["allow_sync"] = int(bool(plex_share.get("allowSync")))
            server["allow_camera_upload"] = int(
                bool(plex_share.get("allowCameraUpload"))
            )
            server["allow_channels"] = int(bool(plex_share.get("allowChannels")))
            server["filter_movies"] = plex_share.get("filterMovies") or ""
            server["filter_television"] = plex_share.get("filterTelevision") or ""
            server["filter_music"] = plex_share.get("filterMusic") or ""

        server["_details_obj"] = details
        servers.append(server)
    return servers


def load_expiration_lock(db, user_id: int) -> dict:
    rows = db.query(
        """
        SELECT
            s.type AS server_type,
            s.name AS server_name,
            mu.role AS media_role,
            mu.raw_json
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
        """,
        (user_id,),
    ) or []

    reasons = []
    for row in rows:
        item = dict(row)
        server_type = (item.get("server_type") or "").strip().lower()
        media_role = (item.get("media_role") or "").strip().lower()
        server_name = (item.get("server_name") or "").strip()
        if server_type == "plex" and media_role == "owner":
            reasons.append(f"Plex owner ({server_name})")
        if server_type == "jellyfin":
            is_admin = media_role == "admin"
            try:
                raw = json.loads(item.get("raw_json") or "{}")
                policy = raw.get("Policy") if isinstance(raw, dict) else {}
                if isinstance(policy, dict) and policy.get("IsAdministrator"):
                    is_admin = True
            except Exception:
                pass
            if is_admin:
                reasons.append(f"Jellyfin admin ({server_name})")

    role_label = ""
    if any(reason.startswith("Plex owner") for reason in reasons):
        role_label = "Owner"
    elif any(reason.startswith("Jellyfin admin") for reason in reasons):
        role_label = "Admin"
    return {
        "locked": bool(reasons),
        "label": " / ".join(reasons),
        "role_label": role_label,
    }


def load_merged_usernames(db, user_id: int, main_username: str):
    main_username_normalized = (main_username or "").strip().lower()
    rows = db.query(
        """
        SELECT DISTINCT username
        FROM media_users
        WHERE vodum_user_id = ?
          AND username IS NOT NULL
          AND TRIM(username) <> ''
        """,
        (user_id,),
    ) or []

    usernames = {}
    for row in rows:
        username = str(row["username"]).strip()
        if not username or username.lower() == main_username_normalized:
            continue
        usernames.setdefault(username.lower(), username)
    return sorted(usernames.values(), key=str.lower)


def load_referral_context(db, user_id: int, referrer_user_id=None):
    referral_row = db.query_one(
        f"""
        SELECT
{REFERRAL_DISPLAY_COLUMNS},
            referrer.username AS referrer_username,
            referrer.email AS referrer_email
        FROM user_referrals r
        LEFT JOIN vodum_users referrer ON referrer.id = r.referrer_user_id
        WHERE r.referred_user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    referral = dict(referral_row) if referral_row else None

    referrer_fallback = None
    if not referral and referrer_user_id:
        fallback_row = db.query_one(
            """
            SELECT id, username, email
            FROM vodum_users
            WHERE id = ?
            LIMIT 1
            """,
            (referrer_user_id,),
        )
        referrer_fallback = dict(fallback_row) if fallback_row else None

    stats_row = db.query_one(
        """
        SELECT
            COUNT(*) AS total_referrals,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_referrals,
            SUM(CASE WHEN status = 'qualified' THEN 1 ELSE 0 END) AS qualified_referrals,
            SUM(CASE WHEN status = 'rewarded' THEN 1 ELSE 0 END) AS rewarded_referrals
        FROM user_referrals
        WHERE referrer_user_id = ?
        """,
        (user_id,),
    )
    referral_stats = dict(stats_row) if stats_row else dict(EMPTY_REFERRAL_STATS)
    referred_users = [
        dict(row)
        for row in (
            db.query(
                """
                SELECT
                    u.id,
                    u.username,
                    u.email,
                    u.status,
                    r.status AS referral_status,
                    r.qualification_due_at
                FROM user_referrals r
                JOIN vodum_users u ON u.id = r.referred_user_id
                WHERE r.referrer_user_id = ?
                ORDER BY u.username ASC
                """,
                (user_id,),
            )
            or []
        )
    ]
    return {
        "referral": referral,
        "referrer_fallback": referrer_fallback,
        "referral_stats": referral_stats,
        "referred_users": referred_users,
    }
