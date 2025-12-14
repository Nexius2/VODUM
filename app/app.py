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
)
from config import Config
#from tasks import create_task, run_task
from tasks_engine import set_db_provider, run_task, start_scheduler, run_task_sequence
import json
from zoneinfo import ZoneInfo
import smtplib
from email.message import EmailMessage
#from flask_login import login_required
import math
from importlib.metadata import version
import platform
from db_utils import open_db
from logging_utils import get_logger
task_logger = get_logger("tasks_ui")
from api.subscriptions import subscriptions_api, update_user_expiration
import uuid
from mailing_utils import build_user_context, render_mail






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
    # Injecte la version globale dans tous les templates

    @app.before_request
    def inject_version():
        g.app_version = APP_VERSION

    app.config.from_object(Config)

    # Répertoire de backup (mounté par Docker, ex: /backups)
    app.config.setdefault("BACKUP_DIR", os.environ.get("VODUM_BACKUP_DIR", "/backups"))
    
    app.register_blueprint(subscriptions_api)

    # -----------------------------
    # DB helpers
    # -----------------------------
    def get_db():
        if "db" not in g:
            g.db = open_db(app.config["DATABASE"])
        return g.db


    def scheduler_db_provider():
        return open_db()


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
        - string "YYYY-MM-DD HH:MM:SS"
        """

        if dt is None:
            return "-"

        # Convertir la valeur brute en datetime
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except Exception:
                # format inconnu → on renvoie la chaîne brute
                return dt

        # À ce stade, dt est un datetime → on le considère comme UTC s'il est naïf
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Charger la timezone depuis la DB
        db = get_db()
        row = db.execute("SELECT timezone FROM settings WHERE id = 1").fetchone()
        tzname = row["timezone"] if row and row["timezone"] else "UTC"

        try:
            local_tz = ZoneInfo(tzname)
            return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            # Si la timezone est invalide, on renvoie l'heure en UTC au format lisible
            return dt.strftime("%Y-%m-%d %H:%M:%S")




    @app.teardown_appcontext
    def close_db(exception):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def table_exists(db, name: str) -> bool:
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def add_log(level, category, message, details=None):
        db = get_db()
        if table_exists(db, "logs"):
            db.execute(
                """
                INSERT INTO logs(level, category, message, details)
                VALUES (?, ?, ?, ?)
                """,
                (level, category, message, json.dumps(details) if details is not None else None),
            )
            db.commit()

    def send_email_via_settings(subject, body, to_email, db=None):
        """
        Envoie un email simple en utilisant les paramètres SMTP de settings.
        Retourne True si OK, sinon lève une exception.
        """
        db = db or get_db()
        settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if not settings:
            raise RuntimeError("No settings row found")

        smtp_host = settings["smtp_host"]
        smtp_port = settings["smtp_port"] or 587
        smtp_tls = bool(settings["smtp_tls"])
        smtp_user = settings["smtp_user"]
        smtp_pass = settings["smtp_pass"]
        mail_from = settings["mail_from"] or smtp_user

        if not smtp_host or not mail_from:
            raise RuntimeError("SMTP host or from address not configured")

        msg = EmailMessage()
        msg["From"] = mail_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_tls:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass or "")
            server.send_message(msg)

        return True


    # -----------------------------
    # HELPERS BACKUP
    # -----------------------------
    def ensure_backup_dir() -> Path:
        backup_dir = Path(app.config["BACKUP_DIR"])
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def create_backup_file() -> str:
        """
        Crée un backup propre et cohérent de la base SQLite.
        Retourne le nom du fichier créé.
        """

        backup_dir = ensure_backup_dir()
        src = Path(app.config["DATABASE"])

        if not src.exists():
            raise FileNotFoundError(f"Database file not found: {src}")

        # 🔥 Étape CRITIQUE : vider / appliquer le WAL avant la copie
        try:
            conn = open_db()
            # Forcer SQLite à écrire tout ce qui est dans le WAL et le vider
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
        except Exception as e:
            # On ne doit jamais arrêter le backup pour un warning de checkpoint
            print(f"[BACKUP] Warning: WAL checkpoint failed: {e}")

        # Nom final du fichier
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        dst_name = f"vodum-{timestamp}.db"
        dst = backup_dir / dst_name

        # 📦 Copie physique du fichier DB
        shutil.copy2(src, dst)

        return dst_name


    def list_backups():
        backup_dir = ensure_backup_dir()
        backups = []
        for f in sorted(backup_dir.glob("vodum-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = f.stat()
            backups.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return backups

    def restore_backup_file(uploaded_path: Path):
        """
        Écrase la base actuelle par le fichier fourni.
        ATTENTION : il est recommandé de redémarrer le conteneur après.
        """
        db_path = Path(app.config["DATABASE"])
        # Sauvegarde de précaution du fichier actuel
        if db_path.exists():
            backup_dir = ensure_backup_dir()
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(db_path, backup_dir / f"pre-restore-{timestamp}.db")

        shutil.copy2(uploaded_path, db_path)

    # ======================
    #   MULTILINGUAL SYSTEM
    # ======================

    def load_language_dict(lang=None):
        # 1) Si aucun paramètre n’est fourni → on choisit via session ou DB
        if not lang:
            lang = session.get("lang")

            if not lang:
                db = get_db()
                cur = db.cursor()
                cur.execute("SELECT default_language FROM settings WHERE id = 1")
                row = cur.fetchone()
                lang = row["default_language"] if row and row["default_language"] else "en"
                session["lang"] = lang

        # 2) Chargement du fichier JSON
        path = os.path.join(os.path.dirname(__file__), "lang", f"{lang}.json")

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            # Fallback FR si fichier manquant
            with open(os.path.join(os.path.dirname(__file__), "lang", "en.json"), "r", encoding="utf-8") as f:
                return json.load(f)

    def get_available_languages():
        lang_dir = os.path.join(os.path.dirname(__file__), "lang")
        languages = {}

        for filename in os.listdir(lang_dir):
            if filename.endswith(".json"):
                code = filename[:-5]  # fr.json → fr

                # lire le "language_name" dans le JSON
                try:
                    with open(os.path.join(lang_dir, filename), "r", encoding="utf-8") as f:
                        data = json.load(f)
                        name = data.get("language_name", code.upper())
                except:
                    name = code.upper()

                languages[code] = name

        return languages



    def get_translator():
        translations = load_language_dict()  # ne pas passer de paramètre !

        def t(key):
            return translations.get(key, key)

        return t



    # Injecte "t" dans tous les templates Jinja
    @app.context_processor
    def inject_globals():
        db = get_db()
        row = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        # Always convert to dict for consistent behavior everywhere
        settings = dict(row) if row else {}

        return {
            "t": get_translator(),
            "settings": settings
        }




    @app.route("/set_language/<lang>")
    def set_language(lang):
        session["lang"] = lang
        return redirect(request.referrer or url_for("dashboard"))


    # -----------------------------
    # ROUTES
    # -----------------------------

    @app.route("/")
    def dashboard():
        db = get_db()

        # --------------------------
        # USER STATS
        # --------------------------
        stats = {
            "total_users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],

            "active_users": db.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'active'"
            ).fetchone()[0],

            # ✔ CORRECTION : expiring soon = reminder + pre_expired
            "expiring_soon": db.execute(
                "SELECT COUNT(*) FROM users WHERE status IN ('pre_expired', 'reminder')"
            ).fetchone()[0],

            "expired_users": db.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'expired'"
            ).fetchone()[0],
        }

        # --------------------------
        # SERVER STATS (tous types)
        # --------------------------
        stats["server_types"] = {}

        server_types = db.execute(
            "SELECT DISTINCT type FROM servers WHERE type IS NOT NULL AND type != '' ORDER BY type"
        ).fetchall()

        for row in server_types:
            stype = row["type"]

            total = db.execute(
                "SELECT COUNT(*) FROM servers WHERE type = ?",
                (stype,),
            ).fetchone()[0]

            online = db.execute(
                "SELECT COUNT(*) FROM servers WHERE type = ? AND status = 'up'",
                (stype,),
            ).fetchone()[0]

            offline = db.execute(
                "SELECT COUNT(*) FROM servers WHERE type = ? AND status = 'down'",
                (stype,),
            ).fetchone()[0]

            stats["server_types"][stype] = {
                "total": total,
                "online": online,
                "offline": offline,
            }

        # --------------------------
        # TASK STATS
        # --------------------------
        if table_exists(db, "tasks"):
            stats["total_tasks"] = db.execute(
                "SELECT COUNT(*) FROM tasks"
            ).fetchone()[0]

            stats["active_tasks"] = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE enabled = 1"
            ).fetchone()[0]

            stats["error_tasks"] = db.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'error'"
            ).fetchone()[0]
        else:
            stats["total_tasks"] = 0
            stats["active_tasks"] = 0
            stats["error_tasks"] = 0

        # --------------------------
        # SERVER LIST (tous types)
        # --------------------------
        servers = db.execute(
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
        ).fetchall()

        # --------------------------
        # LATEST LOGS (fichier)
        # --------------------------
        latest_logs = []

        log_file = "/logs/app.log"
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()[-10:]  # dernier 10 logs
        except FileNotFoundError:
            lines = []

        for line in lines:
            parts = line.split("|", 3)
            if len(parts) == 4:
                latest_logs.append({
                    "created_at": parts[0].strip(),
                    "level": parts[1].strip(),
                    "source": parts[2].strip(),
                    "message": parts[3].strip(),
                })
            else:
                latest_logs.append({
                    "created_at": "",
                    "level": "INFO",
                    "source": "system",
                    "message": line.strip(),
                })

        # --------------------------
        # PAGE RENDERING
        # --------------------------
        return render_template(
            "dashboard.html",
            stats=stats,
            servers=servers,        # ← remplace plex_servers
            latest_logs=latest_logs,
            active_page="dashboard",
        )



    # -----------------------------
    # UTILISATEURS
    # -----------------------------
    
    def get_user_servers_with_access(user_id):
        """
        Retourne la liste des serveurs liés à un utilisateur, avec :
        - serveur
        - bibliothèques auxquelles il a accès (shared_libraries)
        """
        db = get_db()

        # Récupération des serveurs liés à l’utilisateur
        servers = db.execute(
            """
            SELECT s.*
            FROM servers s
            JOIN user_servers us ON us.server_id = s.id
            WHERE us.user_id = ?
            ORDER BY s.name
            """,
            (user_id,),
        ).fetchall()

        # Pour chaque serveur, on récupère les bibliothèques accessibles
        server_list = []
        for s in servers:
            libraries = db.execute(
                """
                SELECT l.*
                FROM libraries l
                JOIN shared_libraries sl ON sl.library_id = l.id
                WHERE sl.user_id = ?
                AND l.server_id = ?
                ORDER BY l.name
                """,
                (user_id, s["id"]),
            ).fetchall()

            server_list.append({
                "server": s,
                "libraries": libraries
            })

        return server_list

    
    @app.route("/users")
    def users_list():
        db = get_db()
        status_filter = request.args.get("status")
        search = request.args.get("q", "").strip()

        query = """
            SELECT
                u.*,
                COUNT(DISTINCT us.server_id) AS servers_count,
                COUNT(DISTINCT sl.library_id) AS libraries_count
            FROM users u
            LEFT JOIN user_servers us ON us.user_id = u.id
            LEFT JOIN shared_libraries sl ON sl.user_id = u.id
        """
        conditions = []
        params = []

        if status_filter:
            conditions.append("u.status = ?")
            params.append(status_filter)
        if search:
            conditions.append("(u.username LIKE ? OR u.email LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " GROUP BY u.id ORDER BY u.username ASC"

        users = db.execute(query, params).fetchall()

        return render_template(
            "users.html",
            users=users,
            status_filter=status_filter,
            search=search,
            active_page="users",
        )

    @app.route("/users/<int:user_id>", methods=["GET", "POST"])
    def user_detail(user_id):
        db = get_db()

        # Charger l’utilisateur
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("Utilisateur introuvable", "error")
            return redirect(url_for("users_list"))

        # --------------------------------------------------------------------
        #  POST → Mise à jour utilisateur + options serveur + jobs SYNC
        # --------------------------------------------------------------------
        if request.method == "POST":
            form = request.form


            # 1) --- Mise à jour des informations utilisateur ---
            firstname       = form.get("firstname") or user["firstname"]
            lastname        = form.get("lastname") or user["lastname"]
            second_email    = form.get("second_email") or user["second_email"]
            expiration_date = form.get("expiration_date") or user["expiration_date"]
            renewal_date    = form.get("renewal_date") or user["renewal_date"]
            renewal_method  = form.get("renewal_method") or user["renewal_method"]

            # Notes : géré uniquement si formulaire notes soumis
            notes = user["notes"]
            if "notes" in form:
                notes = form.get("notes") or user["notes"]

            db.execute(
                """
                UPDATE users
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
            db.commit()

            # Mise à jour de la date d’expiration via la logique métier
            if expiration_date != user["expiration_date"]:
                update_user_expiration(
                    user_id,
                    expiration_date,
                    reason="ui_manual"
                )


            # 2) --- Mise à jour des options serveur ---
            servers = db.execute("SELECT id, type FROM servers").fetchall()

            for s in servers:
                sid = s["id"]

                # Récupérer les valeurs POST
                allow_sync     = 1 if form.get(f"allow_sync_{sid}") else 0
                allow_camera   = 1 if form.get(f"allow_camera_upload_{sid}") else 0
                allow_channels = 1 if form.get(f"allow_channels_{sid}") else 0

                filter_movies      = form.get(f"filter_movies_{sid}") or None
                filter_television  = form.get(f"filter_television_{sid}") or None
                filter_music       = form.get(f"filter_music_{sid}") or None

                # Vérifie si la ligne existe dans user_servers
                row = db.execute(
                    "SELECT 1 FROM user_servers WHERE user_id = ? AND server_id = ?",
                    (user_id, sid)
                ).fetchone()

                if row:
                    db.execute(
                        """
                        UPDATE user_servers
                        SET allow_sync = ?, allow_camera_upload = ?, allow_channels = ?,
                            filter_movies = ?, filter_television = ?, filter_music = ?
                        WHERE user_id = ? AND server_id = ?
                        """,
                        (
                            allow_sync, allow_camera, allow_channels,
                            filter_movies, filter_television, filter_music,
                            user_id, sid
                        ),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO user_servers(
                            user_id, server_id,
                            allow_sync, allow_camera_upload, allow_channels,
                            filter_movies, filter_television, filter_music
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id, sid,
                            allow_sync, allow_camera, allow_channels,
                            filter_movies, filter_television, filter_music
                        ),
                    )

            # 3) --- Ajouter un job SYNC pour chaque serveur PLEX ---
            plex_servers = db.execute(
                "SELECT id FROM servers WHERE type = 'plex'"
            ).fetchall()

            for s in plex_servers:
                db.execute(
                    """
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('sync', ?, ?, NULL, 0)
                    """,
                    (user_id, s["id"])
                )

            db.commit()

            # 4) --- Lancer la tâche apply_plex_access_updates ---
            run_task("apply_plex_access_updates")

            flash("Modifications enregistrées et synchronisation Plex lancée.", "success")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------------------------
        #  GET → Chargement complet user + serveurs + bibliothèques
        # --------------------------------------------------------------------

        # 1) Serveurs accessibles par l’utilisateur (avec options Plex)
        servers = db.execute(
            """
            SELECT
                s.*,
                us.allow_sync,
                us.allow_camera_upload,
                us.allow_channels,
                us.filter_movies,
                us.filter_television,
                us.filter_music,
                CASE WHEN us.user_id IS NOT NULL THEN 1 ELSE 0 END AS has_access
            FROM servers s
            LEFT JOIN user_servers us
                   ON us.server_id = s.id AND us.user_id = ?
            ORDER BY s.name
            """,
            (user_id,),
        ).fetchall()

        # 2) Bibliothèques + accès user
        libraries = db.execute(
            """
            SELECT
                l.*,
                s.name AS server_name,
                CASE WHEN sl.user_id IS NOT NULL THEN 1 ELSE 0 END AS has_access
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            LEFT JOIN shared_libraries sl
                   ON sl.library_id = l.id AND sl.user_id = ?
            ORDER BY s.name, l.name
            """,
            (user_id,),
        ).fetchall()

        # 3) Historique emails
        sent_emails = db.execute(
            """
            SELECT *
            FROM sent_emails
            WHERE user_id = ?
            ORDER BY sent_at DESC
            """,
            (user_id,),
        ).fetchall()

        # --------------------------------------------------------------------
        #  Rendu
        # --------------------------------------------------------------------
        return render_template(
            "user_detail.html",
            user=user,
            servers=servers,
            libraries=libraries,
            user_servers=servers,
            sent_emails=sent_emails,
        )






    @app.route("/users/<int:user_id>/toggle_library", methods=["POST"])
    def user_toggle_library(user_id):
        db = get_db()
        library_id = request.form.get("library_id", type=int)

        if not library_id:
            flash("Bibliothèque invalide", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # Vérifie si l'accès existe déjà
        exists = db.execute(
            "SELECT 1 FROM shared_libraries WHERE user_id = ? AND library_id = ?",
            (user_id, library_id),
        ).fetchone()

        if exists:
            # RETIRER
            db.execute(
                "DELETE FROM shared_libraries WHERE user_id = ? AND library_id = ?",
                (user_id, library_id),
            )
            db.commit()
            flash("Accès retiré", "success")
        else:
            # AJOUTER
            db.execute(
                """
                INSERT INTO shared_libraries(user_id, library_id)
                VALUES(?, ?)
                """,
                (user_id, library_id),
            )
            db.commit()
            flash("Accès ajouté", "success")

        return redirect(url_for("user_detail", user_id=user_id))


    # -----------------------------
    # SERVEURS & BIBLIO
    # -----------------------------
    
    @app.route("/servers/<int:server_id>/sync")
    def sync_server(server_id):
        run_task("sync_server", {"server_id": server_id})

        return redirect(url_for("server_detail", server_id=server_id))
    
    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = db.execute("""
            SELECT
                s.*,
                COUNT(DISTINCT l.id) AS libraries_count,
                COUNT(DISTINCT us.user_id) AS users_count
            FROM servers s
            LEFT JOIN libraries l ON l.server_id = s.id
            LEFT JOIN user_servers us ON us.server_id = s.id
            GROUP BY s.id
            ORDER BY s.name
        """).fetchall()

        return render_template(
            "servers.html",
            servers=servers,
            active_page="servers",
            active_tab="servers"
        )

    @app.route("/libraries", methods=["GET"])
    def libraries_list():
        db = get_db()

        libraries = db.execute("""
            SELECT
                l.*,
                s.name AS server_name,
                COUNT(sl.user_id) AS users_count
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            LEFT JOIN shared_libraries sl ON sl.library_id = l.id
            GROUP BY l.id
            ORDER BY s.name, l.name
        """).fetchall()

        return render_template(
            "libraries.html",
            libraries=libraries,
            active_page="servers",
            active_tab="libraries"
        )


    @app.route("/servers/new", methods=["POST"])
    def server_create():
        db = get_db()

        name = request.form.get("name", "").strip()
        server_type = request.form.get("type", "plex")  # ⬅️ important
        url = request.form.get("url") or None
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None
        server_identifier = str(uuid.uuid4())


        if not name:
            flash("Le nom du serveur est obligatoire", "error")
            return redirect(url_for("servers_list"))

        # Enregistrer le serveur
        db.execute("""
            INSERT INTO servers (name, type, server_identifier, url, local_url, public_url, token,
                                 tautulli_url, tautulli_api_key, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, server_type, server_identifier, url, local_url, public_url, token,
            tautulli_url, tautulli_api_key, "unknown"
        ))
        db.commit()

        # 🔥 Libérer la DB pour éviter le lock
        #if "db" in g and g.db:
        #    g.db.close()
        #    g.db = None

        # 🔥 Lancer les tâches SEULEMENT si c'est un serveur Plex
        if server_type == "plex":
            db.execute("""
                UPDATE tasks
                SET enabled = 1, status = 'queued'
                WHERE name IN ('check_servers', 'sync_plex', 'update_user_status')
            """)
            db.commit()

            flash("Serveur Plex créé. Synchronisation planifiée.", "success")

        else:
            flash("Serveur créé (non Plex). Aucune synchronisation lancée.", "success")

        return redirect(url_for("servers_list"))


    @app.route("/servers/<int:server_id>/delete", methods=["POST"])
    def server_delete(server_id):
        db = get_db()

        # Vérifier que le serveur existe
        server = db.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        if not server:
            flash("Serveur introuvable", "error")
            return redirect(url_for("servers_list"))

        # Suppression
        db.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        db.commit()

        flash("Serveur supprimé", "success")

        return redirect(url_for("servers_list"))


    @app.route("/servers/<int:server_id>", methods=["GET", "POST"])
    def server_detail(server_id):
        db = get_db()

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            server_type = request.form.get("type") or "other"  # ← NEW
            url = request.form.get("url") or None
            local_url = request.form.get("local_url") or None
            public_url = request.form.get("public_url") or None
            token = request.form.get("token") or None
            tautulli_url = request.form.get("tautulli_url") or None
            tautulli_api_key = request.form.get("tautulli_api_key") or None
            status = request.form.get("status") or None

            if not name:
                flash("Le nom du serveur est obligatoire", "error")
                return redirect(url_for("server_detail", server_id=server_id))

            db.execute(
                """
                UPDATE servers
                SET name = ?, type = ?, url = ?, local_url = ?, public_url = ?, token = ?,
                    tautulli_url = ?, tautulli_api_key = ?, status = ?
                WHERE id = ?
                """,
                (name, server_type, url, local_url, public_url, token,
                 tautulli_url, tautulli_api_key, status, server_id),
            )
            db.commit()

            flash("Serveur mis à jour", "success")
            return redirect(url_for("server_detail", server_id=server_id))

        # GET
        server = db.execute(
            "SELECT * FROM servers WHERE id = ?", (server_id,)
        ).fetchone()
        if not server:
            return "Serveur introuvable", 404

        libraries = db.execute(
            """
            SELECT
                l.*,
                COUNT(DISTINCT sl.user_id) AS users_count
            FROM libraries l
            LEFT JOIN shared_libraries sl ON sl.library_id = l.id
            WHERE l.server_id = ?
            GROUP BY l.id
            ORDER BY l.name
            """,
            (server_id,),
        ).fetchall()

        users = db.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                us.server_id
            FROM users u
            JOIN user_servers us ON us.user_id = u.id
            WHERE us.server_id = ?
            ORDER BY u.username
            """,
            (server_id,),
        ).fetchall()

        return render_template(
            "server_detail.html",
            server=server,
            libraries=libraries,
            users=users,
            active_page="servers",
        )



    @app.route("/servers/bulk_grant", methods=["POST"])
    def bulk_grant_libraries():
        db = get_db()
        t = get_translator()

        server_id = request.form.get("server_id", type=int)
        library_ids = request.form.getlist("library_ids")

        if not server_id or not library_ids:
            flash("Aucun serveur ou bibliothèque sélectionné", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # 1️⃣ Récupère seulement les utilisateurs ACTIFS sur ce serveur
        users = db.execute(
            """
            SELECT us.user_id
            FROM user_servers us
            JOIN users u ON u.id = us.user_id
            WHERE us.server_id = ?
              AND u.status = 'active'
            """,
            (server_id,),
        ).fetchall()

        user_ids = [u["user_id"] for u in users]

        if not user_ids:
            flash("Aucun utilisateur actif pour ce serveur", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # 2️⃣ Met à jour la table interne shared_libraries (comme avant)
        for lib_id in library_ids:
            for uid in user_ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO shared_libraries(user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (uid, lib_id),
                )

        # 3️⃣ Ajoute des jobs Plex pour chaque (user, library, server)
        for lib_id in library_ids:
            for uid in user_ids:
                db.execute(
                    """
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('grant', ?, ?, ?, 0)
                    """,
                    (uid, server_id, lib_id),
                )

        # 4️⃣ Active la tâche "apply_plex_access_updates" pour qu'elle traite la file
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

        db.commit()

        flash(t("grant_access_active_success"), "success")
        return redirect(url_for("servers_list", server_id=server_id))

    # -----------------------------
    #  abonnements
    # -----------------------------
    @app.route("/subscriptions", methods=["GET"])
    def subscriptions():
        db = get_db()
        servers = db.execute("SELECT id, name FROM servers ORDER BY name").fetchall()
        return render_template("subscriptions.html", servers=servers)



    # -----------------------------
    # TÂCHES
    # -----------------------------
    
    @app.route("/tasks/run/<int:task_id>", methods=["POST"])
    def task_run(task_id):
        run_task(task_id)
        flash("Tâche lancée.", "success")
        return redirect("/tasks")
    



    @app.route("/tasks", methods=["GET", "POST"])
    def tasks_page():
        db = get_db()

        # ------------------------------------------------------------------
        #  POST : actions sur les tâches (toggle / run_now)
        # ------------------------------------------------------------------
        if request.method == "POST" and table_exists(db, "tasks"):
            task_id = request.form.get("task_id", type=int)
            action = request.form.get("action")

            if not task_id:
                flash("Tâche invalide", "error")
                task_logger.error("POST /tasks → task_id manquant")
                return redirect(url_for("tasks_page"))

            # --------------------------------------------------------------
            # 1) Toggle enable/disable
            # --------------------------------------------------------------
            if action == "toggle":
                db.execute(
                    """
                    UPDATE tasks
                    SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END
                    WHERE id = ?
                    """,
                    (task_id,),
                )
                db.commit()

                new_state = db.execute(
                    "SELECT enabled FROM tasks WHERE id=?", (task_id,)
                ).fetchone()

                task_logger.info(
                    f"Tâche {task_id} → toggle → enabled={new_state['enabled']}"
                )
                flash("Tâche mise à jour", "success")

            # --------------------------------------------------------------
            # 2) run_now → marque la tâche comme queued
            # --------------------------------------------------------------
            elif action == "run_now":
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                db.execute(
                    """
                    UPDATE tasks
                    SET status = ?, last_run = ?
                    WHERE id = ?
                    """,
                    ("queued", now, task_id),
                )
                db.commit()

                task_logger.info(
                    f"Tâche {task_id} marquée 'queued' depuis l'UI à {now}"
                )

                flash("Tâche marquée pour exécution", "success")

            else:
                task_logger.warning(f"Action inconnue sur /tasks : {action}")

        # ------------------------------------------------------------------
        #  GET : affichage liste des tâches
        # ------------------------------------------------------------------
        tasks = []
        if table_exists(db, "tasks"):
            tasks = db.execute(
                """
                SELECT *
                FROM tasks
                ORDER BY name
                """
            ).fetchall()

        task_logger.debug(f"Affichage page tasks → {len(tasks)} tâches détectées")

        return render_template(
            "tasks.html",
            tasks=tasks,
            active_page="tasks",
        )


    # -----------------------------
    # MAILING
    # -----------------------------
    
    @app.post("/api/mailing/toggle")
    def api_mailing_toggle():
        db = get_db()   # ← utilise la connexion Flask, évite les locks

        data = request.get_json(silent=True) or {}
        enabled = 1 if data.get("enabled") else 0

        try:
            # 1️⃣ Mettre à jour le flag de settings
            db.execute(
                "UPDATE settings SET mailing_enabled = ? WHERE id = 1",
                (enabled,)
            )

            # 2️⃣ Activer / désactiver les tâches liées au mailing
            db.execute(
                """
                UPDATE tasks
                SET enabled = ?
                WHERE name IN ('send_expiration_emails', 'send_mail_campaigns')
                """,
                (enabled,)
            )

            db.commit()

            add_log(
                "INFO",
                "mailing",
                f"Mailing toggled → {enabled}"
            )

            return {"status": "ok", "enabled": enabled}

        except Exception as e:
            db.rollback()
            add_log("ERROR", "mailing", "Failed to toggle mailing", {"error": str(e)})
            return {"status": "error", "message": str(e)}, 500



    
    @app.route("/mailing")
    def mailing_page():
        db = get_db()
        row = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        settings = dict(row) if row else None


        print("SETTINGS FROM /mailing:", settings)
        print("KEYS:", list(settings.keys()))

        if settings and settings["mailing_enabled"] == 1:
            return redirect(url_for("mailing_campaigns_page"))
        else:
            return redirect(url_for("mailing_smtp_page"))



    @app.route("/mailing/campaigns", methods=["GET", "POST"])
    def mailing_campaigns_page():
        db = get_db()
        t = get_translator()

        # Fetch list of servers for dropdown
        servers = db.execute("SELECT id, name FROM servers ORDER BY name").fetchall()

        # -----------------------------------------------------------------------------
        # 1. LOAD CAMPAIGN INTO FORM (user clicked on a row)
        # -----------------------------------------------------------------------------
        load_id = request.args.get("load", type=int)
        loaded_campaign = None

        if load_id:
            loaded_campaign = db.execute(
                "SELECT * FROM mail_campaigns WHERE id = ?", (load_id,)
            ).fetchone()

        # -----------------------------------------------------------------------------
        # 2. CREATE NEW CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "create":
            subject = (request.form.get("subject") or "").strip()
            body = (request.form.get("body") or "").strip()
            server_id = request.form.get("server_id", type=int)
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not subject or not body:
                flash(t("campaign_missing_fields"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            db.execute("""
                INSERT INTO mail_campaigns(subject, body, server_id, status, is_test, created_at)
                VALUES (?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
            """, (subject, body, server_id, is_test))
            db.commit()

            add_log("INFO", "mail_campaigns", "Campaign created",
                    {"subject": subject, "is_test": is_test})

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

            db.execute("""
                UPDATE mail_campaigns
                SET subject = ?, body = ?, server_id = ?, is_test = ?
                WHERE id = ?
            """, (subject, body, server_id, is_test, cid))
            db.commit()

            add_log("INFO", "mail_campaigns", "Campaign updated",
                    {"id": cid, "subject": subject})

            flash(t("campaign_saved"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 3. SEND CAMPAIGN
        # -----------------------------------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "send":
            cid = request.form.get("campaign_id", type=int)

            campaign = db.execute(
                "SELECT * FROM mail_campaigns WHERE id = ?", (cid,)
            ).fetchone()

            if not campaign:
                flash(t("campaign_not_found"), "error")
                return redirect(url_for("mailing_campaigns_page"))

            # Mark as sending
            db.execute("UPDATE mail_campaigns SET status='sending' WHERE id=?", (cid,))
            db.commit()

            settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            admin_email = settings["admin_email"]

            # -----------------------------------------------------
            # TEST MODE : send only to admin email
            # -----------------------------------------------------
            if campaign["is_test"]:
                try:
                    send_email_via_settings(campaign["subject"], campaign["body"], admin_email)

                    db.execute("""
                        UPDATE mail_campaigns
                        SET status='finished', finished_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (cid,))
                    db.commit()

                    flash(t("campaign_test_sent"), "success")

                except Exception as e:
                    db.execute("""
                        UPDATE mail_campaigns
                        SET status='error', finished_at=CURRENT_TIMESTAMP
                        WHERE id=?
                    """, (cid,))
                    db.commit()

                    flash(t("campaign_send_failed") + f" ({e})", "error")

                return redirect(url_for("mailing_campaigns_page"))

            # -----------------------------------------------------
            # REAL MASS SENDING
            # -----------------------------------------------------
            if campaign["server_id"]:
                users = db.execute("""
                    SELECT u.email, u.username, u.expiration_date
                    FROM users u
                    JOIN user_servers us ON us.user_id = u.id
                    WHERE us.server_id = ?
                """, (campaign["server_id"],)).fetchall()
            else:
                users = db.execute("""
                    SELECT email, username, expiration_date FROM users
                """).fetchall()

            errors = 0

            for u in users:
                if not u["email"]:
                    continue

                formatted_body = campaign["body"] \
                    .replace("{username}", u["username"]) \
                    .replace("{email}", u["email"]) \
                    .replace("{expiration_date}", u["expiration_date"] or "")

                try:
                    send_email_via_settings(campaign["subject"], formatted_body, u["email"])
                except Exception as e:
                    errors += 1
                    add_log("ERROR", "mail_campaigns",
                            "Sending failed",
                            {"user": u["email"], "campaign": cid, "error": str(e)})

            final_status = "finished" if errors == 0 else "error"

            db.execute("""
                UPDATE mail_campaigns
                SET status=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (final_status, cid))
            db.commit()

            flash(t("campaign_sent"), "success")
            return redirect(url_for("mailing_campaigns_page"))

        # -----------------------------------------------------------------------------
        # 4. DISPLAY PAGE (campaign list + loaded campaign)
        # -----------------------------------------------------------------------------
        campaigns = db.execute("""
            SELECT c.*, s.name AS server_name
            FROM mail_campaigns c
            LEFT JOIN servers s ON s.id = c.server_id
            ORDER BY datetime(c.created_at) DESC
        """).fetchall()

        return render_template(
            "mailing_campaigns.html",
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
                ids
            )
            db.commit()

            add_log(
                "INFO",
                "mail_campaigns",
                "Campaigns deleted",
                {"ids": ids}
            )

            flash(t("campaigns_deleted").format(count=len(ids)), "success")

        except Exception as e:
            db.rollback()

            add_log(
                "ERROR",
                "mail_campaigns",
                "Failed to delete campaigns",
                {"ids": ids, "error": str(e)}
            )

            flash(t("campaign_delete_failed") + f" ({e})", "error")

        return redirect(url_for("mailing_campaigns_page"))



    @app.route("/mailing/templates", methods=["GET", "POST"])
    def mailing_templates_page():
        db = get_db()
        t = get_translator()

        # ---------------------------------------------------
        # S’assurer que les 3 templates existent
        # ---------------------------------------------------
        for type_ in ["preavis", "relance", "fin"]:
            exists = db.execute(
                "SELECT 1 FROM email_templates WHERE type = ?",
                (type_,)
            ).fetchone()

            if not exists:
                db.execute("""
                    INSERT INTO email_templates(type, subject, body, days_before)
                    VALUES (?, '', '', 0)
                """, (type_,))

        db.commit()

        # ---------------------------------------------------
        # SAUVEGARDE DES MODIFICATIONS
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "save":

            templates = db.execute("SELECT * FROM email_templates").fetchall()

            for tpl in templates:
                tid = tpl["id"]

                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()

                days_raw = request.form.get(f"days_before_{tid}", "")
                try:
                    days_before = int(days_raw)
                except Exception:
                    days_before = tpl["days_before"]

                db.execute("""
                    UPDATE email_templates
                    SET subject = ?, body = ?, days_before = ?
                    WHERE id = ?
                """, (subject, body, days_before, tid))

            db.commit()
            add_log("INFO", "mail_templates", "Templates updated", None)
            flash(t("templates_saved"), "success")

        # ---------------------------------------------------
        # ENVOI DE TEST (AVEC RENDU DES VARIABLES)
        # ---------------------------------------------------
        if request.method == "POST" and request.form.get("action") == "test":
            template_id = request.form.get("test_template_id", type=int)

            settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            admin_email = settings["admin_email"] if settings else None

            if not admin_email:
                flash(t("admin_email_missing"), "error")
            else:
                tpl = db.execute(
                    "SELECT * FROM email_templates WHERE id = ?",
                    (template_id,)
                ).fetchone()

                if not tpl:
                    flash(t("template_not_found"), "error")
                else:
                    try:
                        # 🔥 CONTEXTE DE TEST RÉALISTE
                        test_user = {
                            "username": "TestUser",
                            "email": admin_email,
                            "expiration_date": "2025-12-31",
                        }

                        context = build_user_context(test_user)

                        subject = render_mail(tpl["subject"], context)
                        body = render_mail(tpl["body"], context)

                        send_email_via_settings(subject, body, admin_email)

                        add_log(
                            "INFO",
                            "mail_templates",
                            f"Test email sent ({tpl['type']})",
                            {"template_id": tpl["id"]}
                        )
                        flash(t("template_test_sent"), "success")

                    except Exception as e:
                        add_log(
                            "ERROR",
                            "mail_templates",
                            "Template test failed",
                            {"error": str(e)}
                        )
                        flash(t("template_test_failed") + f" ({e})", "error")

        # ---------------------------------------------------
        # AFFICHAGE
        # ---------------------------------------------------
        templates = db.execute(
            "SELECT * FROM email_templates ORDER BY type"
        ).fetchall()

        return render_template(
            "mailing_templates.html",
            templates=templates,
            active_page="mailing"
        )



    @app.route("/mailing/smtp", methods=["GET", "POST"])
    def mailing_smtp_page():
        db = get_db()
        t = get_translator()

        settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        if request.method == "POST":
            action = request.form.get("action")

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
                db.commit()
                add_log("INFO", "smtp_config", "SMTP settings updated", None)
                flash(t("smtp_settings_saved"), "success")

            elif action == "test":
                # Envoi d'un mail de test à l'admin
                settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()
                admin_email = settings["admin_email"] if settings else None

                if not admin_email:
                    flash(t("admin_email_missing"), "error")
                else:
                    try:
                        db.commit()
                        send_email_via_settings(
                            t("smtp_test_subject"),
                            t("smtp_test_body"),
                            admin_email,
                        )
                        add_log(
                            "INFO",
                            "smtp_config",
                            "SMTP test email sent",
                            {"to": admin_email},
                        )
                        flash(t("smtp_test_sent"), "success")
                    except Exception as e:
                        add_log(
                            "ERROR",
                            "smtp_config",
                            "SMTP test failed",
                            {"error": str(e)},
                        )
                        flash(t("smtp_test_failed") + f" ({e})", "error")

        settings = db.execute("SELECT * FROM settings WHERE id = 1").fetchone()

        return render_template(
            "mailing_smtp.html",
            settings=settings,
            active_page="mailing",
        )


    # -----------------------------
    # BACKUP
    # -----------------------------
    @app.route("/backup", methods=["GET", "POST"])
    def backup_page():
        conn = get_db()
        cursor = conn.cursor()

        # Charger les réglages (dont la rétention)
        cursor.execute("SELECT * FROM settings LIMIT 1")
        settings = cursor.fetchone()

        backups = list_backups()

        if request.method == "POST":
            action = request.form.get("action")

            # ───────────────────────────────
            #  Backup manuel
            # ───────────────────────────────
            if action == "create":
                try:
                    name = create_backup_file()
                    flash(f"Backup créé : {name}", "success")
                except Exception as e:
                    flash(f"Erreur lors de la création du backup : {e}", "error")

            # ───────────────────────────────
            #  Restauration d'un backup
            # ───────────────────────────────
            elif action == "restore":
                file = request.files.get("backup_file")
                if not file or file.filename == "":
                    flash("Aucun fichier fourni", "error")
                else:
                    temp_dir = Path("/tmp")
                    temp_dir.mkdir(exist_ok=True)
                    temp_path = temp_dir / f"restore-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db"
                    file.save(temp_path)
                    try:
                        restore_backup_file(temp_path)
                        flash("Backup restauré. Redémarrez le conteneur pour prendre en compte la base restaurée.", "success")
                    except Exception as e:
                        flash(f"Erreur lors de la restauration : {e}", "error")
                    finally:
                        if temp_path.exists():
                            temp_path.unlink(missing_ok=True)

            # ───────────────────────────────
            #  Sauvegarde des paramètres (rétention)
            # ───────────────────────────────
            elif action == "save_settings":
                try:
                    days = int(request.form.get("backup_retention_days", "30"))
                    cursor.execute("UPDATE settings SET backup_retention_days = ?", (days,))
                    conn.commit()
                    flash("Paramètres sauvegardés.", "success")
                except Exception as e:
                    flash(f"Erreur lors de la sauvegarde des paramètres : {e}", "error")

            backups = list_backups()

        return render_template(
            "backup.html",
            backups=backups,
            settings=settings,
            active_page="backup",
        )



    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        db = get_db()
        cur = db.cursor()

        # Charger settings
        settings = cur.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        # Charger les valeurs days_before pour preavis & relance
        tpl_preavis = db.execute(
            "SELECT days_before FROM email_templates WHERE type = 'preavis'"
        ).fetchone()
        tpl_relance = db.execute(
            "SELECT days_before FROM email_templates WHERE type = 'relance'"
        ).fetchone()

        preavis_days = tpl_preavis["days_before"] if tpl_preavis else 0
        relance_days = tpl_relance["days_before"] if tpl_relance else 0

        # ------------------------------------------------------------
        # POST → SAVE ALL SETTINGS
        # ------------------------------------------------------------
        if request.method == "POST":

            # GENERAL + SUBSCRIPTION + SYSTEM
            new_values = {
                "default_language": request.form.get("default_language", settings["default_language"]),
                "timezone": request.form.get("timezone", settings["timezone"]),
                "admin_email": request.form.get("admin_email", settings["admin_email"]),

                # Default subscription
                "default_subscription_days": request.form.get(
                    "default_expiration_days",
                    settings["default_subscription_days"]
                ),

                "delete_after_expiry_days": request.form.get(
                    "delete_after_expiry_days",
                    settings["delete_after_expiry_days"]
                ),

                "disable_on_expiry": 1 if request.form.get("disable_on_expiry") == "1" else 0,

                # System
                "enable_cron_jobs": 1 if request.form.get("enable_cron_jobs") == "1" else 0,
                "maintenance_mode": 1 if request.form.get("maintenance_mode") == "1" else 0,
                "debug_mode": 1 if request.form.get("debug_mode") == "1" else 0,
            }

            # --- Conversions int propres ---
            try:
                new_values["default_subscription_days"] = int(new_values["default_subscription_days"])
            except:
                pass

            try:
                new_values["delete_after_expiry_days"] = int(new_values["delete_after_expiry_days"])
            except:
                pass

            # --------------------------------------------------------
            # UPDATE SETTINGS TABLE
            # --------------------------------------------------------
            cur.execute("""
                UPDATE settings SET
                    default_language = :default_language,
                    timezone = :timezone,
                    admin_email = :admin_email,
                    default_subscription_days = :default_subscription_days,
                    delete_after_expiry_days = :delete_after_expiry_days,
                    disable_on_expiry = :disable_on_expiry,
                    enable_cron_jobs = :enable_cron_jobs,
                    maintenance_mode = :maintenance_mode,
                    debug_mode = :debug_mode
                WHERE id = 1
            """, new_values)

            # --------------------------------------------------------
            # UPDATE DAYS_BEFORE → email_templates
            # --------------------------------------------------------
            try:
                new_preavis = int(request.form.get("preavis_days", preavis_days))
            except:
                new_preavis = preavis_days

            try:
                new_relance = int(request.form.get("relance_days", relance_days))
            except:
                new_relance = relance_days

            db.execute(
                "UPDATE email_templates SET days_before = ? WHERE type = 'preavis'",
                (new_preavis,)
            )
            db.execute(
                "UPDATE email_templates SET days_before = ? WHERE type = 'relance'",
                (new_relance,)
            )

            db.commit()

            # --------------------------------------------------------
            # LOG
            # --------------------------------------------------------
            add_log(
                "INFO",
                "settings",
                "Settings updated",
                {
                    "default_language": new_values["default_language"],
                    "default_subscription_days": new_values["default_subscription_days"],
                    "preavis_days": new_preavis,
                    "relance_days": new_relance,
                }
            )

            # Mise à jour session langue
            session["lang"] = new_values["default_language"]

            flash(get_translator()("settings_saved"), "success")
            return redirect(url_for("settings_page"))

        # ------------------------------
        # GET → RENDER SETTINGS UI
        # ------------------------------
        return render_template(
            "settings.html",
            settings=settings,
            preavis_days=preavis_days,
            relance_days=relance_days,
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
        level = request.args.get("level", "INFO").upper()   # ← INFO par défaut
        search = request.args.get("q", "").strip()

        # Pagination
        page = int(request.args.get("page", 1))
        per_page = 200  # Nombre de lignes de log à afficher par page

        log_file = "/logs/app.log"   # ← CHEMIN ABSOLU CORRIGÉ
        lines = []

        # ----------------------------
        # Lecture fichier de log
        # ----------------------------
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except FileNotFoundError:
            raw_lines = []

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
            "logs.html",
            logs=parsed_logs,
            page=page,
            total_pages=total_pages,
            page_window_start=page_window_start,
            page_window_end=page_window_end,
            level=level,
            search=search,
            active_page="logs",
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
            "about.html",
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

with app.app_context():
    set_db_provider(app.scheduler_db_provider)
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

