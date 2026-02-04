import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import (
    Flask,
    render_template,
    g,
    request,
    redirect,
    url_for,
    flash,
    session,
    Response,
    current_app,
    jsonify,
    make_response,
    abort,
)
from config import Config
#from tasks import create_task, run_task
from tasks_engine import run_task, start_scheduler, run_task_sequence, run_task_by_name, enqueue_task
import json
from zoneinfo import ZoneInfo
import smtplib
from email.message import EmailMessage
#from flask_login import login_required
import math
from importlib.metadata import version
import platform

from logging_utils import get_logger, read_last_logs, read_all_logs
task_logger = get_logger("tasks_ui")
auth_logger = get_logger("auth")

from api.subscriptions import subscriptions_api, update_user_expiration
import uuid
from mailing_utils import build_user_context, render_mail
import threading
import re
from db_manager import DBManager
from typing import Optional
from difflib import SequenceMatcher
import time  
from core.i18n import init_i18n, get_translator, get_available_languages
from core.backup import BackupConfig, ensure_backup_dir, create_backup_file, list_backups, restore_backup_file
from werkzeug.security import generate_password_hash, check_password_hash
from blueprints.users import users_bp
import requests







_I18N_CACHE: dict[str, dict] = {}



# -----------------------------
# AUTH RESET (local file)
# -----------------------------
RESET_FILE = os.environ.get("VODUM_RESET_FILE", "/appdata/password.reset")
RESET_MAGIC = os.environ.get("VODUM_RESET_MAGIC", "RECOVER")


def startup_admin_recover_if_requested(app):
    """
    Reset LOCAL (Unraid/Docker) :
    - si RESET_FILE existe et contient RESET_MAGIC ("RECOVER")
    - au démarrage de l'app uniquement
    -> wipe admin_email + admin_password_hash
    -> supprime le fichier (one-shot)
    """
    if not os.path.exists(RESET_FILE):
        return

    try:
        with open(RESET_FILE, "r", encoding="utf-8") as f:
            marker = (f.read() or "").strip()
    except Exception:
        marker = ""

    # Pour ton nouveau process ultra-simple :
    # on accepte n'importe quel contenu NON vide, mais on garde "RECOVER" comme valeur recommandée
    if not marker:
        app.logger.warning(f"password.reset detected at {RESET_FILE} but file is empty. Ignoring.")
        return

    try:
        db = DBManager(os.environ.get("DATABASE_PATH", "/appdata/database.db"))
        cur = db.execute(
            """
            UPDATE settings
            SET
              admin_email = NULL,
              admin_password_hash = NULL,
              auth_enabled = 1
            WHERE id = 1
            """
        )
        try:
            cur.close()
        except Exception:
            pass

        # one-shot: suppression du fichier reset
        os.remove(RESET_FILE)

        app.logger.warning(
            "Admin credentials cleared via password.reset. Please reinitialize via /setup-admin."
        )
    except Exception as e:
        # si ça échoue, on NE supprime PAS le fichier -> ça retentera au prochain restart
        app.logger.error(f"Startup admin recover failed: {e}")






