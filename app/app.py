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


_I18N_CACHE: dict[str, dict] = {}












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

        - Source unique : fichiers JSON du dossier lang/
        - Mise en cache en mémoire par langue
        """
        logger = get_logger("i18n")

        # --------------------------------------------------
        # Cache en mémoire
        # --------------------------------------------------
        if lang_code in _I18N_CACHE:
            return _I18N_CACHE[lang_code]

        translations: dict[str, str] = {}

        # --------------------------------------------------
        # Chargement fichiers JSON
        # --------------------------------------------------
        lang_dir = os.path.join(current_app.root_path, "lang")
        json_path = os.path.join(lang_dir, f"{lang_code}.json")

        if not os.path.exists(json_path):
            logger.warning(f"[i18n] Fichier de langue introuvable: {json_path}")
            _I18N_CACHE[lang_code] = translations
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

        # --------------------------------------------------
        # Mise en cache
        # --------------------------------------------------
        _I18N_CACHE[lang_code] = translations
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
        row = db.query_one("SELECT * FROM settings WHERE id = 1")

        # Toujours un dict pour un comportement homogène
        settings = dict(row) if row else {}

        # -----------------------------
        # Sync langue session <- settings (si session vide)
        # -----------------------------
        available_langs = tuple(get_available_languages().keys())

        if not session.get("lang"):
            default_lang = settings.get("default_language")
            if default_lang in available_langs:
                session["lang"] = default_lang

        # Sécurité : si langue invalide, fallback en
        if session.get("lang") not in available_langs:
            session["lang"] = "en"

        return {
            "t": get_translator(),  # <= pas d'argument
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
            "dashboard.html",
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
            "users.html",
            users=users,
            selected_statuses=selected_statuses,
            show_archived=show_archived,
            search=search,
            active_page="users",
        )




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

            # -----------------------------------------------
            # Sauvegarde des options Plex en JSON (details_json)
            # -> 1 details_json par media_user (donc par serveur)
            # -----------------------------------------------
            # On ne fait ça que pour les comptes plex de cet user
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

                # Les champs sont attendus en "1"/"0"
                plex_share["allowSync"] = 1 if form.get(f"allow_sync_{mu_id}") == "1" else 0
                plex_share["allowCameraUpload"] = 1 if form.get(f"allow_camera_upload_{mu_id}") == "1" else 0
                plex_share["allowChannels"] = 1 if form.get(f"allow_channels_{mu_id}") == "1" else 0

                plex_share["filterMovies"] = (form.get(f"filter_movies_{mu_id}") or "").strip()
                plex_share["filterTelevision"] = (form.get(f"filter_television_{mu_id}") or "").strip()
                plex_share["filterMusic"] = (form.get(f"filter_music_{mu_id}") or "").strip()

                details["plex_share"] = plex_share

                db.execute(
                    "UPDATE media_users SET details_json = ? WHERE id = ?",
                    (json.dumps(details, ensure_ascii=False), mu_id),
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
                plex_server_ids = sorted({int(mu["server_id"]) for mu in plex_media_for_jobs if mu.get("server_id") is not None})

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

        # -----------------------------------------------
        # Comptes media + serveurs
        #  - 1 ligne = 1 compte media sur 1 serveur
        #  - has_access basé sur media_user_libraries
        # -----------------------------------------------
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

        # --------------------------------------------------
        # Déplier options depuis details_json
        #  - Plex: details_json["plex_share"]
        #  - Jellyfin: tu peux afficher ce que sync_jellyfin écrit (owned/all_libraries/num_libraries…)
        # --------------------------------------------------
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

            # Jellyfin (état calculé par sync_jellyfin)
            r["_details_obj"] = details

            enriched.append(r)

        servers = enriched

        # -----------------------------------------------
        # Bibliothèques + accès (par utilisateur Vodum)
        # -----------------------------------------------
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

        # -----------------------------------------------
        # Mails envoyés (DB v2: template_type / expiration_date / sent_at)
        # -----------------------------------------------
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
            sent_emails=sent_emails,
            allowed_types=allowed_types,
            user_servers=servers,  # si tu as encore des restes dans le template
        )








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
            "libraries.html",
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

        # options spécifiques (comme avant, mais on les mettra dans JSON)
        tautulli_url = request.form.get("tautulli_url") or None
        tautulli_api_key = request.form.get("tautulli_api_key") or None

        server_identifier = str(uuid.uuid4())

        # ---------------------------------------
        # settings_json (clé/valeurs extensibles)
        # ---------------------------------------
        settings = {}

        if tautulli_url or tautulli_api_key:
            settings["tautulli"] = {
                "url": tautulli_url,
                "api_key": tautulli_api_key,
            }

        settings_json = json.dumps(settings) if settings else None

        # ---------------------------------------
        # INSERT serveur (NOUVEAU SCHÉMA)
        # ---------------------------------------
        db.execute(
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

        # --------------------------------------------------
        # Activation des tâches système
        # --------------------------------------------------
        db.execute(
            """
            UPDATE tasks
            SET enabled = 1, status = 'queued'
            WHERE name IN ('check_servers', 'update_user_status')
            """
        )

        try:
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

        server = db.query_one(
            "SELECT id, name FROM servers WHERE id = ?",
            (server_id,),
        )

        if not server:
            flash("server_not_found", "error")
            return redirect(url_for("servers_list"))

        db.execute(
            "DELETE FROM servers WHERE id = ?",
            (server_id,),
        )

        flash("server_deleted", "success")
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
            "settings.html",
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
