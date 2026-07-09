# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines sont documentes dans
`changelog.md`.

Derniere mise a jour: 2026-07-07

## Principes de suivi

- Garder ici seulement les sujets encore utiles a traiter.
- Retirer une ligne quand elle est terminee et la tracer dans `changelog.md`.
- Prioriser les gains qui servent a la fois l'administration actuelle et la
  future partie utilisateur exposee sur internet.
- Eviter les gros changements non valides sur la vraie base sans test terrain.

## P0 - Stabilisation et validation terrain

- [~] Valider sur une instance reelle le cycle Plex complet: invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.
- [~] Valider et renforcer la protection contre les pertes de donnees Plex sur
  instance reelle. Les garde-fous existent, il reste la validation terrain.
- [~] Valider les campagnes Migrations sur de grandes instances reelles Plex et
  Jellyfin avant d'activer davantage d'automatisations destructives.
-[ ] ajouter une case Remember this device for 30 days dans les settings au niveau du 2fa pour eviter de l'avoir trop souvent en local uniquement.

## P1 - Performance UI et experience percue

### Scripts par page

- [~] Continuer a deplacer les scripts inline vers `static/js/pages/*.js`.
  - Deja fait: helpers globaux datepicker/CSRF dans `static/js/app.js`.
  - Deja fait: Tasks dans `static/js/pages/tasks.js`.
  - Deja fait: Logs dans `static/js/pages/logs.js`.
  - Deja fait: Backup restore/auto-refresh dans `static/js/pages/backup.js`.
  - Deja fait: Backup list actions dans `static/js/pages/backup.js`.
  - Deja fait: Dashboard card navigation dans `static/js/pages/dashboard.js`.
  - Deja fait: Login dans `static/js/pages/login.js`.
  - Deja fait: Setup Wizard dans `static/js/pages/setup-wizard.js`.
  - Deja fait: Settings modales securite/telemetrie dans `static/js/pages/settings.js`.
  - Deja fait: Communications campaigns dans `static/js/pages/communications-campaigns.js`.
  - Deja fait: Communications history dans `static/js/pages/communications-history.js`.
  - Deja fait: Communications configuration dans `static/js/pages/communications-configuration.js`.
  - Deja fait: Communications templates dans `static/js/pages/communications-templates.js`.
  - Deja fait: Subscriptions gifts dans `static/js/pages/subscriptions-gifts.js`.
  - Deja fait: Migrations list/detail dans `static/js/pages/migrations.js` et `static/js/pages/migration-campaign-detail.js`.
  - Deja fait: Monitoring shell search/ticker dans `static/js/pages/monitoring.js`.
  - Deja fait: Monitoring user detail IP lookup dans `static/js/pages/monitoring-user-detail.js`.
  - Deja fait: Monitoring user detail profile charts dans `static/js/pages/monitoring-user-detail.js`.
  - Deja fait: Monitoring activity charts dans `static/js/pages/monitoring-activity.js`.
  - Deja fait: Monitoring servers charts dans `static/js/pages/monitoring-servers.js`.
  - Deja fait: Monitoring policies charts/modals dans `static/js/pages/monitoring-policies.js`.
  - Restant: extraire progressivement les scripts metier lourds des pages
    users, monitoring, communications, subscriptions et migrations.

### Fragments et chargement progressif

- [ ] Decouper les gros templates/pages en fragments HTMX ou endpoints JSON
  charges a la demande.
  - Cibles prioritaires: `templates/users/users.html`,
    `templates/monitoring/tabs/policies.html`,
    `templates/users/partials/_user_general.html`,
    `templates/subscriptions/_templates_editor.html`,
    `templates/users/partials/_user_servers.html`,
    `templates/communications/communications_templates.html`,
    `templates/subscriptions/_policies.html`,
    `templates/monitoring/user_detail.html`,
    `templates/migrations/campaign_detail.html`.
  - Exemple User detail: general visible, servers/history/referrals/actions
    charges au clic.
  - Exemple Communications: templates/campaigns/history/config en fragments
    separes.

