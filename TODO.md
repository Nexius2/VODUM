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

- [x] Deplacer les scripts metier inline vers `static/js/pages/*.js`.
  Les extractions deja terminees sont tracees dans `changelog.md`.
  - Deja fait: extraction des scripts de filtres Users, bulk Referrals et modal Create User vers `static/js/pages/users.js`.
  - Deja fait: extraction des confirmations Applications/Templates et resume des plans Subscriptions vers `static/js/pages/subscriptions.js`.
  - Deja fait: extraction de la synchronisation Settings/expiry Subscriptions vers `static/js/pages/subscriptions.js`.
  - Deja fait: extraction des scripts Servers detail/libraries, Settings notifications et Backup Tautulli vers les JS de page.
  - Deja fait: nettoyage du handler dashboard Now Playing, sorti des blocs title/header et centralise dans `static/js/pages/dashboard.js`.
  - Deja fait: centralisation du debounce des formulaires Users/Plex dans `static/js/app.js`.
  - Deja fait: centralisation de l ordre des notifications User detail dans `static/js/app.js`.
  - Deja fait: extraction de la synchronisation expiration/abonnement a vie, du selecteur de parrain et du changement de mot de passe Jellyfin du detail User vers `static/js/pages/user-detail.js`.
  - Deja fait: centralisation des panneaux repliables Plex/Jellyfin/emails du detail User dans `static/js/pages/user-detail.js`.
  - Deja fait: correction des identifiants JavaScript de l'editeur Subscriptions qui incorporaient a tort des traductions.
  - Deja fait: extraction des filtres, pagination et suppression groupee de la table Policies vers `static/js/pages/subscriptions.js`.
  - Deja fait: extraction de la fusion User et de sa previsualisation vers `static/js/pages/user-detail.js`.
  - Deja fait: extraction de l'editeur de templates Subscriptions vers `static/js/pages/subscriptions-template-editor.js`.
  - Les balises script restantes dans les templates ne contiennent que des
    configurations JSON ou chargent des fichiers JavaScript statiques.

### Fragments et chargement progressif

- [x] Decouper les gros templates/pages en fragments HTMX ou endpoints JSON
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
  - Deja fait: la route User detail ne charge plus les historiques, bibliotheques, fusions, parrainages, risque et comptes media enrichis des onglets non affiches.
  - Exemple Communications: templates/campaigns/history/config en fragments
    separes.

- [x] Ajouter des endpoints fragmentaires pour les widgets dashboard.
  - Deja fait: Now Playing et Next Tasks utilisent des endpoints partiels avec skeleton au rendu initial.
  - Deja fait: Now Playing et Next Tasks ont un timeout de 8 secondes et un fallback stable en cas d'erreur.
  - Deja fait: streams coupes et resume des abonnements sont charges dans un fragment independant avec skeleton, timeout et fallback.
  - Deja fait: Usage Risk et sa tendance sont calcules dans un fragment independant apres le rendu initial.
  - Deja fait: liste multi-serveurs et pics de streams sur 7 jours sont charges dans un fragment independant.
  - Les agregations couteuses visibles (lecture en cours/quote, taches, abonnements,
    risque et serveurs) sont isolees; les compteurs et logs legers restent dans le
    rendu initial afin d'eviter des requetes HTTP sans benefice mesurable.
  - Chaque widget asynchrone a un timeout et un fallback stable.

### Listes et layout stable

- [x] Virtualiser ou paginer davantage les listes denses.
  - Garder pagination serveur partout ou une table peut depasser 50-100 lignes.
  - Ajouter mode dense + pagination configurable 20/50/100 sur les listes admin
    repetitives.
  - Eviter d'injecter toutes les modales/actions par ligne; charger la modale au
    clic.
  - Deja fait: listes Users et Referrals paginees cote serveur avec taille configurable 20/50/100 et conservation dans les liens de pagination.
  - Deja fait: historique Monitoring Policies configurable a 20/50/100 lignes avec pagination serveur.
  - Deja fait: historique Communications configurable a 20/50/100 lignes en conservant tri et filtre de type.
  - Deja fait: Subscriptions charge utilisateurs, cadeaux, templates, serveurs et reglages uniquement pour l'onglet consommateur; Applications configurable a 20/50/100.
  - Deja fait: liste Communications Templates paginee cote serveur a 20/50/100 en conservant la langue d'edition.
  - Deja fait: utilisateurs du detail de campagne Migration limites a 20/50/100 lignes rendues, avec compteurs globaux conserves.
  - Deja fait: sujet, corps et metadata des communications envoyees sont charges au clic au lieu d'etre injectes dans chaque ligne.
  - Deja fait: snapshots complets des enforcements Monitoring Policies charges au clic au lieu d'etre injectes dans la table principale.

