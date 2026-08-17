"""Reconcile Jellyfin credential delivery with the Communications queue."""

from __future__ import annotations

import json


def _json_dict(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _payload_without_password(raw) -> str:
    payload = _json_dict(raw)
    payload.pop("temporary_password", None)
    return json.dumps(payload, ensure_ascii=False)


def complete_credentials_delivery(db, job_key: str, *, channels: str) -> None:
    row = db.query_one(
        "SELECT payload_json FROM comm_scheduled WHERE dedupe_key=? LIMIT 1",
        (str(job_key),),
    )
    if not row:
        return
    payload_json = dict(row).get("payload_json")
    db.execute(
        """
        UPDATE comm_scheduled
        SET status='sent', payload_json=?, channels_sent=?, last_error=NULL,
            next_attempt_at=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE dedupe_key=?
        """,
        (_payload_without_password(payload_json), str(channels), str(job_key)),
    )


def expire_credentials_delivery(db, job_key: str) -> None:
    row = db.query_one(
        "SELECT payload_json FROM comm_scheduled WHERE dedupe_key=? LIMIT 1",
        (str(job_key),),
    )
    if not row:
        return
    payload_json = dict(row).get("payload_json")
    db.execute(
        """
        UPDATE comm_scheduled
        SET status='error', payload_json=?, last_error='Migration credentials expired',
            attempt_count=max_attempts, next_attempt_at=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE dedupe_key=?
        """,
        (_payload_without_password(payload_json), str(job_key)),
    )


def reconcile_credentials_delivery(db) -> int:
    updated = 0
    try:
        rows = db.query(
            """SELECT id, result_json FROM migration_users
            WHERE result_json LIKE '%credentials_delivery_job_key%'"""
        ) or []
    except Exception:
        return 0

    for raw in rows:
        migration_user = dict(raw)
        result = _json_dict(migration_user.get("result_json"))
        job_key = str(result.get("credentials_delivery_job_key") or "").strip()
        if not job_key or result.get("credentials_delivered_at"):
            continue
        try:
            scheduled = db.query_one(
                """
                SELECT status, last_error, attempt_count, max_attempts,
                       next_attempt_at, channels_sent, updated_at, payload_json
                FROM comm_scheduled
                WHERE dedupe_key = ?
                LIMIT 1
                """,
                (job_key,),
            )
        except Exception:
            continue
        if not scheduled:
            continue
        delivery = dict(scheduled)
        status = str(delivery.get("status") or "pending").strip().lower()
        attempts = int(delivery.get("attempt_count") or 0)
        max_attempts = max(1, int(delivery.get("max_attempts") or 10))
        final_error = status == "error" and (
            attempts >= max_attempts or not delivery.get("next_attempt_at")
        )
        public_status = "failed" if final_error else "retrying" if status == "error" else status
        changed = result.get("credentials_delivery_status") != public_status
        result["credentials_delivery_status"] = public_status

        if status == "sent":
            complete_credentials_delivery(
                db,
                job_key,
                channels=str(delivery.get("channels_sent") or ""),
            )
            result["credentials_delivered_at"] = str(delivery.get("updated_at") or "")
            result["credentials_delivery_channels"] = str(delivery.get("channels_sent") or "")
            result["credentials_pending_delivery"] = False
            result.pop("encrypted_generated_password", None)
            result.pop("credentials_delivery_error", None)
            changed = True
        elif final_error:
            failed_at = result.get("credentials_delivery_failed_at") or str(delivery.get("updated_at") or "")
            error = str(delivery.get("last_error") or "")
            if result.get("credentials_delivery_failed_at") != failed_at:
                result["credentials_delivery_failed_at"] = failed_at
                changed = True
            if result.get("credentials_delivery_error") != error:
                result["credentials_delivery_error"] = error
                changed = True
            if result.get("credentials_pending_delivery") is not False:
                result["credentials_pending_delivery"] = False
                changed = True

        if not changed:
            continue
        db.execute(
            "UPDATE migration_users SET result_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result, ensure_ascii=False), int(migration_user["id"])),
        )
        updated += 1
    return updated
