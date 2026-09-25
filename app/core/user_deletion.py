"""Local deletion shared by manual and confirmed native deletion workflows."""


def delete_local_user(cursor, user_id: int) -> bool:
    if cursor.execute("SELECT id FROM vodum_users WHERE id=?", (user_id,)).fetchone() is None:
        return False
    cursor.execute("DELETE FROM stream_policies WHERE scope_type='user' AND scope_id=?", (user_id,))
    for table in ("subscription_gift_run_users", "stream_enforcement_state", "stream_enforcements"):
        cursor.execute(f"DELETE FROM {table} WHERE vodum_user_id=?", (user_id,))
    cursor.execute("DELETE FROM media_users WHERE vodum_user_id=?", (user_id,))
    cursor.execute("DELETE FROM vodum_users WHERE id=?", (user_id,))
    return True
