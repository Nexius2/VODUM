from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, get_flashed_messages, g, session
import sqlite3
import os
from datetime import datetime, timedelta, date
import uuid
import threading
import shutil
import time
from werkzeug.utils import secure_filename
from logger import logger
import logging


# Passe le logger 'werkzeug' en DEBUG au lieu de INFO (ou WARNING pour quasi tout masquer)
logging.getLogger('werkzeug').setLevel(logging.DEBUG)
# ou, pour les masquer complètement :
# logging.getLogger('werkzeug').setLevel(logging.WARNING)
import json
from jinja2.runtime import Undefined
from tasks import get_all_tasks, TASKS
from config import DATABASE_PATH
from mailer import send_email
from settings_helper import get_settings
from disable_expired_users import disable_expired_users
from plex_share_helper import share_user_libraries, unshare_all_libraries, set_user_libraries, set_user_libraries_via_api, share_user_libraries_plexapi
   

import send_reminder_emails
import check_servers
import update_plex_users


app = Flask(__name__, template_folder="templates")  # Assure que Flask connaît le dossier "templates"
app.secret_key = "une_clé_secrète_ultra_random"



def create_tables_once():
    # ✅ corrige le chemin si besoin
    tables_sql_path = "/app/tables.sql"
    updates_sql_path = "/app/updates.sql"

    if not os.path.exists(tables_sql_path):
        logger.critical("🚨 ERREUR : Le fichier tables.sql est introuvable !")
        return

    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()

            logger.info("📜 Exécution de tables.sql pour mise à jour des schémas")
            with open(tables_sql_path, "r", encoding="utf-8") as f:
                cursor.executescript(f.read())
            logger.info("✅ Fichier tables.sql exécuté avec succès")

            # Données par défaut (si tu gardes ça)
            try:
                default_data_path = "/app/app/default_data.sql"
                if os.path.exists(default_data_path):
                    with open(default_data_path, "r", encoding="utf-8") as f:
                        cursor.executescript(f.read())
                    logger.info("✅ Données par défaut appliquées (INSERT OR IGNORE)")
                else:
                    logger.info("ℹ️ Pas de default_data.sql à appliquer")
            except Exception as e:
                logger.error(f"❌ Erreur lors de l'application des données par défaut : {e}")

            # ✅ NOUVEAU : exécuter updates.sql s’il existe
            if os.path.exists(updates_sql_path):
                try:
                    logger.info("📜 Exécution de updates.sql (migrations)")
                    with open(updates_sql_path, "r", encoding="utf-8") as f:
                        cursor.executescript(f.read())
                    logger.info("✅ Fichier updates.sql exécuté avec succès")
                except Exception as e:
                    logger.error(f"❌ Erreur lors de l'exécution de updates.sql : {e}")
            else:
                logger.info("ℹ️ Aucun updates.sql trouvé, pas de migrations à appliquer")

            conn.commit()

        # ⚡ Important : exécuter update_vodum après fermeture de la connexion
        from update_vodum import update_vodum
        update_vodum()

    except Exception as e:
        logger.error(f"❌ Erreur lors de la création/mise à jour des tables : {e}")





def cleanup_locks():
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM locks")
        conn.commit()
        conn.close()
        logger.info("🔓 Tous les locks ont été réinitialisés au démarrage.")
    except Exception as e:
        logger.warning(f"⚠️ Échec lors du nettoyage des locks : {e}")



@app.route("/")
def index():
    print("🔍 Flask sert maintenant index.html")  # Ajout de debug
    return render_template("index.html")  # ✅ Sert bien index.html

@app.before_request
def load_lang():
    lang = get_locale()
    g.translations = load_translations(lang)

def _parse_date_any(d):
    """Accepte YYYY-MM-DD ou DD/MM/YYYY ; renvoie date() ou None."""
    if not d:
        return None
    s = str(d).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.replace(" ", ""), fmt).date()
        except ValueError:
            continue
    return None

# Route pour afficher la liste des utilisateurs
@app.route("/users")
def get_users_page():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # On lit le statut calculé par les scripts (status), pas un "statut" maison
    cur.execute("""
        SELECT id, username, email, avatar, expiration_date, status
        FROM users
    """)
    rows = cur.fetchall()
    conn.close()

    today = date.today()
    users = []
    for r in rows:
        exp = _parse_date_any(r["expiration_date"])
        jours_restants = (exp - today).days if exp else None

        users.append({
            "id": r["id"],
            "username": r["username"],
            "email": r["email"],
            "avatar": r["avatar"],
            "expiration_date": r["expiration_date"],  # garde la chaîne telle quelle
            "jours_restants": jours_restants,
            "status": r["status"] or "unknown",       # aligne l’UI sur la DB
        })

    return render_template("users.html", users=users)




