# Changelog

All notable changes to Vodum will be documented in this file.

---

## Unreleased

- Reduit les colonnes chargees par la page Settings pour eviter les `SELECT *` et ne plus transporter les secrets de communication sur ce rendu.
- Remplace les icones Material Icons globales par un sprite SVG local et retire le chargement Google Fonts associe.
- Corrige le mojibake dans les fichiers JSON de langue et ajoute une validation dediee pour prevenir les regressions.
- Optimise l'UI admin: polling des taches adaptatif, rendu groupe des tableaux JS, chargement/decodage non bloquant des images, versionnement/cache des assets statiques, chargement de Chart.js limite aux vues avec graphiques, Flatpickr charge a la demande, preconnects pour les CDN restants, instrumentation optionnelle des routes lentes et compression gzip des reponses texte.
- Ajoute un rollback destination de migration qui retire uniquement les acces bibliotheques ajoutes par la campagne, conserve les comptes et synchronise le provider.
- Ajoute les mappings multiples de bibliotheques en migration, avec surcharges par utilisateur et prise en charge dans les brouillons, l execution et l import de plans.
- Planifie automatiquement l'envoi des identifiants Jellyfin generes pendant les migrations via un template Communications actif de creation utilisateur Jellyfin.
- Ajoute des strategies de mot de passe Jellyfin pour les migrations: generation automatique, mot de passe temporaire defini par l'admin et conservation des comptes existants quand possible.
- Uniformise l'affichage des schedules des taches en humanisant les cron horaires avec minute fixe, listes regulieres de minutes et offsets horaires.
- Corrige plusieurs points de securite/authentification: lecture du trust proxy au demarrage, comparaison CSRF en temps constant, validation TOTP robuste aux secrets invalides et rotation de session lors de la creation admin via wizard.
- Envoie une alerte email admin lorsqu'un verrouillage anti-bruteforce est declenche sur la connexion, avec cooldown par IP/email.
- Ajoute des tests unitaires pour l'authentification SMTP mot de passe/OAuth2, le format XOAUTH2, le dechiffrement du token et la readiness email.
- Ajoute l'authentification SMTP OAuth2/XOAUTH2 avec token chiffre, choix du mode d'authentification dans Communications et support dans le wizard.
- Sépare l email de connexion admin de l email de contact applicatif, ajoute un panneau sécurité dédié pour modifier login/mot de passe, et active la double authentification TOTP dans les settings et le wizard.
- Extrait les regles pures de planification/retry dans `core.tasks.scheduler_rules` et retire `croniter` des imports globaux de `tasks_engine.py`.
- Exclut les dossiers et fichiers non runtime (`tools/`, `tests/`, documentation, screenshots, caches et helpers locaux) des ignores Docker/Git, et retire la copie de `tools/` de l'image Docker.
- Centralise les connexions SQLite internes non-DBManager avec `open_sqlite_connection` pour appliquer les memes PRAGMA, `row_factory` et timeouts sur le bootstrap, la configuration, les logs, la restauration et la suppression serveur.
- Ajoute `tools/validate_db_access_unification.py` pour proteger cette unification et documenter les exceptions SQLite directes reservees aux bases externes ou aux helpers de typage.




