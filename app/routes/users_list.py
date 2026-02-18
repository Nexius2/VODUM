# Auto-split from app.py (keep URLs/endpoints intact)
import os
import json
import time
import re
import math
import platform
import ipaddress
import uuid
import threading
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher


import requests
from flask import (
    render_template, g, request, redirect, url_for, flash, session,
    Response, current_app, jsonify, make_response, abort,
)

from db_manager import DBManager
from logging_utils import get_logger, read_last_logs, read_all_logs
from tasks_engine import run_task, start_scheduler, run_task_sequence, run_task_by_name, enqueue_task
from mailing_utils import build_user_context, render_mail
from discord_utils import is_discord_ready, validate_discord_bot_token
from core.i18n import get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash

from web.helpers import get_db, scheduler_db_provider, table_exists, add_log, send_email_via_settings, get_backup_cfg

task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")
security_logger = get_logger("security")
settings_logger = get_logger("settings")

def register(app):
    @app.route("/users")
    def users_list():
        db = get_db()

        # Multi-status (checkboxes): ?status=active&status=reminder...
        selected_statuses = request.args.getlist("status")

        # Toggle: show archived statuses (expired/unfriended/suspended)
        # (On garde la variable pour compat / futur, mais on ne cache plus par défaut)
        show_archived = request.args.get("show_archived", "0") == "1"

        # Search query
        search = request.args.get("q", "").strip()

        # Default view (daily): hide expired unless explicitly selected or show_archived enabled
        # -> CHANGÉ : on ne cache plus rien par défaut.
        # On conserve ces variables pour ne rien perdre / compat, mais on ne les applique plus automatiquement.
        default_excluded = {"expired"}
        all_statuses = ["active", "pre_expired", "reminder", "expired", "invited", "unfriended", "suspended", "unknown"]

        # AVANT: si pas de sélection -> on excluait expired automatiquement
        # MAINTENANT: si pas de sélection -> on ne filtre PAS par status (donc on affiche tout le monde)
        # Donc: on ne touche pas selected_statuses ici.

        query = """
            SELECT
                u.*,

                COUNT(DISTINCT mu.server_id) AS servers_count,
                COUNT(DISTINCT mul.library_id) AS libraries_count

            FROM vodum_users u
            LEFT JOIN media_users mu
                ON mu.vodum_user_id = u.id

            LEFT JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
        """

        conditions = []
        params = []

        # Status filter (IN)
        # -> On filtre uniquement si l’admin a explicitement coché au moins 1 status
        if selected_statuses:
            placeholders = ",".join(["?"] * len(selected_statuses))
            conditions.append(f"u.status IN ({placeholders})")
            params.extend(selected_statuses)

        # Global search across multiple fields
        if search:
            like = f"%{search}%"
            conditions.append(
                "("
                "COALESCE(u.username,'') LIKE ? OR "
                "COALESCE(u.email,'') LIKE ? OR "
                "COALESCE(u.second_email,'') LIKE ? OR "
                "COALESCE(u.firstname,'') LIKE ? OR "
                "COALESCE(u.lastname,'') LIKE ? OR "
                "COALESCE(u.notes,'') LIKE ?"
                ")"
            )
            params.extend([like, like, like, like, like, like])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += """
            GROUP BY u.id
            ORDER BY u.username ASC
        """

        users = db.query(query, params)

        return render_template(
            "users/users.html",
            users=users,
            selected_statuses=selected_statuses,
            show_archived=show_archived,
            search=search,
            active_page="users",
        )

    ##################################


    @app.route("/users/<int:user_id>/merge/preview", methods=["GET"])
    def user_merge_preview(user_id: int):
        db = get_db()

        other_id = request.args.get("other_id", type=int)
        if not other_id:
            return Response(json.dumps({"error": "missing_other_id"}), status=400, mimetype="application/json")

        master = db.query_one("SELECT * FROM vodum_users WHERE id=?", (user_id,))
        other = db.query_one("SELECT * FROM vodum_users WHERE id=?", (other_id,))
        if not master or not other:
            return Response(json.dumps({"error": "user_not_found"}), status=404, mimetype="application/json")

        master = dict(master)
        other = dict(other)

        preview = build_merge_preview(master, other)

        # Bonus: compter ce qui sera déplacé (utile à afficher)
        changes = {
            "media_users_to_move": db.query_one("SELECT COUNT(*) AS c FROM media_users WHERE vodum_user_id=?", (other_id,))["c"],
            "identities_to_move": db.query_one("SELECT COUNT(*) AS c FROM user_identities WHERE vodum_user_id=?", (other_id,))["c"],
            "sent_emails_to_move": db.query_one("SELECT COUNT(*) AS c FROM sent_emails WHERE user_id=?", (other_id,))["c"],
            "media_jobs_to_move": db.query_one("SELECT COUNT(*) AS c FROM media_jobs WHERE vodum_user_id=?", (other_id,))["c"],
        }

        payload = {
            "master_id": user_id,
            "other_id": other_id,
            "result": preview["result"],
            "sources": preview["sources"],
            "changes": changes,
        }
        return Response(json.dumps(payload, default=str), mimetype="application/json")

    return app