@app.route("/sync_users")
def sync_users_manual():
    import update_plex_users
    update_plex_users.sync_plex_users()
    flash("✅ Synchronisation des utilisateurs terminée", "success")
    return redirect("/users")



# Route pour modifier la date d'expiration
@app.route("/update_expiration", methods=["POST"])
def update_expiration():
    user_id = request.form.get("user_id")
    new_date = request.form.get("new_date")

    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET expiration_date = ? WHERE id = ?", (new_date, user_id))
    conn.commit()
    conn.close()

    return redirect(url_for("get_users_page"))



@app.route("/update_user", methods=["POST"])
def update_user():
    user_id = request.form.get("user_id")
    username = request.form.get("username")
    email = request.form.get("email")
    new_expiration = request.form.get("expiration_date")
    firstname = request.form.get("firstname")
    lastname = request.form.get("lastname")
    second_email = request.form.get("second_email")
    logger.info(f"📥 Formulaire reçu pour mise à jour de l'utilisateur {request.form.get('user_id')}")
    logger.info(f"💾 Mise à jour de l'utilisateur {user_id} avec : "
        f"username={username}, email={email}, expiration={new_expiration}, "
        f"firstname={firstname}, lastname={lastname}, second_email={second_email}")


    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    # Récupérer l'ancienne date d'expiration
    cursor.execute("SELECT expiration_date FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    old_expiration = result[0] if result else None

    # Mise à jour en fonction des champs envoyés
    if username and email:
        cursor.execute("""
            UPDATE users SET username = ?, email = ?, expiration_date = ?, firstname = ?, lastname = ?, second_email = ?
            WHERE id = ?
        """, (username, email, new_expiration, firstname, lastname, second_email, user_id))
    #else:
    #    cursor.execute("""
    #        UPDATE users SET expiration_date = ?
    #        WHERE id = ?
    #    """, (new_expiration, user_id))

    # Réinitialisation des envois si la date change
    if new_expiration != old_expiration:
        cursor.execute("DELETE FROM sent_emails WHERE user_id = ?", (user_id,))
        logger.info(f"🧹 Envois réinitialisés pour l'utilisateur {user_id} (date changée)")

    conn.commit()
    conn.close()

    return redirect(url_for("get_users_page"))



@app.route("/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("get_users_page"))




@app.route("/user/<int:user_id>")
def get_user_page(user_id):
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Récupère l'utilisateur
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return "Utilisateur non trouvé", 404

    user = dict(row)

    # Récupère les serveurs associés
    cursor.execute("""
        SELECT s.*
        FROM servers s
        JOIN user_servers us ON us.server_id = s.id
        WHERE us.user_id = ?
    """, (user_id,))
    user["servers"] = [dict(server) for server in cursor.fetchall()]

    # Récupère les bibliothèques associées
    cursor.execute("""
        SELECT l.*
        FROM libraries l
        JOIN user_libraries ul ON ul.library_id = l.id
        WHERE ul.user_id = ?
    """, (user_id,))
    user["libraries"] = [dict(lib) for lib in cursor.fetchall()]


    # Calcul du statut
    statut = "❓ Inconnu"
    expiration = user.get("expiration_date")
    if expiration:
        try:
            expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            jours_restants = (expiration_date - datetime.now().date()).days
            if jours_restants > 60:
                statut = "🟢 Actif"
            elif jours_restants > 0:
                statut = "🟡 Bientôt expiré"
            else:
                statut = "🔴 Expiré"
        except Exception:
            statut = "⚠️ Date invalide"

    conn.close()
    return render_template("edit_user.html", statut=statut, user=user)

@app.route("/servers")
def servers_page():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM servers")
    servers = cursor.fetchall()
    conn.close()
    return render_template("servers.html", servers=servers)


@app.route("/servers/add", methods=["POST"])
def add_server():
    plex_url = request.form["plex_url"].strip()
    plex_token = request.form["plex_token"].strip()
    tautulli_url = request.form.get("tautulli_url", "").strip()
    tautulli_api_key = request.form.get("tautulli_api_key", "").strip()

    try:
        # Vérifie si le serveur Plex répond
        import requests
        res = requests.get(f"{plex_url}/identity", headers={"X-Plex-Token": plex_token}, timeout=5)
        if res.status_code != 200:
            flash(f"❌ Le serveur Plex ne répond pas correctement (HTTP {res.status_code})", "danger")
            return redirect("/servers")

        # Connexion et vérification doublon
        with sqlite3.connect(DATABASE_PATH, timeout=10) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id FROM servers WHERE plex_url = ? AND plex_token = ?
            """, (plex_url, plex_token))
            exists = cursor.fetchone()
            if exists:
                flash("⚠️ Ce serveur est déjà enregistré.", "warning")
                return redirect("/servers")

            # Insertion
            cursor.execute("""
                INSERT INTO servers (
                    plex_url, plex_token, tautulli_url, tautulli_api_key
                ) VALUES (?, ?, ?, ?)
            """, (plex_url, plex_token, tautulli_url, tautulli_api_key))
            conn.commit()

        flash("✅ Serveur ajouté avec succès", "success")

        try:
            check_servers.run()
        except Exception as e:
            flash(f"⚠️ Vérification échouée : {e}", "danger")

    except Exception as e:
        flash(f"❌ Erreur lors de l’ajout : {e}", "danger")

    return redirect("/servers")




@app.route("/server/<int:server_id>")
def edit_server(server_id):
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    server = cursor.fetchone()
    conn.close()

    if not server:
        return "Serveur introuvable", 404

    return render_template("edit_server.html", server=dict(server))


@app.route("/update_server", methods=["POST"])
def update_server():
    data = request.form
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE servers
        SET name = ?, server_id = ?, plex_url = ?, plex_token = ?,
            plex_status = ?, tautulli_url = ?, tautulli_api_key = ?,
            tautulli_status = ?, local_url = ?, public_url = ?
        WHERE id = ?
    """, (
        data["name"], data["server_id"], data["plex_url"], data["plex_token"],
        data["plex_status"], data["tautulli_url"], data["tautulli_api_key"],
        data["tautulli_status"], data["local_url"], data["public_url"],
        data["id"]
    ))
    conn.commit()
    conn.close()
    flash("✅ Serveur mis à jour avec succès", "success")
    return redirect("/servers")



@app.route("/servers/delete/<int:server_id>", methods=["POST"])
def delete_server(server_id):
    try:
        with sqlite3.connect(DATABASE_PATH, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            conn.commit()
        flash("✅ Serveur supprimé", "success")
    except Exception as e:
        flash(f"❌ Erreur suppression : {e}", "danger")
    return redirect("/servers")




@app.route("/libraries")
def libraries_page():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.*, s.name AS server_name
        FROM libraries l
        LEFT JOIN servers s ON l.server_id = s.server_id
    """)

    libraries = cursor.fetchall()
    conn.close()
    return render_template("libraries.html", libraries=libraries)




@app.route("/check_servers")
def check_servers_manual():
    from check_servers import update_statuses
    update_statuses()
    flash("✅ Vérification des serveurs effectuée !", "success")
    return redirect("/servers")

@app.route("/mailling")
def mailling():
    return render_template("mailling.html")

@app.route("/api/email_templates")
def get_email_templates():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT type, subject, body, days_before FROM email_templates")
    rows = cursor.fetchall()
    conn.close()

    result = {
        row[0]: {
            "subject": row[1],
            "body": row[2],
            "days_before": row[3]
        } for row in rows
    }

    return jsonify(result)


@app.route("/api/email_templates/<template_type>", methods=["POST"])
def update_email_template(template_type):
    data = request.get_json()
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    days_before = data.get("days_before", 0)

    if not subject or not body:
        return jsonify({"error": "Champs manquants"}), 400

    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE email_templates
        SET subject = ?, body = ?, days_before = ?
        WHERE type = ?
    """, (subject, body, days_before, template_type))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


@app.route("/settings", methods=["GET"])
def get_settings_page():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    settings = dict(row) if row else {}

    lang = get_locale()
    translations = load_translations(lang)  # ✅ Ajoute ceci

    return render_template(
        "settings.html",
        settings=settings,
        available_languages=get_available_languages(),
        translations=translations
    )






@app.route("/settings/save", methods=["POST"])
def save_settings():
    fields = [
        "discord_token", "discord_user_id",
        "mail_from", "smtp_host", "smtp_port", "smtp_tls", "smtp_user", "smtp_pass",
        "disable_on_expiry", "delete_after_expiry_days", "default_expiration_days",
        "send_reminders", "enable_cron_jobs",
        "default_language", "timezone", "admin_email", "log_level",
        "maintenance_mode", "debug_mode"
    ]
    data = {field: request.form.get(field) for field in fields}
    logger.debug("DEBUG 🔧 Formulaire reçu : %s", dict(request.form))

    # Vérifie explicitement la présence de disable_on_expiry
    if "disable_on_expiry" not in request.form:
        logger.warning("⚠️ Champ 'disable_on_expiry' manquant dans le formulaire !")

    # Coercition de types
    for key in ["smtp_port", "delete_after_expiry_days", "default_expiration_days"]:
        data[key] = int(data.get(key) or 0)

    for key in ["smtp_tls", "disable_on_expiry", "send_reminders", "enable_cron_jobs", "maintenance_mode", "debug_mode"]:
        data[key] = int(data.get(key) or 0)

    logger.info(f"🧪 disable_on_expiry reçu = {data['disable_on_expiry']}")

    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    cursor = conn.cursor()

    # Vérifie s’il y a déjà une ligne
    cursor.execute("SELECT id FROM settings LIMIT 1")
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE settings SET
              discord_token = :discord_token,
              discord_user_id = :discord_user_id,
              mail_from = :mail_from,
              smtp_host = :smtp_host,
              smtp_port = :smtp_port,
              smtp_tls = :smtp_tls,
              smtp_user = :smtp_user,
              smtp_pass = :smtp_pass,
              disable_on_expiry = :disable_on_expiry,
              delete_after_expiry_days = :delete_after_expiry_days,
              default_expiration_days = :default_expiration_days,
              send_reminders = :send_reminders,
              enable_cron_jobs = :enable_cron_jobs,
              default_language = :default_language,
              timezone = :timezone,
              admin_email = :admin_email,
              log_level = :log_level,
              maintenance_mode = :maintenance_mode,
              debug_mode = :debug_mode
            WHERE id = 1
        """, data)
    else:
        cursor.execute("""
            INSERT INTO settings (
              id, discord_token, discord_user_id, mail_from, smtp_host, smtp_port, smtp_tls,
              smtp_user, smtp_pass, disable_on_expiry, delete_after_expiry_days, default_expiration_days,
              send_reminders, enable_cron_jobs, default_language, timezone, admin_email, log_level,
              maintenance_mode, debug_mode
            ) VALUES (
              1, :discord_token, :discord_user_id, :mail_from, :smtp_host, :smtp_port, :smtp_tls,
              :smtp_user, :smtp_pass, :disable_on_expiry, :delete_after_expiry_days, :default_expiration_days,
              :send_reminders, :enable_cron_jobs, :default_language, :timezone, :admin_email, :log_level,
              :maintenance_mode, :debug_mode
            )
        """, data)

    conn.commit()
    conn.close()

    # Support AJAX/fetch (ex : bouton test email)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "ok"})

    return redirect("/settings")


    # Redémarrer le bot Discord si un token est présent
    if data.get("discord_token"):
        try:
            import subprocess
            subprocess.Popen(["python3", "bot_plex.py"])
            flash("✅ Paramètres enregistrés et bot Discord relancé", "success")
        except Exception as e:
            flash(f"⚠️ Bot non lancé : {e}", "danger")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "ok"})

    return redirect("/settings")



@app.route("/backup/save")
def save_backup():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(DATABASE_PATH), "backup")
    os.makedirs(backup_dir, exist_ok=True)

    backup_file = os.path.join(backup_dir, f"database_{timestamp}.db")
    shutil.copy2(DATABASE_PATH, backup_file)

    flash(f"Sauvegarde effectuée : {os.path.basename(backup_file)}", "success")
    return redirect("/backup")


@app.route("/backup")
def backup_page():
    backup_dir = os.path.join(os.path.dirname(DATABASE_PATH), "backup")
    files = sorted([
        f for f in os.listdir(backup_dir)
        if f.startswith("database_") and f.endswith(".db")
    ], reverse=True)
    return render_template("backup.html", backups=files)


def backup_bdd():
    backup_dir = os.path.join(os.path.dirname(DATABASE_PATH), "backup")
    os.makedirs(backup_dir, exist_ok=True)

    def get_latest_backup_time():
        timestamps = []
        for f in os.listdir(backup_dir):
            if f.startswith("database_") and f.endswith(".db"):
                try:
                    ts_str = f.replace("database_", "").replace(".db", "")
                    ts = datetime.strptime(ts_str, "%Y-%m-%d_%H%M%S")
                    timestamps.append(ts)
                except:
                    continue
        return max(timestamps) if timestamps else None

    while True:
        now = datetime.now()
        last_backup = get_latest_backup_time()

        if not last_backup or (now - last_backup).total_seconds() >= 7 * 86400:
            # Créer une nouvelle sauvegarde
            timestamp = now.strftime("%Y-%m-%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"database_{timestamp}.db")
            shutil.copy2(DATABASE_PATH, backup_file)
            print(f"[🗃️ Backup] Sauvegarde créée : {backup_file}")

            # Garde uniquement les 6 plus récentes
            backups = sorted([
                f for f in os.listdir(backup_dir)
                if f.startswith("database_") and f.endswith(".db")
            ], reverse=True)

            for old_file in backups[6:]:
                try:
                    os.remove(os.path.join(backup_dir, old_file))
                    print(f"[🧹 Cleanup] Supprimée : {old_file}")
                except Exception as e:
                    print(f"[⚠️ Erreur suppression] {old_file} → {e}")
        else:
            print("[⏸️ Backup] Dernière sauvegarde trop récente, rien à faire.")

        # Attente de 24h avant de réessayer
        time.sleep(24 * 3600)




@app.route("/backup/restore_combined", methods=["POST"])
def restore_combined_backup():
    file = request.files.get("backup_file")
    selected_file = request.form.get("selected_file")

    if file and file.filename:
        # Restauration depuis fichier uploadé
        filename = secure_filename(file.filename)
        if not filename.endswith(".db"):
            flash("❌ Fichier invalide", "danger")
            return redirect("/backup")
        file.save(DATABASE_PATH)
        flash(f"✅ Base restaurée depuis le fichier envoyé : {filename}", "success")

    elif selected_file:
        # Restauration depuis une sauvegarde locale
        backup_path = os.path.join(os.path.dirname(DATABASE_PATH), "backup", selected_file)
        if not os.path.exists(backup_path):
            flash("❌ Fichier introuvable", "danger")
            return redirect("/backup")
        shutil.copy2(backup_path, DATABASE_PATH)
        flash(f"✅ Sauvegarde restaurée : {selected_file}", "success")

    else:
        flash("❌ Aucune sauvegarde sélectionnée ou envoyée", "danger")

    return redirect("/backup")

@app.route("/backup/info/<filename>")
def get_backup_info(filename):
    backup_path = os.path.join(os.path.dirname(DATABASE_PATH), "backup", filename)
    if not os.path.exists(backup_path):
        return jsonify({}), 404

    stat = os.stat(backup_path)
    size_kb = round(stat.st_size / 1024, 1)
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({"size": size_kb, "modified": modified})

def get_settings():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}

def detect_level(line):
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        if f"[{level}]" in line:
            return level
    return "INFO"



@app.route("/logs")
def logs_page():
    def detect_level(line):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            if f"[{level}]" in line:
                return level
        return "INFO"

    log_path = os.path.join(os.path.dirname(DATABASE_PATH), "logs", "app.log")
    log_lines = []

    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            for line in reversed(f.readlines()[-500:]):  # Charge les 500 dernières lignes
                line = line.replace("\n", " ").replace("\r", " ").strip()
                if not line:
                    continue
                log_lines.append({
                    "text": line,
                    "level": detect_level(line)
                })

    return render_template("logs.html", log_lines=log_lines, translations=g.translations)

@app.route("/test_email", methods=["GET", "POST"])
def test_email():
    from mailer import send_email
    settings = get_settings()
    recipient = settings.get("mail_from") or settings.get("admin_email")

    if not recipient:
        flash("❌ Aucun destinataire défini pour le test", "danger")
        return redirect("/settings")

    subject = "✅ Test d'envoi d'e-mail"
    body = "Ceci est un message de test envoyé depuis votre configuration SMTP."

    try:
        success, message = send_email(recipient, subject, body)
        if success:
            flash(f"📤 Mail de test envoyé avec succès à {recipient}", "success")
        else:
            if "5.7.9" in message and "gmail" in settings.get("smtp_host", "").lower():
                flash(
                    "❌ Gmail a refusé la connexion : <strong>mot de passe d'application requis</strong>.<br>"
                    "📌 Suivez ces étapes :<br>"
                    "1️⃣ Accédez à <a href='https://myaccount.google.com/apppasswords' target='_blank'>myaccount.google.com/apppasswords</a><br>"
                    "2️⃣ Sélectionnez <em>Mail</em> et générez un mot de passe<br>"
                    "3️⃣ Copiez-collez ce mot de passe dans le champ SMTP",
                    "danger"
                )
            else:
                flash(f"❌ Échec de l'envoi du mail : {message}", "danger")

    except Exception as e:
        flash(f"🚨 Erreur inattendue : {str(e)}", "danger")

    return redirect("/settings")

def launch_check_servers():
    logger.info("🚀 Thread check_servers lancé")
    threading.Thread(target=check_servers.auto_check, daemon=True).start()

def launch_sync_users():
    logger.info("🚀 Thread sync_users lancé")
    threading.Thread(target=update_plex_users.auto_sync, daemon=True).start()

def launch_backup():
    logger.info("🚀 Thread backup_bdd lancé")
    threading.Thread(target=backup_bdd, daemon=True).start()

def launch_reminders():
    logger.info("🚀 Thread reminder_emails lancé")
    threading.Thread(target=send_reminder_emails.auto_reminders, daemon=True).start()

def launch_expiry_disabler():
    settings = get_settings()
    logger.info(f"🔧 disable_on_expiry = {settings.get('disable_on_expiry')}")
    if settings.get("disable_on_expiry"):
        #logger.info("🚀 Thread disable_expired_users lancé")
        threading.Thread(target=disable_expired_users, daemon=True).start()

def start_background_jobs():
    launch_check_servers()
    launch_sync_users()
    launch_backup()
    launch_reminders()
    launch_expiry_disabler()

def format_datetime(dt_str):
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%d/%m/%Y à %H:%M")
    except:
        return dt_str  # fallback brut si problème

@app.route("/tasks")
def tasks():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM task_status")
    rows = {row["name"]: row for row in cursor.fetchall()}
    conn.close()

    tasks = []
    for name, meta in TASKS.items():
        row = rows.get(name)
        tasks.append({
            "name": name,
            "label": meta["label"],
            "last_run": row["last_run"] if row and "last_run" in row.keys() else None,
            "next_run": row["next_run"] if row and "next_run" in row.keys() else None
        })

    return render_template("tasks.html", tasks=tasks)

@app.route("/run_task/<task_name>", methods=["POST"])
def run_task(task_name):
    import subprocess
    task_map = {
        "check_servers": "python check_servers.py",
        "sync_users": "python update_plex_users.py",
        "disable_expired_users": "python disable_expired_users.py",
        "send_reminders": "python send_reminder_emails.py",
        "backup": "python backup.py",
        "delete_expired_users": "python delete_expired_users.py",
        "check_libraries": "python check_libraries.py",
        "update_user_status": "python update_user_status.py"
    }
    command = task_map.get(task_name)
    if command:
        subprocess.Popen(command, shell=True)
        flash(f"🚀 Tâche '{task_name}' lancée manuellement", "info")
        logger.info(f"▶️ Tâche manuelle lancée : {task_name}")
    else:
        flash(f"❌ Tâche inconnue : {task_name}", "danger")
    return redirect("/tasks")

def get_user_status(days_left, thresholds):
    if days_left <= 0:
        return "fin"
    elif days_left <= thresholds.get("relance", 7):
        return "relance"
    elif days_left <= thresholds.get("preavis", 60):
        return "preavis"
    else:
        return "actif"

def update_task_status(task_name, interval_seconds=None):
    now = datetime.now()
    next_run = (now + timedelta(seconds=interval_seconds)).strftime("%Y-%m-%d %H:%M:%S") if interval_seconds else None
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO task_status (name, last_run, next_run)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run = excluded.last_run,
            next_run = excluded.next_run
    """, (task_name, now.strftime("%Y-%m-%d %H:%M:%S"), next_run))
    conn.commit()
    conn.close()

