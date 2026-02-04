import json
import re
from datetime import datetime
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
from core.providers.plex_users import plex_invite_and_share


log = get_logger("users_create")

users_bp = Blueprint("users_bp", __name__)


def get_db() -> DBManager:
    if "db" not in g:
        g.db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
    return g.db


def is_smtp_ready(settings_row: Optional[Dict[str, Any]]) -> bool:
    if not settings_row:
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


@users_bp.post("/api/users/create")
def api_users_create():
    db = get_db()
    payload = request.get_json(silent=True) or {}

    email = (payload.get("email") or "").strip()
    second_email = (payload.get("second_email") or "").strip()
    username = (payload.get("username") or "").strip() or (email.split("@", 1)[0] if email else "")
    firstname = (payload.get("firstname") or "").strip()
    lastname = (payload.get("lastname") or "").strip()

    # --- Dates: support aliases + parsing tolerant ---
    raw_exp = payload.get("expiration_date") or payload.get("expirationDate") or payload.get("expiration") or ""
    expiration_date = _iso_date_or_none(raw_exp)

    raw_renew = payload.get("renewal_date") or payload.get("renewalDate") or ""
    renewal_date = _iso_date_or_none(raw_renew)

    renewal_method = (payload.get("renewal_method") or payload.get("renewalMethod") or "").strip() or None

    notes = (payload.get("notes") or "").strip()

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
    cur = db.execute(
        """
        INSERT INTO vodum_users(
            username, firstname, lastname,
            email, second_email,
            expiration_date,
            renewal_method, renewal_date,
            notes, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            firstname,
            lastname,
            email or None,
            second_email or None,
            expiration_date,
            renewal_method,
            renewal_date,
            notes,
            initial_status,
        ),
    )
    vodum_user_id = cur.lastrowid
    try:
        cur.close()
    except Exception:
        pass

    created_accounts: List[Dict[str, Any]] = []
    mailing_errors: List[str] = []
    provider_errors: List[str] = []

    settings = db.query_one("SELECT * FROM settings WHERE id = 1")
    settings = dict(settings) if settings else {}
    smtp_ok = is_smtp_ready(settings)

    for block in server_blocks:
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

                for s in group_servers:
                    sid2 = int(s["id"])
                    selected_for_this_server = libs_by_server.get(sid2, [])

                    if not selected_for_this_server:
                        continue

                    invited = plex_invite_and_share(
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

                    if not external_user_id and invited.get("external_user_id"):
                        external_user_id = invited.get("external_user_id")
                    if not server_username and invited.get("username"):
                        server_username = invited.get("username")

                details_json["plex_share"] = {
                    "allowSync": allow_sync,
                    "allowCameraUpload": allow_camera,
                    "allowChannels": allow_channels,
                    "filterMovies": filter_movies,
                    "filterTelevision": filter_tv,
                    "filterMusic": filter_music,
                    "linked_group_token": "1" if tok else "0",
                }

                details_json["plex_linked_servers"] = [{"id": int(s["id"]), "name": s.get("name")} for s in group_servers]

            else:
                raise RuntimeError(f"Unsupported server type '{provider}'")

        except Exception as e:
            provider_errors.append(f"server_id={server_id} ({server.get('name')}): {e}")
            log.error(f"Create provider user failed: vodum_user_id={vodum_user_id} server_id={server_id}: {e}", exc_info=True)
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

                if bool(block.get("enqueue_plex_jobs")):
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

        if smtp_ok and email:
            try:
                dedupe_key = f"{provider}:{server.get('id')}"
                if provider == "plex":
                    dedupe_key = f"plex_token:{(server.get('token') or '')}"

                if dedupe_key not in sent_welcome_keys:
                    tpl = get_welcome_template(db, provider, server_id)
                    if tpl:
                        server_url = (server.get("public_url") or server.get("url") or server.get("local_url") or "").strip()
                        ctx = build_user_context({
                            "username": username,
                            "email": email,
                            "expiration_date": expiration_date or "",
                            "firstname": firstname,
                            "lastname": lastname,
                            "server_name": server.get("name") or "",
                            "server_url": server_url,
                            "login_username": username,
                            "temporary_password": (block.get("jellyfin_password") or "") if provider == "jellyfin" else "",
                        })
                        subject = render_mail(tpl.get("subject") or "", ctx)
                        body = render_mail(tpl.get("body") or "", ctx)
                        send_email_via_settings(settings, email, subject, body)

                    sent_welcome_keys.add(dedupe_key)

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