# user merge control
##################################

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _email_local(email: str) -> str:
    email = _norm(email)
    return email.split("@", 1)[0] if "@" in email else email

def _sim(a: str, b: str) -> float:
    a = _norm(a); b = _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _tokens_from_user(u: dict) -> list[str]:
    """
    On extrait des tokens "forts" depuis le master :
    - firstname / lastname / username / email local-part
    - split espace, underscore, point, tiret
    - ignore tokens trop courts (<=2)
    """
    raw = " ".join([
        _norm(u.get("firstname") or ""),
        _norm(u.get("lastname") or ""),
        _norm(u.get("username") or ""),
        _email_local(u.get("email") or ""),
        _email_local(u.get("second_email") or ""),
    ])
    parts = re.split(r"[ \t\.\-_]+", raw)
    toks = []
    for p in parts:
        p = p.strip()
        if len(p) >= 3:
            toks.append(p)
    # dédup en gardant l'ordre
    seen = set()
    out = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def score_candidate(u: dict, c: dict) -> int:
    score = 0

    # ---- 1) emails exacts / croisés (comme toi mais plus strict)
    u_email = _norm(u.get("email") or "")
    u_second = _norm(u.get("second_email") or "")
    c_email = _norm(c.get("email") or "")
    c_second = _norm(c.get("second_email") or "")

    if u_email and c_email and u_email == c_email:
        score += 500
    if u_email and c_second and u_email == c_second:
        score += 420
    if u_second and c_email and u_second == c_email:
        score += 420
    if u_second and c_second and u_second == c_second:
        score += 300

    # ---- 2) “contient / commence par” sur tokens master (PRIORITÉ HAUTE)
    # Ex: "sylvain" dans username/email/etc => ça doit remonter en premier
    tokens = _tokens_from_user(u)

    c_username = _norm(c.get("username") or "")
    c_first = _norm(c.get("firstname") or "")
    c_last = _norm(c.get("lastname") or "")
    c_email_local = _email_local(c.get("email") or "")
    c_second_local = _email_local(c.get("second_email") or "")

    for t in tokens:
        # username : très fort
        if c_username == t:
            score += 260
        elif c_username.startswith(t):
            score += 220
        elif t in c_username:
            score += 180

        # firstname / lastname : fort
        if c_first == t:
            score += 200
        elif c_first.startswith(t):
            score += 160
        elif t in c_first:
            score += 120

        if c_last == t:
            score += 200
        elif c_last.startswith(t):
            score += 160
        elif t in c_last:
            score += 120

        # email local-part : moyen/fort
        if c_email_local == t:
            score += 170
        elif c_email_local.startswith(t):
            score += 140
        elif t in c_email_local:
            score += 110

        if c_second_local == t:
            score += 120
        elif c_second_local.startswith(t):
            score += 90
        elif t in c_second_local:
            score += 70

    # ---- 3) Similarité “fuzzy” (complément)
    score += int(120 * _sim(_email_local(u.get("email") or ""), _email_local(c.get("email") or "")))
    score += int(80  * _sim(u.get("firstname") or "", c.get("firstname") or ""))
    score += int(80  * _sim(u.get("lastname") or "", c.get("lastname") or ""))
    score += int(50  * _sim(u.get("username") or "", c.get("username") or ""))
    return score


