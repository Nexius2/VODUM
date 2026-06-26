# VODUM - TODO

Ce fichier ne contient que le travail restant. Les changements termines sont
documentes dans `changelog.md`.

## Priorite haute

- [~] Valider sur une instance reelle le cycle Plex complet : invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.
- [~] Valider les campagnes Migrations sur de grandes instances reelles Plex et
  Jellyfin avant d'activer davantage d'automatisations destructives.

## Migrations

- [ ] Formaliser un registre de capacites migrations par provider avant
  d'ajouter d'autres providers. Le registre providers actuel couvre surtout le
  monitoring/enforcement Plex/Jellyfin.

## Architecture et routes

- [~] Reduire les dependances globales entre routes, taches et providers.
- [~] Deplacer la logique provider restante des routes/templates vers les
  services et les taches.
- [~] Continuer le decoupage de `tasks_engine.py` : file d'attente dedupliquee,
  execution sequentielle et regles pures de planification sont deja extraites;
  le fichier reste encore trop volumineux.

### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>` : proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## Monitoring et donnees

- [~] Valider et renforcer la protection contre les pertes de donnees Plex sur
  instance reelle. Les garde-fous existent, il reste la validation terrain.

## Communications

- [ ] Enrichir les notifications Discord : meilleure gestion des erreurs,
  diagnostics admin, templates/campagnes plus explicites et eventuels usages
  avances. Les retries et les logs d'erreur de base existent deja.

## UI, configuration et automatisation

- [ ] Ajouter un dashboard avance oriente exploitation : etat global, files de
  jobs, echecs recents, sante providers et indicateurs d'action.

## Refactor

- [~] Decouper les fichiers de plus de 1000 lignes. Restent notamment
  `db_bootstrap.py`, `monitoring_overview.py`, `stream_enforcer.py`,
  `tasks_engine.py`, `sync_plex.py`, `apply_plex_access_updates.py`,
  `users_detail.py` et `core/monitoring/collector.py`.
- [~] Continuer la separation routes / services / providers, surtout sur les
  routes les plus longues : monitoring, users, communications, subscriptions,
  migrations, setup wizard et servers.
- [~] Uniformiser les acces DB applicatifs restants. Les connexions SQLite
  internes de bootstrap, config, logs, restauration et suppression serveur sont
  deja centralisees via `open_sqlite_connection`.
- [~] Supprimer le code mort apres une passe outillee dediee.

## Futur

- [ ] Completer le support Jellyfin sur les ecarts restants avec Plex,
  notamment les migrations avancees, les validations terrain et les workflows
  d'administration moins courants.
- [ ] Permettre au compte admin de se connecter via un compte Plex.
- [ ] Creer un acces web utilisateur completement independant de l'application
  d'administration, idealement sur un port different, avec compte Plex,
  Jellyfin ou email standard selon les cas.
- [ ] Ajouter un mecanisme de paiement ou un lien de paiement sur les profils
  utilisateurs.
- [ ] Ajouter une API publique. ( a discuter, quoi, pourquoi??)
