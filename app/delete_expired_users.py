# /app/delete_expired_users.py
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from logger import logger
from config import DATABASE_PATH
from tasks import update_task_status

# PlexAPI (installé dans ton image)
from plexapi.myplex import MyPlexAccount


def get_setting_days(cur: sqlite3.Cursor) -> Optional[int]:
    """
    Récupère le délai (en jours) après lequel on 'unfriend' les utilisateurs en statut 'expired'.
    Compatible avec 2 schémas :
      - Table settings en key/value : key = 'delete_after_expiry_days' ou 'delete_after_days'
      - Colonne directe dans settings : colonne 'delete_after_expiry_days' ou 'delete_after_days'
    """
    # 1) Schéma key/value
    for key in ("delete_after_expiry_days", "delete_after_days"):
        try:
            cur.execute("SELECT value FROM settings WHERE key=? LIMIT 1", (key,))
            row = cur.fetchone()
            if row and row[0] is not None and str(row[0]).strip() != "":
                return int(str(row[0]).strip())
        except Exception:
            pass

    # 2) Schéma colonnes
    for col in ("delete_after_expiry_days", "delete_after_days"):
        try:
            cur.execute(f"SELECT {col} FROM settings LIMIT 1")
            row = cur.fetchone()
            if row and row[0] is not None and str(row[0]).strip() != "":
                return int(str(row[0]).strip())
        except Exception:
            pass

    return None


def get_admin_token(cur: sqlite3.Cursor) -> Optional[str]:
    """
    Récupère un token Plex admin utilisable.
    Priorité: servers.plex_token (non vide), fallback settings.plex_auth_token.
    """
    # 1) Cherche d'abord dans servers (avec ou sans colonne is_owner selon le schéma)
    for q in (
        """
        SELECT plex_token FROM servers
        WHERE plex_token IS NOT NULL AND TRIM(plex_token) <> ''
        ORDER BY is_owner DESC, id ASC LIMIT 1
        """,
        """
        SELECT plex_token FROM servers
        WHERE plex_token IS NOT NULL AND TRIM(plex_token) <> ''
        ORDER BY id ASC LIMIT 1
        """,
    ):
        try:
            cur.execute(q)
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            continue

    # 2) Ensuite dans settings : d'abord en key/value, puis en colonne directe
    for q in (
        "SELECT value FROM settings WHERE key='plex_auth_token' LIMIT 1",
        "SELECT plex_auth_token FROM settings LIMIT 1",
    ):
        try:
            cur.execute(q)
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            continue

    return None


def list_expired_candidates(cur: sqlite3.Cursor, delete_after_days: int) -> List[Tuple]:
    """
    Cible les utilisateurs:
      - status = 'expired'
      - non admin, username != 'guest'
      - dont la date d'expiration (expiration_date, ou fallback status_changed_at)
        est antérieure à aujourd'hui - delete_after_days.
    Retourne: (id, username, email, status_changed_at, expiration_date)
    """
    cur.execute("""
        SELECT
            id, username, email, status_changed_at, expiration_date
        FROM users
        WHERE status = 'expired'
          AND is_admin = 0
          AND LOWER(username) <> 'guest'
          AND DATE(
                COALESCE(
                    expiration_date,
                    substr(status_changed_at, 1, 10)  -- 'YYYY-MM-DD' extrait si ISO
                ),
                '+' || ? || ' days'
              ) < DATE('now')
    """, (delete_after_days,))
    return cur.fetchall()


def find_friend_obj(account: MyPlexAccount, username: str, email: str):
    """Tente de retrouver l'ami sur Plex via username/email."""
    try:
        friends = account.users()  # liste des amis/partagés sur plex
    except Exception as e:
        logger.error(f"❌ Impossible de récupérer la liste d'amis Plex: {e}")
        return None

    uname = (username or "").strip().lower()
    eml = (email or "").strip().lower()

    for f in friends:
        try:
            fu = (getattr(f, "username", "") or "").strip().lower()
            fe = (getattr(f, "email", "") or "").strip().lower()
            if (uname and fu == uname) or (eml and fe == eml):
                return f
        except Exception:
            continue
    return None


def unfriend_and_update_db(conn: sqlite3.Connection, account: MyPlexAccount, user_row: Tuple):
    """
    Unfriend sur Plex + mise à jour DB locale.
    user_row = (id, username, email, status_changed_at, expiration_date)
    """
    cur = conn.cursor()
    user_id, username, email, status_changed_at, expiration_date = user_row

    # 1) Unfriend Plex
    friend_obj = find_friend_obj(account, username, email)
    try:
        if friend_obj:
            logger.info(f"👋 Unfriend Plex: {username}")
            account.removeFriend(friend_obj)
        else:
            logger.info(f"👋 Unfriend Plex (fallback str): {username}")
            account.removeFriend(username)
    except Exception as e:
        logger.error(f"❌ Echec unfriend Plex pour {username}: {e}")

    # 2) Nettoyage accès locaux
    try:
        cur.execute("DELETE FROM user_servers WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM user_libraries WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM shared_libraries WHERE user_id = ?", (user_id,))
    except Exception as e:
        logger.error(f"⚠️ Nettoyage accès échoué pour {username}: {e}")

    # 3) Statut = 'unfriended'
    cur.execute("""
        UPDATE users
        SET last_status = status,
            status = 'unfriended',
            status_changed_at = ?
        WHERE id = ?
    """, (datetime.now(timezone.utc).isoformat(), user_id))

    conn.commit()
    logger.info(f"✅ {username}: statut 'unfriended' appliqué et accès retirés localement")


def delete_expired_users():
    logger.info("🗑️ Début de la tâche d'unfriend des utilisateurs expirés")

    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1) Délai de suppression
    delete_after_days = get_setting_days(cur)
    if delete_after_days is None:
        logger.info("⚠️ Aucun délai configuré (keys: 'delete_after_expiry_days' ou 'delete_after_days') → tâche ignorée")
        conn.close()
        return

    # 2) Liste des candidats
    candidates = list_expired_candidates(cur, delete_after_days)
    if not candidates:
        logger.info("✅ Aucun utilisateur 'expired' à unfriend selon la fenêtre de temps.")
        conn.close()
        update_task_status("delete_expired_users")
        return

    # 3) Token admin Plex
    admin_token = get_admin_token(cur)
    if not admin_token:
        logger.error("🚨 Aucun token admin Plex trouvé (servers.plex_token ou settings.plex_auth_token)")
        conn.close()
        return

    # 4) Connexion Plex
    try:
        account = MyPlexAccount(token=admin_token)
    except Exception as e:
        logger.error(f"❌ Connexion au compte Plex admin impossible : {e}")
        conn.close()
        return

    # 5) Unfriend + update DB
    for row in candidates:
        try:
            unfriend_and_update_db(conn, account, row)
        except Exception as e:
            logger.error(f"❌ Erreur traitement utilisateur id={row['id']} ({row['username']}): {e}")

    conn.close()
    update_task_status("delete_expired_users")
    logger.info("🏁 Fin de la tâche d'unfriend des utilisateurs expirés")


if __name__ == "__main__":
    delete_expired_users()
