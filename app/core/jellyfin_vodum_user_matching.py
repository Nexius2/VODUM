def is_placeholder_vodum_user(user: dict) -> bool:
    if not user:
        return True
    return (
        not (user.get("email") or "").strip()
        and not (user.get("firstname") or "").strip()
        and not (user.get("lastname") or "").strip()
        and user.get("expiration_date") is None
        and not (user.get("notes") or "").strip()
    )


def pick_best_vodum_user_for_username(db, username: str) -> int | None:
    if not username or not str(username).strip():
        return None
    rows = db.query(
        """
        SELECT id, username, firstname, lastname, email, expiration_date, notes, status
        FROM vodum_users
        WHERE lower(username) = lower(?)
        ORDER BY
          CASE WHEN email IS NOT NULL AND trim(email) <> '' THEN 1 ELSE 0 END DESC,
          CASE WHEN expiration_date IS NOT NULL THEN 1 ELSE 0 END DESC,
          CASE WHEN firstname IS NOT NULL AND trim(firstname) <> '' THEN 1 ELSE 0 END DESC,
          CASE WHEN lastname IS NOT NULL AND trim(lastname) <> '' THEN 1 ELSE 0 END DESC,
          id ASC
        """,
        (str(username).strip(),),
    )
    return int(rows[0]["id"]) if rows else None
