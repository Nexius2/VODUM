#!/usr/bin/env python3
"""
expired_subscription_manager.py
-------------------------------
Mode B (settings.expiry_mode = 'warn_then_disable')

Objectifs:
- À l'expiration : créer une policy system-managed "Subscription expired" (scope=user)
  => max_streams_per_user = 0 + message
- Si renouvellement : supprimer cette policy
- Après X jours (settings.warn_then_disable_days, min 1) : désactiver les accès
  (Plex + Jellyfin) exactement comme disable_expired_users
- Nettoyer les policies système orphelines (user supprimé)

NOTE:
- La policy est "read-only" côté UI (enforced dans app.py)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Dict, Any, Optional, Set, Tuple

from tasks_engine import task_logs
from logging_utils import get_logger

log = get_logger("expired_subscription_manager")

SYSTEM_TAG = "expired_subscription"


def _parse_date(d: Optional[str]) -> Optional[date]:
    """
    Accepte:
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DDTHH:MM:SS'
      - 'YYYY-MM-DD HH:MM:SS'
      - 'DD/MM/YYYY'
    """
    if not d:
        return None

    s = str(d).strip()
    if not s:
        return None

    # ISO datetime -> garder uniquement la date
    if "T" in s:
        s = s.split("T", 1)[0].strip()
    if " " in s:
        # ex: '2026-04-11 00:00:00'
        s = s.split(" ", 1)[0].strip()

    # format FR
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3:
            dd, mm, yyyy = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            try:
                return date.fromisoformat(f"{yyyy}-{mm}-{dd}")
            except Exception:
                return None

    try:
        return date.fromisoformat(s)
    except Exception:
        return None



def _policy_rule(title: str, text: str) -> Dict[str, Any]:
    return {
        "selector": "kill_newest",
        "warn_title": title,
        "warn_text": text,
        "max": 0,
        "allow_local_ip": False,
        "system_tag": SYSTEM_TAG,
    }


def _get_settings(db) -> Dict[str, Any]:
    row = db.query_one("SELECT expiry_mode, warn_then_disable_days FROM settings WHERE id = 1")
    if not row:
        return {"expiry_mode": "none", "warn_then_disable_days": 7}

    r = dict(row)

    mode = (r.get("expiry_mode") or "none").strip()
    if mode not in ("none", "disable", "warn_then_disable"):
        mode = "none"

    try:
        days = int(r.get("warn_then_disable_days") or 7)
    except Exception:
        days = 7

    if days < 1:
        days = 1

    return {"expiry_mode": mode, "warn_then_disable_days": days}



def _find_system_policy_id(db, vodum_user_id: int) -> Optional[int]:
    rows = db.query(
        """
        SELECT id, rule_value_json
        FROM stream_policies
        WHERE scope_type='user' AND scope_id=?
        ORDER BY id DESC
        """,
        (vodum_user_id,),
    )
    for r in rows:
        try:
            rule = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rule = {}
        if rule.get("system_tag") == SYSTEM_TAG:
            return int(r["id"])
    return None


def _create_system_policy(db, vodum_user_id: int) -> int:
    title = "Subscription expired"
    text = "Your subscription has ended. Please renew to restore access."
    rule = _policy_rule(title, text)

    db.execute(
        """
        INSERT INTO stream_policies(
            scope_type, scope_id,
            provider, server_id,
            is_enabled, priority,
            rule_type, rule_value_json
        )
        VALUES (
            'user', ?,
            NULL, NULL,
            1, 1,
            'max_streams_per_user', ?
        )
        """,
        (vodum_user_id, json.dumps(rule)),
    )

    # Ensure stream_enforcer is enabled
    db.execute(
        """
        UPDATE tasks
        SET enabled = 1,
            status = CASE WHEN status='disabled' THEN 'idle' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE name = 'stream_enforcer'
        """
    )

    row = db.query_one("SELECT last_insert_rowid() AS id")
    return int(row["id"]) if row else 0


def _delete_policy(db, policy_id: int) -> None:
    db.execute("DELETE FROM stream_policies WHERE id=?", (policy_id,))


def _disable_access_for_user(db, vodum_user_id: int) -> Tuple[int, int]:
    """
    Disable access (Plex + Jellyfin) for a single vodum_user.
    Returns: (media_accounts_processed, jobs_created)
    """
    rows = db.query(
        """
        SELECT DISTINCT
            mu.id        AS media_user_id,
            mu.server_id AS server_id,
            mu.type      AS provider
        FROM media_users mu
        JOIN servers s_mu ON s_mu.id = mu.server_id
        JOIN media_user_libraries mul ON mul.media_user_id = mu.id
        JOIN libraries l ON l.id = mul.library_id
        JOIN servers s_lib ON s_lib.id = l.server_id
        WHERE mu.vodum_user_id = ?
          AND mu.type IN ('plex','jellyfin')
          AND s_mu.type = mu.type
          AND s_lib.type = mu.type
        """,
        (vodum_user_id,),
    )

    processed_media = 0
    created_jobs = 0

    for r in rows:
        media_user_id = int(r["media_user_id"])
        server_id = int(r["server_id"])
        provider = (r["provider"] or "").strip()

        # Delete libraries for this server only
        db.execute(
            """
            DELETE FROM media_user_libraries
            WHERE media_user_id = ?
              AND library_id IN (SELECT id FROM libraries WHERE server_id = ?)
            """,
            (media_user_id, server_id),
        )
        processed_media += 1

        action = "revoke" if provider == "plex" else "sync"
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

    return processed_media, created_jobs


def _cleanup_orphan_system_policies(db) -> int:
    users = db.query("SELECT id FROM vodum_users") or []
    existing_ids: Set[int] = {int(r["id"]) for r in users}

    rows = db.query(
        "SELECT id, scope_id, rule_value_json FROM stream_policies WHERE scope_type='user'"
    ) or []

    removed = 0
    for r in rows:
        try:
            rule = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rule = {}
        if rule.get("system_tag") != SYSTEM_TAG:
            continue

        try:
            vuid = int(r["scope_id"])
        except Exception:
            vuid = None

        if vuid is None or vuid not in existing_ids:
            _delete_policy(db, int(r["id"]))
            removed += 1

    return removed


def run(task_id: int, db) -> None:
    settings = _get_settings(db)
    if settings["expiry_mode"] != "warn_then_disable":
        return


    task_logs(task_id, "info", "Task expired_subscription_manager started")
    log.info("=== EXPIRED SUBSCRIPTION MANAGER : START ===")

    settings = _get_settings(db)
    if settings["expiry_mode"] != "warn_then_disable":
        msg = "expiry_mode != warn_then_disable, nothing to do."
        log.info(msg)
        task_logs(task_id, "info", msg)
        return

    today = date.today()
    delay_days = int(settings["warn_then_disable_days"])

    try:
        removed_orphans = _cleanup_orphan_system_policies(db)
        if removed_orphans:
            task_logs(task_id, "info", f"Cleaned {removed_orphans} orphan system policies.")

        users = db.query(
            """
            SELECT id, username, expiration_date
            FROM vodum_users
            WHERE expiration_date IS NOT NULL
            """
        ) or []

        created = 0
        removed = 0
        disabled_users = 0
        jobs_created_total = 0

        for u in users:
            vodum_user_id = int(u["id"])
            exp = _parse_date(u["expiration_date"])

            # Si la date est invalide/inparsible, on considère que l'user n'est PAS expiré,
            # et surtout on évite de laisser une policy "expired_subscription" collée.
            if not exp:
                if policy_id:
                    _delete_policy(db, policy_id)
                    removed += 1
                continue


            policy_id = _find_system_policy_id(db, vodum_user_id)

            if exp >= today:
                # renewed (or not expired yet) => remove system policy if any
                if policy_id:
                    _delete_policy(db, policy_id)
                    removed += 1
                continue

            # expired => ensure policy exists
            if not policy_id:
                _create_system_policy(db, vodum_user_id)
                created += 1

            # after delay => disable access + remove policy
            days_since = (today - exp).days
            if days_since >= delay_days:
                _, created_jobs = _disable_access_for_user(db, vodum_user_id)
                jobs_created_total += created_jobs

                policy_id2 = _find_system_policy_id(db, vodum_user_id)
                if policy_id2:
                    _delete_policy(db, policy_id2)
                    removed += 1

                disabled_users += 1

        msg = (
            f"expired_subscription_manager done: "
            f"policies_created={created}, policies_removed={removed}, "
            f"users_disabled={disabled_users}, jobs_created={jobs_created_total}, "
            f"delay_days={delay_days}"
        )
        log.info(msg)
        task_logs(task_id, "success", msg)

    except Exception as e:
        log.error("Error in expired_subscription_manager", exc_info=True)
        task_logs(task_id, "error", f"Error expired_subscription_manager : {e}")
        raise

    finally:
        log.info("=== EXPIRED SUBSCRIPTION MANAGER : END ===")
