"""Provider credential operations kept outside web routes."""

from __future__ import annotations

from core.providers.jellyfin_users import jellyfin_set_password
from logging_utils import get_logger


log = get_logger("user_credentials")


def change_jellyfin_password(db, user_id: int, password: str, server_ids: set[int] | None = None) -> dict:
    clean_password = str(password or "").strip()
    if not clean_password:
        raise ValueError("missing_password")
    selected = {int(value) for value in (server_ids or set())}
    rows = db.query(
        """
        SELECT mu.id,mu.server_id,mu.external_user_id,mu.username,
               s.name AS server_name,s.url,s.local_url,s.public_url,s.token AS token
        FROM media_users mu
        JOIN servers s ON s.id=mu.server_id
        WHERE mu.vodum_user_id=? AND mu.type='jellyfin' AND s.type='jellyfin'
        """,
        (int(user_id),),
    ) or []
    if selected:
        rows = [row for row in rows if int(row["server_id"]) in selected]

    updated = 0
    errors = []
    for raw in rows:
        account = dict(raw)
        try:
            external_user_id = str(account.get("external_user_id") or "").strip()
            if not external_user_id:
                raise ValueError("Jellyfin account has no native identifier.")
            jellyfin_set_password(account, external_user_id, clean_password)
            db.execute("UPDATE media_users SET stored_password=NULL WHERE id=?", (int(account["id"]),))
            updated += 1
            log.info(
                "[JELLYFIN PASSWORD] Updated password vodum_user_id=%s server_id=%s username=%s",
                user_id, account["server_id"], account.get("username"),
            )
        except Exception as exc:
            errors.append(f"{account.get('server_name') or account['server_id']}: {exc}")
            log.error(
                "[JELLYFIN PASSWORD] Failed vodum_user_id=%s server_id=%s username=%s error=%s",
                user_id, account["server_id"], account.get("username"), exc,
            )
    return {"ok": not errors, "updated": updated, "errors": errors}
