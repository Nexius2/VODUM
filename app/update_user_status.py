import os
import sqlite3
from datetime import datetime, UTC
import requests  # pour notifier le serveur Flask
import xml.etree.ElementTree as ET


DATABASE_PATH = "/app/appdata/database.db"
BASE_URL = os.getenv("VODUM_API_BASE", "http://127.0.0.1:5000")


def open_db():
    """Connexion SQLite courte, avec WAL et timeout pour limiter les locks."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def parse_utc(dt_val):
    """
    Retourne un datetime UTC-aware ou None si invalide.
    Gère ISO (YYYY-MM-DD[THH:MM:SS][Z]) et format FR (DD/MM/YYYY).
    """
    if not dt_val:
        return None
    s = str(dt_val).strip()
    if not s:
        return None
    # ISO
    try:
        s_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        pass
    # FR
    try:
        dt = datetime.strptime(s.replace(" ", ""), "%d/%m/%Y")
        return dt.replace(tzinfo=UTC)
    except Exception:
        return None


def trigger_refresh(kind: str):
    """Demande au serveur Flask de rafraîchir l’UI (users/libraries/servers)."""
    try:
        requests.post(f"{BASE_URL}/api/trigger-refresh/{kind}", timeout=2)
    except Exception:
        pass  # on n’échoue pas la tâche juste pour la notif UI


def log_message(cur, level, message):
    cur.execute(
        "INSERT INTO logs (event, timestamp) VALUES (?, ?)",
        (f"[{level}] {message}", datetime.now(UTC).isoformat()),
    )


def log_debug(cur, message): log_message(cur, "DEBUG", message)
def log_info(cur, message):  log_message(cur, "INFO",  message)
def log_error(cur, message): log_message(cur, "ERROR", message)


def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,))
    return cur.fetchone() is not None


def column_exists(cur, table: str, column: str) -> bool:
    try:
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())
    except Exception:
        return False

def get_any_admin_token(cur) -> str | None:
    """
    Récupère un token Plex valide depuis la table servers.
    """
    try:
        cur.execute("""
            SELECT plex_token
            FROM servers
            WHERE plex_token IS NOT NULL AND TRIM(plex_token) <> ''
            ORDER BY last_checked DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        return (row["plex_token"] if row and row["plex_token"] else None)
    except Exception:
        return None

def is_guest_user(user) -> bool:
    uname = (user.get("username") if isinstance(user, dict) else user["username"]) or ""
    return uname.strip().lower() == "guest"


def fetch_friend_ids(plex_token: str):
    """
    Retourne (set_ids, ok)
    - set_ids: ensemble des IDs plex des amis
    - ok: True si la récup a réussi (on peut conclure 'false' par absence),
          False si on doit renvoyer 'unknown'
    """
    if not plex_token:
        return set(), False

    headers = {"X-Plex-Token": plex_token}
    urls = [
        "https://plex.tv/pms/friends/all",  # endpoint historique
        "https://plex.tv/api/friends",      # fallback possible
    ]
    ids = set()
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200 or not r.text.strip():
                continue
            root = ET.fromstring(r.text)
            for el in root.findall(".//User"):
                uid = el.attrib.get("id")
                if uid:
                    ids.add(str(uid))
            # succès si on a pu parser; même si liste vide, ok=True
            return ids, True
        except Exception:
            continue
    return set(), False


