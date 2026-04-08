import json
import re
import traceback
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import smtplib
import os
from flask import Blueprint, jsonify, request, g

from db_manager import DBManager
from logging_utils import get_logger
from mailing_utils import build_user_context, render_mail
from email_layout_utils import build_email_parts

from core.providers.jellyfin_users import (
    jellyfin_create_user,
    jellyfin_set_password,
    jellyfin_set_policy_folders,
    jellyfin_reset_password_required,
)
from communications_engine import (
    send_to_user,
    fetch_template_attachments,
    record_history,
    schedule_template_notification,
    select_comm_template_for_user,
)
from core.providers.plex_users import plex_invite_and_share
from tasks_engine import auto_enable_stream_enforcer

log = get_logger("users_create")

users_bp = Blueprint("users_bp", __name__)


def get_db() -> DBManager:
    if "db" not in g:
        g.db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
    return g.db


def is_smtp_ready(settings_row) -> bool:
    """Retourne True si l'envoi mail est correctement configuré.

    Cette fonction est volontairement tolérante :
    - accepte dict
    - accepte sqlite3.Row (ou tout mapping) => conversion dict(...)
    """
    if not settings_row:
        return False

    if not isinstance(settings_row, dict):
        try:
            settings_row = dict(settings_row)
        except Exception:
            return False

    if not settings_row.get("mailing_enabled"):
        return False

    if not (settings_row.get("smtp_host") and (settings_row.get("smtp_user") or settings_row.get("mail_from"))):
        return False

    return True


def send_email_via_settings(settings: Dict[str, Any], to_email: str, subject: str, body: str) -> bool:
    smtp_host = settings.get("smtp_host")
    smtp_port = settings.get("smtp_port") or 587
    smtp_tls = bool(settings.get("smtp_tls"))
    smtp_user = settings.get("smtp_user")
    smtp_pass = settings.get("smtp_pass") or ""
    mail_from = settings.get("mail_from") or smtp_user

    if not smtp_host or not mail_from or not to_email:
        return False

    try:
        smtp_port = int(smtp_port)
    except Exception:
        smtp_port = 587

    plain, full_html = build_email_parts(body, settings)

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.set_content(plain, subtype="plain", charset="utf-8")
    msg.add_alternative(full_html, subtype="html", charset="utf-8")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if smtp_tls:
            server.starttls()
        if smtp_user:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    return True


