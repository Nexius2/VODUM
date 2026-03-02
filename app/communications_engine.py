from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from logging_utils import get_logger
from notifications_utils import effective_notifications_order, is_email_ready
from discord_utils import enrich_discord_settings, is_discord_ready, send_discord_dm, DiscordSendError
from email_sender import send_email

log = get_logger("communications_engine")


DEFAULT_ATTACHMENTS_DIR = os.environ.get("COMM_ATTACHMENTS_DIR", "/appdata/attachments/communications")


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _as_dict(row_or_dict):
    if row_or_dict is None:
        return {}
    if isinstance(row_or_dict, dict):
        return row_or_dict
    try:
        return dict(row_or_dict)
    except Exception:
        return {}


@dataclass
class SendAttempt:
    channel: str  # 'email'|'discord'
    status: str   # 'sent'|'failed'
    error: Optional[str] = None


def available_channels(db, settings: Dict, user: Dict) -> Dict[str, bool]:
    """Return channel availability for this user given current settings."""
    s = _as_dict(settings)
    u = _as_dict(user)

    # Email
    email_ok = is_email_ready(s)
    user_email_ok = bool((u.get("email") or "").strip() or (u.get("second_email") or "").strip())

    # Discord
    s = enrich_discord_settings(db, s) if db is not None else s
    discord_ok = is_discord_ready(s)
    user_discord_ok = bool((u.get("discord_user_id") or "").strip())

    return {
        "email": bool(email_ok and user_email_ok),
        "discord": bool(discord_ok and user_discord_ok),
    }


def store_uploads(kind: str, object_id: int, files) -> List[Dict]:
    """Save Werkzeug FileStorage list to filesystem.

    Returns a list of attachments dicts: {filename, mime_type, path}

    kind: 'template'|'campaign'
    object_id: template_id or campaign_id
    files: request.files.getlist('attachments')
    """
    saved: List[Dict] = []
    base = Path(DEFAULT_ATTACHMENTS_DIR) / kind / str(object_id)
    _ensure_dir(base)

    for f in files or []:
        try:
            if not f or not getattr(f, "filename", ""):
                continue
            original = (f.filename or "").strip()
            # keep it simple: no external deps; remove path separators
            original = original.replace("/", "_").replace("\\", "_")
            if not original:
                continue

            fname = f"{_now_ts()}__{original}"
            full = base / fname
            f.save(str(full))

            saved.append({
                "filename": original,
                "mime_type": getattr(f, "content_type", None) or None,
                "path": str(full),
            })
        except Exception:
            log.error("Failed to store attachment", exc_info=True)
            continue

    return saved


def fetch_template_attachments(db, template_id: int) -> List[Dict]:
    rows = db.query(
        "SELECT filename, mime_type, path FROM comm_template_attachments WHERE template_id = ? ORDER BY id",
        (template_id,),
    )
    return [dict(r) for r in (rows or [])]


def fetch_campaign_attachments(db, campaign_id: int) -> List[Dict]:
    rows = db.query(
        "SELECT filename, mime_type, path FROM comm_campaign_attachments WHERE campaign_id = ? ORDER BY id",
        (campaign_id,),
    )
    return [dict(r) for r in (rows or [])]


def _normalize_send_mode(settings: Dict) -> str:
    mode = (settings or {}).get("notifications_send_mode")
    mode = (mode or "first").strip().lower()
    if mode not in ("first", "all"):
        mode = "first"
    return mode


def send_to_user(
    *,
    db,
    settings: Dict,
    user: Dict,
    subject: str,
    body: str,
    attachments: List[Dict] | None,
) -> List[SendAttempt]:
    """Send according to unified rules (FIRST / ALL).

    Returns the list of attempts (one per channel that was tried).
    """
    s = _as_dict(settings)
    u = _as_dict(user)

    mode = _normalize_send_mode(s)
    avail = available_channels(db, s, u)

    # Order: user override (if allowed) else global
    order = effective_notifications_order(s, u)

    # In ALL mode, we send on all available channels.
    channels_to_try: List[str] = []
    if mode == "all":
        # deterministic: follow the effective order, but include any other supported channels at the end
        for ch in order:
            if avail.get(ch):
                channels_to_try.append(ch)
        for ch in ("email", "discord"):
            if ch not in channels_to_try and avail.get(ch):
                channels_to_try.append(ch)
    else:
        # FIRST: first available in order
        for ch in order:
            if avail.get(ch):
                channels_to_try = [ch]
                break

    attempts: List[SendAttempt] = []

    # enrich discord token once
    s2 = enrich_discord_settings(db, s) if db is not None else s

    for ch in channels_to_try:
        if ch == "email":
            recipients: List[str] = []
            for r in ((u.get("email") or "").strip(), (u.get("second_email") or "").strip()):
                if r and r not in recipients:
                    recipients.append(r)

            if not recipients:
                attempts.append(SendAttempt(channel="email", status="failed", error="User has no email"))
                continue

            ok_any = False
            errors: List[str] = []
            for r in recipients:
                ok, err = send_email(subject, body, r, s2, attachments=attachments or [])
                if ok:
                    ok_any = True
                elif err:
                    errors.append(f"{r}: {err}")

            if ok_any:
                attempts.append(SendAttempt(channel="email", status="sent", error=None if not errors else "; ".join(errors)[:1000]))
            else:
                attempts.append(SendAttempt(channel="email", status="failed", error=("; ".join(errors) or "Email send failed")[:1000]))

        elif ch == "discord":
            discord_user_id = (u.get("discord_user_id") or "").strip()
            token = (s2.get("discord_bot_token_effective") or s2.get("discord_bot_token") or "").strip()
            if not discord_user_id:
                attempts.append(SendAttempt(channel="discord", status="failed", error="User has no discord_user_id"))
                continue

            # Attachments on Discord DM: not supported in current implementation.
            # We still send the textual message and keep trace in meta_json.
            try:
                send_discord_dm(token, discord_user_id, body)
                attempts.append(SendAttempt(channel="discord", status="sent", error=None))
            except DiscordSendError as e:
                attempts.append(SendAttempt(channel="discord", status="failed", error=str(e)[:1000]))
            except Exception as e:
                attempts.append(SendAttempt(channel="discord", status="failed", error=str(e)[:1000]))

    return attempts


def record_history(
    *,
    db,
    kind: str,
    template_id: Optional[int],
    campaign_id: Optional[int],
    user_id: Optional[int],
    attempt: SendAttempt,
    sent_at: Optional[str] = None,
    meta: Optional[Dict] = None,
) -> None:
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    db.execute(
        """
        INSERT INTO comm_history(kind, template_id, campaign_id, user_id, channel_used, status, error, sent_at, meta_json)
        VALUES(?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?)
        """,
        (
            kind,
            template_id,
            campaign_id,
            user_id,
            attempt.channel,
            attempt.status,
            attempt.error,
            sent_at,
            meta_json,
        ),
    )