def fetch_friend_sets(plex_token: str):
    """
    Renvoie {'ids': set[str], 'emails': set[str], 'usernames': set[str], 'ok': bool}
    ok=False si l'appel a échoué → on posera 'unknown' pour les comptes sans accès.
    """
    out = {"ids": set(), "emails": set(), "usernames": set(), "ok": False}
    if not plex_token:
        return out

    headers = {
        "X-Plex-Token": plex_token,
        "Accept": "application/xml",
        "X-Plex-Client-Identifier": "vodum",
        "X-Plex-Product": "Vodum",
        "X-Plex-Version": "1.0",
    }
    urls = [
        "https://plex.tv/pms/friends/all",
        "https://plex.tv/api/friends",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200 or not r.text.strip():
                continue
            root = ET.fromstring(r.text)

            # <User ... id="" username="" email="">
            for el in root.findall(".//User"):
                uid = el.attrib.get("id")
                if uid: out["ids"].add(str(uid))
                eml = el.attrib.get("email")
                if eml: out["emails"].add(eml.lower())
                un  = el.attrib.get("username")
                if un:  out["usernames"].add(un.lower())

            # <Friend ...> (certains dumps l'utilisent)
            for el in root.findall(".//Friend"):
                uid = el.attrib.get("userID") or el.attrib.get("user_id") or el.attrib.get("id")
                if uid: out["ids"].add(str(uid))
                eml = el.attrib.get("email")
                if eml: out["emails"].add(eml.lower())
                un  = el.attrib.get("username")
                if un:  out["usernames"].add(un.lower())

            out["ok"] = True
            break
        except Exception:
            continue

    return out

def friend_state_from_db(cur, user_id: int) -> str:
    """
    'true'  si user a au moins 1 ligne dans user_servers
    'false' si user n'a aucune ligne et qu'il y a au moins 1 serveur en base
    'unknown' s'il n'y a aucun serveur (pas encore synchro)
    """
    cur.execute("SELECT 1 FROM user_servers WHERE user_id = ? LIMIT 1", (user_id,))
    if cur.fetchone():
        return "true"

    cur.execute("SELECT COUNT(*) FROM servers")
    total_servers = cur.fetchone()[0]
    if total_servers == 0:
        return "unknown"
    return "false"


def decide_friend_state(plex_id: str, friends_ids: set[str], ok: bool) -> str:
    """
    'true' si l'id est dans la liste,
    'false' si la requête a réussi (ok=True) et l'id n'est pas dedans,
    'unknown' si on n'a pas pu récupérer la liste (ok=False).
    """
    if not ok:
        return "unknown"
    return "true" if plex_id and plex_id in friends_ids else "false"

def decide_friend_state_by_sets(plex_id: str, email: str, username: str, friends: dict) -> str:
    """
    'true' si on trouve id/email/username dans la liste des amis.
    'false' si la récupération a réussi et qu'on ne trouve pas.
    'unknown' si on n'a pas pu récupérer la liste (ok=False).
    """
    if not friends.get("ok"):
        return "unknown"
    pid = (plex_id or "").strip()
    eml = (email or "").strip().lower()
    usr = (username or "").strip().lower()
    if (pid and pid in friends["ids"]) or (eml and eml in friends["emails"]) or (usr and usr in friends["usernames"]):
        return "true"
    return "false"


def has_any_library_access(cur, user_row) -> bool:
    uid = user_row["id"]

    cur.execute("SELECT 1 FROM user_libraries  WHERE user_id = ? LIMIT 1", (uid,))
    if cur.fetchone(): return True

    cur.execute("SELECT 1 FROM shared_libraries WHERE user_id = ? LIMIT 1", (uid,))
    if cur.fetchone(): return True

    # Optionnel si tu maintiens users.library_access (CSV)
    cur.execute("""
        SELECT 1 FROM users
        WHERE id = ? AND library_access IS NOT NULL AND TRIM(library_access) <> ''
        LIMIT 1
    """, (uid,))
    return bool(cur.fetchone())



def get_mail_threshold(cur, mail_type: str, default_value: int) -> int:
    """
    Récupère la valeur de seuil (jours avant/après expiration)
    depuis la table email_templates selon le type de mail.
    """
    try:
        cur.execute("SELECT days_before FROM email_templates WHERE type = ?", (mail_type,))
        row = cur.fetchone()
        if row and row["days_before"] is not None:
            return int(row["days_before"])
    except Exception as e:
        log_error(cur, f"Lecture du seuil '{mail_type}' impossible: {e}")
    return default_value





def compute_subscription_status(user: dict, cur) -> str:
    """
    Calcule le statut d’un utilisateur selon :
      - son type (admin, ami, invité…)
      - ses accès (bibliothèques)
      - sa date d’expiration
      - les seuils configurés dans 'email_templates'
    """
    cur_status = (user.get("status") or "").strip()
    is_admin   = int(user.get("is_admin") or 0) == 1
    has_libs   = bool(user.get("has_libraries"))
    friend_st  = (user.get("is_friend_state") or "unknown")
    exp_str    = user.get("expiration_date")

    # 🛑 Statut protégé : suspension prioritaire
    if cur_status == "suspended":
        return "suspended"

    # 👤 Admin = toujours actif
    if is_admin:
        return "active"

    # 🧑‍ guest : neutre si aucun accès
    if is_guest_user(user):
        if not has_libs:
            return "unknown"

    # 📂 Pas d'accès aux bibliothèques → ignorer la date
    if not has_libs:
        if friend_st == "false":
            return "unfriended"
        if friend_st == "true":
            return "expired"
        return "unknown"

    # 📅 Si pas de date d’expiration → actif par défaut
    if not exp_str:
        return "active"

    expiration = parse_utc(exp_str)
    if expiration is None:
        return "active"

    now = datetime.now(UTC)
    if expiration < now:
        return "expired"

    # --- ✅ Lecture dynamique des seuils configurés ---
    preavis_days = get_mail_threshold(cur, "preavis", 30)
    relance_days = get_mail_threshold(cur, "relance", 7)
    fin_days     = get_mail_threshold(cur, "fin", 0)

    # ✅ Calcul précis des jours restants (en jours réels)
    delta_days = (expiration - now).total_seconds() / 86400  # nombre réel de jours
    days_remaining = int(delta_days + 0.5)  # arrondi au jour le plus proche

    # --- 📊 Application de la logique configurée ---
    # ❗️ Si la date est dépassée de plus de fin_days → expiré
    if days_remaining < -fin_days:
        return "expired"

    # 📩 Relance : en dessous ou égal au seuil relance
    if days_remaining <= relance_days:
        return "reminder"

    # ⚠️ Préavis : uniquement si jours restants strictement inférieurs au seuil
    if days_remaining < preavis_days:
        return "pre_expired"

    # ✅ Sinon, utilisateur actif
    return "active"







def log_status_change(cur, user_id, username, old_status, new_status):
    log_info(cur, f"Utilisateur {username} (ID {user_id}) : statut modifié de {old_status} -> {new_status}")


def update_statuses():
    """Connexion courte: met à jour les statuts puis ferme (évite les locks)."""
    conn = open_db()
    cur = conn.cursor()
    try:
        log_info(cur, "🚀 Début de la mise à jour des statuts utilisateurs")

        log_info(cur, "⚙️ Seuils dynamiques (email_templates) activés")


        cur.execute("""
            SELECT
                u.id, u.username, u.email, u.plex_id,
                u.is_admin,
                u.status, u.last_status, u.expiration_date, u.library_access
            FROM users u
        """)
        users = cur.fetchall()
        
        log_info(cur, f"👥 {len(users)} utilisateurs chargés depuis la base")

        changes = 0
        # 1) token admin & amis plex
        admin_token = get_any_admin_token(cur)
        friends = fetch_friend_sets(admin_token)
        if not friends.get("ok"):
            log_error(cur, "Impossible de récupérer la liste d'amis Plex (token/réseau). Les comptes sans accès seront classés 'unknown'.")

        for user in users:
            has_libs = has_any_library_access(cur, user)
            is_friend_state = friend_state_from_db(cur, user["id"])   

            u = dict(user)
            u["has_libraries"]   = 1 if has_libs else 0
            u["is_friend_state"] = is_friend_state

            new_status = compute_subscription_status(u, cur)



            # (facultatif) petit log pour vérifier
            # log_debug(cur, f"uid={user['id']} user={user['username']} friend={is_friend_state} has_libs={has_libs} exp={user['expiration_date']} -> {new_status}")

            if new_status and new_status != user["status"]:
                cur.execute("""
                    UPDATE users
                    SET last_status = status,
                        status = ?,
                        status_changed_at = ?
                    WHERE id = ?
                """, (new_status, datetime.now(UTC).isoformat(), user["id"]))
                changes += 1


        if changes == 0:
            log_info(cur, "ℹ️ Aucun statut utilisateur modifié lors de ce run")
        else:
            log_info(cur, f"✅ {changes} utilisateurs mis à jour")

        conn.commit()
    finally:
        conn.close()


def main():
    # 1) MAJ des statuts (connexion courte)
    update_statuses()

    # 2) Demander un refresh du tableau Users côté UI (process Flask)
    trigger_refresh("users")

    # 3) (option soft) demander au serveur de lancer la tâche update_plex_users (si route dispo)
    try:
        requests.post(f"{BASE_URL}/run_task/update_plex_users", timeout=2)
    except Exception:
        pass

    # 4) Marquer la tâche comme effectuée
    conn = open_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO task_status (name, last_run)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET last_run = excluded.last_run
            """,
            ("update_user_status", datetime.now(UTC).isoformat()),
        )
        conn.commit()
        log_info(cur, "📌 Task status mis à jour")
        log_info(cur, "🎉 Script update_user_status terminé avec succès")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