- [ ] Ajouter des endpoints fragmentaires pour les widgets dashboard.
  - Rendre le dashboard initial rapidement avec skeletons.
  - Charger now playing, stats, top users, top media et quote/cache via HTMX ou
    fetch.
  - Ajouter un timeout/fallback par widget pour qu'une aggregation lente ne
    bloque pas toute la page.
  - Deja fait: Now Playing et Next Tasks utilisent des endpoints partiels avec skeleton au rendu initial.

### Listes et layout stable

- [ ] Virtualiser ou paginer davantage les listes denses.
  - Garder pagination serveur partout ou une table peut depasser 50-100 lignes.
  - Ajouter mode dense + pagination configurable 20/50/100 sur les listes admin
    repetitives.
  - Eviter d'injecter toutes les modales/actions par ligne; charger la modale au
    clic.

- [ ] Ajouter des skeletons et placeholders stables sur dashboard, monitoring et
  users detail.
  - Conserver dimensions fixes pour cards, tableaux et images.
  - Eviter que les boutons/actions changent la hauteur de ligne apres chargement.

## P2 - Monitoring, donnees et backend visible dans l'UI

- [ ] Materialiser certains agregats monitoring pour les grosses instances.
  - Creer une table `monitoring_daily_stats` alimentee par tache.
  - Pre-calculer par jour: sessions, watch_ms, users actifs, top media/user
    approximatifs.
  - Faire lire le dashboard dans une table compacte au lieu de scanner
    `media_session_history`.

- [ ] Evaluer des index supplementaires apres `EXPLAIN QUERY PLAN` sur vraie DB.
  - `vodum_users(username COLLATE NOCASE)` ou index expression `LOWER(username)`.
  - `vodum_users(email COLLATE NOCASE)` si recherche email frequente.
  - `user_referrals(status, start_at)` pour l'onglet referrals.

- [ ] Ajouter un dashboard avance oriente exploitation: etat global, files de
  jobs, echecs recents, sante providers et indicateurs d'action. ( a voir si interessant et/ou comment l'integrer a l'actuel)

## P3 - Architecture, routes et refactor

- [~] Reduire les dependances globales entre routes, taches et providers.
- [~] Deplacer la logique provider restante des routes/templates vers les
  services et les taches.
- [~] Continuer le decoupage de `tasks_engine.py`: file d'attente dedupliquee,
  execution sequentielle et regles pures de planification sont deja extraites;
  le fichier reste encore trop volumineux.
- [~] Decouper les fichiers de plus de 1000 lignes. Restent notamment
  `db_bootstrap.py`, `monitoring_overview.py`, `stream_enforcer.py`,
  `tasks_engine.py`, `sync_plex.py`, `apply_plex_access_updates.py`,
  `users_detail.py` et `core/monitoring/collector.py`.
- [~] Continuer la separation routes / services / providers, surtout sur les
  routes les plus longues: monitoring, users, communications, subscriptions,
  migrations, setup wizard et servers.
- [~] Uniformiser les acces DB applicatifs restants. Les connexions SQLite
  internes de bootstrap, config, logs, restauration et suppression serveur sont
  deja centralisees via `open_sqlite_connection`.
- [~] Supprimer le code mort apres une passe outillee dediee.

### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>`: proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## P4 - Migrations et providers

- [ ] Formaliser un registre de capacites migrations par provider avant
  d'ajouter d'autres providers. Le registre providers actuel couvre surtout le
  monitoring/enforcement Plex/Jellyfin.
- [ ] Completer le support Jellyfin sur les ecarts restants avec Plex,
  notamment les migrations avancees, les validations terrain et les workflows
  d'administration moins courants.

## P5 - Communications

- [ ] Enrichir les notifications Discord: meilleure gestion des erreurs,
  diagnostics admin, templates/campagnes plus explicites et usages avances.
  Les retries et les logs d'erreur de base existent deja.