def get_merge_suggestions(db, user_id: int, limit: int | None = None):
    u = db.query_one("SELECT * FROM vodum_users WHERE id=?", (user_id,))
    if not u:
        return []
    u = dict(u)

    candidates = db.query(
        """
        SELECT id, username, firstname, lastname, email, second_email, expiration_date, status, created_at
        FROM vodum_users
        WHERE id != ?
        """,
        (user_id,),
    )

    scored = []
    for c in candidates:
        c = dict(c)
        s = score_candidate(u, c)
        c["merge_score"] = s
        scored.append(c)

    scored.sort(key=lambda x: x["merge_score"], reverse=True)

    if limit is None:
        return scored
    return scored[:limit]

def _max_date(a, b):
    if not a:
        return b
    if not b:
        return a
    return max(str(a), str(b))  # OK si ISO

def merge_vodum_users(db, master_id: int, other_id: int) -> None:
    if master_id == other_id:
        return

    master = db.query_one("SELECT * FROM vodum_users WHERE id=?", (master_id,))
    other = db.query_one("SELECT * FROM vodum_users WHERE id=?", (other_id,))
    if not master or not other:
        raise ValueError("user not found")

    master = dict(master)
    other = dict(other)

    # ⚠️ IMPORTANT :
    # DBManager.execute() commit déjà (autocommit). Donc PAS de BEGIN/COMMIT/ROLLBACK ici.
    # Sinon tu as exactement "cannot commit/rollback - no transaction is active".

    # 1) Déplacer media_users
    db.execute(
        "UPDATE media_users SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 2) user_identities (éviter collisions UNIQUE)
    db.execute(
        """
        DELETE FROM user_identities
        WHERE vodum_user_id = ?
          AND EXISTS (
            SELECT 1
            FROM user_identities ui2
            WHERE ui2.vodum_user_id = ?
              AND ui2.type = user_identities.type
              AND COALESCE(ui2.server_id, -1) = COALESCE(user_identities.server_id, -1)
              AND ui2.external_user_id = user_identities.external_user_id
          )
        """,
        (other_id, master_id),
    )
    db.execute(
        "UPDATE user_identities SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 3) sent_emails (éviter collisions UNIQUE)
    db.execute(
        """
        DELETE FROM sent_emails
        WHERE user_id = ?
          AND EXISTS (
            SELECT 1
            FROM sent_emails se2
            WHERE se2.user_id = ?
              AND se2.template_type = sent_emails.template_type
              AND se2.expiration_date = sent_emails.expiration_date
          )
        """,
        (other_id, master_id),
    )
    db.execute(
        "UPDATE sent_emails SET user_id=? WHERE user_id=?",
        (master_id, other_id),
    )

    # 3bis) media_jobs (sinon supprimés par ON DELETE CASCADE)
    db.execute(
        "UPDATE media_jobs SET vodum_user_id=? WHERE vodum_user_id=?",
        (master_id, other_id),
    )

    # 4) Merge champs (master prioritaire, other complète)
    merged = {}

    # expiration: garder la plus tardive
    merged["expiration_date"] = _max_date(
        master.get("expiration_date"), other.get("expiration_date")
    )

    # compléter identité
    for f in ("firstname", "lastname", "renewal_method", "renewal_date"):
        if not (master.get(f) or "").strip() and (other.get(f) or "").strip():
            merged[f] = other.get(f)

    # --- notes + emails (inchangé chez toi) ---
    base_notes = (master.get("notes") or "").strip()
    other_notes = (other.get("notes") or "").strip()

    m_email = (master.get("email") or "").strip()
    m_second = (master.get("second_email") or "").strip()

    o_email = (other.get("email") or "").strip()
    o_second = (other.get("second_email") or "").strip()

    def _same(a: str, b: str) -> bool:
        return (a or "").strip().lower() == (b or "").strip().lower()

    def add_note_line(line: str):
        nonlocal base_notes
        line = (line or "").strip()
        if not line:
            return
        if line in base_notes:
            return
        base_notes = (base_notes + "\n" + line).strip() if base_notes else line

    def push_second(val: str):
        nonlocal m_second
        val = (val or "").strip()
        if not val:
            return
        if _same(val, m_email) or _same(val, m_second):
            return
        if not m_second:
            m_second = val
            return
        add_note_line(f"[merge] email additionnel non stocké (second_email déjà pris): {val}")

    if not m_email and o_email:
        m_email = o_email
    elif m_email and o_email and not _same(m_email, o_email):
        push_second(o_email)

    if o_second and not _same(o_second, m_email):
        push_second(o_second)

    if m_email:
        merged["email"] = m_email
    merged["second_email"] = m_second or None

    if other_notes and other_notes not in base_notes:
        add_note_line("--- merged ---")
        add_note_line(other_notes)

    if base_notes != (master.get("notes") or "").strip():
        merged["notes"] = base_notes

    if merged:
        sets = ", ".join([f"{k}=?" for k in merged.keys()])
        db.execute(
            f"UPDATE vodum_users SET {sets} WHERE id=?",
            [*merged.values(), master_id],
        )

    # 5) Supprimer other
    db.execute("DELETE FROM vodum_users WHERE id=?", (other_id,))

def build_merge_preview(master: dict, other: dict) -> dict:
    """
    Reproduit les règles de merge_vodum_users, mais sans écrire en DB.
    Retourne:
      - result: dict des champs vodum_users après fusion
      - sources: dict champ -> 'master'|'target'|'computed'
      - notes_preview: notes finales
    """
    def _same(a: str, b: str) -> bool:
        return (a or "").strip().lower() == (b or "").strip().lower()

    def _max_date(a, b):
        if not a:
            return b
        if not b:
            return a
        return max(str(a), str(b))  # OK si ISO

    sources = {}
    result = dict(master)  # base = master

    # expiration_date = max(master, other) => computed
    exp = _max_date(master.get("expiration_date"), other.get("expiration_date"))
    result["expiration_date"] = exp
    sources["expiration_date"] = "computed"

    # Compléter certains champs si master vide
    for f in ("firstname", "lastname", "renewal_method", "renewal_date"):
        m = (master.get(f) or "").strip()
        o = (other.get(f) or "").strip()
        if not m and o:
            result[f] = other.get(f)
            sources[f] = "target"
        else:
            sources[f] = "master"

    # Emails + notes : mêmes règles que merge_vodum_users
    m_email = (master.get("email") or "").strip()
    m_second = (master.get("second_email") or "").strip()
    o_email = (other.get("email") or "").strip()
    o_second = (other.get("second_email") or "").strip()

    base_notes = (master.get("notes") or "").strip()
    other_notes = (other.get("notes") or "").strip()

    def add_note_line(line: str):
        nonlocal base_notes
        line = (line or "").strip()
        if not line:
            return
        if line in base_notes:
            return
        base_notes = (base_notes + "\n" + line).strip() if base_notes else line

    def push_second(val: str):
        nonlocal m_second
        val = (val or "").strip()
        if not val:
            return
        if _same(val, m_email) or _same(val, m_second):
            return
        if not m_second:
            m_second = val
            return
        add_note_line(f"[merge] email additionnel non stocké (second_email déjà pris): {val}")

    # email principal
    if not m_email and o_email:
        m_email = o_email
        sources["email"] = "target"
    else:
        sources["email"] = "master"

    if m_email and o_email and not _same(m_email, o_email):
        push_second(o_email)

    # second email other
    if o_second and not _same(o_second, m_email):
        push_second(o_second)

    # appliquer email/second_email
    result["email"] = m_email or None
    result["second_email"] = m_second or None

    # source second_email
    if (master.get("second_email") or "").strip():
        sources["second_email"] = "master"
    elif (result["second_email"] or "").strip():
        sources["second_email"] = "target"  # rempli via other
    else:
        sources["second_email"] = "master"

    # notes finales
    if other_notes and other_notes not in base_notes:
        add_note_line("--- merged ---")
        add_note_line(other_notes)

    result["notes"] = base_notes
    # notes = computed si ça a changé
    sources["notes"] = "computed" if (base_notes != (master.get("notes") or "").strip()) else "master"

    # Champs non modifiés dans merge_vodum_users : restent master
    # (username, status, etc.)
    for k in result.keys():
        sources.setdefault(k, "master")

    return {"result": result, "sources": sources}






