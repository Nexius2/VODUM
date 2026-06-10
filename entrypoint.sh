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
###############################################################################

echo "Starting VODUM..."

# ---------------------------------------------------------------------------
# Chemins standards (UNIQUE source de vérité)
# - Respecte DATABASE_PATH / VODUM_BACKUP_DIR / VODUM_LOG_DIR
# - Permet à l’utilisateur de monter ailleurs que /appdata
# ---------------------------------------------------------------------------

DB_PATH="${DATABASE_PATH:-/appdata/database.db}"
DB_DIR="$(dirname "$DB_PATH")"

LOG_DIR="${VODUM_LOG_DIR:-$DB_DIR/logs}"
BACKUP_DIR="${VODUM_BACKUP_DIR:-$DB_DIR/backups}"

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
  log INFO "Database missing → creating a new V2 database"

  sqlite3 "$DB_PATH" < /app/tables.sql

  # Marquer le schéma initial V2 (ta table exige version INTEGER + name TEXT)
  # On utilise "2 / init_v2" comme dans tables.sql
  sqlite3 "$DB_PATH" <<'EOF'
INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (2, 'init_v2');
EOF

  log INFO "V2 database initialized successfully"

else
  log INFO "Existing database detected"
fi

# ---------------------------------------------------------------------------
# 2️⃣ Détection V1 → V2
#
# Règle :
#   - Pas de table tasks → DB V1
#   - Table tasks présente → DB V2
# ---------------------------------------------------------------------------

HAS_TASKS_TABLE=$(
  sqlite3 "$DB_PATH" \
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks' LIMIT 1;" \
    2>/dev/null || true
)

# ---------------------------------------------------------------------------
# 3️⃣ Migration V1 → V2 (rebuild + import)
# ---------------------------------------------------------------------------

if [ -n "$HAS_TASKS_TABLE" ]; then
  log INFO "Database already in V2 → no structural migration required"
else
  log WARN "V1 database detected → starting V1 → V2 rebuild migration"

  TS=$(date '+%Y%m%d_%H%M%S')
  V1_BACKUP="$BACKUP_DIR/database_v1_$TS.db"

  # Sauvegarde intégrale de la DB V1 (intouchable)
  cp "$DB_PATH" "$V1_BACKUP"
  log INFO "Backup V1 created : $V1_BACKUP"

  # Suppression de la DB active (on repart de zéro)
  rm -f "$DB_PATH"
  log INFO "Old database removed (V2 rebuild)"

  # Création du schéma V2 propre
  sqlite3 "$DB_PATH" < /app/tables.sql
  log INFO "V2 schema recreated"

  # Import des données depuis la DB V1
  # NOTE :
  #  - Ce script lit la DB V1
  #  - Insère uniquement les données compatibles V2
  #  - Ignore toute structure obsolète
  python3 /app/migrations/20251213_import_v1_into_v2.py "$V1_BACKUP"

  # Journaliser l'import sans modifier la version structurelle V2.
  # Les migrations datées utilisent leur date comme identifiant unique.
  sqlite3 "$DB_PATH" <<'EOF'
INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (20251213, '20251213_import_v1_into_v2');
EOF

  log INFO "V1 → V2 migration completed successfully"
fi

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

# ---------------------------------------------------------------------------
# 3️⃣.2️⃣ Fix FK legacy (REFERENCES *_old / *__rebuild / *__rebuild_old)
# - Déclenche si:
#   a) le dry-run liste des tables à rebuild
#   b) OU foreign_key_check mentionne un parent avec suffix legacy
# ---------------------------------------------------------------------------

DRY_OUT="$(python3 /app/migrations/20260201_fix_fk_legacy_suffixes.py "$DB_PATH" --dry-run || true)"

# Signal 1 : le script voit des refs legacy
echo "$DRY_OUT" | grep -q "\[DRY\]" && NEED_FIX=1 || NEED_FIX=0

# Signal 2 : sqlite voit des FK cassées vers des tables legacy
FKC_OUT="$(sqlite3 "$DB_PATH" "PRAGMA foreign_key_check;" 2>/dev/null || true)"
echo "$FKC_OUT" | grep -Eiq "(_old|__rebuild_old|__rebuild)" && NEED_FIX=1 || true

if [ "${NEED_FIX:-0}" = "1" ]; then
  log WARN "Legacy FK issue detected → backup then apply fix"

  TS=$(date -u '+%Y%m%d_%H%M%S')
  PRE_FIX_BACKUP="$BACKUP_DIR/backup_${TS}_pre_20260201_fixfk.sqlite"

  # checkpoint WAL avant copie (si WAL actif)
  sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 || true

  cp -f "$DB_PATH" "$PRE_FIX_BACKUP"
  log INFO "Pre-fix backup created: $PRE_FIX_BACKUP"

  python3 /app/migrations/20260201_fix_fk_legacy_suffixes.py "$DB_PATH" || exit 1

  # re-check
  POST_FKC="$(sqlite3 "$DB_PATH" "PRAGMA foreign_key_check;" 2>/dev/null || true)"
  if [ -n "$POST_FKC" ]; then
    log WARN "foreign_key_check still reports issues after fix. First lines:"
    echo "$POST_FKC" | head -n 20 | while read -r line; do log WARN "$line"; done
    # On ne stoppe pas forcément le container, mais tu peux mettre exit 1 si tu préfères bloquer.
  else
    log INFO "Legacy FK fix applied successfully (foreign_key_check clean)"
  fi
else
  log INFO "Legacy FK fix not needed."
fi






log INFO "Starting DB bootstrap"
python3 /app/db_bootstrap.py
log INFO "DB bootstrap completed"

# ---------------------------------------------------------------------------
# 5️⃣ Démarrage de l'application
# ---------------------------------------------------------------------------

log INFO "Starting Waitress production server"
UPLOAD_MB="${VODUM_MAX_UPLOAD_MB:-4096}"
case "$UPLOAD_MB" in
  ''|*[!0-9]*) log ERROR "VODUM_MAX_UPLOAD_MB must be a positive integer"; exit 1 ;;
esac
MAX_REQUEST_BODY_SIZE=$((UPLOAD_MB * 1024 * 1024))

exec waitress-serve \
  --host=0.0.0.0 \
  --port="${VODUM_PORT:-5000}" \
  --threads="${VODUM_WAITRESS_THREADS:-6}" \
  --max-request-body-size="$MAX_REQUEST_BODY_SIZE" \
  run:app
