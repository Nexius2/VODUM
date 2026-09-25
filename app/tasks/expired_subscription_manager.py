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
from typing import Dict, Any, Set, Tuple

from tasks_engine import task_logs
from logging_utils import get_logger
from core.expiration_rules import parse_expiration_date, eligible_expiration_accounts
from core.media_jobs import insert_plex_media_job, insert_jellyfin_media_job

log = get_logger("expired_subscription_manager")

SYSTEM_TAG = "expired_subscription"


_parse_date = parse_expiration_date


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
    if mode not in ("none", "warn_only", "warn_then_disable", "disable"):
        mode = "none"

    try:
        days = int(r.get("warn_then_disable_days") or 7)
    except Exception:
        days = 7

    if days < 1:
        days = 1

    return {"expiry_mode": mode, "warn_then_disable_days": days}



def _create_system_policy(db, vodum_user_id: int, account_ids) -> int:
    title = "Subscription expired"
    text = "Your subscription has ended. Please renew to restore access."
    rule = _policy_rule(title, text)
    rule["expiration_media_user_ids"] = sorted(account_ids)

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


def _sync_system_policy(db, user_id, account_ids):
    rows = db.query("SELECT id,rule_value_json FROM stream_policies WHERE scope_type='user' AND scope_id=? ORDER BY id", (user_id,)) or []
    owned = []
    for row in rows:
        try:
            rule = json.loads(row["rule_value_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(rule, dict) and rule.get("system_tag") == SYSTEM_TAG:
            owned.append((row, rule))
    if not account_ids:
        for row, _ in owned:
            _delete_policy(db, int(row["id"]))
        return 0, len(owned)
    if not owned:
        _create_system_policy(db, user_id, account_ids)
        return 1, 0
    row, rule = owned[0]
    if rule.get("expiration_media_user_ids") != sorted(account_ids):
        rule["expiration_media_user_ids"] = sorted(account_ids)
        db.execute("UPDATE stream_policies SET rule_value_json=? WHERE id=?", (json.dumps(rule), row["id"]))
    for duplicate, _ in owned[1:]:
        _delete_policy(db, int(duplicate["id"]))
    return 0, len(owned) - 1


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
          AND l.server_id = mu.server_id
          AND LOWER(TRIM(mu.type)) IN ('plex','jellyfin')
          AND LOWER(TRIM(s_mu.type)) = LOWER(TRIM(mu.type))
          AND LOWER(TRIM(s_lib.type)) = LOWER(TRIM(mu.type))
        """,
        (vodum_user_id,),
    )

    eligible_ids = {int(a["id"]) for a in eligible_expiration_accounts(db, vodum_user_id)}
    processed_media = 0
    created_jobs = 0

    for r in rows:
        media_user_id = int(r["media_user_id"])
        if media_user_id not in eligible_ids:
            continue
        server_id = int(r["server_id"])
        provider = (r["provider"] or "").strip().lower()

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

        payload = {
            "reason": "expired_subscription_manager",
            "vodum_user_id": vodum_user_id,
            "media_user_id": media_user_id,
        }

        if provider == "plex":
            action = "revoke"
            dedupe_key = f"plex:revoke:server={server_id}:vodum_user={vodum_user_id}"

            inserted = insert_plex_media_job(
                db,
                action=action,
                vodum_user_id=vodum_user_id,
                server_id=server_id,
                library_id=None,
                dedupe_key=dedupe_key,
                payload=payload,
                cancel_reason="Canceled because expired_subscription_manager queued a newer Plex revoke job",
            )
        else:
            action = "sync"
            dedupe_key = f"jellyfin:sync:server={server_id}:vodum_user={vodum_user_id}"

            inserted = insert_jellyfin_media_job(
                db,
                action=action,
                vodum_user_id=vodum_user_id,
                server_id=server_id,
                library_id=None,
                dedupe_key=dedupe_key,
                payload=payload,
                cancel_reason="Canceled because expired_subscription_manager queued a newer Jellyfin sync job",
            )

        if inserted:
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
        if not isinstance(rule, dict) or rule.get("system_tag") != SYSTEM_TAG:
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
    if settings["expiry_mode"] not in ("warn_only", "warn_then_disable"):
        return


    task_logs(task_id, "start", "Task expired_subscription_manager started")
    log.debug("=== EXPIRED SUBSCRIPTION MANAGER : START ===")

    settings = _get_settings(db)
    if settings["expiry_mode"] not in ("warn_only", "warn_then_disable"):
        msg = "expiry_mode is not warn_only or warn_then_disable, nothing to do."
        log.debug(msg)
        task_logs(task_id, "debug", msg)
        return

    today = date.today()
    delay_days = int(settings["warn_then_disable_days"])

    try:
        removed_orphans = _cleanup_orphan_system_policies(db)
        if removed_orphans:
            task_logs(task_id, "success", f"Cleaned {removed_orphans} orphan system policies.")

        users = db.query(
            """
            SELECT id, username, expiration_date
            FROM vodum_users
            """
        ) or []

        created = 0
        removed = 0
        disabled_users = 0
        jobs_created_total = 0

        for u in users:
            vodum_user_id = int(u["id"])

            exp = _parse_date(u["expiration_date"])
            account_ids = []
            if exp and exp < today:
                account_ids = [int(a["id"]) for a in eligible_expiration_accounts(db, vodum_user_id)]
            added, cleared = _sync_system_policy(db, vodum_user_id, account_ids)
            created += added
            removed += cleared
            if not account_ids:
                continue

            # warn_only = keep the expired_subscription policy forever until renewal.
            # warn_then_disable = keep the warning for X days, then hard revoke access.
            if settings["expiry_mode"] != "warn_then_disable":
                continue

            days_since = (today - exp).days
            if days_since >= delay_days:
                _, created_jobs = _disable_access_for_user(db, vodum_user_id)
                jobs_created_total += created_jobs

                _, cleared = _sync_system_policy(db, vodum_user_id, [])
                removed += cleared

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