- [x] Ajouter des skeletons et placeholders stables sur dashboard, monitoring et
  users detail.
  - Conserver dimensions fixes pour cards, tableaux et images.
  - Eviter que les boutons/actions changent la hauteur de ligne apres chargement.
  - Deja fait: skeletons stables pour tous les widgets dashboard fragmentes, y compris Usage Risk, et pour l'iframe Monitoring du detail User avec fallback temporise.

## P2 - Monitoring, donnees et backend visible dans l'UI

- [x] Materialiser certains agregats monitoring pour les grosses instances.
  - Table reconstructible `monitoring_daily_stats` alimentee quotidiennement.
  - Sessions, watch_ms, utilisateurs distincts et tops media/user approximatifs
    sont precalcules sur 31 jours.
  - L'overview Monitoring lit les lignes compactes quand la fenetre est complete
    et conserve la requete historique comme fallback pendant le backfill.

- [x] Evaluer des index supplementaires avec `EXPLAIN QUERY PLAN`.
  - Les index `username`/`email` ne sont pas ajoutes: la recherche multi-colonnes
    utilise volontairement un `LIKE '%terme%'`, incompatible avec leur usage par
    SQLite, et le tri Users reste domine par les priorites/agregations.
  - Ajout de `user_referrals(status, start_at DESC, id DESC)`: le plan confirme
    son usage et la disparition du tri temporaire pour les vues filtrees.
  - Un validateur reproductible conserve ces hypotheses de plan dans le depot.

## P3 - Architecture, routes et refactor

- [x] Premier lot: supprimer le helper mort d'acces serveurs/bibliotheques qui
  etait reste imbrique dans la route dashboard, ainsi que ses constantes SQL.
  - Les constructeurs de donnees des widgets ont aussi ete extraits vers
    `core/dashboard_widgets.py`; la route conserve uniquement l'orchestration HTTP.

- [~] Reduire les dependances globales entre routes, taches et providers.
- [~] Deplacer la logique provider restante des routes/templates vers les
  services et les taches.
  - Deja fait P3: selection du compte Plex prefere et orchestration des resyncs
    Plex/Jellyfin extraites de `users_actions.py` vers `core/user_sync_jobs.py`;
    duplication correspondante supprimee de `servers.py`.
- [x] Decouper `tasks_engine.py`: l'orchestrateur est passe sous 1000 lignes;
  file, execution, sequences, auto-activation, configuration et cycle de vie du
  scheduler sont maintenant isoles dans `core/tasks/`.
  - Deja fait P3: validation pure des retours/timeout extraite dans
    `core/tasks/result_validation.py`, couverte par tests unitaires.
  - Deja fait P3: signaux concurrents d'execution forcee et d'auto-configuration
    extraits dans `core/tasks/runtime_signals.py`, avec semantique consume-once testee.
  - Deja fait P3: normalisation des valeurs DB et decisions de retry/occupation/echeance
    extraites dans `core/tasks/scheduler_rules.py`, avec tests des cas limites.
  - Deja fait P3: file FIFO des sequences extraite dans
    `core/tasks/sequence_queue.py`, avec propriete de worker unique testee en concurrence.
  - Deja fait P3: attribution du worker principal extraite dans
    `core/tasks/worker_lease.py`, sans verrou ni booleen global dans l'orchestrateur.
  - Deja fait P3: orchestration FIFO des sequences, attente bloquante et choix
    discovery Plex/Jellyfin extraits dans `core/tasks/sequences.py` et testes.
  - Deja fait P3: premieres regles pures d'auto-activation extraites dans
    `core/tasks/auto_enable_rules.py` avec normalisation defensive des compteurs.
  - Deja fait P3: orchestration complete de l'auto-activation extraite dans
    `core/tasks/auto_enable.py`; les fonctions historiques sont desormais des facades.
  - Deja fait P3: cycle complet d'execution d'une tache extrait dans
    `core/tasks/execution.py` avec transitions, validation, retries et failsafe testes.
  - Deja fait P3: tick scheduler (retries, bootstrap, echeances et next_run)
    extrait dans `core/tasks/scheduler.py`, independant de la boucle de sommeil.