def fromjson_safe(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None
    return None

def load_version():
    info_path = "/app/INFO"
    if not os.path.exists(info_path):
        return "dev"

    version = "dev"
    with open(info_path) as f:
        for line in f:
            if line.startswith("VERSION="):
                version = line.split("=", 1)[1].strip()
                break
    return version

APP_VERSION = load_version()



def create_app():
    app = Flask(__name__)

    # Injecte la version globale dans tous les 
    
    app.jinja_env.filters["fromjson"] = fromjson_safe

    @app.before_request
    def inject_version():
        g.app_version = APP_VERSION

    app.config.from_object(Config)

    # RESET au démarrage (avant routes / scheduler)
    startup_admin_recover_if_requested(app)

    # Répertoire de backup (mounté par Docker, ex: /backups)
    app.config.setdefault("BACKUP_DIR", os.environ.get("VODUM_BACKUP_DIR", "/appdata/backups"))
    backup_cfg = BackupConfig(
    backup_dir=app.config["BACKUP_DIR"],
    database_path=app.config["DATABASE"],
)

    app.register_blueprint(subscriptions_api)
    app.register_blueprint(users_bp)


    # -----------------------------
    # DB helpers
    # -----------------------------
    def get_db():
        if "db" not in g:
            g.db = DBManager(app.config["DATABASE"])
        return g.db

    init_i18n(app, get_db)

    def scheduler_db_provider():
        return DBManager(app.config["DATABASE"])

    @app.context_processor
    def inject_brand_name():
        try:
            db = get_db()
            row = db.query_one("SELECT brand_name FROM settings WHERE id = 1")
            brand_name = None
            if row:
                # sqlite3.Row -> accès par clé
                brand_name = row["brand_name"]
            brand_name = (brand_name or "").strip()
        except Exception:
            brand_name = ""

        return {
            "app_brand_name": brand_name if brand_name else "VODUM"
        }


    @app.template_filter("safe_datetime")
    def safe_datetime(value):
        from datetime import datetime
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value  # fallback string

    @app.template_filter("cron_human")
    def cron_human(expr):
        """
        Convertit une expression CRON en phrase lisible, multilingue via t().
        """
        t = get_translator()  # ← indispensable pour le multilingue !

        if not expr:
            return ""

        parts = expr.split()
        if len(parts) != 5:
            return expr  # fallback direct

        minute, hour, dom, month, dow = parts

        # Toutes les X minutes → "*/5 * * * *"
        if hour == "*" and dom == "*" and month == "*" and dow == "*" and minute.startswith("*/"):
            return t("cron_every_x_minutes").format(x=minute[2:])
            
        # Toutes les heures → "0 * * * *"
        if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
            return t("cron_every_hour_at").format(m="00")


        # Toutes les X heures → "0 */6 * * *"
        if minute == "0" and dom == "*" and month == "*" and dow == "*" and hour.startswith("*/"):
            return t("cron_every_x_hours").format(x=hour[2:])

        # Tous les jours → "0 3 * * *"
        if dom == "*" and month == "*" and dow == "*":
            try:
                return t("cron_every_day_at").format(
                    h=f"{int(hour):02d}",
                    m=f"{int(minute):02d}"
                )
            except:
                return expr

        # Tous les X jours → "0 3 */3 * *"
        if dom.startswith("*/") and month == "*" and dow == "*":
            try:
                return t("cron_every_x_days_at").format(
                    x=dom[2:],
                    h=f"{int(hour):02d}",
                    m=f"{int(minute):02d}"
                )
            except:
                return expr

        # Jour de semaine → "0 3 * * 1"
        if dow != "*" and dom == "*" and month == "*":
            weekdays = {
                "1": t("monday"),
                "2": t("tuesday"),
                "3": t("wednesday"),
                "4": t("thursday"),
                "5": t("friday"),
                "6": t("saturday"),
                "0": t("sunday"),
            }

            dayname = weekdays.get(dow, dow)

            try:
                return t("cron_every_weekday_at").format(
                    day=dayname,
                    h=f"{int(hour):02d}",
                    m=f"{int(minute):02d}"
                )
            except:
                return t("cron_every_weekday").format(day=dayname)

        return expr

    @app.template_filter("tz")
    def tz_filter(dt):
        """
        Convertit un datetime UTC vers le fuseau horaire configuré dans settings.
        Accepte :
        - datetime object
        - string ISO "YYYY-MM-DD HH:MM:SS"
        """
        if dt is None:
            return "-"

        # --------------------------------------------------
        # 1) Normalisation datetime
        # --------------------------------------------------
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except Exception:
                return dt  # format inconnu → fallback brut

        if not isinstance(dt, datetime):
            return dt

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # --------------------------------------------------
        # 2) Charger timezone depuis la DB (READ ONLY)
        # --------------------------------------------------
        db = get_db()
        row = db.query_one(
            "SELECT timezone FROM settings WHERE id = 1"
        )

        tzname = "UTC"
        if row:
            try:
                tzname = row["timezone"] or "UTC"
            except (KeyError, IndexError):
                tzname = "UTC"



        # --------------------------------------------------
        # 3) Conversion
        # --------------------------------------------------
        try:
            local_tz = ZoneInfo(tzname)
            return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M")
        except Exception:
            # Timezone invalide → UTC lisible
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")





    @app.teardown_appcontext
    def close_db(exception):
        g.pop("db", None)


    def table_exists(db, name: str) -> bool:
        row = db.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return row is not None


    def add_log(level, category, message, details=None):
        """
        Log applicatif centralisé.
        Écrit UNIQUEMENT dans les logs texte via logging_utils.

        - Aucun accès DB
        - Aucun lock possible
        - Anonymisation gérée par logging_utils
        """
        logger = get_logger(category)

        # Construction message enrichi
        if details is not None:
            try:
                message = f"{message} | details={details}"
            except Exception:
                message = f"{message} | details=<unserializable>"

        level = str(level).lower()

        if level == "debug":
            logger.debug(message)
        elif level == "info":
            logger.info(message)
        elif level in ("warn", "warning"):
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "critical":
            logger.critical(message)
        else:
            logger.info(message)




    def _html_to_plain(html: str) -> str:
        """Fallback texte propre à partir d'un HTML simple."""
        if not html:
            return ""
        txt = re.sub(r"(?i)<br\s*/?>", "\n", html)
        txt = re.sub(r"(?i)</p\s*>", "\n\n", txt)
        txt = re.sub(r"<[^>]+>", "", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt)
        return txt.strip()


    def _normalize_body_to_html(body: str) -> str:
        """
        Si le template contient du texte brut (sans balises),
        on transforme les retours ligne en <br>.
        Si c'est déjà du HTML, on ne touche pas.
        """
        if not body:
            return ""
        if re.search(r"<[a-zA-Z][^>]*>", body):  # détecte grossièrement du HTML
            return body

        # texte brut -> html basique (escape minimal)
        escaped = (
            body.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
        return escaped.replace("\n", "<br>\n")


    def _wrap_email_html(inner_html: str, title: str = "Stream Empire") -> str:
        """
        Enveloppe 'email-safe' (Gmail/Outlook) : tables + styles inline.
        """
        inner_html = inner_html or ""
        return f"""\
    <!DOCTYPE html>
    <html>
      <body style="margin:0;padding:0;background-color:#0b1220;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0b1220;padding:24px 0;">
          <tr>
            <td align="center">
              <table width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;background:#111a2e;border:1px solid rgba(255,255,255,0.08);border-radius:12px;overflow:hidden;">
                <tr>
                  <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:bold;color:#ffffff;border-bottom:1px solid rgba(255,255,255,0.08);">
                    {title}
                  </td>
                </tr>
                <tr>
                  <td style="padding:18px 22px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#e5e7eb;">
                    {inner_html}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 22px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.4;color:#9ca3af;border-top:1px solid rgba(255,255,255,0.08);">
                    © {title} — Ceci est un email automatique.
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


    def send_email_via_settings(
        to_email: str,
        subject: str,
        body: str,
        *,
        is_html: bool = False,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
    ) -> bool:
        """
        Envoie un email en utilisant la configuration stockée en base (table settings).

        ✅ Supporte TEXTE BRUT dans Vodum (auto converti en HTML joli)
        ✅ Envoie multipart/alternative (texte + html)
        ✅ Corrige sqlite3.Row (pas de .get())
        """
        logger = get_logger("mailing")

        if not to_email:
            logger.warning("[MAIL] Destinataire vide, envoi annulé")
            return False

        db = get_db()

        # --------------------------------------------------
        # 1) Charger configuration mail
        # --------------------------------------------------
        settings_row = db.query_one("SELECT * FROM settings LIMIT 1")
        if not settings_row:
            logger.error("[MAIL] Aucun paramètre mail trouvé en base")
            return False

        # IMPORTANT: sqlite3.Row n'a pas .get() → on convertit en dict
        settings = dict(settings_row)

        if not settings.get("mailing_enabled"):
            logger.info("[MAIL] Mailing désactivé dans les paramètres")
            return False

        smtp_host = settings.get("smtp_host")
        smtp_port = settings.get("smtp_port") or 587
        smtp_user = settings.get("smtp_user")
        smtp_pass = settings.get("smtp_pass") or ""
        smtp_tls = bool(settings.get("smtp_tls"))
        mail_from = settings.get("mail_from") or smtp_user

        try:
            smtp_port = int(smtp_port)
        except (TypeError, ValueError):
            smtp_port = 587

        if not smtp_host:
            logger.error("[MAIL] Configuration SMTP incomplète (host manquant)")
            return False

        if not mail_from:
            logger.error("[MAIL] Adresse d'expéditeur introuvable")
            return False

        # --------------------------------------------------
        # 2) Construire plain + html
        # --------------------------------------------------
        if is_html:
            body_html_inner = body or ""
            body_plain = _html_to_plain(body_html_inner)
        else:
            body_html_inner = _normalize_body_to_html(body or "")
            body_plain = (body or "").strip()

        body_html = _wrap_email_html(body_html_inner, title="Stream Empire")

        # --------------------------------------------------
        # 3) Construire message multipart/alternative
        # --------------------------------------------------
        msg = EmailMessage()
        msg["From"] = mail_from
        msg["To"] = to_email
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        # texte d'abord, puis HTML
        msg.set_content(body_plain, subtype="plain", charset="utf-8")
        msg.add_alternative(body_html, subtype="html", charset="utf-8")

        recipients = [to_email]
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        # --------------------------------------------------
        # 4) Envoi SMTP
        # --------------------------------------------------
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if smtp_tls:
                    server.starttls()

                if smtp_user:
                    server.login(smtp_user, smtp_pass)

                server.send_message(msg, from_addr=mail_from, to_addrs=recipients)

            logger.info(f"[MAIL] Email envoyé à {to_email}")
            return True

        except Exception as e:
            logger.error(f"[MAIL] Erreur SMTP vers {to_email}: {e}", exc_info=True)
            return False








    # =====================================================================
    # ⚠️ START MONITORING ROUTES
    # =====================================================================

    @app.route("/monitoring")
    def monitoring_page():
        db = get_db()
        tab = request.args.get("tab", "overview")

        # Une session est considérée "live" si vue dans les 120 dernières secondes
        live_window_seconds = 120
        live_window_sql = f"-{live_window_seconds} seconds"

        # --------------------------
        # Serveurs (statuts) (utilisé partout)
        # --------------------------
        servers = db.query(
            """
            SELECT id, name, type, url, local_url, public_url, status, last_checked
            FROM servers
            WHERE type IN ('plex','jellyfin')
            ORDER BY type, name
            """
        )

        server_stats = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) AS online,
              SUM(CASE WHEN status='down' THEN 1 ELSE 0 END) AS offline,
              COUNT(*) AS total
            FROM servers
            WHERE type IN ('plex','jellyfin')
            """
        ) or {"online": 0, "offline": 0, "total": 0}
        server_stats = dict(server_stats) if server_stats else {"online": 0, "offline": 0, "total": 0}

        # --------------------------
        # Sessions live (overview)
        # --------------------------
        sessions_stats = db.query_one(
            """
            SELECT
              COUNT(*) AS live_sessions,
              SUM(CASE WHEN is_transcode = 1 THEN 1 ELSE 0 END) AS transcodes
            FROM media_sessions
            WHERE datetime(last_seen_at) >= datetime('now', ?)
            """,
            (live_window_sql,),
        ) or {"live_sessions": 0, "transcodes": 0}
        sessions_stats = dict(sessions_stats) if sessions_stats else {"live_sessions": 0, "transcodes": 0}

        sessions = db.query(
            """
            SELECT
              ms.id,
              ms.server_id,
              s.name AS server_name,
              s.type AS provider,

              ms.media_type,
              ms.title,
              ms.grandparent_title,
              ms.parent_title,

              ms.state,
              ms.client_name,
              mu.username AS username,
              ms.is_transcode,
              ms.last_seen_at,

              ms.raw_json,
              ms.media_key
            FROM media_sessions ms
            JOIN servers s ON s.id = ms.server_id
            LEFT JOIN media_users mu ON mu.id = ms.media_user_id
            WHERE datetime(ms.last_seen_at) >= datetime('now', ?)
            ORDER BY datetime(ms.last_seen_at) DESC
            """,
            (live_window_sql,),
        )

        # ------------------------------------------------------------------
        # Enrich Now Playing: SxxExx + jaquette (sans changer la DB)
        # ------------------------------------------------------------------
        def _safe_int(v):
            try:
                if v is None:
                    return None
                return int(v)
            except Exception:
                return None

        sessions = [dict(r) for r in sessions]

        for s in sessions:
            s["season_number"] = None
            s["episode_number"] = None
            s["episode_code"] = None
            s["poster_url"] = None

            raw = s.get("raw_json")
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                data = {}

            provider = (s.get("provider") or "").lower()

            # ---------- PLEX ----------
            if provider == "plex":
                attrs = (data.get("VideoOrTrack") or {})

                # Episode numbers (Plex XML attribs are stored in raw_json)
                # parentIndex = season number, index = episode number
                season = _safe_int(attrs.get("parentIndex"))
                episode = _safe_int(attrs.get("index"))

                s["season_number"] = season
                s["episode_number"] = episode

                if season is not None and episode is not None:
                    s["episode_code"] = f"S{season:02d}E{episode:02d}"
                elif season is not None:
                    s["episode_code"] = f"S{season}"

                # Poster path preference for series:
                # grandparentThumb (show poster) > parentThumb (season poster) > thumb (item)
                poster_path = (
                    attrs.get("grandparentThumb")
                    or attrs.get("parentThumb")
                    or attrs.get("thumb")
                )
                if poster_path:
                    s["poster_url"] = url_for(
                        "api_monitoring_poster",
                        server_id=s["server_id"],
                        path=poster_path,
                    )

            # ---------- JELLYFIN ----------
            elif provider == "jellyfin":
                now = (data.get("NowPlayingItem") or {})

                season = _safe_int(now.get("ParentIndexNumber"))
                episode = _safe_int(now.get("IndexNumber"))

                s["season_number"] = season
                s["episode_number"] = episode

                if season is not None and episode is not None:
                    s["episode_code"] = f"S{season:02d}E{episode:02d}"
                elif season is not None:
                    s["episode_code"] = f"S{season}"

                # Poster: for episodes, prefer SeriesId (show poster). fallback to item Id.
                poster_item_id = now.get("SeriesId") or now.get("Id") or s.get("media_key")
                if poster_item_id:
                    s["poster_url"] = url_for(
                        "api_monitoring_poster",
                        server_id=s["server_id"],
                        item_id=str(poster_item_id),
                    )


        events = db.query(
            """
            SELECT
              e.id,
              s.name AS server_name,
              e.provider,
              e.event_type,
              e.ts,
              e.title
            FROM media_events e
            JOIN servers s ON s.id = e.server_id
            ORDER BY e.ts DESC
            LIMIT 30
            """
        )

        # --------------------------
        # Stats 7d + tops
        # --------------------------
        stats_7d = db.query_one(
            """
            SELECT
              COUNT(*) AS sessions,
              COUNT(DISTINCT media_user_id) AS active_users,
              SUM(watch_ms) AS total_watch_ms,
              AVG(CASE WHEN watch_ms > 0 THEN watch_ms END) AS avg_watch_ms
            FROM media_session_history
            WHERE started_at >= datetime('now', '-7 days')
            """
        ) or {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}
        stats_7d = dict(stats_7d) if stats_7d else {"sessions": 0, "active_users": 0, "total_watch_ms": 0, "avg_watch_ms": 0}

        top_users_30d = db.query(
            """
            SELECT
              mu.username,
              COUNT(*) AS sessions,
              SUM(h.watch_ms) AS watch_ms
            FROM media_session_history h
            LEFT JOIN media_users mu ON mu.id = h.media_user_id
            WHERE h.started_at >= datetime('now', '-30 days')
            GROUP BY h.media_user_id
            ORDER BY watch_ms DESC
            LIMIT 10
            """
        )

        top_content_30d = db.query(
            """
            SELECT
              COALESCE(title, '-') AS title,
              COALESCE(grandparent_title, '') AS grandparent_title,
              COUNT(*) AS sessions,
              SUM(watch_ms) AS watch_ms
            FROM media_session_history
            WHERE started_at >= datetime('now', '-30 days')
            GROUP BY title, grandparent_title
            ORDER BY watch_ms DESC
            LIMIT 10
            """
        )

        # --------------------------
        # Peak streams (7d) = pic simultané "light"
        # bucket = 300s (5min). Pour encore + light -> 600 (10min)
        # --------------------------
        concurrent_7d = db.query_one(
            """
            WITH events AS (
              -- +1 au début
              SELECT
                (CAST(strftime('%s', started_at) AS INTEGER) / 300) * 300 AS bucket_ts,
                +1 AS delta
              FROM media_session_history
              WHERE started_at >= datetime('now', '-7 days')
                AND started_at IS NOT NULL

              UNION ALL

              -- -1 à la fin
              SELECT
                (CAST(strftime('%s', stopped_at) AS INTEGER) / 300) * 300 AS bucket_ts,
                -1 AS delta
              FROM media_session_history
              WHERE started_at >= datetime('now', '-7 days')
                AND stopped_at IS NOT NULL
            ),
            per_bucket AS (
              SELECT bucket_ts, SUM(delta) AS delta
              FROM events
              GROUP BY bucket_ts
            ),
            running AS (
              SELECT
                bucket_ts,
                SUM(delta) OVER (
                  ORDER BY bucket_ts
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS concurrent
              FROM per_bucket
            )
            SELECT MAX(concurrent) AS peak_streams
            FROM running
            """
        ) or {"peak_streams": 0}
        concurrent_7d = dict(concurrent_7d) if concurrent_7d else {"peak_streams": 0}

        # Sécurité UX : peak >= streams live actuels
        live_now = int(sessions_stats.get("live_sessions") or 0)
        peak = int(concurrent_7d.get("peak_streams") or 0)
        concurrent_7d["peak_streams"] = max(peak, live_now)

        sort_key = None
        sort_dir = None


        # --------------------------
        # Tabs data
        # --------------------------
        policies = []
        rows = []
        filters = {}
        pagination = None
        

        if tab == "history":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            q = (request.args.get("q") or "").strip()
            provider = (request.args.get("provider") or "").strip()
            media_type = (request.args.get("media_type") or "").strip()
            playback = (request.args.get("playback") or "").strip()
            server_id = request.args.get("server", type=int)

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "date").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "desc").strip().lower()

            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            # whitelist anti-injection SQL (IMPORTANT)
            SORT_MAP = {
                "date": "h.stopped_at",
                "user": "mu.username",
                "server": "s.name",
                "media": "h.title",
                "type": "h.media_type",
                "playback": "playback_type",   # alias défini dans SELECT
                "device": "h.device",
                "duration": "h.watch_ms",
            }
            if sort_key not in SORT_MAP:
                sort_key = "date"

            order_col = SORT_MAP[sort_key]
            order_sql = f"{order_col} {'ASC' if sort_dir == 'asc' else 'DESC'}"


            where = ["1=1"]
            params = []

            if q:
                where.append("(h.title LIKE ? OR h.grandparent_title LIKE ?)")
                params += [f"%{q}%", f"%{q}%"]
            if provider:
                where.append("s.type = ?")
                params.append(provider)
            if media_type:
                where.append("h.media_type = ?")
                params.append(media_type)
            if playback:
                pb = playback.lower()
                if pb in ("transcode", "transcoding"):
                    where.append("h.was_transcode = 1")
                elif pb in ("directplay", "direct", "direct_play"):
                    where.append("h.was_transcode = 0")
            if server_id:
                where.append("h.server_id = ?")
                params.append(server_id)

            where_sql = " AND ".join(where)

            total = db.query_one(
                f"""
                SELECT COUNT(*) AS cnt
                FROM media_session_history h
                JOIN servers s ON s.id = h.server_id
                WHERE {where_sql}
                """,
                tuple(params),
            ) or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            rows = db.query(
                f"""
                SELECT
                  h.stopped_at,
                  s.name AS server_name,
                  s.type AS provider,
                  mu.username,
                  h.title,
                  h.grandparent_title,
                  h.media_type,
                  CASE WHEN h.was_transcode = 1 THEN 'transcode' ELSE 'directplay' END AS playback_type,
                  h.device,
                  h.client_name,
                  h.watch_ms
                FROM media_session_history h
                JOIN servers s ON s.id = h.server_id
                LEFT JOIN media_users mu ON mu.id = h.media_user_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                tuple(params + [offset]),
            )

            rows = [dict(r) for r in rows]
            for r in rows:
                ms = r.get("watch_ms") or 0
                r["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

            total_rows = int(total.get("cnt") or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["tab"] = "history"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
            }

            filters = {
                "q": q,
                "provider": provider,
                "media_type": media_type,
                "playback": playback,
                "server": server_id,
            }

        elif tab == "users":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            total = db.query_one(
                """
                SELECT COUNT(DISTINCT media_user_id) AS cnt
                FROM media_session_history
                WHERE media_user_id IS NOT NULL
                """
            ) or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "last").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "desc").strip().lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"

            SORT_MAP = {
                "user": "mu.username",
                "last": "lr.last_watch_at",
                "plays": "a.total_plays",
                "watch": "a.watch_ms",
                "ip": "lr.ip",
                # on trie sur une expression stable (comme l’affichage)
                "platform": "COALESCE(lr.device, lr.client_product, '-')",
                "player": "COALESCE(lr.client_name, lr.client_product, '-')",
            }
            if sort_key not in SORT_MAP:
                sort_key = "last"

            # SQLite n’a pas toujours NULLS LAST => petit hack portable:
            col = SORT_MAP[sort_key]
            direction = "ASC" if sort_dir == "asc" else "DESC"
            order_sql = f"({col} IS NULL) ASC, {col} {direction}"

            rows = db.query(
                f"""
                WITH ranked AS (
                  SELECT
                    h.media_user_id,
                    h.stopped_at,
                    h.ip,
                    h.device,
                    h.client_name,
                    h.client_product,
                    ROW_NUMBER() OVER (
                      PARTITION BY h.media_user_id
                      ORDER BY h.stopped_at DESC
                    ) AS rn
                  FROM media_session_history h
                  WHERE h.media_user_id IS NOT NULL
                ),
                last_rows AS (
                  SELECT
                    media_user_id,
                    stopped_at AS last_watch_at,
                    ip,
                    device,
                    client_name,
                    client_product
                  FROM ranked
                  WHERE rn = 1
                ),
                agg AS (
                  SELECT
                    h.media_user_id,
                    COUNT(*) AS total_plays,
                    SUM(h.watch_ms) AS watch_ms
                  FROM media_session_history h
                  WHERE h.media_user_id IS NOT NULL
                  GROUP BY h.media_user_id
                )
                SELECT
                  mu.id AS user_id,
                  mu.username,
                  mu.type AS provider,
                  mu.server_id,
                  lr.last_watch_at,
                  a.total_plays,
                  a.watch_ms,
                  lr.ip AS last_ip,
                  COALESCE(lr.device, lr.client_product, '-') AS platform,
                  COALESCE(lr.client_name, lr.client_product, '-') AS player
                FROM last_rows lr
                JOIN agg a ON a.media_user_id = lr.media_user_id
                JOIN media_users mu ON mu.id = lr.media_user_id
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                (offset,),
            )

            rows = [dict(r) for r in rows]
            for u in rows:
                ms = u.get("watch_ms") or 0
                u["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"
                if not u.get("last_ip"):
                    u["last_ip"] = "-"


        elif tab == "policies":
            policies = db.query("""
                SELECT
                  p.*,
                  s.name AS server_name
                FROM stream_policies p
                LEFT JOIN servers s ON s.id = p.server_id
                ORDER BY p.is_enabled DESC, p.priority ASC, p.id DESC
            """)
            policies = [dict(r) for r in policies]


        elif tab == "libraries":
            page = request.args.get("page", type=int, default=1)
            per_page = 30
            offset = (page - 1) * per_page

            total = db.query_one("SELECT COUNT(*) AS cnt FROM libraries") or {"cnt": 0}
            total = dict(total) if total else {"cnt": 0}

            cookie_sort = request.cookies.get(f"monitoring_{tab}_sort")
            cookie_dir  = request.cookies.get(f"monitoring_{tab}_dir")

            sort_key = (request.args.get("sort") or cookie_sort or "last").strip()
            sort_dir = (request.args.get("dir") or cookie_dir or "asc").strip().lower()

            if sort_dir not in ("asc", "desc"):
                sort_dir = "asc"

            SORT_MAP = {
                "server": "s.name",
                "library": "l.name",
                "type": "l.type",
                "items": "l.item_count",
                "last": "last_stream_at",
                "plays": "total_plays",
                "duration": "played_ms",
            }

            if sort_key not in SORT_MAP:
                sort_key = "server"

            order_sql = f"{SORT_MAP[sort_key]} {'ASC' if sort_dir == 'asc' else 'DESC'}"

            rows = db.query(
                f"""
                SELECT
                  l.name AS library_name,
                  s.name AS server_name,
                  l.type AS media_type,

                  l.item_count AS item_count,

                  (
                    SELECT MAX(h.stopped_at)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS last_stream_at,

                  (
                    SELECT COUNT(*)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS total_plays,

                  (
                    SELECT COALESCE(SUM(h.watch_ms), 0)
                    FROM media_session_history h
                    WHERE h.server_id = l.server_id
                      AND h.library_section_id = l.section_id
                  ) AS played_ms

                FROM libraries l
                JOIN servers s ON s.id = l.server_id
                ORDER BY {order_sql}
                LIMIT {per_page} OFFSET ?
                """,
                (offset,),
            )


            rows = [dict(r) for r in rows]
            for r in rows:
                ms = r.get("played_ms") or 0
                r["played_duration"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

            total_rows = int(total.get("cnt") or 0)
            total_pages = max(1, (total_rows + per_page - 1) // per_page)

            def build_url(p):
                args = dict(request.args)
                args["tab"] = "libraries"
                args["page"] = p
                return url_for("monitoring_page", **args)

            pagination = {
                "page": page,
                "total_pages": total_pages,
                "total_rows": total_rows,
                "prev_url": build_url(page - 1),
                "next_url": build_url(page + 1),
            }

        # ------------------------------------------------------------------
        # HTMX: si requête dynamique, on renvoie uniquement le contenu de l’onglet
        # ------------------------------------------------------------------
        is_hx = bool(request.headers.get("HX-Request"))
        if is_hx:
            tab_tpl = {
                "overview": "monitoring/overview_body.html",
                "policies": "monitoring/tabs/policies.html",
                "activity": "monitoring/tabs/activity.html",
                "history": "monitoring/tabs/history.html",
                "libraries": "monitoring/tabs/libraries.html",
                "users": "monitoring/tabs/users.html",
            }.get(tab, "monitoring/overview_body.html")

            resp = make_response(render_template(
                tab_tpl,
                active_page="monitoring",
                tab=tab,
                servers=servers,
                server_stats=server_stats,
                sessions_stats=sessions_stats,
                sessions=sessions,
                events=events,
                live_window_seconds=live_window_seconds,
                stats_7d=stats_7d,
                top_users_30d=top_users_30d,
                top_content_30d=top_content_30d,
                concurrent_7d=concurrent_7d,
                rows=rows,
                filters=filters,
                pagination=pagination,
                sort_key=sort_key,
                sort_dir=sort_dir,
                policies=policies,
            ))
            if sort_key and sort_dir:
                resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
                resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)

            return resp

        # Page complète (chargement normal)
        resp = make_response(render_template(
            "monitoring/monitoring.html",
            active_page="monitoring",
            tab=tab,
            servers=servers,
            server_stats=server_stats,
            sessions_stats=sessions_stats,
            sessions=sessions,
            events=events,
            live_window_seconds=live_window_seconds,
            stats_7d=stats_7d,
            top_users_30d=top_users_30d,
            top_content_30d=top_content_30d,
            concurrent_7d=concurrent_7d,
            rows=rows,
            filters=filters,
            pagination=pagination,
            sort_key=sort_key,
            sort_dir=sort_dir,
            policies=policies,
        ))
        
        if sort_key and sort_dir:
            resp.set_cookie(f"monitoring_{tab}_sort", str(sort_key), max_age=60*60*24*365)
            resp.set_cookie(f"monitoring_{tab}_dir",  str(sort_dir),  max_age=60*60*24*365)
        return resp

    @app.route("/api/monitoring/poster/<int:server_id>")
    def api_monitoring_poster(server_id: int):
        db = get_db()
        srv = db.query_one(
            """
            SELECT id, type, url, local_url, public_url, token
            FROM servers
            WHERE id = ?
              AND type IN ('plex','jellyfin')
            LIMIT 1
            """,
            (server_id,),
        )
        if not srv:
            abort(404)

        srv = dict(srv)
        stype = (srv.get("type") or "").lower()
        token = srv.get("token")
        if not token:
            abort(404)

        # url > local_url > public_url
        bases = []
        for u in (srv.get("url"), srv.get("local_url"), srv.get("public_url")):
            if u and str(u).strip():
                b = str(u).strip().rstrip("/")
                if b not in bases:
                    bases.append(b)

        if not bases:
            abort(502)

        def _try_get(full_url, headers=None, params=None):
            r = requests.get(full_url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            return r

        # ---------------- PLEX ----------------
        if stype == "plex":
            path = request.args.get("path")
            if not path:
                abort(400)

            if not path.startswith("/"):
                path = "/" + path

            params = {"X-Plex-Token": token}

            last_err = None
            for base in bases:
                try:
                    r = _try_get(base + path, params=params)
                    ct = r.headers.get("Content-Type") or "image/jpeg"
                    return Response(
                        r.content,
                        mimetype=ct,
                        headers={"Cache-Control": "public, max-age=300"},
                    )
                except Exception as e:
                    last_err = e
                    continue

            abort(502)

        # --------------- JELLYFIN --------------
        if stype == "jellyfin":
            item_id = request.args.get("item_id")
            if not item_id:
                abort(400)

            # small poster size by default
            w = request.args.get("w", "120")
            q = request.args.get("q", "90")

            path = f"/Items/{item_id}/Images/Primary"
            params = {"maxWidth": w, "quality": q}
            headers = {"X-Emby-Token": token}

            last_err = None
            for base in bases:
                try:
                    r = _try_get(base + path, headers=headers, params=params)
                    ct = r.headers.get("Content-Type") or "image/jpeg"
                    return Response(
                        r.content,
                        mimetype=ct,
                        headers={"Cache-Control": "public, max-age=300"},
                    )
                except Exception as e:
                    last_err = e
                    continue

            abort(502)

        abort(404)


    # =====================================================================
    # ⚠️ END MONITORING ROUTES
    # =====================================================================

    @app.route("/monitoring/user/<int:user_id>")
    def monitoring_user_detail(user_id: int):
        db = get_db()

        # Stats user global
        u = db.query_one(
            """
            SELECT
              mu.id,
              mu.username,
              mu.type,
              mu.server_id
            FROM media_users mu
            WHERE mu.id = ?
            """,
            (user_id,),
        )
        if not u:
            flash("invalid_user", "error")
            return redirect(url_for("monitoring_page", tab="users"))

        agg = db.query_one(
            """
            SELECT
              COUNT(*) AS total_plays,
              SUM(watch_ms) AS watch_ms,
              MAX(stopped_at) AS last_watch_at
            FROM media_session_history
            WHERE media_user_id = ?
            """,
            (user_id,),
        ) or {"total_plays": 0, "watch_ms": 0, "last_watch_at": None}

        agg = dict(agg) if agg else {"total_plays":0,"watch_ms":0,"last_watch_at":None}
        ms = agg.get("watch_ms") or 0
        u["total_plays"] = agg.get("total_plays") or 0
        u["last_watch_at"] = agg.get("last_watch_at")
        u["watch_time"] = f"{ms // 3600000}h {((ms % 3600000) // 60000)}m"

        # History paginé
        page = request.args.get("page", type=int, default=1)
        per_page = 30
        offset = (page - 1) * per_page
        q = (request.args.get("q") or "").strip()

        where = ["h.media_user_id = ?"]
        params = [user_id]

        if q:
            where.append("(h.title LIKE ? OR h.grandparent_title LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]

        where_sql = " AND ".join(where)

        total = db.query_one(
            f"""
            SELECT COUNT(*) AS cnt
            FROM media_session_history h
            WHERE {where_sql}
            """,
            tuple(params),
        ) or {"cnt": 0}

        rows = db.query(
            f"""
            SELECT
              h.stopped_at,
              s.name AS server_name,
              s.type AS provider,
              h.title,
              h.grandparent_title,
              h.media_type,
              CASE WHEN h.was_transcode = 1 THEN 'transcode' ELSE 'directplay' END AS playback_type,
              h.device,
              h.client_name,
              h.watch_ms,
              h.raw_json
            FROM media_session_history h
            JOIN servers s ON s.id = h.server_id
            WHERE {where_sql}
            ORDER BY h.stopped_at DESC
            LIMIT {per_page} OFFSET ?
            """,
            tuple(params + [offset]),
        )

        # parse ip from raw_json if possible (sinon "-")
        import json as _json
        for r in rows:
            ms2 = r.get("watch_ms") or 0
            r["watch_time"] = f"{ms2 // 3600000}h {((ms2 % 3600000) // 60000)}m"
            r["ip"] = "-"
            try:
                raw = r.get("raw_json")
                if raw:
                    j = _json.loads(raw)
                    # best-effort: plex/jellyfin variants
                    r["ip"] = j.get("ip") or j.get("IPAddress") or j.get("RemoteEndPoint") or "-"
            except Exception:
                pass

        total_rows = int(total["cnt"])
        total_pages = max(1, (total_rows + per_page - 1) // per_page)

        def build_url(p):
            args = dict(request.args)
            args["page"] = p
            return url_for("monitoring_user_detail", user_id=user_id, **args)

        pagination = {
            "page": page,
            "total_pages": total_pages,
            "total_rows": total_rows,
            "prev_url": build_url(page - 1),
            "next_url": build_url(page + 1),
        }

        return render_template(
            "monitoring/user_detail.html",
            active_page="monitoring",
            tab="users",
            user=u,
            rows=rows,
            q=q,
            pagination=pagination,
        )


    @app.route("/monitoring/session/<int:session_row_id>")
    def monitoring_session_detail(session_row_id: int):
        db = get_db()

        sess = db.query_one(
            """
            SELECT
              ms.*,
              s.name AS server_name,
              s.type AS provider,
              mu.username AS username
            FROM media_sessions ms
            JOIN servers s ON s.id = ms.server_id
            LEFT JOIN media_users mu ON mu.id = ms.media_user_id
            WHERE ms.id = ?
            """,
            (session_row_id,),
        )

        if not sess:
            flash("monitoring.session_not_found", "error")
            return redirect(url_for("monitoring_page"))

        events = db.query(
            """
            SELECT id, event_type, ts, payload_json
            FROM media_events
            WHERE server_id = ?
              AND session_key = ?
            ORDER BY ts DESC
            LIMIT 30
            """,
            (sess["server_id"], sess["session_key"]),
        )

        return render_template(
            "monitoring/session_detail.html",
            active_page="monitoring",
            sess=sess,
            events=events,
        )

    @app.post("/monitoring/policies/create")
    def stream_policy_create():
        db = get_db()

        rule_type = request.form.get("rule_type", "").strip()
        scope_type = request.form.get("scope_type", "global").strip()
        scope_id_raw = (request.form.get("scope_id") or "").strip()
        provider = (request.form.get("provider") or "").strip() or None
        server_id_raw = (request.form.get("server_id") or "").strip()
        priority = int((request.form.get("priority") or "100").strip() or 100)
        is_enabled = 1 if (request.form.get("is_enabled") or "1") == "1" else 0

        scope_id = int(scope_id_raw) if scope_id_raw.isdigit() else None
        server_id = int(server_id_raw) if server_id_raw.isdigit() else None

        selector = (request.form.get("selector") or "kill_newest").strip()
        warn_title = (request.form.get("warn_title") or "Stream limit").strip()
        warn_text = (request.form.get("warn_text") or "You reached your limit. If this continues, the most recent stream will be stopped.").strip()

        max_value = (request.form.get("max_value") or "").strip()
        max_kbps = (request.form.get("max_kbps") or "").strip()
        allowed_devices = (request.form.get("allowed_devices") or "").strip()

        rule = {
            "selector": selector,
            "warn_title": warn_title,
            "warn_text": warn_text,
        }

        # attach rule-specific fields
        if rule_type in ("max_streams_per_user", "max_transcodes_global", "max_streams_per_ip", "max_ips_per_user"):
            rule["max"] = int(max_value) if max_value.isdigit() else 1

        # options IP
        if rule_type in ("max_streams_per_ip", "max_ips_per_user"):
            rule["ignore_unknown"] = True
            rule["per_server"] = True



        if rule_type == "max_bitrate_kbps":
            rule["max_kbps"] = int(max_kbps) if max_kbps.isdigit() else 20000

        if rule_type == "device_allowlist":
            allowed = []
            if allowed_devices:
                allowed = [x.strip() for x in allowed_devices.split(",") if x.strip()]
            rule["allowed"] = allowed

        if rule_type == "ban_4k_transcode":
            # rien de plus requis
            pass

        db.execute("""
            INSERT INTO stream_policies(scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, rule_value_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (scope_type, scope_id, provider, server_id, is_enabled, priority, rule_type, json.dumps(rule)))

        # ✅ Auto-enable stream_enforcer si la policy est activée
        if is_enabled == 1:
            db.execute("""
                UPDATE tasks
                SET enabled = 1,
                    status = CASE WHEN status = 'disabled' THEN 'idle' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = 'stream_enforcer'
            """)


        flash("Policy created", "success")
        return redirect(url_for("monitoring_page", tab="policies"))


    @app.post("/monitoring/policies/<int:policy_id>/delete")
    def stream_policy_delete(policy_id: int):
        db = get_db()
        db.execute("DELETE FROM stream_policies WHERE id=?", (policy_id,))
        flash("Policy deleted", "success")
        return redirect(url_for("monitoring_page", tab="policies"))










    @app.route("/api/tasks/list", methods=["GET"])
    def api_tasks_list():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"tasks": []}

        t = get_translator()

        rows = db.query(
            """
            SELECT
                id,
                name,
                description,
                schedule,
                status,
                enabled,
                last_run,
                next_run
            FROM tasks
            ORDER BY name
            """
        )

        tasks = []
        for r in rows:
            name = r["name"]
            desc = r["description"]

            # Labels comme dans tasks.html:
            # {{ t("task." ~ task.name) or task.name }}
            # {{ t("task_description." ~ task.name) or task.description or "-" }}
            name_label = t(f"task.{name}") or name
            desc_label = t(f"task_description.{name}") or (desc or "-")

            schedule = r["schedule"] or ""
            schedule_human = cron_human(schedule) if schedule else "-"

            last_run_human = tz_filter(r["last_run"]) if r["last_run"] else "-"
            next_run_human = tz_filter(r["next_run"]) if r["next_run"] else "-"

            tasks.append({
                "id": r["id"],
                "name": name,
                "description": desc,
                "schedule": schedule,
                "status": r["status"],
                "enabled": bool(r["enabled"]),
                "name_label": name_label,
                "description_label": desc_label,
                "schedule_human": schedule_human,
                "last_run_human": last_run_human,
                "next_run_human": next_run_human,
            })

        return {"tasks": tasks}



    @app.route("/api/tasks/activity", methods=["GET"])
    def api_tasks_activity():
        db = get_db()

        if not table_exists(db, "tasks"):
            return {"active": 0, "running": 0, "queued": 0}

        row = db.query_one(
            """
            SELECT
              SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
              SUM(CASE WHEN status = 'queued'  THEN 1 ELSE 0 END) AS queued
            FROM tasks
            WHERE status IN ('running', 'queued')
            """
        )

        if row is None:
            return {"active": 0, "running": 0, "queued": 0}

        running = row["running"] or 0
        queued  = row["queued"]  or 0
        active  = running + queued

        return {
            "active": active,
            "running": running,
            "queued": queued
        }







    # -----------------------------
    # ROUTES
    # -----------------------------
    @app.route("/")
    def dashboard():
        db = get_db()

        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))


        # --------------------------
        # USER STATS (legacy: stats)
        # --------------------------
        stats = {}

        stats["total_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users"
        )["cnt"] or 0

        stats["active_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status = 'active'"
        )["cnt"] or 0

        # expiring soon = reminder + pre_expired (legacy view)
        stats["expiring_soon"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status IN ('pre_expired', 'reminder')"
        )["cnt"] or 0

        stats["expired_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM vodum_users WHERE status = 'expired'"
        )["cnt"] or 0

        # --------------------------
        # USER STATS (new: users_stats used by dashboard.html)
        # --------------------------
        row = db.query_one(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN status = 'pre_expired' THEN 1 ELSE 0 END) AS pre_expired,
              SUM(CASE WHEN status = 'reminder' THEN 1 ELSE 0 END) AS reminder,
              SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired
            FROM vodum_users
            """
        )

        # db.query_one renvoie souvent sqlite3.Row -> pas de .get()
        row = dict(row) if row else {}

        users_stats = {
            "total": int(row.get("total") or 0),
            "active": int(row.get("active") or 0),
            "pre_expired": int(row.get("pre_expired") or 0),
            "reminder": int(row.get("reminder") or 0),
            "expired": int(row.get("expired") or 0),
        }

        # --------------------------
        # SERVER STATS (tous types)
        # --------------------------
        stats["server_types"] = {}

        server_types = db.query(
            """
            SELECT DISTINCT type
            FROM servers
            WHERE type IS NOT NULL AND type != ''
            ORDER BY type
            """
        )

        for row in server_types:
            stype = row["type"]

            total = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ?",
                (stype,),
            )["cnt"] or 0

            online = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'up'",
                (stype,),
            )["cnt"] or 0

            offline = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'down'",
                (stype,),
            )["cnt"] or 0

            stats["server_types"][stype] = {
                "total": int(total),
                "online": int(online),
                "offline": int(offline),
            }

        # --------------------------
        # TASK STATS
        # --------------------------
        if table_exists(db, "tasks"):
            stats["total_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks"
            )["cnt"] or 0

            stats["active_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE enabled = 1"
            )["cnt"] or 0

            stats["error_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE status = 'error'"
            )["cnt"] or 0
        else:
            stats["total_tasks"] = 0
            stats["active_tasks"] = 0
            stats["error_tasks"] = 0

        # --------------------------
        # SERVER LIST (tous types)
        # --------------------------
        servers = db.query(
            """
            SELECT
                s.id,
                s.name,
                s.type,
                COALESCE(s.url, s.local_url, s.public_url) AS url,
                s.status,
                s.last_checked
            FROM servers s
            ORDER BY s.type, s.name
            """
        )

        # --------------------------
        # LATEST LOGS (fichier)
        # --------------------------
        latest_logs = []

        lines = read_last_logs(30)  # on lit plus large, on filtre après
        ALLOWED_LEVELS = {"INFO", "ERROR", "CRITICAL"}

        for line in lines:
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue

            level = parts[1].strip().upper()
            if level not in ALLOWED_LEVELS:
                continue

            latest_logs.append({
                "created_at": parts[0].strip(),
                "level": level,
                "source": parts[2].strip(),
                "message": parts[3].strip(),
            })

        latest_logs = latest_logs[:10]

        # --------------------------
        # PAGE RENDERING
        # --------------------------
        return render_template(
            "dashboard/dashboard.html",
            stats=stats,              # ✅ conservé (rien perdu)
            users_stats=users_stats,  # ✅ nouveau (pour ton template)
            servers=servers,
            latest_logs=latest_logs,
            active_page="dashboard",
        )




    # -----------------------------
    # UTILISATEURS
    # -----------------------------

    def get_user_servers_with_access(vodum_user_id):
        """
        Retourne les serveurs associés à un utilisateur VODUM, avec
        la liste des bibliothèques auxquelles ses comptes media ont accès.
        """

        db = get_db()

        server_list = []

        # --------------------------------------------------
        # 1) Serveurs sur lesquels l'utilisateur possède un media_user
        # --------------------------------------------------
        servers = db.query(
            """
            SELECT DISTINCT s.*
            FROM servers s
            JOIN media_users mu ON mu.server_id = s.id
            WHERE mu.vodum_user_id = ?
            ORDER BY s.name
            """,
            (vodum_user_id,),
        )

        for s in servers:

            # --------------------------------------------------
            # 2) Bibliothèques accessibles via ses comptes media
            # --------------------------------------------------
            libraries = db.query(
                """
                SELECT DISTINCT l.*
                FROM libraries l
                JOIN media_user_libraries mul ON mul.library_id = l.id
                JOIN media_users mu ON mu.id = mul.media_user_id
                WHERE mu.vodum_user_id = ?
                  AND l.server_id = ?
                ORDER BY l.name
                """,
                (vodum_user_id, s["id"]),
            )

            server_list.append({
                "server": s,
                "libraries": libraries,
            })

        return server_list
    


            
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

        def contains_bonus(token: str, field: str, weight: int):
            nonlocal score
            if not token or not field:
                return
            if token == field:
                score += weight + 120          # exact match
            elif field.startswith(token):
                score += weight + 70           # startswith
            elif token in field:
                score += weight + 40           # contains

        # champs à scorer fortement
        for t in tokens:
            contains_bonus(t, c_user, 120)     # username est très discriminant
            contains_bonus(t, c_fn,   90)
            contains_bonus(t, c_ln,   90)
            contains_bonus(t, c_em,   80)
            contains_bonus(t, c_em2,  60)

        # ---- 3) Fuzzy léger en complément (pas le coeur du score)
        score += int(25 * _sim(u_user, c_user))
        score += int(20 * _sim(u_fn, c_fn))
        score += int(20 * _sim(u_ln, c_ln))

        # ---- 4) petit bonus si même domaine email
        if "@" in u_em and "@" in c_em:
            if u_em.split("@", 1)[1] == c_em.split("@", 1)[1]:
                score += 10

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


    @app.route("/users/<int:user_id>", methods=["GET", "POST"])
    def user_detail(user_id):
        db = get_db()

        # --------------------------------------------------
        # Charger l’utilisateur (VODUM)
        # --------------------------------------------------
        user = db.query_one(
            "SELECT * FROM vodum_users WHERE id = ?",
            (user_id,),
        )

        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        # on convertit en dict pour éviter les surprises sqlite3.Row
        user = dict(user)

        # --------------------------------------------------
        # Types de serveurs réellement liés à l'utilisateur
        # (basé sur media_users + servers)
        # --------------------------------------------------
        allowed_types = [
            row["type"]
            for row in db.query(
                """
                SELECT DISTINCT s.type
                FROM servers s
                JOIN media_users mu ON mu.server_id = s.id
                WHERE mu.vodum_user_id = ?
                """,
                (user_id,),
            )
            if row["type"]
        ]

        # ==================================================
        # POST → Mise à jour utilisateur + options + jobs plex
        # ==================================================
        if request.method == "POST":
            form = request.form

            firstname       = form.get("firstname") or user.get("firstname")
            lastname        = form.get("lastname") or user.get("lastname")
            second_email    = form.get("second_email") or user.get("second_email")
            expiration_date = form.get("expiration_date") or user.get("expiration_date")
            renewal_date    = form.get("renewal_date") or user.get("renewal_date")
            renewal_method  = form.get("renewal_method") or user.get("renewal_method")
            notes           = form.get("notes") if "notes" in form else user.get("notes")

            # --- MAJ infos Vodum ---
            db.execute(
                """
                UPDATE vodum_users
                SET firstname = ?, lastname = ?, second_email = ?,
                    renewal_date = ?, renewal_method = ?, notes = ?
                WHERE id = ?
                """,
                (
                    firstname, lastname, second_email,
                    renewal_date, renewal_method, notes,
                    user_id,
                ),
            )

            # Gestion expiration (vodum_users.expiration_date est contractuel)
            if expiration_date != user.get("expiration_date"):
                update_user_expiration(
                    user_id,
                    expiration_date,
                    reason="ui_manual",
                )

            # ------------------------------------------------------------------
            # Helper pour répliquer les flags Plex sur serveurs même owner
            # ------------------------------------------------------------------
            def replicate_plex_flags_same_owner(db, vodum_user_id: int, changed_mu_id: int, plex_share_new: dict):
                """
                Réplique allowSync/allowCameraUpload/allowChannels + filtres sur tous les serveurs Plex
                qui partagent le même owner (approché par même servers.token).
                """
                # serveur lié à ce media_user
                row = db.query_one("SELECT server_id FROM media_users WHERE id = ?", (changed_mu_id,))
                if not row:
                    return
                changed_server_id = int(row["server_id"])

                # token du serveur => proxy owner
                srv = db.query_one("SELECT token FROM servers WHERE id = ?", (changed_server_id,))
                if not srv:
                    return
                srv = dict(srv)
                owner_token = srv.get("token")
                if not owner_token:
                    return

                # tous les serveurs plex du même owner
                owner_servers = db.query(
                    "SELECT id FROM servers WHERE type='plex' AND token = ?",
                    (owner_token,),
                )
                owner_server_ids = [int(s["id"]) for s in owner_servers]
                if not owner_server_ids:
                    return

                placeholders = ",".join(["?"] * len(owner_server_ids))

                rows = db.query(
                    f"""
                    SELECT mu.id, mu.details_json
                    FROM media_users mu
                    JOIN servers s ON s.id = mu.server_id
                    WHERE mu.vodum_user_id = ?
                      AND s.type = 'plex'
                      AND mu.type = 'plex'
                      AND mu.server_id IN ({placeholders})
                    """,
                    (vodum_user_id, *owner_server_ids),
                )

                for r in rows:
                    mu_id2 = int(r["id"])
                    try:
                        details2 = json.loads(r["details_json"] or "{}")
                    except Exception:
                        details2 = {}

                    if not isinstance(details2, dict):
                        details2 = {}

                    plex_share2 = details2.get("plex_share", {})
                    if not isinstance(plex_share2, dict):
                        plex_share2 = {}

                    # réplique les champs qui doivent être identiques pour un même owner
                    for k in ("allowSync", "allowCameraUpload", "allowChannels", "filterMovies", "filterTelevision", "filterMusic"):
                        if k in plex_share_new:
                            plex_share2[k] = plex_share_new[k]

                    details2["plex_share"] = plex_share2

                    db.execute(
                        "UPDATE media_users SET details_json = ? WHERE id = ?",
                        (json.dumps(details2, ensure_ascii=False), mu_id2),
                    )

            # -----------------------------------------------
            # Sauvegarde des options Plex en JSON (details_json)
            # -> 1 details_json par media_user (donc par serveur)
            # -----------------------------------------------
            plex_media = db.query(
                """
                SELECT mu.id, mu.details_json
                FROM media_users mu
                JOIN servers s ON s.id = mu.server_id
                WHERE mu.vodum_user_id = ?
                  AND s.type = 'plex'
                  AND mu.type = 'plex'
                """,
                (user_id,),
            )

            truthy = {"1", "true", "on", "yes"}

            for mu in plex_media:
                mu_id = int(mu["id"])

                # Charge le JSON existant
                try:
                    details = json.loads(mu["details_json"] or "{}")
                except Exception:
                    details = {}

                if not isinstance(details, dict):
                    details = {}

                plex_share = details.get("plex_share", {})
                if not isinstance(plex_share, dict):
                    plex_share = {}

                # allowSync
                vals = form.getlist(f"allow_sync_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_sync getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowSync"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowSync"] = int(plex_share.get("allowSync", 0) or 0)

                # allowCameraUpload
                vals = form.getlist(f"allow_camera_upload_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_camera_upload getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowCameraUpload"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowCameraUpload"] = int(plex_share.get("allowCameraUpload", 0) or 0)

                # allowChannels
                vals = form.getlist(f"allow_channels_{mu_id}")
                task_logger.debug(f"FORM DEBUG mu_id={mu_id} allow_channels getlist={vals}")
                v = vals[-1] if vals else None
                if v is not None:
                    plex_share["allowChannels"] = 1 if str(v).strip().lower() in truthy else 0
                else:
                    plex_share["allowChannels"] = int(plex_share.get("allowChannels", 0) or 0)

                plex_share["filterMovies"] = (form.get(f"filter_movies_{mu_id}") or "").strip()
                plex_share["filterTelevision"] = (form.get(f"filter_television_{mu_id}") or "").strip()
                plex_share["filterMusic"] = (form.get(f"filter_music_{mu_id}") or "").strip()

                details["plex_share"] = plex_share

                db.execute(
                    "UPDATE media_users SET details_json = ? WHERE id = ?",
                    (json.dumps(details, ensure_ascii=False), mu_id),
                )

                # Réplication même owner
                replicate_plex_flags_same_owner(
                    db,
                    vodum_user_id=user_id,
                    changed_mu_id=mu_id,
                    plex_share_new=plex_share,
                )

            # -----------------------------------------------
            # SYNC Plex : pour chaque serveur plex lié à cet user,
            # créer un job compatible apply_plex_access_updates (media_jobs)
            # -----------------------------------------------
            if "plex" in allowed_types:
                plex_media_for_jobs = db.query(
                    """
                    SELECT mu.id, mu.server_id
                    FROM media_users mu
                    JOIN servers s ON s.id = mu.server_id
                    WHERE mu.vodum_user_id = ?
                      AND s.type = 'plex'
                      AND mu.type = 'plex'
                    """,
                    (user_id,),
                )

                # On déduplique par serveur : un sync par serveur suffit (il applique toutes les libs de l'user)
                plex_server_ids = sorted({int(mu["server_id"]) for mu in plex_media_for_jobs if mu["server_id"] is not None})

                for server_id in plex_server_ids:
                    dedupe_key = f"plex:sync:server={server_id}:vodum_user={user_id}:user_detail_save"

                    payload = {
                        "reason": "user_detail_save",
                        "updated_options": True,
                    }

                    db.execute(
                        """
                        INSERT OR IGNORE INTO media_jobs(
                            provider, action,
                            vodum_user_id, server_id, library_id,
                            payload_json,
                            processed, success, attempts,
                            dedupe_key
                        )
                        VALUES(
                            'plex', 'sync',
                            ?, ?, NULL,
                            ?,
                            0, 0, 0,
                            ?
                        )
                        """,
                        (user_id, server_id, json.dumps(payload, ensure_ascii=False), dedupe_key),
                    )

                # Activer + queue apply_plex_access_updates
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = 1, status = 'queued'
                    WHERE name = 'apply_plex_access_updates'
                    """
                )

                try:
                    row = db.query_one("SELECT id FROM tasks WHERE name='apply_plex_access_updates'")
                    if row:
                        enqueue_task(row["id"])
                except Exception:
                    # pas bloquant si enqueue échoue
                    pass

            flash("user_saved", "success")
            return redirect(url_for("user_detail", user_id=user_id))

        # ==================================================
        # GET → Chargement infos complètes
        # ==================================================

        servers = db.query(
            """
            SELECT
                s.*,
                s.id AS server_id,

                mu.id AS media_user_id,
                mu.external_user_id,
                mu.username AS media_username,
                mu.email AS media_email,
                mu.avatar AS media_avatar,
                mu.type AS media_type,
                mu.role AS media_role,
                mu.joined_at,
                mu.accepted_at,
                mu.details_json,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM media_user_libraries mul
                        WHERE mul.media_user_id = mu.id
                        LIMIT 1
                    ) THEN 1
                    ELSE 0
                END AS has_access
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.vodum_user_id = ?
            ORDER BY s.type, s.name
            """,
            (user_id,),
        )

        enriched = []
        for row in servers:
            r = dict(row)

            # defaults pour le template
            r["allow_sync"] = 0
            r["allow_camera_upload"] = 0
            r["allow_channels"] = 0
            r["filter_movies"] = ""
            r["filter_television"] = ""
            r["filter_music"] = ""

            try:
                details = json.loads(r.get("details_json") or "{}")
            except Exception:
                details = {}

            if not isinstance(details, dict):
                details = {}

            # Plex
            if r.get("media_type") == "plex":
                plex_share = details.get("plex_share", {})
                if not isinstance(plex_share, dict):
                    plex_share = {}

                r["allow_sync"] = 1 if plex_share.get("allowSync") else 0
                r["allow_camera_upload"] = 1 if plex_share.get("allowCameraUpload") else 0
                r["allow_channels"] = 1 if plex_share.get("allowChannels") else 0
                r["filter_movies"] = plex_share.get("filterMovies") or ""
                r["filter_television"] = plex_share.get("filterTelevision") or ""
                r["filter_music"] = plex_share.get("filterMusic") or ""

            r["_details_obj"] = details
            enriched.append(r)

        servers = enriched

        libraries = db.query(
            """
            SELECT
                l.*,
                s.name AS server_name,
                CASE
                    WHEN mul.media_user_id IS NOT NULL THEN 1
                    ELSE 0
                END AS has_access
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            LEFT JOIN media_user_libraries mul
                   ON mul.library_id = l.id
                  AND mul.media_user_id IN (
                        SELECT id
                        FROM media_users
                        WHERE vodum_user_id = ?
                   )
            ORDER BY s.name, l.name
            """,
            (user_id,),
        )

        sent_emails = db.query(
            """
            SELECT *
            FROM sent_emails
            WHERE user_id = ?
            ORDER BY sent_at DESC
            """,
            (user_id,),
        )

        merge_suggestions = get_merge_suggestions(db, user_id, limit=None)

        return render_template(
            "users/user_detail.html",
            user=user,
            servers=servers,
            libraries=libraries,
            sent_emails=sent_emails,
            allowed_types=allowed_types,
            merge_suggestions=merge_suggestions,
            user_servers=servers,
        )



    @app.route("/users/<int:user_id>/plex/share/filter", methods=["POST"])
    def update_plex_share_filter(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        value = (form.get("value") or "").strip()

        allowed_fields = {"filterMovies", "filterTelevision", "filterMusic"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = value
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        return redirect(url_for("user_detail", user_id=user_id))


    @app.route("/users/<int:user_id>/plex/share/toggle", methods=["POST"])
    def toggle_plex_share_option(user_id):
        db = get_db()
        form = request.form

        server_id = int(form.get("server_id") or 0)
        media_user_id = int(form.get("media_user_id") or 0)
        field = (form.get("field") or "").strip()
        vals = form.getlist("value")
        v = vals[-1] if vals else "0"

        truthy = {"1", "true", "on", "yes"}
        new_val = 1 if str(v).strip().lower() in truthy else 0

        allowed_fields = {"allowSync", "allowCameraUpload", "allowChannels"}
        if field not in allowed_fields:
            flash("invalid_field", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # sécurité: s'assurer que ce media_user appartient bien au user_id + server_id
        mu = db.query_one(
            """
            SELECT mu.id, mu.details_json
            FROM media_users mu
            JOIN servers s ON s.id = mu.server_id
            WHERE mu.id = ?
              AND mu.vodum_user_id = ?
              AND mu.server_id = ?
              AND s.type = 'plex'
              AND mu.type = 'plex'
            """,
            (media_user_id, user_id, server_id),
        )
        if not mu:
            flash("media_user_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # load json
        try:
            details = json.loads(mu["details_json"] or "{}")
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}

        plex_share = details.get("plex_share", {})
        if not isinstance(plex_share, dict):
            plex_share = {}

        plex_share[field] = new_val
        details["plex_share"] = plex_share

        db.execute(
            "UPDATE media_users SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(mu["id"])),
        )

        # Optionnel mais recommandé: réplication même owner + jobs
        # -> tu peux réutiliser exactement ta logique existante
        #    (celle de replicate_plex_flags_same_owner + création media_jobs + queue task)

        flash("user_saved", "success")
        return redirect(url_for("user_detail", user_id=user_id))


    @app.route("/users/<int:user_id>/merge", methods=["POST"])
    def user_merge(user_id):
        db = get_db()

        other_id = request.form.get("other_id", type=int)
        if not other_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        if other_id == user_id:
            flash("invalid_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        try:
            merge_vodum_users(db, master_id=user_id, other_id=other_id)
            flash("user_merged", "success")
        except Exception as e:
            task_logger.error(f"[MERGE] error master={user_id} other={other_id}: {e}", exc_info=True)
            flash("merge_failed", "error")

        return redirect(url_for("user_detail", user_id=user_id))





    @app.route("/users/<int:user_id>/toggle_library", methods=["POST"])
    def user_toggle_library(user_id):
        db = get_db()

        library_id = request.form.get("library_id", type=int)
        if not library_id:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # Récup library + server (pour savoir sur quel serveur on agit)
        # --------------------------------------------------
        lib = db.query_one(
            "SELECT id, server_id, name FROM libraries WHERE id = ?",
            (library_id,),
        )
        if not lib:
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        server = db.query_one(
            "SELECT id, type, name FROM servers WHERE id = ?",
            (lib["server_id"],),
        )
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # IMPORTANT : on ne doit toggler QUE les media_users
        # de CE serveur (sinon tu peux lier une lib Plex à un compte Jellyfin)
        # --------------------------------------------------
        media_users = db.query(
            """
            SELECT id
            FROM media_users
            WHERE vodum_user_id = ?
              AND server_id = ?
            """,
            (user_id, lib["server_id"]),
        )
        if not media_users:
            flash("no_media_accounts_for_user", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        media_user_ids = [mu["id"] for mu in media_users]
        placeholders = ",".join("?" * len(media_user_ids))

        # --------------------------------------------------
        # Vérifier si l'accès existe déjà
        # --------------------------------------------------
        exists = db.query_one(
            f"""
            SELECT 1
            FROM media_user_libraries
            WHERE library_id = ?
              AND media_user_id IN ({placeholders})
            LIMIT 1
            """,
            (library_id, *media_user_ids),
        )

        removed = False

        # --------------------------------------------------
        # TOGGLE en DB
        # --------------------------------------------------
        if exists:
            db.execute(
                f"""
                DELETE FROM media_user_libraries
                WHERE library_id = ?
                  AND media_user_id IN ({placeholders})
                """,
                (library_id, *media_user_ids),
            )
            removed = True
            flash("library_access_removed", "success")
        else:
            for mid in media_user_ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (mid, library_id),
                )
            flash("library_access_added", "success")

        # --------------------------------------------------
        # Création d'un job pour apply_plex_access_updates
        # -> uniquement si serveur Plex (pour Jellyfin on fera plus tard)
        # --------------------------------------------------
        if server["type"] == "plex":
            # Combien de libs restent pour CE user sur CE serveur ?
            remaining = db.query_one(
                f"""
                SELECT COUNT(DISTINCT mul.library_id) AS c
                FROM media_user_libraries mul
                JOIN libraries l ON l.id = mul.library_id
                WHERE mul.media_user_id IN ({placeholders})
                  AND l.server_id = ?
                """,
                (*media_user_ids, lib["server_id"]),
            )
            remaining_count = int(remaining["c"] or 0)

            # --------------------------------------------------
            # Choix de l'action:
            # - Ajout d'une bibliothèque => grant (équivalent plex_api_share.py --add --libraries X)
            # - Retrait d'une bibliothèque => sync (réapplique la liste DB), ou revoke si plus rien
            # --------------------------------------------------
            if removed and remaining_count == 0:
                action = "revoke"
                job_library_id = None
                dedupe_key = f"plex:revoke:server={lib['server_id']}:user={user_id}"
            elif removed:
                action = "sync"
                job_library_id = None
                dedupe_key = f"plex:sync:server={lib['server_id']}:user={user_id}"
            else:
                action = "grant"
                job_library_id = library_id
                dedupe_key = f"plex:grant:server={lib['server_id']}:user={user_id}:lib={library_id}"

            payload = {
                "reason": "library_toggle",
                "library_id": library_id,
                "library_name": lib["name"],
                "removed": removed,
                "remaining_count": remaining_count,
            }

            db.execute(
                """
                INSERT OR IGNORE INTO media_jobs
                    (provider, action, vodum_user_id, server_id, library_id, payload_json, dedupe_key)
                VALUES
                    ('plex', ?, ?, ?, ?, ?, ?)
                """,
                (action, user_id, lib["server_id"], job_library_id, json.dumps(payload), dedupe_key),
            )


            # Activer + queue la tâche apply_plex_access_updates
            db.execute(
                """
                UPDATE tasks
                SET enabled = 1, status = 'queued'
                WHERE name = 'apply_plex_access_updates'
                """
            )

            try:
                row = db.query_one("SELECT id FROM tasks WHERE name='apply_plex_access_updates'")
                if row:
                    enqueue_task(row["id"])
            except Exception:
                # pas bloquant si enqueue échoue, le scheduler le prendra plus tard
                pass

        elif server["type"] == "jellyfin":
            # --------------------------------------------------
            # Jellyfin : on fait un job "SYNC" (source de vérité = DB)
            # -> 1 seul job par user+server, réarmé à chaque toggle
            # --------------------------------------------------

            action = "sync"
            job_library_id = None

            # Dedupe par user+server (pas par lib)
            dedupe_key = f"jellyfin:sync:server={lib['server_id']}:user={user_id}"

            payload = {
                "reason": "library_toggle",
                "toggled_library_id": library_id,
                "toggled_library_name": lib["name"],
                "removed": removed,
            }

            # IMPORTANT:
            # - tables.sql: dedupe_key n'est pas UNIQUE => pas de ON CONFLICT possible
            # - on réarme le job en supprimant l'existant (processed ou non), puis insert
            db.execute(
                "DELETE FROM media_jobs WHERE dedupe_key = ?",
                (dedupe_key,),
            )

            # Laisse SQLite appliquer les DEFAULT (processed=0, success=0, attempts=0)
            db.execute(
                """
                INSERT INTO media_jobs
                    (provider, action, vodum_user_id, server_id, library_id, payload_json, dedupe_key)
                VALUES
                    ('jellyfin', ?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    user_id,
                    lib["server_id"],
                    job_library_id,
                    json.dumps(payload, ensure_ascii=False),
                    dedupe_key,
                ),
            )

            # Activer + queue la tâche Jellyfin
            db.execute(
                """
                UPDATE tasks
                SET enabled = 1, status = 'queued'
                WHERE name = 'apply_jellyfin_access_updates'
                """
            )

            try:
                row = db.query_one("SELECT id FROM tasks WHERE name='apply_jellyfin_access_updates'")
                if row:
                    enqueue_task(row["id"])
            except Exception:
                pass




        return redirect(url_for("user_detail", user_id=user_id))





    # -----------------------------
    # SERVEURS & BIBLIO
    # -----------------------------
    @app.route("/servers/<int:server_id>/sync")
    def sync_server(server_id):
        db = get_db()

        # --------------------------------------------------
        # Vérifier que le serveur existe
        # --------------------------------------------------
        server = db.query_one(
            "SELECT id, type FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Si ce n'est pas un serveur Plex, ne pas créer de job Plex
        # --------------------------------------------------
        if server["type"] != "plex":
            flash("sync_not_supported_for_server_type", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Cibler les vodum_users qui ont AU MOINS 1 accès sur ce serveur
        # (évite le cas où apply_sync_job bloque quand sections == [])
        # --------------------------------------------------
        vodum_users = db.query(
            """
            SELECT DISTINCT vu.id AS vodum_user_id
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            JOIN media_user_libraries mul
                ON mul.media_user_id = mu.id
            JOIN libraries l
                ON l.id = mul.library_id
            WHERE mu.server_id = ?
              AND l.server_id = ?
              AND mu.type = 'plex'
            """,
            (server_id, server_id),
        )

        if not vodum_users:
            flash("no_users_to_sync_for_server", "warning")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------------------------------
        # Créer 1 job sync par vodum_user (dans media_jobs)
        # --------------------------------------------------
        created = 0
        for r in vodum_users:
            vodum_user_id = int(r["vodum_user_id"])
            dedupe_key = f"plex:sync:server={server_id}:vodum_user={vodum_user_id}"

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
                    'plex', 'sync',
                    ?, ?, NULL,
                    NULL,
                    0, 0, 0,
                    ?
                )
                """,
                (vodum_user_id, server_id, dedupe_key),
            )
            # rowcount vaut souvent 1 si insert, 0 si déjà présent (IGNORE)
            try:
                if getattr(db, "last_rowcount", None):
                    pass
            except Exception:
                pass
            created += 1

        # --------------------------------------------------
        # Activer + déclencher apply_plex_access_updates
        # --------------------------------------------------
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

        try:
            from tasks_engine import enqueue_task
            task = db.query_one("SELECT id FROM tasks WHERE name = 'apply_plex_access_updates'")
            if task:
                enqueue_task(task["id"])
        except Exception:
            # pas bloquant, le scheduler la prendra
            pass

        flash("sync_jobs_created", "success")
        return redirect(url_for("server_detail", server_id=server_id))




    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = db.query(
            """
            SELECT
                s.*,

                -- nb bibliothèques
                COUNT(DISTINCT l.id) AS libraries_count,

                -- nb d'utilisateurs Vodum ayant au moins un compte sur ce serveur
                COUNT(DISTINCT mu.vodum_user_id) AS users_count

            FROM servers s
            LEFT JOIN libraries l
                   ON l.server_id = s.id

            LEFT JOIN media_users mu
                   ON mu.server_id = s.id

            GROUP BY s.id
            ORDER BY s.name
            """
        )

        return render_template(
            "servers/servers.html",
            servers=servers,
            active_page="servers",
            active_tab="servers",
        )



    @app.route("/libraries", methods=["GET"])
    def libraries_list():
        db = get_db()

        libraries = db.query(
            """
            SELECT
                l.*,
                s.name AS server_name,

                -- nb d'utilisateurs Vodum ayant accès
                COUNT(DISTINCT mu.vodum_user_id) AS users_count

            FROM libraries l
            JOIN servers s
                ON s.id = l.server_id

            LEFT JOIN media_user_libraries mul
                ON mul.library_id = l.id

            LEFT JOIN media_users mu
                ON mu.id = mul.media_user_id

            GROUP BY l.id
            ORDER BY s.name, l.name
            """
        )

        return render_template(
            "servers/libraries.html",
            libraries=libraries,
            active_page="servers",
            active_tab="libraries",
        )






    @app.route("/servers/new", methods=["POST"])
    def server_create():
        db = get_db()

        server_type = (request.form.get("type") or "generic").lower()
        name = f"{server_type.upper()} - pending"

        url = request.form.get("url") or None
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None

        # Options spécifiques (stockées dans settings_json)
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None

        server_identifier = str(uuid.uuid4())

        # settings_json (clé/valeurs extensibles)
        settings = {}
        if tautulli_url or tautulli_api_key:
            settings["tautulli"] = {"url": tautulli_url, "api_key": tautulli_api_key}
        settings_json = json.dumps(settings) if settings else None

        try:
            # --------------------------------------------------
            # 1) INSERT serveur
            # --------------------------------------------------
            cur = db.execute(
                """
                INSERT INTO servers (
                    name,
                    type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    server_type,
                    server_identifier,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    "unknown",
                ),
            )
            server_id = getattr(cur, "lastrowid", None)

            # --------------------------------------------------
            # 2) Activation des tâches système
            # --------------------------------------------------
            db.execute(
                """
                UPDATE tasks
                SET enabled = 1,
                    status = CASE
                        WHEN status = 'disabled' THEN 'idle'
                        WHEN status IN ('idle','error','running','queued') THEN status
                        ELSE 'idle'
                    END
                WHERE name IN ('check_servers', 'update_user_status')
                """
            )


            # --------------------------------------------------
            # 3) Commit avant enqueue (évite des incohérences + locks)
            # --------------------------------------------------
            try:
                db.commit()
            except Exception:
                # Si ton get_db() auto-commit déjà, ce commit peut ne pas exister
                # ou lever selon ton wrapper. Dans ce cas, on ignore.
                pass

            # --------------------------------------------------
            # 4) Enchaîner check + sync (FIFO, jamais perdu)
            # --------------------------------------------------
            try:
                if server_type == "plex":
                    run_task_sequence(["check_servers", "sync_plex"])
                elif server_type == "jellyfin":
                    run_task_sequence(["check_servers", "sync_jellyfin"])
                else:
                    run_task_sequence(["check_servers"])
            except Exception as e:
                app.logger.warning(f"Failed to queue sequence after server creation: {e}")


        except Exception as e:
            # Si l'insert serveur ou l'update tasks a planté
            app.logger.exception(f"Server creation failed: {e}")
            flash("server_create_failed", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # 5) Message UI
        # --------------------------------------------------
        if server_type == "plex":
            flash("plex_server_created_sync_planned", "success")
        elif server_type == "jellyfin":
            flash("jellyfin_server_created_sync_planned", "success")
        else:
            flash("server_created_no_sync", "success")

        return redirect(url_for("servers_list"))






    @app.route("/servers/<int:server_id>/delete", methods=["POST"])
    def server_delete(server_id):
        db = get_db()

        server = db.query_one(
            "SELECT id, name FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        try:
            # IMPORTANT: on supprime uniquement les entrées "par serveur" (media_users),
            # pas les utilisateurs globaux vodum_users.
            db.execute("DELETE FROM media_users WHERE server_id = ?", (server_id,))

            # Ensuite on peut supprimer le serveur.
            # Les tables liées en ON DELETE CASCADE (libraries, media_jobs, user_identities, etc.)
            # seront nettoyées automatiquement.
            db.execute("DELETE FROM servers WHERE id = ?", (server_id,))

            flash("server_deleted", "success")

        except Exception as e:
            flash(f"server_delete_failed ({e})", "error")

        return redirect(url_for("servers_list"))





    @app.route("/servers/<int:server_id>", methods=["GET", "POST"])
    def server_detail(server_id):
        db = get_db()

        # ======================================================
        # POST : mise à jour d'un serveur
        # ======================================================
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            server_type = request.form.get("type") or "other"
            url = request.form.get("url") or None
            local_url = request.form.get("local_url") or None
            public_url = request.form.get("public_url") or None
            token = request.form.get("token") or None
            status = request.form.get("status") or None

            # paramètres spécifiques (ex : Tautulli — stockés en JSON)
            tautulli_url = request.form.get("tautulli_url") or None
            tautulli_api_key = request.form.get("tautulli_api_key") or None

            if not name:
                flash("Le nom du serveur est obligatoire", "error")
                return redirect(url_for("server_detail", server_id=server_id))

            # charger l'ancien JSON pour le merger proprement
            row = db.query_one(
                "SELECT settings_json FROM servers WHERE id = ?",
                (server_id,),
            )

            settings = {}
            if row and row["settings_json"]:
                try:
                    settings = json.loads(row["settings_json"])
                except Exception:
                    settings = {}

            # MAJ éventuelle des paramètres spéciaux
            if tautulli_url or tautulli_api_key:
                settings["tautulli"] = {
                    "url": tautulli_url,
                    "api_key": tautulli_api_key,
                }

            settings_json = json.dumps(settings) if settings else None

            # UPDATE (nouveau schéma)
            db.execute(
                """
                UPDATE servers
                SET name = ?,
                    type = ?,
                    url = ?,
                    local_url = ?,
                    public_url = ?,
                    token = ?,
                    settings_json = ?,
                    status = ?
                WHERE id = ?
                """,
                (
                    name,
                    server_type,
                    url,
                    local_url,
                    public_url,
                    token,
                    settings_json,
                    status,
                    server_id,
                ),
            )

            flash("server_updated", "success")
            return redirect(url_for("server_detail", server_id=server_id))

        # ======================================================
        # GET : affichage du serveur
        # ======================================================
        server = db.query_one(
            "SELECT * FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            return "Serveur introuvable", 404

        # --- bibliothèques ---
        libraries = db.query(
            """
            SELECT
                l.*,
                COUNT(DISTINCT mu.vodum_user_id) AS users_count
            FROM libraries l
            LEFT JOIN media_user_libraries mul
                   ON mul.library_id = l.id
            LEFT JOIN media_users mu
                   ON mu.id = mul.media_user_id
            WHERE l.server_id = ?
            GROUP BY l.id
            ORDER BY l.name
            """,
            (server_id,),
        )

        # --- utilisateurs reliés au serveur ---
        users = db.query(
            """
            SELECT
                vu.id,
                vu.username,
                vu.email
            FROM vodum_users vu
            JOIN media_users mu
                ON mu.vodum_user_id = vu.id
            WHERE mu.server_id = ?
            GROUP BY vu.id
            ORDER BY vu.username
            """,
            (server_id,),
        )

        return render_template(
            "servers/server_detail.html",
            server=server,
            libraries=libraries,
            users=users,
            active_page="servers",
        )



    @app.route("/servers/bulk_grant", methods=["POST"])
    def bulk_grant_libraries():
        db = get_db()

        server_id = request.form.get("server_id", type=int)
        library_ids = request.form.getlist("library_ids")

        if not server_id or not library_ids:
            flash("no_server_or_library_selected", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Vérifier que c'est bien un serveur Plex
        # --------------------------------------------------
        server = db.query_one("SELECT id, type FROM servers WHERE id = ?", (server_id,))
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        if server["type"] != "plex":
            flash("sync_not_supported_for_server_type", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Nettoyage + cast des lib ids
        # --------------------------------------------------
        try:
            library_ids_int = [int(x) for x in library_ids]
        except ValueError:
            flash("invalid_library", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # Validation : ne garder que les libraries appartenant au server_id
        # (évite les incohérences si l'UI envoie autre chose)
        # --------------------------------------------------
        placeholders = ",".join("?" * len(library_ids_int))
        valid_rows = db.query(
            f"""
            SELECT id
            FROM libraries
            WHERE server_id = ?
              AND id IN ({placeholders})
            """,
            (server_id, *library_ids_int),
        )
        valid_library_ids = [int(r["id"]) for r in valid_rows]

        if not valid_library_ids:
            flash("no_valid_libraries_for_server", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # 1) Utilisateurs ACTIFS liés à ce serveur
        #    + vodum_user_id indispensable pour media_jobs
        # --------------------------------------------------
        users = db.query(
            """
            SELECT mu.id AS media_user_id,
                   mu.vodum_user_id AS vodum_user_id
            FROM media_users mu
            JOIN vodum_users vu ON vu.id = mu.vodum_user_id
            WHERE mu.server_id = ?
              AND mu.type = 'plex'
              AND vu.status = 'active'
            """,
            (server_id,),
        )

        if not users:
            flash("no_active_users_for_server", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # --------------------------------------------------
        # 2) Donner accès aux bibliothèques (media_user_libraries)
        # --------------------------------------------------
        for lib_id in valid_library_ids:
            for u in users:
                db.execute(
                    """
                    INSERT OR IGNORE INTO media_user_libraries(media_user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (u["media_user_id"], lib_id),
                )

        # --------------------------------------------------
        # 3) Créer des jobs compatibles worker: media_jobs
        #    -> 1 sync par vodum_user (un sync suffit après bulk grant)
        # --------------------------------------------------
        vodum_user_ids = sorted({
            int(u["vodum_user_id"])
            for u in users
            if u.get("vodum_user_id") is not None
        })

        for vodum_user_id in vodum_user_ids:
            dedupe_key = f"plex:sync:server={server_id}:vodum_user={vodum_user_id}:bulk_grant"

            payload = {
                "reason": "bulk_grant",
                "library_ids": valid_library_ids,
            }

            db.execute(
                """
                INSERT OR IGNORE INTO media_jobs(
                    provider, action,
                    vodum_user_id, server_id, library_id,
                    payload_json,
                    processed, success, attempts,
                    dedupe_key
                )
                VALUES(
                    'plex', 'sync',
                    ?, ?, NULL,
                    ?,
                    0, 0, 0,
                    ?
                )
                """,
                (vodum_user_id, server_id, json.dumps(payload), dedupe_key),
            )

        # --------------------------------------------------
        # 4) Activer + déclencher apply_plex_access_updates
        # --------------------------------------------------
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

        try:
            row = db.query_one("SELECT id FROM tasks WHERE name='apply_plex_access_updates'")
            if row:
                enqueue_task(row["id"])
        except Exception:
            # pas bloquant si enqueue échoue, le scheduler le prendra
            pass

        flash("grant_access_active_success", "success")
        return redirect(url_for("servers_list", server_id=server_id))




    # -----------------------------
    #  abonnements
    # -----------------------------
    @app.route("/subscriptions", methods=["GET"])
    def subscriptions():
        db = get_db()
        servers = db.query(
            "SELECT id, name FROM servers ORDER BY name"
        )
        return render_template(
            "subscriptions/subscriptions.html",
            servers=servers,
        )




    # -----------------------------
    # TÂCHES
    # -----------------------------
    
    @app.route("/tasks/run/<int:task_id>", methods=["POST"])
    def task_run(task_id):
        db = get_db()

        row = db.query_one(
            "SELECT status, enabled FROM tasks WHERE id = ?",
            (task_id,),
        )
        if not row:
            flash("task_not_found", "error")
            return redirect("/tasks")

        if not row["enabled"] or row["status"] == "disabled":
            flash("task_disabled", "warning")
            return redirect("/tasks")

        # ✅ On empile une exécution, même si déjà queued/running
        from tasks_engine import enqueue_task
        enqueue_task(task_id)

        flash("task_queued", "success")
        return redirect("/tasks")




    def json_rows(rows):
        return json.dumps([dict(r) for r in rows], ensure_ascii=False), 200, {"Content-Type": "application/json"}

    @app.route("/api/monitoring/activity")
    def api_monitoring_activity():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              strftime('%Y-%m-%d', started_at) AS day,
              COUNT(*) AS sessions
            FROM media_session_history
            WHERE {where}
            GROUP BY strftime('%Y-%m-%d', started_at)
            ORDER BY day ASC
            """,
            params,
        )
        return json_rows(rows)




    @app.route("/api/monitoring/media_types")
    def api_monitoring_media_types():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              COALESCE(media_type, 'unknown') AS media_type,
              COUNT(*) AS sessions
            FROM media_session_history
            WHERE {where}
            GROUP BY COALESCE(media_type, 'unknown')
            ORDER BY sessions DESC
            """,
            params,
        )
        return json_rows(rows)

    @app.route("/api/monitoring/per_server")
    def api_monitoring_per_server():
        db = get_db()
        rng = request.args.get("range", "7d")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"7d": "-7 days", "1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-7 days")
            where = "h.started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              COALESCE(NULLIF(s.name, ''), 'Server ' || h.server_id) AS server_name,
              COUNT(*) AS sessions
            FROM media_session_history h
            LEFT JOIN servers s ON s.id = h.server_id
            WHERE {where}
            GROUP BY h.server_id
            ORDER BY sessions DESC
            """,
            params,
        )
        return json_rows(rows)



    @app.route("/api/monitoring/weekday")
    def api_monitoring_weekday():
        db = get_db()
        rng = request.args.get("range", "1m")

        if rng == "all":
            where = "1=1"
            params = ()
        else:
            delta = {"1m": "-1 month", "6m": "-6 months", "12m": "-12 months"}.get(rng, "-1 month")
            where = "started_at >= datetime('now', ?)"
            params = (delta,)

        rows = db.query(
            f"""
            SELECT
              CAST(strftime('%w', started_at) AS INTEGER) AS weekday,
              COUNT(*) AS sessions
            FROM media_session_history
            WHERE {where}
            GROUP BY CAST(strftime('%w', started_at) AS INTEGER)
            ORDER BY weekday
            """,
            params,
        )
        return json_rows(rows)




    @app.route("/tasks", methods=["GET", "POST"])
    def tasks_page():
        db = get_db()

        # ------------------------------------------------------------------
        # POST : actions sur les tâches (toggle / run_now)
        # ------------------------------------------------------------------
        if request.method == "POST" and table_exists(db, "tasks"):
            task_id = request.form.get("task_id", type=int)
            action = request.form.get("action", type=str)

            if not task_id:
                flash("invalid_task", "error")
                task_logger.error("POST /tasks → task_id manquant")
                return redirect(url_for("tasks_page"))

            # On récupère la tâche une fois pour valider l'existence / état
            task = db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
            if not task:
                flash("invalid_task", "error")
                task_logger.error(f"POST /tasks → task_id introuvable: {task_id}")
                return redirect(url_for("tasks_page"))

            # --------------------------------------------------------------
            # 1) Toggle enable/disable
            # --------------------------------------------------------------
            if action == "toggle":
                # 1) Toggle enabled (0 <-> 1)
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END
                    WHERE id = ?
                    """,
                    (task_id,),
                )

                # 2) Relire la valeur enabled après update
                row = db.query_one("SELECT enabled FROM tasks WHERE id = ?", (task_id,))
                enabled = int(row["enabled"]) if row else 0

                # 3) Synchroniser le status + reset champs utiles
                if enabled == 1:
                    # tâche activée -> prête à tourner
                    db.execute(
                        """
                        UPDATE tasks
                        SET status='idle',
                            last_error=NULL,
                            next_run=NULL
                        WHERE id=?
                        """,
                        (task_id,),
                    )
                    task_logger.info(f"Tâche {task_id} → ENABLED (status=idle)")
                else:
                    # tâche désactivée
                    db.execute(
                        """
                        UPDATE tasks
                        SET status='disabled'
                        WHERE id=?
                        """,
                        (task_id,),
                    )
                    task_logger.info(f"Tâche {task_id} → DISABLED (status=disabled)")

                flash("task_updated", "success")
                return redirect(url_for("tasks_page"))

            # --------------------------------------------------------------
            # 2) run_now → enqueue + status queued (optionnel mais utile)
            # --------------------------------------------------------------
            elif action == "run_now":
                # Re-lire enabled au cas où
                row = db.query_one("SELECT enabled, status, name FROM tasks WHERE id = ?", (task_id,))
                enabled = int(row["enabled"]) if row else 0
                name = row["name"] if row and "name" in row else f"#{task_id}"

                if enabled != 1:
                    flash("task_disabled", "error")
                    task_logger.warning(f"run_now refusé: tâche {task_id} ({name}) désactivée")
                    return redirect(url_for("tasks_page"))

                # Marquer queued (si tu veux une UI plus lisible)
                # On ne force pas "queued" si déjà running, mais tu peux choisir.
                if row and row.get("status") not in ("running",):
                    db.execute(
                        """
                        UPDATE tasks
                        SET status='queued',
                            last_error=NULL
                        WHERE id=?
                        """,
                        (task_id,),
                    )

                try:
                    from tasks_engine import enqueue_task
                    enqueue_task(task_id)
                    flash("task_queued", "success")
                    task_logger.info(f"Tâche {task_id} ({name}) → run_now → enqueued")
                except Exception as e:
                    flash("task_queue_failed", "error")
                    task_logger.error(f"run_now erreur pour tâche {task_id} ({name}): {e}", exc_info=True)
                    # On garde une trace DB si possible
                    try:
                        db.execute(
                            """
                            UPDATE tasks
                            SET status='error',
                                last_error=?
                            WHERE id=?
                            """,
                            (str(e), task_id),
                        )
                    except Exception:
                        pass

                return redirect(url_for("tasks_page"))

            # --------------------------------------------------------------
            # Action inconnue
            # --------------------------------------------------------------
            else:
                task_logger.warning(f"Action inconnue sur /tasks : {action} (task_id={task_id})")
                flash("unknown_action", "error")
                return redirect(url_for("tasks_page"))

        # ------------------------------------------------------------------
        # GET : affichage liste des tâches
        # ------------------------------------------------------------------
        tasks = []
        if table_exists(db, "tasks"):
            tasks = db.query(
                """
                SELECT *
                FROM tasks
                ORDER BY name
                """
            )

        task_logger.debug(f"Affichage page tasks → {len(tasks)} tâches détectées")

        return render_template(
            "tasks/tasks.html",
            tasks=tasks,
            active_page="tasks",
        )




    # -----------------------------
    # MAILING
    # -----------------------------
    
    def is_smtp_ready(settings) -> bool:
        if not settings:
            return False

        try:
            return bool(
                settings["mailing_enabled"]
                and settings["smtp_host"]
                and settings["smtp_port"]
                and settings["smtp_user"]
                and settings["smtp_pass"]
                and settings["mail_from"]
            )
        except (KeyError, TypeError):
            return False


    
    @app.post("/api/mailing/toggle")
    def api_mailing_toggle():
        db = get_db()

        data = request.get_json(silent=True) or {}
        enabled = 1 if data.get("enabled") else 0

        try:
            # 1️⃣ Mettre à jour le flag settings (WRITE)
            db.execute(
                "UPDATE settings SET mailing_enabled = ? WHERE id = 1",
                (enabled,),
            )

            # 2️⃣ Activer / désactiver les tâches liées au mailing (WRITE)
            db.execute(
                """
                UPDATE tasks
                SET enabled = ?
                WHERE name IN ('send_expiration_emails', 'send_mail_campaigns')
                """,
                (enabled,),
            )

            add_log(
                "info",
                "mailing",
                f"Mailing toggled → {enabled}",
            )

            return {"status": "ok", "enabled": enabled}

        except Exception as e:
            # ⚠️ pas de rollback avec DBManager
            add_log(
                "error",
                "mailing",
                "Failed to toggle mailing",
                {"error": str(e)},
            )
            return {"status": "error", "message": str(e)}, 500


    @app.route("/mailing")
    def mailing_page():
        db = get_db()

        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        if is_smtp_ready(settings):
            return redirect(url_for("mailing_campaigns_page"))

        return redirect(url_for("mailing_smtp_page"))





    @app.route("/mailing/campaigns", methods=["GET", "POST"])
    def mailing_campaigns_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # Fetch list of servers for dropdown (READ)
        servers = db.query(
            "SELECT id, name FROM servers ORDER BY name"
        )

        # -----------------------------------------------------------------------------
        # 1. LOAD CAMPAIGN INTO FORM
        # -----------------------------------------------------------------------------
        load_id = request.args.get("load", type=int)
        loaded_campaign = None

        if load_id:
            loaded_campaign = db.query_one(
                "SELECT * FROM mail_campaigns WHERE id = ?",
                (load_id,),
            )

        # -----------------------------------------------------------------------------
        # 2. CREATE NEW CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "create":
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            server_id = request.form.get("server_id", type=int)
            
            # "All servers" ou valeur vide → NULL
            raw_server_id = request.form.get("server_id")
            server_id = None

            if raw_server_id:
                try:
                    sid = int(raw_server_id)
                    exists = db.query_one(
                        "SELECT 1 FROM servers WHERE id = ?",
                        (sid,),
                    )
                    if exists:
                        server_id = sid
                except ValueError:
                    server_id = None
            
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not subject or not body:
                flash(t("campaign_missing_fields"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            add_log(
                "debug",
                "mail_campaigns",
                "Normalized server_id",
                {"raw": raw_server_id, "final": server_id},
            )


            db.execute(
                """
                INSERT INTO mail_campaigns(
                    subject, body, server_id, status, is_test, created_at
                )
                VALUES (?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """,
                (subject, body, server_id, is_test),
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaign created",
                {"subject": subject, "is_test": is_test},
            )

            flash(t("campaign_created"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 2.b UPDATE EXISTING CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "save":
            cid = request.form.get("campaign_id", type=int)
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            server_id = request.form.get("server_id", type=int)
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not cid:
                flash(t("campaign_not_found"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            db.execute(
                """
                UPDATE mail_campaigns
                SET subject = ?, body = ?, server_id = ?, is_test = ?
                WHERE id = ?
                """,
                (subject, body, server_id, is_test, cid),
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaign updated",
                {"id": cid, "subject": subject},
            )

            flash(t("campaign_saved"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 3. SEND CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "send":
            cid = request.form.get("campaign_id", type=int)

            campaign = db.query_one(
                "SELECT * FROM mail_campaigns WHERE id = ?",
                (cid,),
            )
            if not campaign:
                flash(t("campaign_not_found"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            # Mark as sending
            db.execute(
                "UPDATE mail_campaigns SET status = 'sending' WHERE id = ?",
                (cid,),
            )

            settings = db.query_one("SELECT * FROM settings WHERE id = 1")
            admin_email = settings["admin_email"] if settings else None

            # -----------------------------------------------------
            # TEST MODE
            # -----------------------------------------------------
            if campaign["is_test"]:
                try:
                    send_email_via_settings(
                        admin_email,
                        campaign["subject"],
                        campaign["body"],
                    )

                    db.execute(
                        """
                        UPDATE mail_campaigns
                        SET status = 'finished', finished_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (cid,),
                    )

                    flash(t("campaign_test_sent"), "success")

                except Exception as e:
                    db.execute(
                        """
                        UPDATE mail_campaigns
                        SET status = 'error', finished_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (cid,),
                    )

                    flash(f"{t('campaign_send_failed')} ({e})", "error")

                return redirect(url_for("mailing_campaigns_page"))

            # -----------------------------------------------------
            # REAL MASS SENDING
            # -----------------------------------------------------
            if campaign["server_id"]:
                # utilisateurs ayant AU MOINS un compte sur ce serveur
                users = db.query(
                    """
                    SELECT DISTINCT
                        vu.email,
                        vu.username,
                        vu.expiration_date
                    FROM vodum_users vu
                    JOIN media_users mu
                          ON mu.vodum_user_id = vu.id
                    WHERE mu.server_id = ?
                    """,
                    (campaign["server_id"],),
                )

            else:
                # toutes les personnes dans Vodum
                users = db.query(
                    """
                    SELECT
                        email,
                        username,
                        expiration_date
                    FROM vodum_users
                    """
                )

            errors = 0

            for u in users:
                if not u["email"]:
                    continue

                formatted_body = (
                    campaign["body"]
                    .replace("{username}", u["username"] or "")
                    .replace("{email}", u["email"] or "")
                    .replace("{expiration_date}", u["expiration_date"] or "")
                )

                try:
                    send_email_via_settings(
                        u["email"],
                        campaign["subject"],
                        formatted_body,
                    )
                except Exception as e:
                    errors += 1
                    add_log(
                        "error",
                        "mail_campaigns",
                        "Sending failed",
                        {
                            "user": u["email"],
                            "campaign": cid,
                            "error": str(e),
                        },
                    )

            final_status = "finished" if errors == 0 else "error"

            db.execute(
                """
                UPDATE mail_campaigns
                SET status = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (final_status, cid),
            )

            flash(t("campaign_sent"), "success")
            return redirect(url_for("mailing_campaigns_page"))


        # -----------------------------------------------------------------------------
        # 4. DISPLAY PAGE
        # -----------------------------------------------------------------------------
        campaigns = db.query(
            """
            SELECT c.*, s.name AS server_name
            FROM mail_campaigns c
            LEFT JOIN servers s ON s.id = c.server_id
            ORDER BY datetime(c.created_at) DESC
            """
        )

        return render_template(
            "mailing/mailing_campaigns.html",
            campaigns=campaigns,
            servers=servers,
            loaded_campaign=loaded_campaign,
            active_page="mailing",
        )





    @app.post("/mailing/campaigns/delete")
    def mailing_campaigns_delete():
        db = get_db()
        t = get_translator()

        ids = request.form.getlist("campaign_ids")

        if not ids:
            flash(t("no_campaign_selected"), "error")
            return redirect(url_for("mailing_campaigns_page"))

        placeholders = ",".join("?" for _ in ids)

        try:
            db.execute(
                f"DELETE FROM mail_campaigns WHERE id IN ({placeholders})",
                ids,
            )

            add_log(
                "info",
                "mail_campaigns",
                "Campaigns deleted",
                {"ids": ids},
            )

            flash(
                t("campaigns_deleted").format(count=len(ids)),
                "success",
            )

        except Exception as e:
            # Pas de rollback avec DBManager
            add_log(
                "error",
                "mail_campaigns",
                "Failed to delete campaigns",
                {"ids": ids, "error": str(e)},
            )

            flash(
                f"{t('campaign_delete_failed')} ({e})",
                "error",
            )

        return redirect(url_for("mailing_campaigns_page"))


    @app.route("/mailing/templates", methods=["GET", "POST"])
    def mailing_templates_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # ---------------------------------------------------
        # S’assurer que les 3 templates existent
        # ---------------------------------------------------
        for type_ in ("preavis", "relance", "fin"):
            exists = db.query_one(
                "SELECT 1 FROM email_templates WHERE type = ?",
                (type_,),
            )
            if not exists:
                db.execute(
                    """
                    INSERT INTO email_templates(type, subject, body, days_before)
                    VALUES (?, '', '', 0)
                    """,
                    (type_,),
                )

        # ---------------------------------------------------
        # SAUVEGARDE DES MODIFICATIONS
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "save":

            # -----------------------------
            # Délais globaux (settings)
            # -----------------------------
            settings = db.query_one(
                "SELECT preavis_days, reminder_days FROM settings WHERE id = 1"
            )

            try:
                preavis_days = int(request.form.get("preavis_days"))
            except Exception:
                preavis_days = settings["preavis_days"]

            try:
                reminder_days = int(request.form.get("reminder_days"))
            except Exception:
                reminder_days = settings["reminder_days"]

            db.execute(
                """
                UPDATE settings
                SET preavis_days = ?, reminder_days = ?
                WHERE id = 1
                """,
                (preavis_days, reminder_days),
            )

            # -----------------------------
            # Mise à jour des templates
            # -----------------------------
            templates = db.query(
                "SELECT * FROM email_templates"
            )

            for tpl in templates:
                tid = tpl["id"]

                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()

                db.execute(
                    """
                    UPDATE email_templates
                    SET subject = ?, body = ?
                    WHERE id = ?
                    """,
                    (subject, body, tid),
                )

            add_log(
                "info",
                "mail_templates",
                "Templates updated",
                {
                    "preavis_days": preavis_days,
                    "reminder_days": reminder_days,
                },
            )

            flash(t("templates_saved"), "success")

        # ---------------------------------------------------
        # ENVOI DE TEST (INCHANGÉ)
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "test":
            template_id = request.form.get("test_template_id", type=int)

            settings = db.query_one(
                "SELECT * FROM settings WHERE id = 1"
            )
            admin_email = settings["admin_email"] if settings else None

            if not admin_email:
                flash(t("admin_email_missing"), "error")
            else:
                tpl = db.query_one(
                    "SELECT * FROM email_templates WHERE id = ?",
                    (template_id,),
                )

                if not tpl:
                    flash(t("template_not_found"), "error")
                else:
                    try:
                        test_user = {
                            "username": "TestUser",
                            "email": admin_email,
                            "expiration_date": "2025-12-31",
                        }

                        context = build_user_context(test_user)

                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        send_email_via_settings(
                            admin_email,
                            subject,
                            body,
                        )

                        add_log(
                            "info",
                            "mail_templates",
                            f"Test email sent ({tpl['type']})",
                            {"template_id": tpl["id"]},
                        )
                        flash(t("template_test_sent"), "success")

                    except Exception as e:
                        add_log(
                            "error",
                            "mail_templates",
                            "Template test failed",
                            {"error": str(e)},
                        )
                        flash(
                            f"{t('template_test_failed')} ({e})",
                            "error",
                        )

        # ---------------------------------------------------
        # AFFICHAGE
        # ---------------------------------------------------
        templates = db.query(
            "SELECT * FROM email_templates ORDER BY type"
        )

        return render_template(
            "mailing/mailing_templates.html",
            templates=templates,
            active_page="mailing",
        )

    @app.route("/mailing/welcome-templates", methods=["GET", "POST"])
    def mailing_welcome_templates_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        t = get_translator()

        # Create/override empty row
        if request.method == "POST" and request.form.get("action") == "create_or_override":
            provider = (request.form.get("provider") or "").strip().lower()
            server_id_raw = (request.form.get("server_id") or "").strip()
            server_id = int(server_id_raw) if server_id_raw else None

            if provider not in ("plex", "jellyfin"):
                flash("Invalid provider", "error")
            else:
                exists = db.query_one(
                    """
                    SELECT 1 FROM welcome_email_templates
                    WHERE provider=? AND server_id IS ?
                    """,
                    (provider, server_id),
                )
                if not exists:
                    db.execute(
                        """
                        INSERT INTO welcome_email_templates(provider, server_id, subject, body)
                        VALUES (?, ?, ?, ?)
                        """,
                        (provider, server_id, "", ""),
                    )
                    flash("Template created.", "success")

        # Save all
        if request.method == "POST" and request.form.get("action") == "save_all":
            rows = db.query("SELECT id FROM welcome_email_templates")
            for r in rows:
                tid = r["id"]
                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()
                db.execute(
                    """
                    UPDATE welcome_email_templates
                    SET subject=?, body=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (subject, body, tid),
                )
            add_log("info", "mail_templates", "Welcome templates updated", {})
            flash("Welcome templates saved.", "success")

        # Test send
        if request.method == "POST" and request.form.get("test_template_id"):
            template_id = request.form.get("test_template_id", type=int)

            settings = db.query_one("SELECT * FROM settings WHERE id = 1")
            admin_email = settings["admin_email"] if settings else None

            if not admin_email:
                flash(t("admin_email_missing"), "error")
            else:
                tpl = db.query_one(
                    "SELECT * FROM welcome_email_templates WHERE id = ?",
                    (template_id,),
                )
                if not tpl:
                    flash("Template not found", "error")
                else:
                    try:
                        fake_user = {
                            "username": "TestUser",
                            "email": admin_email,
                            "expiration_date": "2026-12-31",
                            "firstname": "John",
                            "lastname": "Doe",
                            "server_name": "My Server",
                            "server_url": "https://example.com",
                            "login_username": "TestUser",
                            "temporary_password": "TempPass123!",
                        }
                        context = build_user_context(fake_user)
                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        send_email_via_settings(admin_email, subject, body)

                        add_log("info", "mail_templates", "Welcome template test email sent", {"template_id": template_id})
                        flash("Test email sent to admin.", "success")
                    except Exception as e:
                        add_log("error", "mail_templates", "Welcome template test failed", {"error": str(e)})
                        flash(f"Test failed ({e})", "error")

        templates = db.query("""
            SELECT w.*,
                   s.name as server_name
            FROM welcome_email_templates w
            LEFT JOIN servers s ON s.id = w.server_id
            ORDER BY w.provider ASC, (w.server_id IS NOT NULL) ASC, s.name ASC
        """)

        servers = db.query("SELECT id, name, type FROM servers ORDER BY name ASC")

        return render_template(
            "mailing/mailing_welcome_templates.html",
            templates=templates,
            servers=servers,
            active_page="mailing",
            current_subpage="welcome_templates",
            settings=settings
        )


    # -------------------------------------------------------------------------
    # MAILING HISTORY (sent_emails + mail_campaigns)
    # -------------------------------------------------------------------------

    def _purge_email_history(db, retention_years):
        """Delete sent email history entries older than retention_years.
        retention_years <= 0 -> no purge.
        """
        try:
            ry = int(retention_years or 0)
        except Exception:
            ry = 0

        if ry <= 0:
            return {"sent_emails": 0, "mail_campaigns": 0}

        # SQLite: DATE('now', '-X years')
        threshold = f"-{ry} years"

        # sent_emails: use sent_at
        cur1 = db.execute(
            "DELETE FROM sent_emails WHERE sent_at < DATETIME('now', ?)",
            (threshold,),
        )

        # mail_campaigns: use created_at
        cur2 = db.execute(
            "DELETE FROM mail_campaigns WHERE created_at < DATETIME('now', ?)",
            (threshold,),
        )

        c1 = getattr(cur1, "rowcount", None) or 0
        c2 = getattr(cur2, "rowcount", None) or 0
        return {"sent_emails": c1, "mail_campaigns": c2}


    @app.route("/mailing/history")
    def mailing_history_page():
        db = get_db()
        settings = db.query_one("SELECT * FROM settings WHERE id = 1")

        if not is_smtp_ready(settings):
            return redirect(url_for("mailing_smtp_page"))

        # Retention purge (best-effort)
        try:
            _purge_email_history(db, (settings["email_history_retention_years"] if settings else 0))
        except Exception as e:
            add_log("error", "mailing_history", "Retention purge failed", {"error": str(e)})

        history = db.query(
            """
            SELECT
                'user' AS source,
                se.id AS id,
                se.user_id AS user_id,
                se.template_type AS type,
                NULL AS subject,
                vu.username AS username,
                vu.email AS email,
                NULL AS server_name,
                NULL AS status,
                se.expiration_date AS expiration_date,
                se.sent_at AS date
            FROM sent_emails se
            JOIN vodum_users vu ON vu.id = se.user_id

            UNION ALL

            SELECT
                'campaign' AS source,
                mc.id AS id,
                NULL AS user_id,
                'campaign' AS type,
                mc.subject AS subject,
                NULL AS username,
                NULL AS email,
                COALESCE(s.name, '-') AS server_name,
                mc.status AS status,
                NULL AS expiration_date,
                mc.created_at AS date
            FROM mail_campaigns mc
            LEFT JOIN servers s ON s.id = mc.server_id

            ORDER BY date DESC
            """
        )

        return render_template(
            "mailing/mailing_history.html",
            settings=settings,
            history=history,
        )


    @app.post("/mailing/history/retention")
    def mailing_history_retention():
        db = get_db()
        t = get_translator()

        years_raw = request.form.get("retention_years", "").strip()
        try:
            years = int(years_raw)
        except Exception:
            years = 2

        if years < 0:
            years = 0
        if years > 50:
            years = 50

        db.execute(
            "UPDATE settings SET email_history_retention_years = ? WHERE id = 1",
            (years,),
        )

        add_log("info", "mailing_history", "Retention updated", {"years": years})
        flash(t("retention_saved").format(years=years), "success")
        return redirect(url_for("mailing_history_page"))


    @app.post("/mailing/history/purge")
    def mailing_history_purge():
        db = get_db()
        t = get_translator()

        settings = db.query_one("SELECT * FROM settings WHERE id = 1")
        years = (settings["email_history_retention_years"] if settings else 0)

        try:
            counts = _purge_email_history(db, years)
            flash(
                t("history_purged").format(sent=counts["sent_emails"], campaigns=counts["mail_campaigns"]),
                "success",
            )
            add_log("info", "mailing_history", "History purged", {"years": years, **counts})
        except Exception as e:
            add_log("error", "mailing_history", "Purge failed", {"error": str(e)})
            flash(f"{t('purge_failed')} ({e})", "error")

        return redirect(url_for("mailing_history_page"))


    @app.post("/mailing/history/delete")
    def mailing_history_delete():
        db = get_db()
        t = get_translator()

        items = request.form.getlist("items")
        if not items:
            flash(t("no_item_selected"), "error")
            return redirect(url_for("mailing_history_page"))

        sent_ids = []
        camp_ids = []
        for it in items:
            try:
                src, rid = it.split(":", 1)
                rid = int(rid)
            except Exception:
                continue
            if src == "user":
                sent_ids.append(rid)
            elif src == "campaign":
                camp_ids.append(rid)

        try:
            total = 0
            if sent_ids:
                placeholders = ",".join("?" for _ in sent_ids)
                db.execute(f"DELETE FROM sent_emails WHERE id IN ({placeholders})", sent_ids)
                total += len(sent_ids)

            if camp_ids:
                placeholders = ",".join("?" for _ in camp_ids)
                db.execute(f"DELETE FROM mail_campaigns WHERE id IN ({placeholders})", camp_ids)
                total += len(camp_ids)

            add_log("info", "mailing_history", "History rows deleted", {"sent_ids": sent_ids, "campaign_ids": camp_ids})
            flash(t("items_deleted").format(count=total), "success")

        except Exception as e:
            add_log("error", "mailing_history", "Delete failed", {"error": str(e)})
            flash(f"{t('delete_failed')} ({e})", "error")

        return redirect(url_for("mailing_history_page"))


    @app.route("/mailing/smtp", methods=["GET", "POST"])
    def mailing_smtp_page():
        db = get_db()
        t = get_translator()

        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        if request.method == "POST":
            action = request.form.get("action")

            # --------------------------------------------------
            # SAVE SMTP SETTINGS
            # --------------------------------------------------
            if action == "save":
                mail_from = request.form.get("mail_from") or None
                smtp_host = request.form.get("smtp_host") or None
                smtp_port = request.form.get("smtp_port", type=int)
                smtp_tls = 1 if request.form.get("smtp_tls") == "1" else 0
                smtp_user = request.form.get("smtp_user") or None
                smtp_pass = request.form.get("smtp_pass") or None

                db.execute(
                    """
                    UPDATE settings
                    SET mail_from = ?, smtp_host = ?, smtp_port = ?, smtp_tls = ?,
                        smtp_user = ?, smtp_pass = ?
                    WHERE id = 1
                    """,
                    (mail_from, smtp_host, smtp_port, smtp_tls, smtp_user, smtp_pass),
                )

                add_log(
                    "info",
                    "smtp_config",
                    "SMTP settings updated",
                    None,
                )
                flash(t("smtp_settings_saved"), "success")

            # --------------------------------------------------
            # TEST SMTP
            # --------------------------------------------------
            elif action == "test":
                admin_email = settings["admin_email"] if settings else None

                if not admin_email:
                    flash(t("admin_email_missing"), "error")
                else:
                    try:
                        send_email_via_settings(
                            admin_email,
                            t("smtp_test_subject"),
                            t("smtp_test_body"),
                        )

                        add_log(
                            "info",
                            "smtp_config",
                            "SMTP test email sent",
                            {"to": admin_email},
                        )
                        flash(t("smtp_test_sent"), "success")

                    except Exception as e:
                        add_log(
                            "error",
                            "smtp_config",
                            "SMTP test failed",
                            {"error": str(e)},
                        )
                        flash(
                            f"{t('smtp_test_failed')} ({e})",
                            "error",
                        )

            return redirect(url_for("mailing_smtp_page"))

        return render_template(
            "mailing/mailing_smtp.html",
            settings=settings,
            active_page="mailing",
        )


    # -----------------------------
    # BACKUP
    # -----------------------------
    def restore_db_file(backup_path: Path):
        db_path = Path(app.config["DATABASE"])

        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))

        # Sauvegarde de précaution
        backup_dir = ensure_backup_dir()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        if db_path.exists():
            shutil.copy2(
                db_path,
                backup_dir / f"pre_restore_{timestamp}.sqlite",
            )

        shutil.copy2(backup_path, db_path)

    def safe_restore(backup_path: Path):
        """
        Restaure un fichier de base SQLite.

        ⚠️ Fonction volontairement destructive :
        - désactive les tâches
        - passe en maintenance
        - écrase le fichier DB
        - nécessite un redémarrage du conteneur

        Compatible DBManager (aucun close / commit / rollback manuel)
        """
        logger = get_logger("backup")
        db = get_db()

        # 1️⃣ Désactiver toutes les tâches
        db.execute(
            "UPDATE tasks SET enabled = 0"
        )

        # 2️⃣ Attendre que toutes les tâches soient arrêtées
        for _ in range(30):
            row = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE status = 'running'"
            )
            if not row or row["cnt"] == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Some tasks are still running")

        # 3️⃣ Passer l’application en maintenance
        db.execute(
            "UPDATE settings SET maintenance_mode = 1 WHERE id = 1"
        )

        # ⚠️ IMPORTANT
        # - pas de close DB
        # - pas de commit
        # - pas de rollback
        # DBManager gère l’état, le process devient volontairement incohérent

        # 4️⃣ Restaurer le fichier DB (copie fichier)
        restore_db_file(backup_path)

        logger.warning(
            "[BACKUP] Base restaurée – redémarrage du conteneur requis"
        )

    def get_sqlite_db_size_bytes(db_path: str) -> int | None:
        """
        Retourne la taille disque de la DB SQLite.
        Inclut le fichier -wal / -shm si présents (utile si WAL activé).
        """
        try:
            p = Path(db_path)
            if not p.exists():
                return None

            total = p.stat().st_size

            wal = p.with_name(p.name + "-wal")
            shm = p.with_name(p.name + "-shm")

            if wal.exists():
                total += wal.stat().st_size
            if shm.exists():
                total += shm.stat().st_size

            return int(total)
        except Exception:
            return None
    

    @app.route("/backup", methods=["GET", "POST"])
    def backup_page():
        t = get_translator()
        db = get_db()

        # Charger les réglages (dont la rétention)
        settings = db.query_one(
            "SELECT * FROM settings LIMIT 1"
        )

        db_size_bytes = get_sqlite_db_size_bytes(app.config["DATABASE"])

        backups = list_backups(backup_cfg)

        if request.method == "POST":
            action = request.form.get("action")

            # ───────────────────────────────
            # Backup manuel
            # ───────────────────────────────
            if action == "create":
                try:
                    name = create_backup_file(get_db, backup_cfg)
                    flash(
                        t("backup_created").format(name=name),
                        "success",
                    )
                except Exception as e:
                    flash(
                        t("backup_create_error").format(error=str(e)),
                        "error",
                    )

            # ───────────────────────────────
            # Restauration d'un backup
            # ───────────────────────────────
            elif action == "restore":
                selected = request.form.get("selected_backup")

                # 1️⃣ Restore depuis un backup existant
                if selected:
                    backup_path = Path(app.config["BACKUP_DIR"]) / selected

                    if not backup_path.exists():
                        flash(t("backup_not_found"), "error")
                    else:
                        try:
                            safe_restore(backup_path)
                            flash(
                                t("backup_restore_success_restart"),
                                "success",
                            )
                        except Exception as e:
                            flash(
                                t("backup_restore_error").format(error=str(e)),
                                "error",
                            )

                # 2️⃣ Restore par upload
                else:
                    file = request.files.get("backup_file")

                    if not file or file.filename == "":
                        flash(t("backup_no_file"), "error")
                    else:
                        temp_dir = Path("/tmp")
                        temp_dir.mkdir(exist_ok=True)
                        temp_path = temp_dir / f"restore-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sqlite"

                        file.save(temp_path)

                        try:
                            restore_backup_file(temp_path, backup_cfg)
                            flash(
                                t("backup_restore_success_restart"),
                                "success",
                            )
                        except Exception as e:
                            flash(
                                t("backup_restore_error").format(error=str(e)),
                                "error",
                            )
                        finally:
                            if temp_path.exists():
                                temp_path.unlink(missing_ok=True)

            # ───────────────────────────────
            # Sauvegarde des paramètres (rétention)
            # ───────────────────────────────
            elif action == "save_settings":
                try:
                    days = int(request.form.get("backup_retention_days", "30"))

                    db.execute(
                        "UPDATE settings SET backup_retention_days = ?",
                        (days,),
                    )

                    flash(
                        t("backup_settings_saved"),
                        "success",
                    )
                except Exception as e:
                    flash(
                        t("backup_settings_error").format(error=str(e)),
                        "error",
                    )

            backups = list_backups(backup_cfg)

        return render_template(
            "backup/backup.html",
            backups=backups,
            settings=settings,
            db_size_bytes=db_size_bytes, 
            active_page="backup",
        )



    # -----------------------------
    # AUTH (admin) - guard global
    # -----------------------------
    def _get_auth_settings():
        db = get_db()
        row = db.query_one(
            "SELECT admin_email, admin_password_hash, auth_enabled FROM settings WHERE id = 1"
        )
        return dict(row) if row else {"admin_email": "", "admin_password_hash": None, "auth_enabled": 1}

    def _is_auth_configured(s: dict) -> bool:
        return bool((s.get("admin_password_hash") or "").strip())

    def _is_logged_in() -> bool:
        return session.get("vodum_logged_in") is True

    @app.before_request
    def auth_guard():
        """
        🔒 Auth = UI uniquement
        - Les routes HTML sont protégées
        - Les routes /api restent accessibles (pour tâches / automation / healthchecks) SAUF si tu veux les bloquer.
        """
        s = _get_auth_settings()

        # assets toujours OK
        always_allowed_prefixes = ("/static", "/set_language", "/health")
        if request.path.startswith(always_allowed_prefixes) or request.path in ("/favicon.ico",):
            return

        # si auth désactivée -> open bar
        if int(s.get("auth_enabled") or 1) == 0:
            return

        configured = _is_auth_configured(s)

        # ✅ IMPORTANT : on ne protège PAS /api (background)
        if request.path.startswith("/api/"):
            return

        # pages auth accessibles
        auth_pages = ("/login", "/logout", "/setup-admin")
        if request.path in auth_pages:
            if request.path == "/login" and not configured:
                return redirect(url_for("setup_admin"))
            return

        # Si pas configuré => forcer setup admin pour toute UI
        if not configured:
            return redirect(url_for("setup_admin"))

        # Si configuré => login obligatoire pour UI
        if not _is_logged_in():
            return redirect(url_for("login", next=request.path))




    # -----------------------------
    # AUTH ROUTES
    # -----------------------------

    @app.route("/setup-admin", methods=["GET", "POST"])
    def setup_admin():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        # déjà configuré => go login/home
        if (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("login"))

        if request.method == "POST":
            # Récupération + normalisation (ne plante jamais)
            email_input = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")

            # ✅ Stricte: email obligatoire.
            # Si l'utilisateur laisse vide MAIS qu'un email existe déjà en DB, on le reprend.
            email = email_input or (s.get("admin_email") or "").strip().lower()

            # ✅ Validation stricte (pas seulement "@")
            # - non vide
            # - contient exactement un "@"
            # - pas d'espaces
            # - a un domaine avec un "."
            if (
                not email
                or " " in email
                or email.count("@") != 1
                or "." not in email.split("@", 1)[1]
            ):
                flash("Un email admin valide est obligatoire.", "error")
                return redirect(url_for("setup_admin"))

            # ✅ Mot de passe strict
            if len(password) < 8:
                flash("Mot de passe trop court (8 caractères minimum).", "error")
                return redirect(url_for("setup_admin"))

            pwd_hash = generate_password_hash(password)

            db.execute(
                "UPDATE settings SET admin_email = ?, admin_password_hash = ?, auth_enabled = 1 WHERE id = 1",
                (email, pwd_hash),
            )

            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email

            # ensuite seulement, si aucun serveur -> page serveurs
            row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
            if row and int(row["cnt"] or 0) == 0:
                return redirect(url_for("servers_list"))

            return redirect(url_for("dashboard"))

        return render_template(
            "auth/setup_admin.html",
            admin_email=(s.get("admin_email") or "")
        )



    @app.route("/login", methods=["GET", "POST"])
    def login():
        db = get_db()
        s = db.query_one("SELECT admin_email, admin_password_hash FROM settings WHERE id = 1")
        s = dict(s) if s else {"admin_email": "", "admin_password_hash": None}

        if not (s.get("admin_password_hash") or "").strip():
            return redirect(url_for("setup_admin"))

        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            if not email or email != (s.get("admin_email") or "").strip().lower():
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            if not check_password_hash(s["admin_password_hash"], password):
                flash("Email ou mot de passe incorrect.", "error")
                return redirect(url_for("login"))

            session["vodum_logged_in"] = True
            session["vodum_admin_email"] = email

            next_url = request.args.get("next") or url_for("dashboard")
            auth_logger.info("AUTH login ok email=%s ip=%s ua=%s", email, request.remote_addr, request.user_agent.string)
            return redirect(next_url)

        reset_host_example = os.environ.get(
            "VODUM_RESET_FILE_EXAMPLE",
            "/mnt/user/appdata/VODUM/password.reset"
        )
        reset_cmd = f'echo "{RESET_MAGIC}" > {reset_host_example}'

        return render_template(
            "auth/login.html",
            reset_available=os.path.exists(RESET_FILE),
            reset_cmd=reset_cmd,
        )



    @app.route("/logout")
    def logout():
        session.clear()
        auth_logger.info("AUTH logout ip=%s ua=%s", request.remote_addr, request.user_agent.string)
        return redirect(url_for("login"))

 


    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.before_request
    def setup_guard_no_servers():
        """
        Mode "setup" : si aucun serveur n'est configuré, on force l'accès
        uniquement à la page serveurs pour permettre l'initialisation.

        Ne rentre pas en conflit avec un futur système d'auth admin :
        - on laisse passer /login (si tu l'ajoutes plus tard)
        - et on peut ajuster facilement une whitelist.
        """
        # Routes toujours autorisées (setup)
        allowed_prefixes = (
            "/static",
            "/set_language",
            "/servers",       # liste + detail
            "/servers/new",   # création
            "/api/tasks/activity",  # optionnel (évite du bruit console UI)
            "/health",        # optionnel si tu as un healthcheck
            "/login",         # futur admin login
            "/logout",        # futur admin logout
            "/setup-admin",
        )

        if request.path.startswith(allowed_prefixes):
            return

        # On évite de bloquer les fichiers favicon & co
        if request.path in ("/favicon.ico",):
            return

        db = get_db()

        # Si la table servers n'existe pas encore, on considère "setup"
        try:
            exists = db.query_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='servers'"
            )
            if not exists:
                return redirect(url_for("servers_list"))
        except Exception:
            # si DB indispo, on ne force pas ici
            return

        # Si aucun serveur → setup mode actif
        row = db.query_one("SELECT COUNT(*) AS cnt FROM servers")
        if row and int(row["cnt"] or 0) == 0:
            return redirect(url_for("servers_list"))
    
    @app.before_request
    def maintenance_guard():
        # Routes toujours autorisées
        allowed = (
            request.path.startswith("/static"),
            request.path.startswith("/set_language"),
            request.path.startswith("/settings"),
        )

        if any(allowed):
            return

        db = get_db()
        row = db.query_one(
            "SELECT maintenance_mode FROM settings WHERE id = 1"
        )

        if row and row["maintenance_mode"] == 1:
            return (
                render_template(
                    "maintenance.html",
                    active_page="settings",
                ),
                503,
            )
            
            
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        db = get_db()

        # ------------------------------
        # Charger settings (source unique)
        # ------------------------------
        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        settings = dict(settings)

        # ------------------------------------------------------------
        # POST → SAVE ALL SETTINGS
        # ------------------------------------------------------------
        if request.method == "POST":

            new_values = {
                "default_language": request.form.get(
                    "default_language", settings["default_language"]
                ),
                "timezone": request.form.get(
                    "timezone", settings["timezone"]
                ),
                "admin_email": request.form.get(
                    "admin_email", settings["admin_email"]
                ),
                "default_subscription_days": request.form.get(
                    "default_expiration_days",
                    settings["default_subscription_days"],
                ),
                "delete_after_expiry_days": request.form.get(
                    "delete_after_expiry_days",
                    settings["delete_after_expiry_days"],
                ),

                # ✅ délais statut (settings ONLY)
                "preavis_days": request.form.get(
                    "preavis_days",
                    settings["preavis_days"],
                ),
                "reminder_days": request.form.get(
                    "relance_days",
                    settings["reminder_days"],
                ),
                "brand_name": request.form.get("brand_name", settings.get("brand_name")),

                "disable_on_expiry": 1 if request.form.get("disable_on_expiry") == "1" else 0,
                "enable_cron_jobs": 1 if request.form.get("enable_cron_jobs") == "1" else 0,
                "maintenance_mode": 1 if request.form.get("maintenance_mode") == "1" else 0,
                "debug_mode": 1 if request.form.get("debug_mode") == "1" else 0,
            }

            # --------------------------------------------------
            # Conversions INT (uniformes)
            # --------------------------------------------------
            for key in (
                "default_subscription_days",
                "delete_after_expiry_days",
                "preavis_days",
                "reminder_days",
            ):
                try:
                    new_values[key] = int(new_values[key])
                except Exception:
                    new_values[key] = settings[key]

            # --------------------------------------------------
            # UPDATE settings (source unique)
            # --------------------------------------------------
            db.execute(
                """
                UPDATE settings SET
                    default_language = :default_language,
                    timezone = :timezone,
                    admin_email = :admin_email,
                    brand_name = :brand_name,
                    default_subscription_days = :default_subscription_days,
                    delete_after_expiry_days = :delete_after_expiry_days,
                    preavis_days = :preavis_days,
                    reminder_days = :reminder_days,
                    disable_on_expiry = :disable_on_expiry,
                    enable_cron_jobs = :enable_cron_jobs,
                    maintenance_mode = :maintenance_mode,
                    debug_mode = :debug_mode
                WHERE id = 1
                """,
                new_values,
            )

            # --------------------------------------------------
            # Update admin password (optional)
            # --------------------------------------------------
            new_pwd = request.form.get("admin_password") or ""
            new_pwd = new_pwd.strip()
            if new_pwd:
                if len(new_pwd) < 8:
                    flash("Mot de passe admin trop court (8 caractères minimum).", "error")
                    return redirect(url_for("settings_page"))

                db.execute(
                    "UPDATE settings SET admin_password_hash = ? WHERE id = 1",
                    (generate_password_hash(new_pwd),),
                )
                flash("Mot de passe admin mis à jour.", "success")


            # --------------------------------------------------
            # Sync TASKS from SETTINGS (source unique)
            # --------------------------------------------------
            task_enabled = 1 if (
                new_values["enable_cron_jobs"] == 1
                and new_values["disable_on_expiry"] == 1
            ) else 0

            db.execute(
                """
                UPDATE tasks
                SET enabled = ?,
                    status  = CASE WHEN ? = 1 THEN 'idle' ELSE 'disabled' END
                WHERE name = 'disable_expired_users'
                """,
                (task_enabled, task_enabled),
            )




            # --------------------------------------------------
            # Log cohérent
            # --------------------------------------------------
            add_log(
                "info",
                "settings",
                "Settings updated",
                {
                    "default_language": new_values["default_language"],
                    "default_subscription_days": new_values["default_subscription_days"],
                    "preavis_days": new_values["preavis_days"],
                    "reminder_days": new_values["reminder_days"],
                },
            )

            session["lang"] = new_values["default_language"]

            flash(get_translator()("settings_saved"), "success")
            return redirect(url_for("settings_page"))

        # ------------------------------
        # GET → RENDER SETTINGS UI
        # ------------------------------
        return render_template(
            "settings/settings.html",
            settings=settings,   # ✅ source unique
            active_page="settings",
            current_lang=session.get("lang", settings["default_language"]),
            available_languages=get_available_languages(),
            app_version=g.get("app_version", "dev"),
        )



    # -----------------------------
    # LOGS
    # -----------------------------
    
    def paginate(logs, page, per_page=10):
        start = (page - 1) * per_page
        end = start + per_page
        total_pages = (len(logs) + per_page - 1) // per_page
        return logs[start:end], total_pages

    
    @app.route("/logs")
    def logs_page():
        # Filtres
        level = request.args.get("level")
        if not level:
            # Pas de filtre demandé => on choisit le défaut selon debug_mode
            db = get_db()
            row = db.query_one("SELECT debug_mode FROM settings WHERE id = 1")
            debug_mode = int(row["debug_mode"]) if row and row["debug_mode"] is not None else 0
            level = "ALL" if debug_mode == 1 else "INFO"

        level = level.upper()

        search = request.args.get("q", "").strip()

        # Pagination
        page = int(request.args.get("page", 1))
        per_page = 200  # Nombre de lignes de log à afficher par page

        
        lines = []

        # ----------------------------
        # Lecture fichier de log
        # ----------------------------
        raw_lines = read_all_logs()
        # ----------------------------
        # Filtrage + parsing minimal
        # ----------------------------
        for line in raw_lines:
            line = line.strip()

            # Filtre niveau
            if level != "ALL" and f"| {level} |" not in line:
                continue

            # Filtre recherche
            if search and search.lower() not in line.lower():
                continue

            lines.append(line)

        total_logs = len(lines)
        lines.reverse()  # ✅ plus récents d'abord


        # Pagination
        total_pages = max(1, math.ceil(total_logs / per_page))
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        paginated = lines[start:end]

        # ----------------------------
        # Parser chaque ligne
        # Format réel :
        # 2025-01-01 12:00:00 | INFO | module | Message...
        # ----------------------------
        parsed_logs = []

        for l in paginated:
            try:
                parts = l.split("|", 3)
                created_at = parts[0].strip()
                level_part = parts[1].strip()
                source_part = parts[2].strip()
                message_part = parts[3].strip()

                parsed_logs.append({
                    "created_at": created_at,
                    "level": level_part,
                    "source": source_part,
                    "message": message_part,
                })
            except:
                parsed_logs.append({
                    "created_at": "",
                    "level": "INFO",
                    "source": "system",
                    "message": l,
                })

        # ----------------------------
        # Fenêtre de pagination
        # ----------------------------
        window_size = 10
        page_window_start = max(1, page - 4)
        page_window_end = min(total_pages, page_window_start + window_size - 1)

        if (page_window_end - page_window_start) < (window_size - 1):
            page_window_start = max(1, page_window_end - window_size + 1)

        # ----------------------------
        # Rendu HTML
        # ----------------------------
        return render_template(
            "logs/logs.html",
            logs=parsed_logs,
            page=page,
            total_pages=total_pages,
            page_window_start=page_window_start,
            page_window_end=page_window_end,
            level=level,
            search=search,
            active_page="logs",
        )






    @app.route("/logs/download")
    def download_logs():
        log_path = "/logs/app.log"

        # Même règles d’anonymisation que logging_utils
        EMAIL_REGEX = re.compile(
            r'([a-zA-Z0-9._%+-])([a-zA-Z0-9._%+-]*)(@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        )
        TOKEN_REGEX = re.compile(
            r'(?i)\b(x-plex-token|token|authorization|bearer)\b\s*[:=]\s*[a-z0-9\-._]+'
        )

        def anonymize(line: str) -> str:
            line = EMAIL_REGEX.sub(
                lambda m: f"{m.group(1)}{'*' * len(m.group(2))}{m.group(3)}",
                line
            )
            line = TOKEN_REGEX.sub(
                lambda m: f"{m.group(1)}=***REDACTED***",
                line
            )
            return line

        output = []

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    output.append(anonymize(line))
        except FileNotFoundError:
            output.append("No logs available.\n")

        # 🆕 Nom de fichier avec date en préfixe
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today}_vodum-logs-anonymized.log"

        return Response(
            "".join(output),
            mimetype="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )







    # -----------------------------
    # ABOUT
    # -----------------------------


    @app.route("/about")
    def about_page():
        flask_version = version("flask")
        python_version = platform.python_version()
        os_info = f"{platform.system()} {platform.release()}-{platform.version()}"
        
        return render_template(
            "about/about.html",
            flask_version=flask_version,
            python_version=python_version,
            os_info=os_info,
            active_page="about"
        )




    # Expose helpers pour d’éventuels scripts internes
    app.get_db = get_db
    app.table_exists = table_exists
    app.scheduler_db_provider = scheduler_db_provider


    return app


app = create_app()

# ✅ Evite double démarrage du scheduler en mode debug (reloader)
# - En debug: Flask lance 2 process (parent + enfant). WERKZEUG_RUN_MAIN='true' seulement dans l'enfant.
# - En prod (sans reloader): la variable n'est pas définie => on démarre.
if (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    with app.app_context():
        start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, use_reloader=False)
