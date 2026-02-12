#!/usr/bin/env python3
"""
disable_expired_users.py
------------------------
Mode A (settings.expiry_mode = 'disable')

✓ Désactive les accès des utilisateurs expirés (Plex + Jellyfin)
✓ Indépendant du mailing/discord
✓ Compatible multi-serveurs
✓ S'appuie sur media_user_libraries + media_jobs

Principe:
- Pour chaque vodum_user expiré, on supprime les accès en base (media_user_libraries)
- Puis on crée un media_job pour appliquer la révocation côté serveur:
  - Plex    : job action='revoke' (apply_plex_access_updates)
  - Jellyfin: job action='sync'   (apply_jellyfin_access_updates)

NB: Les comptes utilisateurs restent chez Plex/Jellyfin, seuls les accès sont retirés.
"""

from __future__ import annotations

from datetime import date
import json

from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("disable_expired_users")

SYSTEM_TAG = "expired_subscription"

def _purge_expired_subscription_policies(db) -> int:
    """
    En mode expiry_mode='disable', on ne veut AUCUNE policy de type 'expired_subscription'.
    On les purge toutes.
    """
    rows = db.query(
        "SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user'"
    ) or []

    removed = 0
    for r in rows:
        try:
            rule = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rule = {}

        if rule.get("system_tag") == SYSTEM_TAG:
            db.execute("DELETE FROM stream_policies WHERE id = ?", (int(r["id"]),))
            removed += 1

    return removed


def _get_settings(db) -> dict:
    row = db.query_one("SELECT expiry_mode FROM settings WHERE id = 1") or {}
    return dict(row)


def run(task_id: int, db):
    settings = _get_settings(db)
    mode = (settings.get("expiry_mode") or "none").strip()

    if mode != "disable":
        return

    # En mode disable, on purge les anciennes policies système éventuelles
    try:
        removed = _purge_expired_subscription_policies(db)
        if removed:
            log.info(f"Purged {removed} expired_subscription system policy(ies) (expiry_mode=disable)")
    except Exception:
        log.error("Failed to purge expired_subscription policies", exc_info=True)


    task_logs(task_id, "info", "Task disable_expired_users started")
    log.info("=== DISABLE EXPIRED USERS : START ===")

    settings = _get_settings(db)
    if (settings.get("expiry_mode") or "disable") != "disable":
        msg = "Skipped: expiry_mode is not 'disable'."
        log.info(msg)
        task_logs(task_id, "info", msg)
        return

    today = date.today()

    try:
        # 1) Select expired vodum_users that still have at least one library on at least one media account
        rows = db.query(
            """
            SELECT DISTINCT
                vu.id            AS vodum_user_id,
                vu.username      AS vodum_username,
                mu.id            AS media_user_id,
                mu.server_id     AS server_id,
                mu.type          AS provider
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            JOIN servers s_mu
                ON s_mu.id = mu.server_id
            JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
            JOIN libraries l
                ON l.id = mul.library_id
            JOIN servers s_lib
                ON s_lib.id = l.server_id
            WHERE vu.expiration_date IS NOT NULL
              AND date(vu.expiration_date) < date(?)
              AND mu.type IN ('plex','jellyfin')
              AND s_mu.type = mu.type
              AND s_lib.type = mu.type
            """,
            (today.isoformat(),),
        )

        if not rows:
            msg = "No expired users with media server access."
            log.info(msg)
            task_logs(task_id, "info", msg)
            return

        vodum_ids = sorted({r["vodum_user_id"] for r in rows})
        log.info(f"{len(vodum_ids)} Expired user(s) to disable")

        processed_media = 0
        created_jobs = 0

        for r in rows:
            vodum_user_id = int(r["vodum_user_id"])
            vodum_username = r["vodum_username"]
            media_user_id = int(r["media_user_id"])
            server_id = int(r["server_id"])
            provider = (r["provider"] or "").strip().lower()

            log.info(
                f"[VODUM #{vodum_user_id}] Removing access from database "
                f"(provider={provider}, media_user_id={media_user_id}, server_id={server_id}, user={vodum_username})"
            )

            # Delete only libraries for THIS server
            db.execute(
                """
                DELETE FROM media_user_libraries
                WHERE media_user_id = ?
                  AND library_id IN (SELECT id FROM libraries WHERE server_id = ?)
                """,
                (media_user_id, server_id),
            )

            processed_media += 1

            # Create a deduped job to apply on provider side
            if provider == "plex":
                action = "revoke"
            else:
                # Jellyfin worker applies desired folders; any action triggers sync
                action = "sync"

            dedupe_key = f"{provider}:{action}:server={server_id}:vodum_user={vodum_user_id}"

            exists = db.query_one(
                """
                SELECT 1
                FROM media_jobs
                WHERE provider = ?
                  AND action = ?
                  AND server_id = ?
                  AND vodum_user_id = ?
                  AND library_id IS NULL
                  AND processed = 0
                LIMIT 1
                """,
                (provider, action, server_id, vodum_user_id),
            )

            if not exists:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_jobs(
                        provider, action,
                        vodum_user_id, server_id, library_id,
                        payload_json,
                        processed, success, attempts,
                        dedupe_key
                    )
                    VALUES (
                        ?, ?,
                        ?, ?, NULL,
                        NULL,
                        0, 0, 0,
                        ?
                    )
                    """,
                    (provider, action, vodum_user_id, server_id, dedupe_key),
                )
                created_jobs += 1

        msg = (
            f"{len(vodum_ids)} user(s) disabled "
            f"(media accounts processed={processed_media}, jobs created={created_jobs})"
        )
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        log.error("Error in disable_expired_users", exc_info=True)
        task_logs(task_id, "error", f"Error disable_expired_users : {e}")
        raise

    finally:
        log.info("=== DISABLE EXPIRED USERS : END ===")