- [~] Decouper les fichiers de plus de 1000 lignes. Restent notamment
  `db_bootstrap.py`, `monitoring_overview.py` et `stream_enforcer.py`.
  - Deja fait P3: schema des politiques et enforcements de streaming extrait
    de `db_bootstrap.py` vers `core/db_bootstrap_streams.py`, avec creation
    idempotente testee sur SQLite.
  - Deja fait P3: tables techniques des imports Tautulli et du stockage
    Monitoring extraites vers `core/db_bootstrap_monitoring.py`, avec
    migrations de colonnes et index testees sur SQLite.
  - Deja fait P3: fondations SQLite des campagnes de migration extraites vers
    `core/db_bootstrap_migrations.py`; tables, colonnes et index sont testes
    de maniere idempotente.
  - Deja fait P3: migration des taches cron vers le mode intervalle extraite
    vers `core/db_bootstrap_tasks.py`, avec frequences des workers et
    idempotence testees.
  - Deja fait P3: validation des tables principales, colonnes serveurs/comptes
    media et reglages applicatifs extraite vers `core/db_bootstrap_core.py`.
  - Deja fait P3: historique des recommandations Usage Risk extrait vers
    `core/db_bootstrap_usage_risk.py`, avec schema et index testes sur SQLite.
  - Deja fait P3: reglages, table principale et migration des anciens statuts
    de parrainage extraits vers `core/db_bootstrap_referrals.py`.
  - Deja fait P3: journal des evenements de parrainage extrait vers
    `core/db_bootstrap_referral_events.py`, avec creation idempotente testee.
  - Deja fait P3: reconstruction des anciens statuts et colonnes de profil des
    utilisateurs extraite vers `core/db_bootstrap_users.py`, avec conservation
    des donnees testee.
  - Deja fait P3: schema et amorcage unique des modeles d'abonnement extraits
    vers `core/db_bootstrap_subscriptions.py`; une suppression admin reste
    respectee aux demarrages suivants.
  - Deja fait P3: colonnes obligatoires Tasks/Settings et protection
    anti-bruteforce extraites vers `core/db_bootstrap_settings.py`, avec
    valeurs par defaut et index testes.
  - Deja fait P3: collecte et persistance des statistiques CPU/RAM serveur
    extraites de `core/monitoring/collector.py` vers
    `core/monitoring/resource_stats.py`, avec parsing Plex teste.
  - Deja fait P3: politiques actives, historique de notifications, snapshots
    d'abonnement et contexte profil/parrainage extraits de `users_detail.py`,
    qui repasse sous 1000 lignes.
  - Deja fait P3: resolution robuste et synchronisation des identites Plex
    extraites de `apply_plex_access_updates.py` vers
    `core/plex_access_identity.py`.
  - Deja fait P3: nettoyage des jobs, selection du compte media et lecture des
    options de partage extraits vers `core/plex_access_jobs.py`.
  - Deja fait P3: diagnostics HTTP Plex extraits vers
    `core/plex_access_runtime.py`; les anciens helpers de pilotage inutilises
    ont ete supprimes et `apply_plex_access_updates.py` repasse sous 1000 lignes.
  - Deja fait P3: mode d'import Plex extrait vers `core/plex_sync_config.py`,
    detection d'invitation mutualisee et anciens helpers inutilises supprimes
    de `sync_plex.py`.
  - Deja fait P3: client XML Plex.tv (compte admin, users et shared servers)
    extrait de `sync_plex.py` vers `core/plex_sync_api.py`.
  - Deja fait P3: orchestration globale des serveurs, bibliotheques et acces
    extraite vers `core/plex_sync_orchestrator.py`.
  - Deja fait P3: comptage des sections et application des diffs d'acces aux
    bibliotheques extraits vers `core/plex_library_access.py`.
  - Deja fait P3: rapprochement et upsert du proprietaire de chaque serveur
    Plex extraits vers `core/plex_owner_sync.py`.
  - Deja fait P3: decouverte, reconciliation et nettoyage des bibliotheques
    extraits vers `core/plex_library_sync.py`; `sync_plex.py` repasse sous
    1000 lignes.
