import sqlite3
from config import DATABASE_PATH
from logger import logger

def add_column_if_not_exists(cur, table, column, coltype):
    """
    Ajoute une colonne si elle n'existe pas déjà dans la table.
    """
    cur.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]
    if column not in columns:
        logger.info(f"➕ Ajout de la colonne '{column}' dans '{table}'")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    else:
        logger.debug(f"✔️ Colonne '{column}' déjà présente dans '{table}'")

def update_vodum():
    """
    Met à jour le schéma de la base Vodum (ajout colonnes, etc.)
    """
    logger.info("🚀 Démarrage de la mise à jour Vodum")
    try:
        conn = sqlite3.connect(DATABASE_PATH, timeout=30)
        cur = conn.cursor()

        # Limite les locks
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.execute("PRAGMA synchronous=NORMAL;")

        # Vérifier / ajouter colonnes dans la table users
        add_column_if_not_exists(cur, "users", "status", "TEXT")
        add_column_if_not_exists(cur, "users", "last_status", "TEXT")
        add_column_if_not_exists(cur, "users", "status_changed_at", "DATETIME")
        add_column_if_not_exists(cur, "users", "library_access", "TEXT")
        
        
        # --- 👇👇 AJOUTER ICI les colonnes manquantes pour l'UI Edit User ---
        add_column_if_not_exists(cur, "users", "allow_sync",      "INTEGER DEFAULT 0")
        add_column_if_not_exists(cur, "users", "allow_deletion",  "INTEGER DEFAULT 0")
        add_column_if_not_exists(cur, "users", "allow_sharing",   "INTEGER DEFAULT 1")
        add_column_if_not_exists(cur, "users", "remote_quality",  "TEXT DEFAULT 'Auto'")
        add_column_if_not_exists(cur, "users", "local_quality",   "TEXT DEFAULT 'Auto'")
        add_column_if_not_exists(cur, "users", "audio_boost",     "INTEGER DEFAULT 0")
        add_column_if_not_exists(cur, "users", "bandwidth_limit", "INTEGER")
        add_column_if_not_exists(cur, "users", "content_restriction", "TEXT")

        # (Optionnel) appliquer les valeurs par défaut sur les anciennes lignes
        cur.execute("UPDATE users SET allow_sync=0 WHERE allow_sync IS NULL")
        cur.execute("UPDATE users SET allow_deletion=0 WHERE allow_deletion IS NULL")
        cur.execute("UPDATE users SET allow_sharing=1 WHERE allow_sharing IS NULL")
        cur.execute("UPDATE users SET remote_quality='Auto' WHERE remote_quality IS NULL")
        cur.execute("UPDATE users SET local_quality='Auto' WHERE local_quality IS NULL")
        cur.execute("UPDATE users SET audio_boost=0 WHERE audio_boost IS NULL")

        conn.commit()
        conn.close()
        logger.info("✅ Mise à jour Vodum terminée avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors de la mise à jour Vodum : {e}")
