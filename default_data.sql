-- ============================================================
--  VODUM V2 - Données par défaut (corrigé)
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
--  TÂCHES SYSTÈME
-- ============================================================
-- ⚙️ Tâche automatique : synchronisation Plex
-- Exécution : toutes les 6 heures → "0 */6 * * *"

INSERT INTO tasks (
    name,
    description,
    schedule,
    enabled,
    status,
    last_run,
    next_run,
    last_error
) VALUES (
    'sync_plex',
    'Synchronisation complète Plex (serveurs, utilisateurs, bibliothèques et partages).',
    '0 */6 * * *',
    1,
    'idle',
    NULL,
    NULL,
    NULL
);


-- ============================================================
--  CONFIGURATION GÉNÉRALE MINIMALE
--  (table settings de tables.sql)
-- ============================================================

INSERT INTO settings (
    id,
    mail_from,
    smtp_host,
    smtp_port,
    smtp_tls,
    smtp_user,
    smtp_pass,
    disable_on_expiry,
    delete_after_expiry_days,
    send_reminders,
    default_language,
    timezone,
    admin_email,
    enable_cron_jobs,
    default_expiration_days,
    maintenance_mode,
    debug_mode
) VALUES (
    1,
    '',
    '',
    587,
    1,
    '',
    '',
    0,
    30,
    1,
    'fr',
    'Europe/Paris',
    '',
    1,
    90,
    0,
    0
);
