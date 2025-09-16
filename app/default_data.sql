

INSERT OR IGNORE INTO email_templates (type, subject, body, days_before) VALUES
('preavis', 'Fin d’abonnement dans 60 jours', 'Bonjour {{username}}, votre abonnement expire bientôt...', 60),
('relance', 'Rappel - Votre abonnement arrive à expiration', 'Bonjour {{username}}, ceci est un rappel...', 7),
('fin', 'Abonnement expiré', 'Bonjour {{username}}, votre accès a été désactivé...', 0);



INSERT OR IGNORE INTO settings (
  id, discord_token, discord_user_id,
  mail_from, smtp_host, smtp_port, smtp_tls,
  smtp_user, smtp_pass,
  disable_on_expiry, delete_after_expiry_days, default_expiration_days,
  send_reminders, enable_cron_jobs,
  default_language, timezone, admin_email, log_level,
  maintenance_mode, debug_mode
) VALUES (
  1, '', '',
  'admin@localhost', 'smtp.local', 587, 1,
  '', '',
  1, 30, 90,
  1, 1,
  'en', 'Europe/Paris', 'admin@localhost', 'info',
  0, 0
);

INSERT OR IGNORE INTO task_status (name, last_run, next_run) VALUES
('check_servers', NULL, NULL),
('sync_users', NULL, NULL),
('disable_expired_users', NULL, NULL),
('send_reminders', NULL, NULL),
('backup', NULL, NULL),
('delete_expired_users', NULL, NULL),
('check_libraries', NULL, NULL);