- [~] Continuer la separation routes / services / providers, surtout sur les
  routes les plus longues: monitoring, users, communications, subscriptions,
  migrations, setup wizard et servers.
  - Deja fait P3: contrat de pagination (normalisation, bornes, offsets et liens)
    extrait dans `web/pagination.py`; routes Users et Servers migrees.
  - Deja fait P3: resolution et presentation des politiques actives du detail
    User extraites de la route vers `core/user_active_policies.py`.
  - Deja fait P3: pagination, tri et libelles de l'historique de notifications
    du detail User extraits vers `core/user_notification_history.py`.
  - Deja fait P3: application et nettoyage des snapshots de templates
    d'abonnement extraits du detail User vers
    `core/user_subscription_snapshots.py`.
  - Deja fait P3: verrou d'expiration, alias media, donnees de parrainage,
    normalisation des dates et enrichissement des serveurs extraits vers
    `core/user_profile_context.py`.
  - Deja fait P3: lecture et application des statistiques CPU/RAM extraites de
    `monitoring_overview.py` vers le service Monitoring existant.
  - Deja fait P3: endpoints JSON de detail et d'historique des enforcements
    extraits vers `routes/monitoring_enforcements.py`.
  - Deja fait P3: contexte serveurs partage et donnees Now Playing extraits
    vers `core/monitoring/overview_servers.py` et `overview_live.py`.
  - Deja fait P3: activite recente et contexte Usage Risk extraits vers
    `core/monitoring/overview_activity.py` et `overview_usage_risk.py`.
  - Deja fait P3: parametres, tri, formatage et pagination de l'onglet Users
    Monitoring extraits vers `core/monitoring/overview_users.py`.
  - Deja fait P3: comptage filtre de l'onglet Users Monitoring extrait vers
    `core/monitoring/overview_users.py`.
  - Deja fait P3: requete agregee et formatage de la liste Users Monitoring
    extraits vers `core/monitoring/overview_users.py`.
  - Deja fait P3: normalisation et bornage de la pagination des enforcements
    Policies extraits vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: catalogue, decodage JSON et compteurs des policies extraits
    vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: statistiques du dashboard Policies et fenetres 24 h/7 jours
    extraites vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: repartitions scopes, providers et regles Policies extraites
    vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: classement des utilisateurs touches par les enforcements
    extrait vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: liste paginee des enforcements recents extraite vers
    `core/monitoring/overview_policies.py`.
  - Deja fait P3: regroupement des enforcements par acteur et etat des sessions
    suivies extraits vers `core/monitoring/overview_policies.py`.
  - Deja fait P3: chronologie completee warn/kill sur 30 jours extraite vers
    `core/monitoring/overview_policies.py`; onglet Policies decouple.
  - Deja fait P3: filtres, tri, requetes, formatage et pagination de l'onglet
    History extraits vers `core/monitoring/overview_history.py`.
  - Deja fait P3: parametres, tri et pagination de l'onglet Libraries extraits
    vers `core/monitoring/overview_libraries.py`.
  - Deja fait P3: table agregee Libraries, acces utilisateurs et durees jouees
    extraits vers `core/monitoring/overview_libraries.py`.
  - Deja fait P3: liste des utilisateurs du filtre Libraries extraite vers
    `core/monitoring/overview_libraries.py`.
  - Deja fait P3: construction des filtres de periode/utilisateur du classement
    Libraries extraite vers `core/monitoring/overview_libraries.py`.
  - Deja fait P3: classement Top played Libraries et enrichissement des visuels
    extraits vers `core/monitoring/overview_libraries.py`.
  - Deja fait P3: statistiques combinees, details, series temporelles et
    classements de l'onglet Servers extraits vers
    `core/monitoring/overview_servers.py`; `monitoring_overview.py` ne conserve
    plus que l'orchestration HTTP et repasse largement sous 1000 lignes.
