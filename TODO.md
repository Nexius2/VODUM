# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines sont documentes dans
`changelog.md`.

Derniere mise a jour: 2026-07-15

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

## P1 - Performance UI et experience percue

### Scripts par page

- [~] Continuer a deplacer les scripts inline vers `static/js/pages/*.js`.
  Les extractions deja terminees sont tracees dans `changelog.md`.
  - Deja fait: extraction des scripts de filtres Users, bulk Referrals et modal Create User vers `static/js/pages/users.js`.
  - Deja fait: extraction des confirmations Applications/Templates et resume des plans Subscriptions vers `static/js/pages/subscriptions.js`.
  - Deja fait: extraction de la synchronisation Settings/expiry Subscriptions vers `static/js/pages/subscriptions.js`.
  - Deja fait: extraction des scripts Servers detail/libraries, Settings notifications et Backup Tautulli vers les JS de page.
  - Deja fait: nettoyage du handler dashboard Now Playing, sorti des blocs title/header et centralise dans `static/js/pages/dashboard.js`.
  - Deja fait: centralisation du debounce des formulaires Users/Plex dans `static/js/app.js`.
  - Deja fait: centralisation de l ordre des notifications User detail dans `static/js/app.js`.
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

- [~] Ajouter des endpoints fragmentaires pour les widgets dashboard.
  - Deja fait: Now Playing et Next Tasks utilisent des endpoints partiels avec skeleton au rendu initial.
  - Restant: charger stats, top users, top media et quote/cache via HTMX ou fetch.
  - Ajouter un timeout/fallback par widget pour qu'une aggregation lente ne bloque pas toute la page.

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

## P7 - Revoir l'UI mobile

	## Mobile responsive UI
	- Review all pages on mobile width.
	- Keep one responsive UI, no separate mobile app/UI.

	### Global layout
	- Verify desktop sidebar remains unchanged.
	- Deja fait: menu mobile avec fermeture backdrop, Escape et navigation.
	- Deja fait: padding principal `p-4` mobile, `md:p-6` desktop.
	- Deja fait: premiere passe large effectuee sur Dashboard, Monitoring, Users, Servers, Logs, Communications et Subscriptions.
	- Restant: validation terrain mobile sur l'UI reelle et corrections ponctuelles.

	### Tables
	- Deja fait: filet global mobile pour encapsuler les tableaux non proteges dans un scroll horizontal, y compris les fragments HTMX.
	- Deja fait: tableaux non proteges encapsules automatiquement en scroll horizontal mobile; listes Logs/Communications/Monitoring/Subscriptions controlees cote code.
	- Restant: validation terrain mobile des tableaux longs sur donnees reelles.

	### Buttons / actions
	- Deja fait: filet global mobile pour autoriser le retour a la ligne des groupes d'actions et neutraliser les largeurs fixes hors tableaux.
	- Deja fait: barres d'actions Logs, Servers et footers de modales Communications/Servers passent en pile sur mobile.
	- Deja fait: actions Logs, Servers, Communications, Subscriptions et modales principales passent en pile/retour ligne sur mobile.
	- Restant: validation terrain des actions restantes sur vraie largeur mobile.

	### Dashboard
	- Deja fait: layout principal en 1 colonne mobile et carte Usage Risk empilee sur petite largeur.
	- Deja fait: Now Playing Monitoring utilise des cards fluides sans largeur minimale mobile forcee.
	- Restant: validation terrain Users, Tasks, Servers et Latest logs sur vraie largeur mobile.

	### Forms
	- Deja fait: filet global mobile pour borner inputs/selects/textareas et largeurs fixes dans les formulaires.
	- Deja fait: champs SMTP port/TLS Communications passent en 1 colonne mobile.
	- Deja fait: formulaires Communications SMTP et Subscriptions denses adaptes; filet global contre les largeurs fixes mobiles.
	- Restant: validation terrain Settings, Servers, Users edit et Communications.

	### Modals
	- Deja fait: filet global mobile pour borner largeur/hauteur des modales.
	- Deja fait: modales Communications variables/delete/duplicate et confirmation serveur adaptees mobile.
	- Deja fait: modales lourdes Communications, Servers, Subscriptions et Monitoring policies contraintes/empilees sur mobile.
	- Restant: validation terrain des modales Users et cas longs.

	### Text / badges
	- Long usernames, emails, server names, IPs must wrap or truncate.
	- Badges should wrap instead of overflowing.
	- Deja fait: graphiques du detail Monitoring User empiles sur mobile et stats principales en 1 colonne si necessaire.
	- Deja fait: grilles label/valeur Users/User detail et actions de merge/referrer passent en pile sur mobile.
	- Deja fait: petites grilles Monitoring Usage Risk et Subscriptions templates/gifts relachees sur mobile.
	- Restant: verifier textes longs/badges restants sur vraie largeur mobile.

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
