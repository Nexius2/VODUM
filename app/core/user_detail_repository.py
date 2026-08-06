USER_DETAIL_COLUMNS = """
    id, username, firstname, lastname, email, second_email,
    expiration_date, renewal_method, renewal_date, created_at, notes,
    status, last_status, status_changed_at, max_streams_override,
    notifications_order_override, expiration_date_override, referrer_user_id,
    subscription_template_id, discord_user_id, discord_name
"""

USER_DETAIL_SETTINGS_COLUMNS = """
    user_notifications_can_override, notifications_order, debug_mode
"""

USER_SERVER_ACCESS_COLUMNS = """
    s.id AS server_id, s.name, s.type, s.url, s.local_url,
    s.public_url, s.status
"""

USER_LIBRARY_ACCESS_COLUMNS = """
    l.id, l.server_id, l.name, l.type, l.section_id
"""


def load_user_access_rows(
    db,
    user_id: int,
    *,
    include_servers: bool,
    include_libraries: bool,
) -> tuple[list, list]:
    servers = db.query(
        f"""
        SELECT
{USER_SERVER_ACCESS_COLUMNS},
            mu.id AS media_user_id, mu.external_user_id,
            mu.username AS media_username, mu.email AS media_email,
            mu.avatar AS media_avatar, mu.type AS media_type,
            mu.role AS media_role, mu.joined_at, mu.accepted_at,
            mu.raw_json, mu.details_json,
            CASE WHEN EXISTS (
                SELECT 1 FROM media_user_libraries mul
                WHERE mul.media_user_id = mu.id LIMIT 1
            ) THEN 1 ELSE 0 END AS has_access
        FROM media_users mu
        JOIN servers s ON s.id = mu.server_id
        WHERE mu.vodum_user_id = ?
          AND mu.id = (
                SELECT mu2.id FROM media_users mu2
                WHERE mu2.vodum_user_id = mu.vodum_user_id
                  AND mu2.server_id = mu.server_id
                ORDER BY
                    CASE WHEN COALESCE(NULLIF(TRIM(mu2.details_json), ''), '') <> '' THEN 0 ELSE 1 END,
                    CASE WHEN COALESCE(NULLIF(TRIM(mu2.raw_json), ''), '') <> '' THEN 0 ELSE 1 END,
                    mu2.id ASC
                LIMIT 1
          )
        ORDER BY s.type, s.name
        """,
        (user_id,),
    ) if include_servers else []

    libraries = db.query(
        f"""
        SELECT
{USER_LIBRARY_ACCESS_COLUMNS},
            s.name AS server_name,
            CASE WHEN EXISTS (
                SELECT 1
                FROM media_user_libraries mul
                JOIN media_users mu ON mu.id = mul.media_user_id
                WHERE mul.library_id = l.id
                  AND mu.vodum_user_id = ?
                  AND mu.server_id = l.server_id
            ) THEN 1 ELSE 0 END AS has_access
        FROM libraries l
        JOIN servers s ON s.id = l.server_id
        ORDER BY s.name, l.name
        """,
        (user_id,),
    ) if include_libraries else []
    return servers, libraries


def load_user_detail(db, user_id: int):
    row = db.query_one(
        f"SELECT {USER_DETAIL_COLUMNS} FROM vodum_users WHERE id = ?",
        (user_id,),
    )
    return dict(row) if row else None


def load_user_detail_settings(db) -> dict:
    row = db.query_one(f"SELECT {USER_DETAIL_SETTINGS_COLUMNS} FROM settings WHERE id = 1")
    return dict(row) if row else {}


def load_referral_admin_data(db, user_id: int) -> tuple[dict, dict | None]:
    settings = db.query_one(
        """
        SELECT allow_referrer_change_before_qualification,
               qualification_days, reward_days
        FROM user_referral_settings
        WHERE id = 1
        """
    )
    current = db.query_one(
        """
        SELECT id, referrer_user_id, status
        FROM user_referrals
        WHERE referred_user_id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    return dict(settings) if settings else {}, dict(current) if current else None


def load_user_provider_types(db, user_id: int) -> list[str]:
    return [
        row["type"]
        for row in db.query(
            """
            SELECT DISTINCT s.type
            FROM servers s
            JOIN media_users mu ON mu.server_id = s.id
            WHERE mu.vodum_user_id = ?
            """,
            (user_id,),
        )
        if row["type"]
    ]