- [~] Uniformiser les acces DB applicatifs restants. Les connexions SQLite
  internes de bootstrap, config, logs, restauration et suppression serveur sont
  deja centralisees via `open_sqlite_connection`.
  - Deja fait P3: validation et lecture des imports Tautulli/Backup migrees vers
    la factory commune en lecture seule; un validateur interdit desormais tout
    nouvel appel direct a `sqlite3.connect` hors de `db_manager.py`.
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

## P6 - Logs, erreurs et diagnostic

- [x] Auditer de bout en bout la couverture des erreurs et completer les logs
  manquants dans les routes, services, providers, taches et workers.
  - Inventorier les blocs `except` qui avalent une exception, retournent un
    fallback ou affichent seulement un `flash` sans journaliser la cause.
  - Deja fait P6: audit AST reproductible `tools/audit_exception_logging.py`
    pour inventorier les handlers silencieux sans imposer de logs aux fallbacks legitimes.
  - Journaliser les erreurs inattendues avec `exc_info=True`, une source stable
    et le contexte utile (operation, provider, serveur, tache ou identifiant),
    sans exposer token, mot de passe ni donnee personnelle sensible.
  - Distinguer les erreurs attendues/metier des incidents techniques afin de ne
    pas transformer la page Logs en bruit inutilisable.
  - Deja fait P6: premier lot de chemins UI qui affichaient seulement une erreur
    a l'admin maintenant journalises avec traceback: backup/restore, campagnes
    et retries Communications, test Discord et application groupee Subscriptions.
  - Deja fait P6: echecs de demarrage des workers d'acces Plex/Jellyfin et panne
    du provider de geolocalisation Monitoring journalises avec contexte minimal.
  - Deja fait P6: lot large Users/Servers/Migrations/Tasks couvrant les workers
    non demarres, les echecs d'import/export et la persistance d'erreur secondaire.
  - Verifier les points d'entree globaux Flask, threads, scheduler et jobs pour
    qu'une exception non geree soit toujours capturee et visible.
  - Deja fait P6: les exceptions Flask non gerees et celles qui s'echappent des
    threads Python sont journalisees avec traceback et contexte requete/thread.
- [x] Verifier que la page Logs restitue bien toutes les erreurs applicatives.
  - Controler la chaine complete `get_logger` / `add_log` / fichier `app.log` /
    rotation / lecture et filtres de `/logs`.
  - Verifier que les erreurs des fichiers rotates restent consultables ou
    telechargeables selon une retention explicite.
  - Ajouter des filtres/compteurs utiles pour ERROR et CRITICAL et signaler
    clairement une erreur de lecture ou de parsing des logs.
  - Deja fait P6: le filtre initial de `/logs` est maintenant `ALL`; l'ancien
    defaut `INFO` masquait exactement les WARNING, ERROR et CRITICAL. Le niveau
    CRITICAL est aussi selectionnable explicitement.
  - Deja fait P6: compteurs cliquables ALL, WARNING, ERROR et CRITICAL calcules
    sur toute la retention, independamment de la page courante.
  - Tester les erreurs multilignes et tracebacks: elles doivent rester rattachees
    a leur evenement au lieu d'apparaitre comme de fausses lignes INFO.
  - Deja fait P6: `/logs` et son telechargement lisent maintenant `app.log` et
    les cinq rotations dans l'ordre chronologique; les tracebacks multilignes
    restent rattaches a leur evenement et donc a son niveau ERROR/CRITICAL.
  - Deja fait P6: une erreur de lecture d'un fichier actif/rotate est affichee
    dans la page au lieu de produire silencieusement une liste incomplete.
- [x] Valider le systeme de logs en modes normal et debug.
  - Confirmer les niveaux effectivement captures, affiches et filtres dans les
    deux modes, ainsi que l'absence de doublons.
  - Tester l'anonymisation du fichier telecharge et l'absence de secrets dans
    les messages, details et tracebacks.
  - Deja fait P6: le telechargement force l'anonymisation meme lorsque le mode
    debug est actif, avec test de non-regression email/token/IP.
  - Ajouter un audit reproductible et des tests de non-regression pour les
    chemins critiques et les gestionnaires d'erreurs globaux.
  - Deja fait P6: handler fichier et filtre d'anonymisation rendus idempotents;
    tests des modes normal/debug, absence de doublons, export force et hooks globaux.

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
