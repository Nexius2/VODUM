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
from api.subscriptions import subscriptions_api, update_user_expiration
import uuid
from mailing_utils import build_user_context, render_mail
import threading
import re
from db_manager import DBManager
from typing import Optional














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
            g.db = DBManager()
        return g.db



    def scheduler_db_provider():
        return DBManager()



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
            return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            # Timezone invalide → UTC lisible
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")





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

        - Lecture DB via DBManager (READ ONLY)
        - Aucun cursor()
        - Aucun commit / rollback
        - Logs UNIQUEMENT via logging_utils
        - Comportement fonctionnel inchangé
        """
        logger = get_logger("mailing")

        if not to_email:
            logger.warning("[MAIL] Destinataire vide, envoi annulé")
            return False

        db = get_db()

        # --------------------------------------------------
        # 1) Charger configuration mail
        # --------------------------------------------------
        settings = db.query_one("SELECT * FROM settings LIMIT 1")
        if not settings:
            logger.error("[MAIL] Aucun paramètre mail trouvé en base")
            return False

        if not settings.get("mailing_enabled"):
            logger.info("[MAIL] Mailing désactivé dans les paramètres")
            return False

        smtp_host = settings.get("smtp_host")
        smtp_port = settings.get("smtp_port")
        smtp_user = settings.get("smtp_user")
        smtp_pass = settings.get("smtp_pass")
        smtp_tls = bool(settings.get("smtp_tls"))
        mail_from = settings.get("mail_from") or smtp_user

        # Validation minimale
        try:
            smtp_port = int(smtp_port)
        except (TypeError, ValueError):
            smtp_port = None

        if not smtp_host or not smtp_port:
            logger.error(
                "[MAIL] Configuration SMTP incomplète "
                f"(host={smtp_host}, port={smtp_port})"
            )
            return False

        if not mail_from:
            logger.error("[MAIL] Adresse d'expéditeur introuvable")
            return False

        # --------------------------------------------------
        # 2) Construction message
        # --------------------------------------------------
        try:
            subtype = "html" if is_html else "plain"
            msg = MIMEText(body, subtype, "utf-8")

            msg["From"] = mail_from
            msg["To"] = to_email
            msg["Subject"] = subject

            if cc:
                msg["Cc"] = ", ".join(cc)
            if bcc:
                msg["Bcc"] = ", ".join(bcc)

        except Exception as e:
            logger.error(
                f"[MAIL] Erreur construction message: {e}",
                exc_info=True,
            )
            return False

        recipients = [to_email]
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        # --------------------------------------------------
        # 3) Envoi SMTP
        # --------------------------------------------------
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if smtp_tls:
                    server.starttls()

                if smtp_user:
                    server.login(smtp_user, smtp_pass)

                server.sendmail(mail_from, recipients, msg.as_string())

            logger.info(f"[MAIL] Email envoyé à {to_email}")
            return True

        except Exception as e:
            logger.error(
                f"[MAIL] Erreur SMTP vers {to_email}: {e}",
                exc_info=True,
            )
            return False


    # -----------------------------
    # HELPERS BACKUP
    # -----------------------------
    def ensure_backup_dir() -> Path:
        """
        S'assure que le dossier de sauvegarde existe.

        - Aucun accès DB
        - Compatible Flask
        - Logging applicatif via logging_utils
        - Exception explicite si le dossier ne peut pas être créé
        """
        logger = get_logger("backup")

        try:
            backup_dir = Path(app.config["BACKUP_DIR"])
        except KeyError:
            logger.error("[BACKUP] BACKUP_DIR non défini dans la configuration")
            raise

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(
                f"[BACKUP] Impossible de créer le dossier de sauvegarde "
                f"({backup_dir}): {e}",
                exc_info=True,
            )
            raise

        logger.debug(f"[BACKUP] Dossier de sauvegarde prêt: {backup_dir}")
        return backup_dir


    def create_backup_file() -> str | None:
        """
        Crée un fichier de sauvegarde de la base SQLite.

        - Compatible DBManager (une seule connexion)
        - WAL checkpoint safe
        - Aucun close manuel
        - Aucun lock long
        - Logs applicatifs UNIQUEMENT via logging_utils
        - Retourne le nom du fichier de sauvegarde ou None
        """
        logger = get_logger("backup")
        db = get_db()

        # --------------------------------------------------
        # 0) Dossier de sauvegarde
        # --------------------------------------------------
        try:
            backup_dir = ensure_backup_dir()
        except Exception:
            # ensure_backup_dir a déjà loggué l'erreur
            return None

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.sqlite"
        backup_path = backup_dir / backup_filename

        try:
            # --------------------------------------------------
            # 1) Forcer un checkpoint WAL (sans fermer la DB)
            # --------------------------------------------------
            db.execute("PRAGMA wal_checkpoint(TRUNCATE);")

            # --------------------------------------------------
            # 2) Copie fichier DB → backup
            # --------------------------------------------------
            db_path = app.config.get("DATABASE")

            if not db_path or not os.path.exists(db_path):
                logger.error("[BACKUP] Fichier DB introuvable")
                return None

            shutil.copy2(db_path, backup_path)

            logger.info(f"[BACKUP] Sauvegarde créée: {backup_filename}")
            return backup_filename

        except Exception as e:
            logger.error(
                f"[BACKUP] Erreur création backup: {e}",
                exc_info=True,
            )
            return None



    def list_backups():
        """
        Liste les fichiers de sauvegarde disponibles.

        - Aucun accès DB
        - Compatible Flask
        - Logging via logging_utils
        - Retourne une liste de métadonnées triée par date décroissante
        """
        logger = get_logger("backup")

        try:
            backup_dir = ensure_backup_dir()
        except Exception:
            # ensure_backup_dir a déjà loggué l'erreur
            return []

        backups = []

        try:
            files = sorted(
                backup_dir.glob("backup_*.sqlite"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            for f in files:
                stat = f.stat()
                backups.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )

            logger.debug(f"[BACKUP] {len(backups)} sauvegarde(s) trouvée(s)")
            return backups

        except Exception as e:
            logger.error(
                f"[BACKUP] Erreur lors de la liste des sauvegardes: {e}",
                exc_info=True,
            )
            return []


    def restore_backup_file(uploaded_path: Path):
        """
        Écrase la base actuelle par le fichier fourni.

        ⚠️ Action destructive :
        - crée une sauvegarde de précaution avant écrasement
        - n'interrompt pas le process
        - un redémarrage du conteneur est recommandé après restauration

        - Aucun accès DB
        - Logging via logging_utils
        """
        logger = get_logger("backup")

        db_path = Path(app.config["DATABASE"])

        # --------------------------------------------------
        # Validation du fichier fourni
        # --------------------------------------------------
        if not uploaded_path or not uploaded_path.exists():
            logger.error("[BACKUP] Fichier de restauration introuvable")
            raise FileNotFoundError("Backup file not found")

        if uploaded_path.stat().st_size == 0:
            logger.error("[BACKUP] Fichier de restauration vide")
            raise ValueError("Backup file is empty")

        # --------------------------------------------------
        # Sauvegarde de précaution de la DB actuelle
        # --------------------------------------------------
        try:
            if db_path.exists():
                backup_dir = ensure_backup_dir()
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                pre_restore_backup = backup_dir / f"pre_restore_{timestamp}.sqlite"

                shutil.copy2(db_path, pre_restore_backup)
                logger.info(
                    f"[BACKUP] Sauvegarde pré-restauration créée: {pre_restore_backup.name}"
                )
        except Exception as e:
            logger.error(
                f"[BACKUP] Impossible de créer la sauvegarde pré-restauration: {e}",
                exc_info=True,
            )
            raise

        # --------------------------------------------------
        # Restauration
        # --------------------------------------------------
        try:
            shutil.copy2(uploaded_path, db_path)
            logger.warning(
                "[BACKUP] Base restaurée avec succès – redémarrage recommandé"
            )
        except Exception as e:
            logger.error(
                f"[BACKUP] Erreur lors de la restauration de la base: {e}",
                exc_info=True,
            )
            raise


    # ======================
    #   MULTILINGUAL SYSTEM
    # ======================

    def load_language_dict(lang_code: str) -> dict:
        """
        Charge le dictionnaire de traduction pour une langue donnée.

        - Priorité : base de données (table translations)
        - Fallback : fichiers JSON du dossier lang/
        - Compatible DBManager
        - Aucun cursor()
        - Aucun commit / rollback
        """
        logger = get_logger("i18n")
        db = get_db()

        translations: dict[str, str] = {}

        # --------------------------------------------------
        # 1) Chargement depuis la DB (READ ONLY)
        # --------------------------------------------------
        try:
            rows = db.query(
                """
                SELECT key, value
                FROM translations
                WHERE lang = ?
                """,
                (lang_code,),
            )

            for row in rows:
                # DBManager renvoie des rows indexables
                key = row["key"]
                value = row["value"]

                if key and value is not None:
                    translations[key] = value

            if translations:
                logger.debug(
                    f"[i18n] {len(translations)} traductions chargées depuis la DB ({lang_code})"
                )
                return translations

        except Exception as e:
            logger.warning(
                f"[i18n] Impossible de charger les traductions depuis la DB ({lang_code}): {e}"
            )

        # --------------------------------------------------
        # 2) Fallback fichiers JSON
        # --------------------------------------------------
        lang_dir = os.path.join(current_app.root_path, "lang")
        json_path = os.path.join(lang_dir, f"{lang_code}.json")

        if not os.path.exists(json_path):
            logger.warning(f"[i18n] Fichier de langue introuvable: {json_path}")
            return translations

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                translations.update(data)
                logger.debug(
                    f"[i18n] {len(translations)} traductions chargées depuis fichier ({lang_code})"
                )

        except Exception as e:
            logger.error(
                f"[i18n] Erreur lecture fichier langue {json_path}: {e}",
                exc_info=True,
            )

        return translations


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
        """
        Retourne une fonction de traduction utilisable dans les templates.

        - Détermine la langue active (session / navigateur)
        - Charge le dictionnaire via load_language_dict(lang)
        - Ne fait AUCUN accès DB direct
        - Compatible DBManager
        """
        logger = get_logger("i18n")

        available_langs = tuple(get_available_languages().keys())

        # --------------------------------------------------
        # 1) Déterminer la langue active
        # --------------------------------------------------
        lang = session.get("lang")

        if not lang:
            lang = request.accept_languages.best_match(available_langs)
            if not lang:
                lang = "en"  # fallback final
            session["lang"] = lang

        # Sécurité : langue inconnue
        if lang not in available_langs:
            logger.warning(
                f"[i18n] Langue invalide '{lang}', fallback navigateur/en"
            )
            lang = request.accept_languages.best_match(available_langs) or "en"
            session["lang"] = lang

        # --------------------------------------------------
        # 2) Charger le dictionnaire
        # --------------------------------------------------
        try:
            translations = load_language_dict(lang)
        except Exception as e:
            logger.error(
                f"[i18n] Erreur chargement dictionnaire langue '{lang}': {e}",
                exc_info=True,
            )
            translations = {}

        # --------------------------------------------------
        # 3) Fonction traducteur
        # --------------------------------------------------
        def _translate(key: str):
            if not key:
                return ""
            return translations.get(key, key)

        return _translate





    # Injecte "t" dans tous les templates Jinja
    @app.context_processor
    def inject_globals():
        """
        Variables globales injectées dans tous les templates Jinja.

        - settings : paramètres globaux
        - t        : fonction de traduction

        Compatible DBManager
        Aucun cursor
        Aucun execute+fetch
        Aucun commit
        """
        db = get_db()

        # READ ONLY via DBManager
        row = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )

        # Toujours un dict pour un comportement homogène
        settings = dict(row) if row else {}

        return {
            "t": get_translator(),
            "settings": settings,
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
        stats = {}

        stats["total_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM users"
        )["cnt"]

        stats["active_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM users WHERE status = 'active'"
        )["cnt"]

        # expiring soon = reminder + pre_expired
        stats["expiring_soon"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM users WHERE status IN ('pre_expired', 'reminder')"
        )["cnt"]

        stats["expired_users"] = db.query_one(
            "SELECT COUNT(*) AS cnt FROM users WHERE status = 'expired'"
        )["cnt"]

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
            )["cnt"]

            online = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'up'",
                (stype,),
            )["cnt"]

            offline = db.query_one(
                "SELECT COUNT(*) AS cnt FROM servers WHERE type = ? AND status = 'down'",
                (stype,),
            )["cnt"]

            stats["server_types"][stype] = {
                "total": total,
                "online": online,
                "offline": offline,
            }

        # --------------------------
        # TASK STATS
        # --------------------------
        if table_exists(db, "tasks"):
            stats["total_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks"
            )["cnt"]

            stats["active_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE enabled = 1"
            )["cnt"]

            stats["error_tasks"] = db.query_one(
                "SELECT COUNT(*) AS cnt FROM tasks WHERE status = 'error'"
            )["cnt"]
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

        lines = read_last_logs(10)


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
            servers=servers,
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

        Compatible DBManager
        READ only
        """
        db = get_db()

        # --------------------------------------------------
        # 1) Récupération des serveurs liés à l’utilisateur
        # --------------------------------------------------
        servers = db.query(
            """
            SELECT s.*
            FROM servers s
            JOIN user_servers us ON us.server_id = s.id
            WHERE us.user_id = ?
            ORDER BY s.name
            """,
            (user_id,),
        )

        server_list = []

        # --------------------------------------------------
        # 2) Pour chaque serveur, récupérer les bibliothèques accessibles
        # --------------------------------------------------
        for s in servers:
            libraries = db.query(
                """
                SELECT l.*
                FROM libraries l
                JOIN shared_libraries sl ON sl.library_id = l.id
                WHERE sl.user_id = ?
                  AND l.server_id = ?
                ORDER BY l.name
                """,
                (user_id, s["id"]),
            )

            server_list.append({
                "server": s,
                "libraries": libraries,
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
                COUNT(DISTINCT l.server_id) AS servers_count,
                COUNT(DISTINCT sl.library_id) AS libraries_count
            FROM users u
            LEFT JOIN shared_libraries sl ON sl.user_id = u.id
            LEFT JOIN libraries l ON l.id = sl.library_id
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

        # READ ONLY via DBManager
        users = db.query(query, params)

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

        # --------------------------------------------------
        # Charger l’utilisateur
        # --------------------------------------------------
        user = db.query_one(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        )
        if not user:
            flash("user_not_found", "error")
            return redirect(url_for("users_list"))

        # ==================================================
        # POST → Mise à jour utilisateur + options serveur
        # ==================================================
        if request.method == "POST":
            form = request.form

            # 1) --- Mise à jour infos utilisateur ---
            firstname       = form.get("firstname") or user["firstname"]
            lastname        = form.get("lastname") or user["lastname"]
            second_email    = form.get("second_email") or user["second_email"]
            expiration_date = form.get("expiration_date") or user["expiration_date"]
            renewal_date    = form.get("renewal_date") or user["renewal_date"]
            renewal_method  = form.get("renewal_method") or user["renewal_method"]

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

            # Logique métier expiration
            if expiration_date != user["expiration_date"]:
                update_user_expiration(
                    user_id,
                    expiration_date,
                    reason="ui_manual",
                )

            # 2) --- Mise à jour options serveur ---
            servers = db.query("SELECT id FROM servers")

            for s in servers:
                sid = s["id"]

                allow_sync     = 1 if form.get(f"allow_sync_{sid}") else 0
                allow_camera   = 1 if form.get(f"allow_camera_upload_{sid}") else 0
                allow_channels = 1 if form.get(f"allow_channels_{sid}") else 0

                filter_movies     = form.get(f"filter_movies_{sid}") or None
                filter_television = form.get(f"filter_television_{sid}") or None
                filter_music      = form.get(f"filter_music_{sid}") or None

                exists = db.query_one(
                    """
                    SELECT 1
                    FROM user_servers
                    WHERE user_id = ? AND server_id = ?
                    """,
                    (user_id, sid),
                )

                if exists:
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
                            user_id, sid,
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
                            filter_movies, filter_television, filter_music,
                        ),
                    )

            # 3) --- Ajouter jobs SYNC Plex ---
            plex_servers = db.query(
                "SELECT id FROM servers WHERE type = 'plex'"
            )

            for s in plex_servers:
                db.execute(
                    """
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('sync', ?, ?, NULL, 0)
                    """,
                    (user_id, s["id"]),
                )

            # 4) --- Lancer tâche apply_plex_access_updates ---
            run_task_by_name("apply_plex_access_updates")

            flash("user_saved_and_plex_sync_started", "success")
            return redirect(url_for("user_detail", user_id=user_id))

        # ==================================================
        # GET → Chargement complet user + serveurs + libs
        # ==================================================

        servers = db.query(
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
        )

        libraries = db.query(
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
            flash("invalid_library", "error")
            return redirect(url_for("user_detail", user_id=user_id))

        # --------------------------------------------------
        # Vérifier si l'accès existe déjà (READ)
        # --------------------------------------------------
        exists = db.query_one(
            """
            SELECT 1
            FROM shared_libraries
            WHERE user_id = ? AND library_id = ?
            """,
            (user_id, library_id),
        )

        # --------------------------------------------------
        # Toggle accès
        # --------------------------------------------------
        if exists:
            # RETIRER
            db.execute(
                """
                DELETE FROM shared_libraries
                WHERE user_id = ? AND library_id = ?
                """,
                (user_id, library_id),
            )
            flash("library_access_removed", "success")
        else:
            # AJOUTER
            db.execute(
                """
                INSERT INTO shared_libraries(user_id, library_id)
                VALUES (?, ?)
                """,
                (user_id, library_id),
            )
            flash("library_access_added", "success")

        return redirect(url_for("user_detail", user_id=user_id))



    # -----------------------------
    # SERVEURS & BIBLIO
    # -----------------------------
        
    @app.route("/servers/<int:server_id>/sync")
    def sync_server(server_id):
        db = get_db()

        # --------------------------------------------------
        # Vérifier que le serveur existe (READ)
        # --------------------------------------------------
        server = db.query_one(
            "SELECT id FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        # --------------------------------------------------
        # Ajouter un job de synchronisation (WRITE)
        # --------------------------------------------------
        db.execute(
            """
            INSERT INTO plex_jobs (action, server_id)
            VALUES ('sync', ?)
            """,
            (server_id,),
        )

        # --------------------------------------------------
        # Lancer la tâche de traitement
        # --------------------------------------------------
        run_task_by_name("check_servers")

        return redirect(url_for("server_detail", server_id=server_id))


    @app.route("/servers", methods=["GET"])
    def servers_list():
        db = get_db()

        servers = db.query(
            """
            SELECT
                s.*,
                COUNT(DISTINCT l.id) AS libraries_count,
                COUNT(DISTINCT us.user_id) AS users_count
            FROM servers s
            LEFT JOIN libraries l ON l.server_id = s.id
            LEFT JOIN user_servers us ON us.server_id = s.id
            GROUP BY s.id
            ORDER BY s.name
            """
        )

        return render_template(
            "servers.html",
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
                COUNT(sl.user_id) AS users_count
            FROM libraries l
            JOIN servers s ON s.id = l.server_id
            LEFT JOIN shared_libraries sl ON sl.library_id = l.id
            GROUP BY l.id
            ORDER BY s.name, l.name
            """
        )

        return render_template(
            "libraries.html",
            libraries=libraries,
            active_page="servers",
            active_tab="libraries",
        )



    @app.route("/servers/new", methods=["POST"])
    def server_create():
        db = get_db()

        name = request.form.get("name", "").strip()
        server_type = request.form.get("type", "plex")
        url = request.form.get("url") or None
        local_url = request.form.get("local_url") or None
        public_url = request.form.get("public_url") or None
        token = request.form.get("token") or None
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None
        server_identifier = str(uuid.uuid4())

        if not name:
            flash("server_name_required", "error")
            return redirect(url_for("servers_list"))

        # Création du serveur (WRITE)
        db.execute(
            """
            INSERT INTO servers (
                name, type, server_identifier,
                url, local_url, public_url, token,
                tautulli_url, tautulli_api_key, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, server_type, server_identifier,
                url, local_url, public_url, token,
                tautulli_url, tautulli_api_key, "unknown",
            ),
        )

        # Toujours activer check_servers + update_user_status (si présents),
        # puis check_servers mettra à jour le status des serveurs,
        # et tasks_engine.auto_enable_sync_tasks activera sync_plex/sync_jellyfin selon les serveurs UP.
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name IN ('check_servers', 'update_user_status')
            """
        )

        # On ne force PAS sync_plex/sync_jellyfin ici :
        # -> c'est auto_enable_sync_tasks() qui décide en fonction des serveurs réellement UP.
        # Mais on déclenche immédiatement check_servers pour éviter "base vide" après ajout.
        try:
            # ✅ File d’attente: on empile une exécution de check_servers
            row = db.query_one("SELECT id FROM tasks WHERE name='check_servers'")
            if row:
                enqueue_task(row["id"])

        except Exception:
            pass

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

        # Vérifier que le serveur existe (READ)
        server = db.query_one(
            "SELECT id FROM servers WHERE id = ?",
            (server_id,),
        )
        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        # Suppression (WRITE)
        db.execute(
            "DELETE FROM servers WHERE id = ?",
            (server_id,),
        )

        flash("server_deleted", "success")
        return redirect(url_for("servers_list"))



    @app.route("/servers/<int:server_id>", methods=["GET", "POST"])
    def server_detail(server_id):
        db = get_db()

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            server_type = request.form.get("type") or "other"
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

            # UPDATE (WRITE)
            db.execute(
                """
                UPDATE servers
                SET name = ?, type = ?, url = ?, local_url = ?, public_url = ?, token = ?,
                    tautulli_url = ?, tautulli_api_key = ?, status = ?
                WHERE id = ?
                """,
                (
                    name, server_type, url, local_url, public_url, token,
                    tautulli_url, tautulli_api_key, status, server_id,
                ),
            )

            flash("server_updated", "success")
            return redirect(url_for("server_detail", server_id=server_id))

        # --------------------------
        # GET
        # --------------------------
        server = db.query_one(
            "SELECT * FROM servers WHERE id = ?",
            (server_id,),
        )
        if not server:
            return "Serveur introuvable", 404

        libraries = db.query(
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
        )

        users = db.query(
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
        )

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

        server_id = request.form.get("server_id", type=int)
        library_ids = request.form.getlist("library_ids")

        if not server_id or not library_ids:
            flash("no_server_or_library_selected", "error")
            return redirect(url_for("servers_list", server_id=server_id))

        # 1️⃣ Utilisateurs ACTIFS sur ce serveur (READ)
        users = db.query(
            """
            SELECT us.user_id
            FROM user_servers us
            JOIN users u ON u.id = us.user_id
            WHERE us.server_id = ?
              AND u.status = 'active'
            """,
            (server_id,),
        )

        user_ids = [u["user_id"] for u in users]

        if not user_ids:
            flash("no_active_users_for_server", "warning")
            return redirect(url_for("servers_list", server_id=server_id))

        # 2️⃣ Mise à jour shared_libraries (WRITE)
        for lib_id in library_ids:
            for uid in user_ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO shared_libraries(user_id, library_id)
                    VALUES (?, ?)
                    """,
                    (uid, lib_id),
                )

        # 3️⃣ Jobs Plex (WRITE)
        for lib_id in library_ids:
            for uid in user_ids:
                db.execute(
                    """
                    INSERT INTO plex_jobs(action, user_id, server_id, library_id, processed)
                    VALUES ('grant', ?, ?, ?, 0)
                    """,
                    (uid, server_id, lib_id),
                )

        # 4️⃣ Activer la tâche apply_plex_access_updates
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name = 'apply_plex_access_updates'
            """
        )

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
            "subscriptions.html",
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






    @app.route("/tasks", methods=["GET", "POST"])
    def tasks_page():
        db = get_db()

        # ------------------------------------------------------------------
        # POST : actions sur les tâches (toggle / run_now)
        # ------------------------------------------------------------------
        if request.method == "POST" and table_exists(db, "tasks"):
            task_id = request.form.get("task_id", type=int)
            action = request.form.get("action")

            if not task_id:
                flash("invalid_task", "error")
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

                new_state = db.query_one(
                    "SELECT enabled FROM tasks WHERE id = ?",
                    (task_id,),
                )

                task_logger.info(
                    f"Tâche {task_id} → toggle → enabled={new_state['enabled']}"
                )
                flash("task_updated", "success")

            # --------------------------------------------------------------
            # 2) run_now → marque la tâche comme queued
            # --------------------------------------------------------------
            elif action == "run_now":
                from tasks_engine import enqueue_task
                enqueue_task(task_id)
                flash("task_queued", "success")


            else:
                task_logger.warning(f"Action inconnue sur /tasks : {action}")

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
            "tasks.html",
            tasks=tasks,
            active_page="tasks",
        )



    # -----------------------------
    # MAILING
    # -----------------------------
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

        enabled = False
        if settings:
            try:
                enabled = settings["mailing_enabled"] == 1
            except (KeyError, IndexError):
                enabled = False

        if enabled:
            return redirect(url_for("mailing_campaigns_page"))
        else:
            return redirect(url_for("mailing_smtp_page"))




    @app.route("/mailing/campaigns", methods=["GET", "POST"])
    def mailing_campaigns_page():
        db = get_db()
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
            is_test = 1 if request.form.get("is_test") == "1" else 0

            if not subject or not body:
                flash(t("campaign_missing_fields"), "error")
                return redirect(url_for("mailing_campaigns_page"))

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
                users = db.query(
                    """
                    SELECT u.email, u.username, u.expiration_date
                    FROM users u
                    JOIN user_servers us ON us.user_id = u.id
                    WHERE us.server_id = ?
                    """,
                    (campaign["server_id"],),
                )
            else:
                users = db.query(
                    "SELECT email, username, expiration_date FROM users"
                )

            errors = 0

            for u in users:
                if not u["email"]:
                    continue

                formatted_body = (
                    campaign["body"]
                    .replace("{username}", u["username"])
                    .replace("{email}", u["email"])
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
            templates = db.query(
                "SELECT * FROM email_templates"
            )

            for tpl in templates:
                tid = tpl["id"]

                subject = request.form.get(f"subject_{tid}", "").strip()
                body = request.form.get(f"body_{tid}", "").strip()

                days_raw = request.form.get(f"days_before_{tid}", "")
                try:
                    days_before = int(days_raw)
                except Exception:
                    days_before = tpl["days_before"]

                db.execute(
                    """
                    UPDATE email_templates
                    SET subject = ?, body = ?, days_before = ?
                    WHERE id = ?
                    """,
                    (subject, body, days_before, tid),
                )

            add_log("info", "mail_templates", "Templates updated", None)
            flash(t("templates_saved"), "success")

        # ---------------------------------------------------
        # ENVOI DE TEST (AVEC RENDU DES VARIABLES)
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
            "mailing_templates.html",
            templates=templates,
            active_page="mailing",
        )

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
            "mailing_smtp.html",
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



    @app.route("/backup", methods=["GET", "POST"])
    def backup_page():
        t = get_translator()
        db = get_db()

        # Charger les réglages (dont la rétention)
        settings = db.query_one(
            "SELECT * FROM settings LIMIT 1"
        )

        backups = list_backups()

        if request.method == "POST":
            action = request.form.get("action")

            # ───────────────────────────────
            # Backup manuel
            # ───────────────────────────────
            if action == "create":
                try:
                    name = create_backup_file()
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
                        temp_path = temp_dir / f"restore-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"

                        file.save(temp_path)

                        try:
                            restore_backup_file(temp_path)
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

            backups = list_backups()

        return render_template(
            "backup.html",
            backups=backups,
            settings=settings,
            active_page="backup",
        )
    # ⚠️ À partir d’ici l’état mémoire ≠ état disque
# Le process DOIT être redémarré





    # -----------------------------
    # SETTINGS / PARAMÈTRES
    # -----------------------------
    @app.before_request
    def maintenance_guard():
        # Routes toujours autorisées
        allowed = (
            request.path.startswith("/static"),
            request.path.startswith("/set_language"),
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
                    active_page=None,
                ),
                503,
            )
            
            
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        db = get_db()

        # Charger settings
        settings = db.query_one(
            "SELECT * FROM settings WHERE id = 1"
        )
        if not settings:
            flash("Settings row missing in DB", "error")
            return redirect("/")

        # Charger les valeurs days_before pour preavis & relance
        tpl_preavis = db.query_one(
            "SELECT days_before FROM email_templates WHERE type = 'preavis'"
        )
        tpl_relance = db.query_one(
            "SELECT days_before FROM email_templates WHERE type = 'relance'"
        )

        preavis_days = tpl_preavis["days_before"] if tpl_preavis else 0
        relance_days = tpl_relance["days_before"] if tpl_relance else 0

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
                "disable_on_expiry": 1 if request.form.get("disable_on_expiry") == "1" else 0,
                "enable_cron_jobs": 1 if request.form.get("enable_cron_jobs") == "1" else 0,
                "maintenance_mode": 1 if request.form.get("maintenance_mode") == "1" else 0,
                "debug_mode": 1 if request.form.get("debug_mode") == "1" else 0,
            }

            # Conversions int propres
            try:
                new_values["default_subscription_days"] = int(
                    new_values["default_subscription_days"]
                )
            except Exception:
                pass

            try:
                new_values["delete_after_expiry_days"] = int(
                    new_values["delete_after_expiry_days"]
                )
            except Exception:
                pass

            # UPDATE settings
            db.execute(
                """
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
                """,
                new_values,
            )

            # UPDATE email_templates.days_before
            try:
                new_preavis = int(request.form.get("preavis_days", preavis_days))
            except Exception:
                new_preavis = preavis_days

            try:
                new_relance = int(request.form.get("relance_days", relance_days))
            except Exception:
                new_relance = relance_days

            db.execute(
                "UPDATE email_templates SET days_before = ? WHERE type = 'preavis'",
                (new_preavis,),
            )
            db.execute(
                "UPDATE email_templates SET days_before = ? WHERE type = 'relance'",
                (new_relance,),
            )

            add_log(
                "info",
                "settings",
                "Settings updated",
                {
                    "default_language": new_values["default_language"],
                    "default_subscription_days": new_values["default_subscription_days"],
                    "preavis_days": new_preavis,
                    "relance_days": new_relance,
                },
            )

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

        return Response(
            "".join(output),
            mimetype="text/plain",
            headers={
                "Content-Disposition": "attachment; filename=vodum-logs-anonymized.log"
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
    
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