def get_locale():
    user_setting = get_settings()
    return user_setting.get("default_language") or request.accept_languages.best_match(get_available_languages().keys()) or "en"








def load_translations(lang_code):
    path = os.path.join(os.path.dirname(__file__), "lang", f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Erreur de chargement des traductions ({lang_code}): {e}")
        return {}

def _(key):
    return g.translations.get(key, key)

@app.context_processor
def inject_translation_function():
    def safe_translate(key):
        try:
            return g.translations.get(key, key)
        except Exception:
            return key
    return dict(_=safe_translate)

def get_available_languages():
    lang_dir = os.path.join(os.path.dirname(__file__), "lang")
    langs = {}
    for filename in os.listdir(lang_dir):
        if filename.endswith(".json"):
            code = filename[:-5]
            try:
                with open(os.path.join(lang_dir, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    label = str(data.get("lang_label", code) or code)
                    langs[code] = label
            except Exception as e:
                print(f"❌ Erreur lecture {filename} : {e}")
    return langs


def _parse_date(d):
    if not d:
        return None
    s = str(d).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.replace(" ", ""), fmt).date()
        except Exception:
            pass
    return None

def get_all_users():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, avatar, expiration_date, status FROM users")
    rows = cur.fetchall()
    conn.close()

    today = date.today()
    users = []
    for r in rows:
        exp = _parse_date(r["expiration_date"])
        jours_restants = (exp - today).days if exp else None
        users.append({
            "id": r["id"],
            "username": r["username"],
            "email": r["email"],
            "avatar": r["avatar"],
            "expiration_date": r["expiration_date"],
            "jours_restants": jours_restants,
            # ⚠️ aligne l’UI sur la DB
            "status": r["status"] or "unknown",
        })
    return users


@app.template_filter("t")
def translate(key):
    return g.translations.get(key, key)

@app.route("/change_lang", defaults={"lang_code": None})
@app.route("/change_lang/<lang_code>")
def change_lang(lang_code):
    if not lang_code:
        lang_code = request.args.get("lang", "en")
    session["lang"] = lang_code
    return redirect(request.referrer or "/")

@app.route("/about")
def about():
    info_path = os.path.join(os.path.dirname(__file__), "INFO")
    try:
        with open(info_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        content = _("INFO file not found.")
    return render_template("about.html", info_content=content)

@app.route("/api/tasks")
def api_tasks():
    tasks = get_all_tasks()
    return render_template("partials/tasks_table.html", tasks=tasks)

user_refresh_flag = False

def trigger_user_refresh_flag():
    global user_refresh_flag
    user_refresh_flag = True

def clear_user_refresh_flag():
    global user_refresh_flag
    user_refresh_flag = False

def should_refresh_users():
    return user_refresh_flag

# --- Triggers exposés pour les autres process (cron) ---

@app.route("/api/trigger-refresh/users", methods=["POST"])
def api_trigger_refresh_users():
    trigger_user_refresh_flag()  # met le flag global du process Flask
    return "", 204

@app.route("/api/trigger-refresh/libraries", methods=["POST"])
def api_trigger_refresh_libraries():
    trigger_library_refresh_flag()  # met le flag global du process Flask
    return "", 204

# (optionnel si tu veux un trigger serveurs aussi)
@app.route("/api/trigger-refresh/servers", methods=["POST"])
def api_trigger_refresh_servers():
    trigger_server_refresh_flag()  # si tu as déjà cette fonction
    return "", 204


@app.route("/api/users")
def api_users():
    users = get_all_users()
    return render_template("partials/users_table.html", users=users)

@app.route("/api/should-refresh/users")
def api_should_refresh_users():
    from flask import jsonify
    return jsonify({"refresh": should_refresh_users()})

@app.route("/api/clear-refresh/users", methods=["POST"])
def api_clear_refresh_users():
    clear_user_refresh_flag()
    return "", 204

server_refresh_flag = False

def trigger_server_refresh_flag():
    global server_refresh_flag
    server_refresh_flag = True

def clear_server_refresh_flag():
    global server_refresh_flag
    server_refresh_flag = False

def should_refresh_servers():
    return server_refresh_flag

@app.route("/api/servers")
def api_servers():
    servers = get_all_servers()
    return render_template("partials/servers_table.html", servers=servers)

@app.route("/api/should-refresh/servers")
def api_should_refresh_servers():
    from flask import jsonify
    return jsonify({"refresh": should_refresh_servers()})

@app.route("/api/clear-refresh/servers", methods=["POST"])
def api_clear_refresh_servers():
    clear_server_refresh_flag()
    return "", 204

@app.route("/api/logs")
def api_logs():
    log_lines = get_log_lines()  # ta fonction existante
    return render_template("partials/logs_table.html", log_lines=log_lines)

library_refresh_flag = False

def trigger_library_refresh_flag():
    global library_refresh_flag
    library_refresh_flag = True

def clear_library_refresh_flag():
    global library_refresh_flag
    library_refresh_flag = False

def should_refresh_libraries():
    return library_refresh_flag

@app.route("/api/libraries")
def api_libraries():
    libraries = get_all_libraries()
    return render_template("partials/libraries_table.html", libraries=libraries)

@app.route("/api/should-refresh/libraries")
def api_should_refresh_libraries():
    from flask import jsonify
    return jsonify({"refresh": should_refresh_libraries()})

@app.route("/api/clear-refresh/libraries", methods=["POST"])
def api_clear_refresh_libraries():
    clear_library_refresh_flag()
    return "", 204

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    user_id = int(user_id)  # S'assure que c'est bien un int (utile dans le POST aussi)

    if request.method == 'GET':
        # Récupère l'utilisateur
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            flash("Utilisateur introuvable.", "danger")
            conn.close()
            return redirect(url_for('get_users_page'))

        # Récupère les serveurs de type 'plex' auxquels cet utilisateur a accès
        cursor.execute("""
            SELECT s.*
            FROM servers s
            JOIN user_servers us ON us.server_id = s.id
            WHERE us.user_id = ? AND s.type = 'plex'
        """, (user_id,))
        servers = cursor.fetchall()

        print("SERVERS:", [(srv['id'], srv['name'], srv['server_id']) for srv in servers])

        # Récupère les bibliothèques déjà partagées à cet utilisateur
        cursor.execute("SELECT library_id FROM user_libraries WHERE user_id = ?", (user_id,))
        shared_ids = set(row['library_id'] for row in cursor.fetchall())

        # Pour chaque serveur, récupère ses bibliothèques
        server_bibs = {}
        for srv in servers:
            server_bibs[srv['id']] = []
            cursor.execute("SELECT * FROM libraries WHERE server_id = ?", (srv['server_id'],))
            libs = cursor.fetchall()
            for lib in libs:
                lib_dict = dict(lib)
                lib_dict['shared'] = lib['id'] in shared_ids
                server_bibs[srv['id']].append(lib_dict)
        print("SERVER_BIBS:", {k: [l['name'] for l in v] for k, v in server_bibs.items()})

        return render_template(
            'edit_user.html',
            user=user,
            servers=servers,
            server_bibs=server_bibs
        )



    if request.method == 'POST':
        logger.info(f"✏️ [edit_user] POST reçu pour user_id={user_id}")

        # 1. Récupère l'utilisateur
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            logger.warning(f"❌ [edit_user] Utilisateur {user_id} introuvable en base (POST)")
            flash("Utilisateur introuvable.", "danger")
            conn.close()
            return redirect(url_for('get_users_page'))
        else:
            logger.info(f"👤 [edit_user] Utilisateur trouvé : username={user['username']} (id={user_id})")
            # Ici on ne récupère QUE ce qui est dans la table users :
            allowSync = bool(dict(user).get('allow_sync', 0))

        # 2. Récupère les champs à mettre à jour
        second_email = request.form.get('second_email')
        firstname = request.form.get('firstname')
        lastname = request.form.get('lastname')
        expiration_date = request.form.get('expiration_date')
        logger.info(f"📝 [edit_user] Mise à jour infos utilisateur : second_email={second_email}, firstname={firstname}, lastname={lastname}, expiration_date={expiration_date}")

        # 3. Mets à jour l'utilisateur
        cursor.execute("""
            UPDATE users
            SET second_email = ?, firstname = ?, lastname = ?, expiration_date = ?
            WHERE id = ?
        """, (second_email, firstname, lastname, expiration_date, user_id))
        logger.info("[edit_user] Infos utilisateur mises à jour en base")

        # 4. Gestion des accès aux bibliothèques
        selected_library_ids = request.form.getlist('library_ids')
        selected_library_ids = [int(x) for x in selected_library_ids]
        logger.info(f"🗃️ [edit_user] Bibliothèques sélectionnées : {selected_library_ids}")

        cursor.execute("DELETE FROM user_libraries WHERE user_id = ?", (user_id,))
        logger.info(f"🗑️ [edit_user] Anciennes associations user_libraries supprimées pour user_id={user_id}")

        for lib_id in selected_library_ids:
            cursor.execute(
                "INSERT INTO user_libraries (user_id, library_id) VALUES (?, ?)",
                (user_id, lib_id)
            )
        conn.commit()
        logger.info(f"✅ [edit_user] Nouvelles associations user_libraries insérées ({len(selected_library_ids)} bibliothèques)")

        # 5. Synchronise Plex pour CHAQUE serveur (par noms de bibliothèques)
        if selected_library_ids:
            placeholders = ','.join(['?'] * len(selected_library_ids))
            cursor.execute(f"SELECT name FROM libraries WHERE id IN ({placeholders})", tuple(selected_library_ids))
            library_names = [row[0] for row in cursor.fetchall()]
        else:
            library_names = []

        # Récupère SEULEMENT les serveurs accessibles à cet utilisateur
        cursor.execute("""
            SELECT s.*
            FROM servers s
            JOIN user_servers us ON us.server_id = s.id
            WHERE s.type = 'plex' AND us.user_id = ?
        """, (user_id,))
        servers = cursor.fetchall()
        for srv in servers:
            logger.info(f"🔄 [edit_user] Serveur {srv['name']} : bibliothèques à partager = {library_names}")
            logger.debug(f"[edit_user] Appel PlexAPI avec username='{user['username']}' sur serveur '{srv['name']}'")

            # Récupère les droits pour ce user ET ce serveur
            cursor.execute(
                "SELECT * FROM user_servers WHERE user_id = ? AND server_id = ?",
                (user_id, srv['server_id'])
            )
            user_server = cursor.fetchone()
            if user_server:
                allowSync = bool(user_server['allow_sync'])
                camera = bool(user_server['allow_camera_upload'])
                channels = bool(user_server['allow_channels'])
                filterMovies = user_server['filter_movies'] or {}
                filterTelevision = user_server['filter_television'] or {}
                filterMusic = user_server['filter_music'] or {}

                share_user_libraries_plexapi(
                    plex_token=srv['plex_token'],
                    plex_url=srv['plex_url'],
                    username=user['username'],
                    library_names=library_names,
                    allowSync=allowSync,
                    camera=camera,
                    channels=channels,
                    filterMovies=filterMovies,
                    filterTelevision=filterTelevision,
                    filterMusic=filterMusic,
                )

                
                
            else:
                logger.warning(f"[edit_user] Pas de droits user_servers pour user={user_id} sur serveur={srv['server_id']} : aucune synchro Plex effectuée.")
                # On ne fait rien du tout (ni ajout, ni suppression côté Plex)

            if library_names:
                logger.info(f"🤝 [edit_user] Partage des bibliothèques effectué pour user={user['username']} sur serveur {srv['name']}")
            else:
                logger.info(f"🚫 [edit_user] Retrait de tous les partages pour user={user['username']} sur serveur {srv['name']}")

        conn.close()
        logger.info(f"🏁 [edit_user] POST terminé pour user_id={user_id}")
        flash("Accès mis à jour pour l'utilisateur !", "success")
        return redirect(url_for('get_users_page'))






if __name__ == "__main__":
    create_tables_once()
    cleanup_locks()
    settings = get_settings() 
    logger.setLevel(logging.DEBUG if settings.get("log_level") == "DEBUG" else logging.INFO)
    #start_background_jobs()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

