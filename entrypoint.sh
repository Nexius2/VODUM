#!/bin/bash
set -euo pipefail

###############################################################################
# VODUM – ENTRYPOINT
#
# Rôle :
#  - Initialiser la base de données si absente
#  - Détecter une éventuelle base V1
#  - Migrer V1 → V2 via une reconstruction propre
#  - Lancer le bootstrap (idempotent)
#  - Démarrer l'application Flask
#
# IMPORTANT :
#  - AUCUNE table V1 ne doit survivre dans la DB V2 finale
#  - La DB V1 est toujours conservée (backup)
###############################################################################

echo "🚀 Démarrage VODUM..."

# ---------------------------------------------------------------------------
# Chemins standards (UNIQUE source de vérité)
# ---------------------------------------------------------------------------

DB_DIR="/appdata"
DB_PATH="$DB_DIR/database.db"
LOG_DIR="$DB_DIR/logs"
BACKUP_DIR="$DB_DIR/backups"

mkdir -p "$DB_DIR" "$LOG_DIR" "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# Fonction utilitaire de log (stdout + fichier)
# ---------------------------------------------------------------------------

log() {
  local level="$1"
  local message="$2"
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')

  echo "$ts | $level | entrypoint | $message" | tee -a "$LOG_DIR/entrypoint.log"
}

# ---------------------------------------------------------------------------
# 1️⃣ Détection de la présence de la DB
# ---------------------------------------------------------------------------

if [ ! -f "$DB_PATH" ]; then
  log INFO "Base absente → création d'une base V2 neuve"

  sqlite3 "$DB_PATH" < /app/tables.sql

  # Marquer le schéma initial V2
  sqlite3 "$DB_PATH" <<EOF
INSERT OR IGNORE INTO schema_migrations (version)
VALUES ('20250330_initial_v2_schema');
EOF

  log INFO "Base V2 initialisée avec succès"

else
  log INFO "Base existante détectée"
fi

# ---------------------------------------------------------------------------
# 2️⃣ Détection V1 → V2
#
# Règle :
#   - Pas de table schema_migrations → DB V1
#   - Table schema_migrations présente → DB V2
# ---------------------------------------------------------------------------

HAS_TASKS_TABLE=$(sqlite3 "$DB_PATH" \
  "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks';" \
  2>/dev/null || true)



# ---------------------------------------------------------------------------
# 3️⃣ Migration V1 → V2 (rebuild + import)
# ---------------------------------------------------------------------------

if [ -n "$HAS_TASKS_TABLE" ]; then
  log INFO "Base déjà en V2 → aucune migration structurelle nécessaire"
else

  log WARN "Base V1 détectée → lancement de la migration rebuild V1 → V2"

  TS=$(date '+%Y%m%d_%H%M%S')
  V1_BACKUP="$BACKUP_DIR/database_v1_$TS.db"

  # Sauvegarde intégrale de la DB V1 (intouchable)
  cp "$DB_PATH" "$V1_BACKUP"
  log INFO "Backup V1 créé : $V1_BACKUP"

  # Suppression de la DB active (on repart de zéro)
  rm -f "$DB_PATH"
  log INFO "Ancienne DB supprimée (reconstruction V2)"

  # Création du schéma V2 propre
  sqlite3 "$DB_PATH" < /app/tables.sql
  log INFO "Schéma V2 recréé"

  # Import des données depuis la DB V1
  # NOTE :
  #  - Ce script lit la DB V1
  #  - Insère uniquement les données compatibles V2
  #  - Ignore toute structure obsolète
  python3 /app/migrations/20251213_import_v1_into_v2.py "$V1_BACKUP"

  # Marquer la migration comme appliquée
  sqlite3 "$DB_PATH" <<EOF
INSERT INTO schema_migrations (version)
VALUES ('20250402_rebuild_from_v1');
EOF

  log INFO "Migration V1 → V2 terminée avec succès"
fi

# ---------------------------------------------------------------------------
# 3️⃣.1️⃣ Migrations V2 incrémentales
# ---------------------------------------------------------------------------

#log INFO "Vérification des migrations V2"

#HAS_JELLYFIN_MIGRATION=$(sqlite3 "$DB_PATH" \
#  "SELECT 1 FROM schema_migrations WHERE version = '2025_07_add_jellyfin_id_and_nullable_plex_id';" \
#  2>/dev/null || true)

#if [ -z "$HAS_JELLYFIN_MIGRATION" ]; then
#  log INFO "Application migration Jellyfin (plex_id nullable + jellyfin_id)"
#  python3 /app/migrations/20251215_add_jellyfin_id_and_nullable_plex_id.py "$DB_PATH"
#  log INFO "Migration Jellyfin appliquée avec succès"
#else
#  log INFO "Migration Jellyfin déjà appliquée"
#fi



# ---------------------------------------------------------------------------
# 4️⃣ Bootstrap DB (idempotent)
#
# Rôle :
#  - Vérifier la présence des colonnes
#  - Ajouter les valeurs par défaut
#  - Créer les tâches, templates, settings manquants
#
# Peut être exécuté À CHAQUE démarrage sans risque
# ---------------------------------------------------------------------------

log INFO "Lancement du bootstrap DB"
python3 /app/db_bootstrap.py
log INFO "Bootstrap DB terminé"

# ---------------------------------------------------------------------------
# 5️⃣ Démarrage de l'application
# ---------------------------------------------------------------------------

log INFO "Lancement du serveur Flask"
exec python3 /app/app.py