def get_welcome_template(db: DBManager, provider: str, server_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one(
        """
        SELECT * FROM welcome_email_templates
        WHERE provider = ? AND server_id = ?
        LIMIT 1
        """,
        (provider, server_id),
    )
    if row:
        return dict(row)

    row = db.query_one(
        """
        SELECT * FROM welcome_email_templates
        WHERE provider = ? AND server_id IS NULL
        LIMIT 1
        """,
        (provider,),
    )
    return dict(row) if row else None


def _iso_date_or_none(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw:
        return None

    # 1) Formats "classiques"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except Exception:
            pass

    # 2) Tolérance: YYYY-M-D (sans zéros) -> on normalise
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        try:
            return datetime.strptime(f"{y}-{mo}-{d}", "%Y-%m-%d").date().isoformat()
        except Exception:
            pass

    # 3) Tolérance: ISO datetime (ex: 2026-02-02T00:00:00Z / +01:00 / etc.)
    try:
        # On coupe à la date si jamais il y a une heure derrière
        date_part = raw.split("T", 1)[0].split(" ", 1)[0]
        m2 = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", date_part)
        if m2:
            y, mo, d = m2.group(1), m2.group(2).zfill(2), m2.group(3).zfill(2)
            return datetime.strptime(f"{y}-{mo}-{d}", "%Y-%m-%d").date().isoformat()

        return datetime.fromisoformat(raw).date().isoformat()
    except Exception:
        return None



def _valid_email(email: str) -> bool:
    email = (email or "").strip()
    if not email:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def _parse_json_list(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _delete_locked_subscription_policies(db: DBManager, vodum_user_id: int) -> None:
    rows = db.query(
        "SELECT id, rule_value_json FROM stream_policies WHERE scope_type='user' AND scope_id=?",
        (vodum_user_id,),
    ) or []

    for r in rows:
        try:
            rule_json = json.loads(r["rule_value_json"] or "{}")
        except Exception:
            rule_json = {}

        if rule_json.get("locked") and rule_json.get("subscription_name"):
            db.execute("DELETE FROM stream_policies WHERE id=?", (int(r["id"]),))


def _apply_subscription_template_snapshot(db: DBManager, vodum_user_id: int, template_id: int) -> str:
    tpl = db.query_one(
        "SELECT id, name, policies_json FROM subscription_templates WHERE id=?",
        (template_id,),
    )
    if not tpl:
        raise ValueError("Subscription template not found")

    tpl = dict(tpl)
    template_name = tpl.get("name") or ""
    policies = _parse_json_list(tpl.get("policies_json") or "[]")

    _delete_locked_subscription_policies(db, vodum_user_id)

    any_enabled = False

    for p in policies:
        if not isinstance(p, dict):
            continue

        rule_type = (p.get("rule_type") or "").strip()
        if not rule_type:
            continue

        rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
        rule = dict(rule)
        rule["locked"] = True
        rule["subscription_name"] = template_name

        provider = (p.get("provider") or "").strip() or None
        server_id = int(p["server_id"]) if str(p.get("server_id", "")).isdigit() else None
        is_enabled = 1 if str(p.get("is_enabled", "1")) == "1" else 0
        priority = int(p.get("priority") or 100)

        if is_enabled == 1:
            any_enabled = True

        db.execute(
            """
            INSERT INTO stream_policies(scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, rule_value_json)
            VALUES ('user', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vodum_user_id,
                provider,
                server_id,
                is_enabled,
                priority,
                rule_type,
                json.dumps(rule),
            ),
        )

    db.execute(
        "UPDATE vodum_users SET subscription_template_id=? WHERE id=?",
        (template_id, vodum_user_id),
    )

    if any_enabled:
        auto_enable_stream_enforcer()

    return template_name

@users_bp.get("/api/servers")
def api_servers():
    db = get_db()
    rows = db.query(
        """
        SELECT id, name, type, url, local_url, public_url, server_identifier, status, token
        FROM servers
        ORDER BY name ASC
        """
    )

    servers = [dict(r) for r in rows]

    # Group Plex servers by token (same admin/token concept in your DB)
    plex_groups = {}
    for s in servers:
        if (s.get("type") or "").lower() == "plex":
            tok = (s.get("token") or "")
            plex_groups.setdefault(tok, []).append(s)

    out = []
    for s in servers:
        d = {
            "id": s["id"],
            "name": s.get("name"),
            "type": s.get("type"),
            "url": s.get("url"),
            "local_url": s.get("local_url"),
            "public_url": s.get("public_url"),
            "server_identifier": s.get("server_identifier"),
            "status": s.get("status"),
            "linked_servers": [],
        }

        if (s.get("type") or "").lower() == "plex":
            tok = (s.get("token") or "")
            linked = [x for x in plex_groups.get(tok, []) if x["id"] != s["id"]]
            d["linked_servers"] = [{"id": x["id"], "name": x.get("name")} for x in linked]

        out.append(d)

    return jsonify(out)



@users_bp.get("/api/servers/<int:server_id>/libraries")
def api_server_libraries(server_id: int):
    db = get_db()

    server = db.query_one("SELECT id, name, type, token FROM servers WHERE id = ?", (server_id,))
    if not server:
        return jsonify([])

    server = dict(server)
    provider = (server.get("type") or "").lower()

    server_ids = [server_id]

    # Plex: include servers with same token (linked)
    if provider == "plex":
        token = server.get("token") or ""
        if token:
            linked = db.query(
                "SELECT id FROM servers WHERE type='plex' AND token = ? ORDER BY name ASC",
                (token,),
            )
            server_ids = [int(r["id"]) for r in linked] or [server_id]

    placeholders = ",".join(["?"] * len(server_ids))
    rows = db.query(
        f"""
        SELECT l.id, l.server_id, l.section_id, l.name, l.type,
               s.name AS server_name
        FROM libraries l
        JOIN servers s ON s.id = l.server_id
        WHERE l.server_id IN ({placeholders})
        ORDER BY s.name ASC, l.name ASC
        """,
        server_ids,
    )
    return jsonify([dict(r) for r in rows])

@users_bp.get("/api/users/referrer-candidates")
def api_referrer_candidates():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    like = f"%{q}%"

    rows = db.query(
        """
        SELECT
            u.id,
            u.username,
            u.email,
            u.expiration_date,
            COUNT(r.id) AS referrals_count
        FROM vodum_users u
        LEFT JOIN user_referrals r ON r.referrer_user_id = u.id
        WHERE u.status = 'active'
          AND (
                ? = ''
                OR COALESCE(u.username,'') LIKE ?
                OR COALESCE(u.email,'') LIKE ?
                OR COALESCE(u.firstname,'') LIKE ?
                OR COALESCE(u.lastname,'') LIKE ?
              )
        GROUP BY u.id
        ORDER BY u.username ASC
        LIMIT 50
        """,
        (q, like, like, like, like),
    ) or []

    return jsonify([dict(r) for r in rows])

@users_bp.post("/api/users/create")
def api_users_create():
    db = get_db()
    payload = request.get_json(silent=True) or {}
    log.info(f"[CREATE USER] payload received: keys={list(payload.keys())}")
    print(f"[CREATE USER STDOUT] payload received: keys={list(payload.keys())}", flush=True)

    email = (payload.get("email") or "").strip()
    second_email = (payload.get("second_email") or "").strip()
    username = (payload.get("username") or "").strip() or (email.split("@", 1)[0] if email else "")
    firstname = (payload.get("firstname") or "").strip()
    lastname = (payload.get("lastname") or "").strip()
    vodum_username = username or None

    # --- Dates: support aliases + parsing tolerant ---
    raw_exp = payload.get("expiration_date") or payload.get("expirationDate") or payload.get("expiration") or ""
    expiration_date = _iso_date_or_none(raw_exp)

    raw_renew = payload.get("renewal_date") or payload.get("renewalDate") or ""
    renewal_date = _iso_date_or_none(raw_renew)

    renewal_method = (payload.get("renewal_method") or payload.get("renewalMethod") or "").strip() or None

    notes = (payload.get("notes") or "").strip()

    # Fallback: if expiration date is empty, use today + default_subscription_days
    settings = db.query_one("SELECT * FROM settings WHERE id = 1")
    settings = dict(settings) if settings else {}

    if not expiration_date:
        try:
            default_days = int(settings.get("default_subscription_days") or 90)
        except Exception:
            default_days = 90

        if default_days < 1:
            default_days = 90

        expiration_date = (datetime.utcnow().date() + timedelta(days=default_days)).isoformat()

    referrer_user_id_raw = payload.get("referrer_user_id")
    referrer_user_id = None
    if referrer_user_id_raw not in (None, "", "null", "none"):
        if not str(referrer_user_id_raw).isdigit():
            return jsonify({"ok": False, "error": "Invalid referrer_user_id"}), 400
        referrer_user_id = int(referrer_user_id_raw)

        referrer = db.query_one(
            "SELECT id, username, status FROM vodum_users WHERE id = ?",
            (referrer_user_id,),
        )
        if not referrer:
            return jsonify({"ok": False, "error": "Referrer not found"}), 400

        if (referrer["status"] or "").lower() != "active":
            return jsonify({"ok": False, "error": "Referrer must be active"}), 400

    subscription_template_id_raw = payload.get("subscription_template_id")
    subscription_template_id = None
    if subscription_template_id_raw not in (None, "", "null", "none"):
        if not str(subscription_template_id_raw).isdigit():
            return jsonify({"ok": False, "error": "Invalid subscription_template_id"}), 400

        subscription_template_id = int(subscription_template_id_raw)

        tpl = db.query_one(
            "SELECT id FROM subscription_templates WHERE id = ?",
            (subscription_template_id,),
        )
        if not tpl:
            return jsonify({"ok": False, "error": "Subscription template not found"}), 400

    server_blocks = payload.get("servers") or []
    if not isinstance(server_blocks, list) or not server_blocks:
        return jsonify({"ok": False, "error": "No server selected"}), 400

    if email and not _valid_email(email):
        return jsonify({"ok": False, "error": "Invalid email"}), 400

    servers_by_id: Dict[int, Dict[str, Any]] = {}
    sent_welcome_keys = set()  # avoid duplicate welcome mails (plex linked servers)
    for block in server_blocks:
        try:
            sid = int(block.get("server_id"))
        except Exception:
            return jsonify({"ok": False, "error": "Invalid server_id"}), 400

        srv = db.query_one("SELECT * FROM servers WHERE id = ?", (sid,))
        if not srv:
            return jsonify({"ok": False, "error": f"Server not found (id={sid})"}), 400
        servers_by_id[sid] = dict(srv)

        lib_ids = block.get("library_ids") or []
        if not isinstance(lib_ids, list):
            return jsonify({"ok": False, "error": "Invalid library_ids"}), 400

        if lib_ids:
            # If Plex: allow libraries from linked servers (same token)
            srv_type = (dict(srv).get("type") or "").lower()
            allowed_server_ids = [sid]

            if srv_type == "plex":
                tok = (dict(srv).get("token") or "")
                if tok:
                    linked = db.query("SELECT id FROM servers WHERE type='plex' AND token=?", (tok,))
                    allowed_server_ids = [int(r["id"]) for r in linked] or [sid]

            placeholders_ids = ",".join(["?"] * len(lib_ids))
            placeholders_srv = ",".join(["?"] * len(allowed_server_ids))

            rows = db.query(
                f"""
                SELECT id FROM libraries
                WHERE id IN ({placeholders_ids})
                  AND server_id IN ({placeholders_srv})
                """,
                [int(x) for x in lib_ids] + [int(x) for x in allowed_server_ids],
            )

            if len(rows) != len(set([int(x) for x in lib_ids])):
                return jsonify({"ok": False, "error": "One or more libraries do not belong to the selected server or its linked Plex servers"}), 400

    initial_status = "active"
    if any((servers_by_id[int(b.get("server_id"))].get("type") or "").lower() == "plex" for b in server_blocks):
        initial_status = "invited"

    # --- INSERT: include renewal_method + renewal_date ---
    try:
        cur = db.execute(
            """
            INSERT INTO vodum_users(
                username, firstname, lastname,
                email, second_email,
                expiration_date,
                renewal_method, renewal_date,
                notes, status,
                referrer_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vodum_username,
                firstname,
                lastname,
                email or None,
                second_email or None,
                expiration_date,
                renewal_method,
                renewal_date,
                notes,
                initial_status,
                referrer_user_id,
            ),
        )
    except Exception as e:
        log.error(f"Create Vodum user failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": f"Failed to create Vodum user: {e}"}), 500
    vodum_user_id = cur.lastrowid
    log.info(f"[CREATE USER] vodum_user created id={vodum_user_id} email={email} username={vodum_username}")
    print(f"[CREATE USER STDOUT] vodum_user created id={vodum_user_id} email={email} username={vodum_username}", flush=True)
    try:
        cur.close()
    except Exception:
        pass

    if referrer_user_id is not None:
        referral_settings = db.query_one("SELECT * FROM user_referral_settings WHERE id = 1")
        referral_settings = dict(referral_settings) if referral_settings else {}

        qualification_days = int(referral_settings.get("qualification_days") or 60)
        reward_days = int(referral_settings.get("reward_days") or 60)

        db.execute(
            """
            INSERT INTO user_referrals(
                referrer_user_id,
                referred_user_id,
                status,
                referral_source,
                start_at,
                qualification_due_at,
                qualification_days_snapshot,
                reward_days_snapshot,
                created_at,
                updated_at
            )
            VALUES(
                ?, ?, 'pending', 'manual',
                CURRENT_TIMESTAMP,
                datetime('now', ?),
                ?, ?,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (
                referrer_user_id,
                int(vodum_user_id),
                f"+{qualification_days} days",
                qualification_days,
                reward_days,
            ),
        )

        referral_row = db.query_one(
            "SELECT id FROM user_referrals WHERE referred_user_id = ?",
            (int(vodum_user_id),),
        )
        if referral_row:
            db.execute(
                """
                INSERT INTO user_referral_events(
                    referral_id, event_type, actor,
                    old_referrer_user_id, new_referrer_user_id, details_json
                )
                VALUES (?, 'created', 'ui', NULL, ?, ?)
                """,
                (
                    int(referral_row["id"]),
                    referrer_user_id,
                    json.dumps({
                        "source": "create_user",
                        "referred_user_id": int(vodum_user_id),
                    }, ensure_ascii=False),
                ),
            )

    if subscription_template_id is not None:
        try:
            _apply_subscription_template_snapshot(db, int(vodum_user_id), subscription_template_id)
        except Exception as e:
            log.error(f"Apply subscription template failed for vodum_user_id={vodum_user_id}: {e}", exc_info=True)
            return jsonify({"ok": False, "error": f"Failed to apply subscription template: {e}"}), 500

    created_accounts: List[Dict[str, Any]] = []
    mailing_errors: List[str] = []
    provider_errors: List[str] = []

    settings = db.query_one("SELECT * FROM settings WHERE id = 1")
    settings = dict(settings) if settings else {}
    smtp_ok = is_smtp_ready(settings)

    for block in server_blocks:
        log.info(f"[CREATE USER] processing block: {block}")
        print(f"[CREATE USER STDOUT] processing block: {block}", flush=True)
        server_id = int(block.get("server_id"))
        server = servers_by_id[server_id]
        provider = (server.get("type") or "").lower()
        library_ids = [int(x) for x in (block.get("library_ids") or [])]

        libs = []
        if library_ids:
            placeholders = ",".join(["?"] * len(library_ids))
            libs = [dict(r) for r in db.query(
                f"""
                SELECT l.id, l.name, l.section_id, l.server_id, s.name AS server_name
                FROM libraries l
                JOIN servers s ON s.id = l.server_id
                WHERE l.id IN ({placeholders})
                """,
                library_ids,
            )]

        external_user_id: Optional[str] = None
        server_username: Optional[str] = None
        details_json: Dict[str, Any] = {}

        try:
            if provider == "jellyfin":
                existing = db.query_one(
                    """
                    SELECT 1
                    FROM media_users
                    WHERE server_id = ? AND type = 'jellyfin' AND lower(username) = lower(?)
                    """,
                    (server_id, username),
                )
                if existing:
                    raise RuntimeError(f"Jellyfin: username already exists on server '{server.get('name')}'")

                created = jellyfin_create_user(server, username)
                external_user_id = str(created.get("Id"))
                server_username = created.get("Name") or username

                jf_pass = (block.get("jellyfin_password") or "").strip()
                force_pw_change = bool(block.get("jellyfin_force_password_change"))

                if jf_pass:
                    jellyfin_set_password(server, external_user_id, jf_pass)
                    jellyfin_reset_password_required(server, external_user_id, force_pw_change)

                enabled_folders = [str(l["section_id"]) for l in libs]
                jellyfin_set_policy_folders(server, external_user_id, enabled_folders, force_password_change=force_pw_change)

                details_json["jellyfin"] = {
                    "enabled_folders": enabled_folders,
                    "force_password_change": force_pw_change,
                }

            elif provider == "plex":
                if not email:
                    raise RuntimeError("Plex: email is required")

                tok = (server.get("token") or "")
                if tok:
                    group_rows = db.query(
                        "SELECT * FROM servers WHERE type='plex' AND token=? ORDER BY name ASC",
                        (tok,),
                    )
                    group_servers = [dict(r) for r in group_rows] or [server]
                else:
                    group_servers = [server]

                libs_by_server = {}
                for l in libs:
                    libs_by_server.setdefault(int(l["server_id"]), []).append(l)

                plex_flags = block.get("plex_share") or {}
                allow_sync = bool(plex_flags.get("allowSync"))
                allow_camera = bool(plex_flags.get("allowCameraUpload"))
                allow_channels = bool(plex_flags.get("allowChannels"))
                filter_movies = str(plex_flags.get("filterMovies") or "")
                filter_tv = str(plex_flags.get("filterTelevision") or "")
                filter_music = str(plex_flags.get("filterMusic") or "")

                external_user_id = None
                server_username = None

                # IMPORTANT: avoid sending multiple Plex invites for the same user.
                # If we have multiple Plex servers linked by the same token, we only
                # send ONE invite (on the server selected in this block).
                # Additional servers will be handled after acceptance (via jobs / manual apply).

                # Choose the primary server for the invite:
                primary_sid = int(server_id)
                if primary_sid not in libs_by_server:
                    # if user picked libraries only from linked servers, fallback to first server having libs
                    primary_sid = int(next(iter(libs_by_server.keys())))

                invite_state = {"is_friend": False, "is_pending": False}

                # 1) Invite/update on primary server
                primary_server = next((x for x in group_servers if int(x.get("id")) == primary_sid), None)
                if primary_server is not None:
                    selected_primary = libs_by_server.get(primary_sid, [])
                    if selected_primary:
                        log.info(
                            f"[PLEX INVITE] server={primary_server.get('name')} "
                            f"email={email} libs={[x['name'] for x in selected_primary]}"
                        )
                        print(
                            f"[PLEX INVITE STDOUT] server={primary_server.get('name')} "
                            f"email={email} libs={[x['name'] for x in selected_primary]}",
                            flush=True
                        )
                        invite_state = plex_invite_and_share(
                            primary_server,
                            email=email,
                            libraries_names=[x["name"] for x in selected_primary],
                            allow_sync=allow_sync,
                            allow_camera_upload=allow_camera,
                            allow_channels=allow_channels,
                            filter_movies=filter_movies,
                            filter_television=filter_tv,
                            filter_music=filter_music,
                        )
                        log.info(f"[PLEX INVITE RESULT] {invite_state}")
                        print(f"[PLEX INVITE RESULT STDOUT] {invite_state}", flush=True)


                        if not external_user_id and invite_state.get("external_user_id"):
                            external_user_id = invite_state.get("external_user_id")
                        if not server_username and invite_state.get("username"):
                            server_username = invite_state.get("username")

                # 2) If user is ALREADY friend, we can update other servers immediately.
                # If invite is pending, do NOT re-invite on other servers (this is what creates
                # the 'Manage Library Access' + 'Library Requests Sent' double presence).
                if invite_state.get("is_friend"):
                    for s in group_servers:
                        sid2 = int(s["id"])
                        if sid2 == primary_sid:
                            continue
                        selected_for_this_server = libs_by_server.get(sid2, [])
                        if not selected_for_this_server:
                            continue

                        log.info(
                            f"[PLEX INVITE LINKED] server={s.get('name')} "
                            f"email={email} libs={[x['name'] for x in selected_for_this_server]}"
                        )
                        st2 = plex_invite_and_share(
                            s,
                            email=email,
                            libraries_names=[x["name"] for x in selected_for_this_server],
                            allow_sync=allow_sync,
                            allow_camera_upload=allow_camera,
                            allow_channels=allow_channels,
                            filter_movies=filter_movies,
                            filter_television=filter_tv,
                            filter_music=filter_music,
                        )
                        log.info(f"[PLEX INVITE LINKED RESULT] {st2}")

                        if not external_user_id and st2.get("external_user_id"):
                            external_user_id = st2.get("external_user_id")
                        if not server_username and st2.get("username"):
                            server_username = st2.get("username")

                details_json["plex_invite_state"] = {
                    "is_friend": bool(invite_state.get("is_friend")),
                    "is_pending": bool(invite_state.get("is_pending")),
                    "primary_server_id": int(primary_sid),
                }

                details_json["plex_linked_servers"] = [{"id": int(s["id"]), "name": s.get("name")} for s in group_servers]

            else:
                raise RuntimeError(f"Unsupported server type '{provider}'")

        except Exception as e:
            provider_errors.append(f"server_id={server_id} ({server.get('name')}): {e}")
            log.error(
                f"[ERROR CREATE USER] vodum_user_id={vodum_user_id} server_id={server_id} provider={provider} error={e}",
                exc_info=True
            )
            print(
                f"[ERROR CREATE USER STDOUT] vodum_user_id={vodum_user_id} "
                f"server_id={server_id} provider={provider} error={e}",
                flush=True
            )
            traceback.print_exc()
            continue

        # ... le reste de ta fonction inchangé ...
        # (j’ai laissé volontairement le reste identique pour que tu puisses coller sans te perdre)

        if provider == "jellyfin":
            cur2 = db.execute(
                """
                INSERT INTO media_users(server_id, vodum_user_id, external_user_id, username, email, type, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server_id,
                    vodum_user_id,
                    external_user_id,
                    server_username or username,
                    email or None,
                    provider,
                    json.dumps(details_json) if details_json else None,
                ),
            )
            media_user_id = cur2.lastrowid
            try:
                cur2.close()
            except Exception:
                pass

            if external_user_id:
                db.execute(
                    """
                    INSERT OR IGNORE INTO user_identities(vodum_user_id, type, server_id, external_user_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (vodum_user_id, provider, server_id, external_user_id),
                )

            if library_ids:
                db.executemany(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    [(media_user_id, lid) for lid in library_ids],
                )

            db.execute(
                """
                INSERT INTO media_jobs(provider, action, vodum_user_id, server_id, library_id, payload_json)
                VALUES ('jellyfin','grant', ?, ?, NULL, ?)
                """,
                (vodum_user_id, server_id, json.dumps({"source": "create_user"})),
            )

            created_accounts.append({
                "server_id": server_id,
                "provider": provider,
                "external_user_id": external_user_id,
                "username": server_username or username,
            })

        elif provider == "plex":
            try:
                tok = (server.get("token") or "")
                if tok:
                    group_rows = db.query(
                        "SELECT * FROM servers WHERE type='plex' AND token=? ORDER BY name ASC",
                        (tok,),
                    )
                    group_servers = [dict(r) for r in group_rows] or [server]
                else:
                    group_servers = [server]

                libs_by_server = {}
                for l in libs:
                    libs_by_server.setdefault(int(l["server_id"]), []).append(int(l["id"]))

                for s in group_servers:
                    sid2 = int(s["id"])
                    selected_lib_ids = libs_by_server.get(sid2, [])
                    if not selected_lib_ids:
                        continue

                    existing_mu = None

                    # 1) priorité absolue : même user Vodum + même serveur
                    existing_mu = db.query_one(
                        """
                        SELECT id
                        FROM media_users
                        WHERE server_id = ?
                          AND vodum_user_id = ?
                        LIMIT 1
                        """,
                        (sid2, vodum_user_id),
                    )

                    # 2) sinon on tente via l'identité Plex native
                    if not existing_mu and external_user_id:
                        existing_mu = db.query_one(
                            """
                            SELECT id
                            FROM media_users
                            WHERE server_id = ?
                              AND type = 'plex'
                              AND external_user_id = ?
                            LIMIT 1
                            """,
                            (sid2, str(external_user_id)),
                        )

                    # 3) sinon par email
                    if not existing_mu and email:
                        existing_mu = db.query_one(
                            """
                            SELECT id
                            FROM media_users
                            WHERE server_id = ?
                              AND type = 'plex'
                              AND lower(email) = lower(?)
                            LIMIT 1
                            """,
                            (sid2, email),
                        )

                    # 4) sinon par username
                    if not existing_mu and (server_username or username):
                        existing_mu = db.query_one(
                            """
                            SELECT id
                            FROM media_users
                            WHERE server_id = ?
                              AND type = 'plex'
                              AND lower(username) = lower(?)
                            LIMIT 1
                            """,
                            (sid2, server_username or username),
                        )

                    if existing_mu:
                        db.execute(
                            """
                            UPDATE media_users
                            SET vodum_user_id = ?,
                                external_user_id = COALESCE(?, external_user_id),
                                username = ?,
                                email = ?,
                                type = 'plex',
                                details_json = ?
                            WHERE id = ?
                            """,
                            (
                                vodum_user_id,
                                external_user_id or None,
                                server_username or username,
                                email or None,
                                json.dumps(details_json) if details_json else None,
                                existing_mu["id"],
                            ),
                        )
                        media_user_id = existing_mu["id"]
                    else:
                        cur2 = db.execute(
                            """
                            INSERT INTO media_users(server_id, vodum_user_id, external_user_id, username, email, type, details_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid2,
                                vodum_user_id,
                                external_user_id,
                                server_username or username,
                                email or None,
                                "plex",
                                json.dumps(details_json) if details_json else None,
                            ),
                        )
                        media_user_id = cur2.lastrowid
                        try:
                            cur2.close()
                        except Exception:
                            pass

                    if external_user_id:
                        db.execute(
                            """
                            INSERT OR IGNORE INTO user_identities(vodum_user_id, type, server_id, external_user_id)
                            VALUES (?, 'plex', NULL, ?)
                            """,
                            (vodum_user_id, external_user_id),
                        )

                    db.executemany(
                        """
                        INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                        VALUES (?, ?)
                        """,
                        [(media_user_id, lid) for lid in selected_lib_ids],
                    )

                    enqueue_jobs = bool(block.get("enqueue_plex_jobs")) or bool(
                        (details_json.get("plex_invite_state") or {}).get("is_pending")
                    )

                    if enqueue_jobs:
                        for lid in selected_lib_ids:
                            db.execute(
                                """
                                INSERT INTO media_jobs(provider, action, vodum_user_id, server_id, library_id, payload_json)
                                VALUES ('plex','grant', ?, ?, ?, ?)
                                """,
                                (vodum_user_id, sid2, lid, json.dumps({"source": "create_user"})),
                            )

                    created_accounts.append({
                        "server_id": sid2,
                        "provider": "plex",
                        "external_user_id": external_user_id,
                        "username": server_username or username,
                    })

            except Exception as e:
                provider_errors.append(f"server_id={server_id} ({server.get('name')}) persistence: {e}")
                log.error(
                    f"Plex persistence failed: vodum_user_id={vodum_user_id} server_id={server_id}: {e}",
                    exc_info=True,
                )
                continue

        # ------------------------------------------------------------
        # USER CREATION NOTIFICATION (EMAIL ONLY, 1 TEMPLATE MAX)
        # Rules:
        # - If no comm_templates(trigger_event='user_creation') => send NOTHING
        # - Email only (no Discord)
        # - Only one template is used (first one by id)
        # - days_after > 0 => schedule in comm_scheduled (picked by send_expiration_emails flush)
        # ------------------------------------------------------------
        if email:
            try:
                welcome_gate_key = f"{provider}:{server.get('id')}"
                if provider == "plex":
                    welcome_gate_key = f"plex_token:{(server.get('token') or '')}"

                if welcome_gate_key not in sent_welcome_keys:
                    ct = select_comm_template_for_user(
                        db=db,
                        trigger_event="user_creation",
                        provider=provider,
                        user_id=int(vodum_user_id),
                    )

                    if ct:
                        try:
                            days_after = int(ct.get("days_after")) if ct.get("days_after") is not None else None
                        except Exception:
                            days_after = None

                        queue_server_id = int(server_id)
                        if provider == "plex":
                            queue_server_id = int(
                                (details_json.get("plex_invite_state") or {}).get("primary_server_id") or server_id
                            )

                        queue_dedupe_key = (
                            f"user_creation:template:{int(ct['id'])}:user:{int(vodum_user_id)}:"
                            f"provider:{provider}:server:{queue_server_id}"
                        )

                        payload = {
                            "trigger_event": "user_creation",
                            "expiration_date": (expiration_date or "")[:10],
                            "username": username,
                            "firstname": firstname,
                            "lastname": lastname,
                            "email": email,
                        }

                        if days_after is not None and days_after > 0:
                            schedule_template_notification(
                                db=db,
                                template_id=int(ct["id"]),
                                user_id=int(vodum_user_id),
                                provider=provider,
                                server_id=queue_server_id,
                                send_at_modifier=f"+{days_after} days",
                                payload=payload,
                                dedupe_key=queue_dedupe_key,
                                max_attempts=10,
                            )
                        else:
                            schedule_template_notification(
                                db=db,
                                template_id=int(ct["id"]),
                                user_id=int(vodum_user_id),
                                provider=provider,
                                server_id=queue_server_id,
                                send_at_modifier=None,
                                payload=payload,
                                dedupe_key=queue_dedupe_key,
                                max_attempts=10,
                            )

                    sent_welcome_keys.add(welcome_gate_key)

            except Exception as e:
                mailing_errors.append(f"server_id={server_id}: {e}")

    if not created_accounts:
        db.execute(
            "UPDATE vodum_users SET status = 'unknown' WHERE id = ?",
            (vodum_user_id,),
        )

    return jsonify(
        {
            "ok": True,
            "vodum_user_id": vodum_user_id,
            "created_accounts": created_accounts,
            "provider_errors": provider_errors,
            "mailing_errors": mailing_errors,
        }
    )