-[ ] controle du mecanisme de log, ajout au endroit manquant, controle du system de log en mode debug 

## P7 Revoir l'ui pour les mobile 

	## Mobile responsive UI
	- Review all pages on mobile width.
	- Keep one responsive UI, no separate mobile app/UI.

	### Global layout
	- Verify desktop sidebar remains unchanged.
	- Verify mobile menu opens/closes correctly.
	- Close mobile menu on backdrop click, Escape key, and nav click.
	- Reduce mobile padding: `p-4` mobile, `md:p-6` desktop.
	- Prevent horizontal page overflow globally.

	### Tables
	- Wrap every large table in `overflow-x-auto`.
	- Ensure tables keep readable minimum width.
	- Check Users, Monitoring, Communication History, Logs, Tasks, Servers, Libraries.

	### Buttons / actions
	- Make action button groups wrap on mobile.
	- Use `flex-wrap gap-2`.
	- Avoid fixed-width buttons that overflow.
	- Ensure forms/buttons stay tappable on iPhone.

	### Dashboard
	- Verify all cards stack correctly on mobile.
	- Force 1-column layout on mobile.
	- Keep multi-column layout only on `md`, `lg`, or `xl`.
	- Check Now Playing, Users, Tasks, Servers, Latest logs, Usage Risk.

	### Forms
	- Inputs/selects/textareas must use full width on mobile.
	- Multi-column forms should become one column on mobile.
	- Check Settings, Servers, Users edit, Communications.

	### Modals
	- Modals must fit mobile screen.
	- Add max height and internal scroll if needed.
	- Avoid modals wider than viewport.

	### Text / badges
	- Long usernames, emails, server names, IPs must wrap or truncate.
	- Badges should wrap instead of overflowing.
	- Check Now Playing and user detail pages.

	### Mobile priority pages
	1. Dashboard
	2. Users list
	3. User detail
	4. Monitoring / Now Playing
	5. Communication History
	6. Settings
	7. Servers
	8. Logs / Tasks

	### Rule
	- Do not change backend logic, routes, translations, permissions, or database schema.
	- Desktop UI must stay visually unchanged.

## P8 - Partie utilisateur et ouverture externe

- [ ] Permettre au compte admin de se connecter via un compte Plex.
- [ ] Creer un acces web utilisateur configurable depuis un nouveau menu admin.
  - Login possible via compte admin, Plex, Jellyfin ou email standard selon les
    cas.
  - Le user a acces a son profil, son abonnement, les infos liees au compte et le monitoring le concernant.
  - Gestion des roles et autorisations utilisateur: admin, user, autres eventuel?
  - Configuration domaine / lien d'acces.
  - Regles d'acces, mot de passe, double acceptation et zone support.
- [ ] Ajouter toutes les possibilites manquantes de Plex et Jellyfin, notamment l edition profil comme sur Plex ou Jellyfin.
- [ ] Ajouter un mecanisme de paiement ou un lien de paiement sur les profils
  utilisateurs.
- [ ] Ajouter une API publique apres cadrage: quoi exposer, pourquoi, securite,
  quotas et authentification.
- [ ] amelioration de la creation user / mail d'invitation sur le web user vodum pour gestion / creation automatique ou controlé, aidé de compte user sur plex & jellyfin / lien fourni au user pour telecharger le lecteur media et le configurer, etc....

## Notes de prudence

- Ne pas supprimer le cache artwork existant: il est utile et deja raccorde aux
  headers HTTP.
- Ne pas remplacer `sync` par `revoke` partout cote provider: Plex a
  volontairement un garde-fou contre sync vide.
- Les optimisations SQL doivent etre validees avec la vraie base et
  `EXPLAIN QUERY PLAN`; ajouter trop d'index peut ralentir les ecritures et le
  bootstrap.
- Les modifications de fichiers contenant du texte corrige doivent rester
  ciblees pour eviter de recreer du mojibake.
