"""Paginated administrative user reads, isolated from background writer work."""
from db_manager import isolated_read_operation
from web.pagination import page_bounds

USER_LIST_COLUMNS = "u.id, u.username, u.email, u.status, u.expiration_date"


@isolated_read_operation
def load_users_page(db, *, sort, order, selected_statuses, status_none_requested, search, page, per_page):
    order = "desc" if order == "desc" else "asc"
    offset = (page - 1) * per_page
    sort_map = {
        "username": "u.username",
        "email": "u.email",
        "status": "u.status",
        "subscription": "subscription_sort_label",
        "expiration_date": "u.expiration_date",
        "servers_count": "servers_count",
        "libraries_count": "libraries_count",
    }
    sort_column = sort_map.get(sort, "u.username")

    # Do not multiply each media account by all its library grants to find
    # its role/server count. Independent indexed subqueries also keep aggregate
    # sorts proportional to the grants, rather than repeating role checks.
    role_sql = """
        CASE
          WHEN EXISTS (
            SELECT 1 FROM media_users mu JOIN servers s ON s.id=mu.server_id
            WHERE mu.vodum_user_id=u.id AND LOWER(COALESCE(s.type, ''))='plex'
              AND LOWER(COALESCE(mu.role, ''))='owner'
          ) THEN 'Owner'
          WHEN EXISTS (
            SELECT 1 FROM media_users mu JOIN servers s ON s.id=mu.server_id
            WHERE mu.vodum_user_id=u.id AND LOWER(COALESCE(s.type, ''))='jellyfin'
              AND (LOWER(COALESCE(mu.role, ''))='admin'
                OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator":true%'
                OR COALESCE(mu.raw_json, '') LIKE '%"IsAdministrator": true%')
          ) THEN 'Admin'
          ELSE NULL
        END
    """
    query = f"""
        SELECT {USER_LIST_COLUMNS}, st.name AS subscription_name,
          {role_sql} AS subscription_role_label,
          COALESCE({role_sql}, st.name) AS subscription_sort_label,
          (SELECT COUNT(DISTINCT mu.server_id) FROM media_users mu
           WHERE mu.vodum_user_id=u.id) AS servers_count,
          (SELECT COUNT(DISTINCT mul.library_id) FROM media_users mu
           JOIN media_user_libraries mul ON mul.media_user_id=mu.id
           WHERE mu.vodum_user_id=u.id) AS libraries_count
        FROM vodum_users u
        LEFT JOIN subscription_templates st ON st.id=u.subscription_template_id
    """

    conditions = []
    params = []

    if status_none_requested:
        conditions.append("1 = 0")
    elif selected_statuses:
        placeholders = ",".join(["?"] * len(selected_statuses))
        conditions.append(f"u.status IN ({placeholders})")
        params.extend(selected_statuses)

    if search:
        like = f"%{search}%"
        conditions.append(
            "("
            "COALESCE(u.username,'') LIKE ? OR "
            "COALESCE(u.email,'') LIKE ? OR "
            "COALESCE(u.second_email,'') LIKE ? OR "
            "COALESCE(u.phone,'') LIKE ? OR "
            "COALESCE(u.firstname,'') LIKE ? OR "
            "COALESCE(u.lastname,'') LIKE ? OR "
            "COALESCE(u.notes,'') LIKE ? OR "
            "EXISTS ("
            "   SELECT 1 FROM media_users mu_search "
            "   WHERE mu_search.vodum_user_id = u.id "
            "   AND COALESCE(mu_search.username,'') LIKE ?"
            ")"
            ")"
        )

        params.extend([
            like,  # username
            like,  # email
            like,  # second_email
            like,  # phone
            like,  # firstname
            like,  # lastname
            like,  # notes
            like,  # media_users.username
        ])

    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_sql = f"""
        ORDER BY
            CASE
                WHEN u.status IN ('active', 'pre_expired', 'reminder') THEN 0
                ELSE 1
            END ASC,

            CASE
                WHEN {sort_column} IS NULL OR {sort_column} = '' THEN 1
                ELSE 0
            END ASC,

            {sort_column} {order.upper()},
            LOWER(COALESCE(u.username, '')) ASC,
            u.id ASC
    """
    page_first = sort_column.startswith("u.")
    if page_first:
        query = (
            f"WITH selected_users AS (SELECT u.* FROM vodum_users u {where_sql} "
            f"{order_sql} LIMIT ? OFFSET ?) "
            + query.replace("FROM vodum_users u", "FROM selected_users u")
            + order_sql
        )
    else:
        query += where_sql + order_sql + " LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    count_query = """
        SELECT COUNT(*) as total FROM vodum_users u
    """
    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)

    count_params = params[:-2]
    total_row = db.query_one(count_query, count_params) or {"total": 0}
    total_users = int(total_row["total"] or 0)
    pagination = page_bounds(page, per_page, total_users)
    total_pages = pagination["total_pages"]

    if page > total_pages:
        page = total_pages
        offset = (page - 1) * per_page
        params = count_params + [per_page, offset]

    users = db.query(query, params) or []
    return users, total_users, total_pages, page
