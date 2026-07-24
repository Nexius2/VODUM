# Changelog

- Correction d'une régression du découpage des notifications d'expiration :
  l'alias `_safe_int` utilisé par la tâche est désormais réimporté depuis le
  service de sélection, avec un test de contrat dédié.
- Lot P3 synchronisation Jellyfin : sélection des utilisateurs techniques et
  comptage des éléments de bibliothèques déplacés dans `core/jellyfin_http.py`,
  avec conservation des fallbacks par utilisateur. `sync_jellyfin.py` repasse
  sous 1000 lignes.
- Lot P3 Subscriptions et Communications : parsing/validation des politiques et
  restauration des modèles d'abonnement déplacés vers des modules core; ranking
  et sélection des modèles Communications extraits dans
  `core/communication_template_selection.py`. `subscriptions_page.py` et
  `communications_engine.py` repassent sous 1000 lignes.
- Lot P3 Users : fusion et prévisualisation déplacées de `routes/users_list.py`
  vers `core/user_merge.py`; snapshots d'abonnement mutualisés; emails de
  bienvenue et provisionnement des comptes Plex/Jellyfin extraits du blueprint
  vers `core/user_welcome_email.py` et `core/user_provider_provisioning.py`.
  Les deux anciens fichiers Users repassent sous 1000 lignes.
- Lot P3 parallèle sur deux tâches volumineuses : validation, découverte du
  serveur et rapprochement des bibliothèques Tautulli déplacés dans
  `core/tautulli_discovery.py`, puis sélection des modèles et fenêtres
  d'expiration isolée dans `core/expiration_template_selection.py`.
  `tasks/send_expiration_emails.py` repasse sous 1000 lignes.
- Lot P3 parallèle sur les routes Migrations et Servers : sélection des
  serveurs disponibles et préparation des correspondances de bibliothèques
  déplacées dans `core/migrations/page_data.py`, puis centralisation des
  colonnes SQL et des types de bibliothèques dans `core/server_page_queries.py`.
  `routes/servers.py` repasse sous 1000 lignes.
- Nouveau lot P3 mené en parallèle sur deux routes volumineuses : calcul des
  suggestions de fusion déplacé de `routes/users_list.py` vers un module core
  testé, et suppression de la logique d'instantanés d'abonnement dupliquée dans
  `routes/subscriptions_page.py` au profit du service commun existant.
- Sixième lot P3 en deux déplacements sur `routes/communications.py` : routes
  de liste paginée et de détail de l'historique regroupées dans
  `communications_history.py`. Le fichier principal repasse sous 1000 lignes.
- Cinquième lot P3 en deux extractions sur `routes/communications.py` : lecture
  et rendu du détail d'historique déplacés dans le service de pages, puis
  préparation de la configuration avec masquage des secrets et résumé de file.
- Quatrième lot P3 en deux extractions sur `routes/communications.py` : chargement
  de la page Campagnes et chargement paginé de la page Modèles déplacés dans un
  service commun, pièces jointes et traductions comprises.
- Troisième lot P3 en deux opérations sur `routes/communications.py` : parsing
  sécurisé du formulaire de configuration extrait, puis suppression du rendu
  d'historique local devenu mort après son déplacement dans le service dédié.
- Deuxième lot P3 en deux extractions sur `routes/communications.py` : règles
  de déclenchement/délai des modèles centralisées, puis persistance commune des
  pièces jointes de campagnes et modèles avec conservation du schéma existant.
- Nouveau lot P3 en deux extractions sur `routes/communications.py` : rendu des
  messages d'historique déplacé dans un service dédié, puis isolation de la
  normalisation des clés/secrets et des traductions administrables de modèles.
- Suppression des avertissements Python sur `datetime.utcnow()` dans les deux
  écritures de présence provider Jellyfin, avec horodatage UTC conscient du
  fuseau et conservation exacte du format ISO à la seconde terminé par `Z`.
- Grande passe de non-régression après les découpages P3 : cartographie des
  fonctions et constantes historiques, parité différentielle du bootstrap,
  suite complète et audits applicatifs. Mise à jour des validateurs
  Communications, catalogue des tâches et sécurité de file afin qu'ils suivent
  les nouveaux modules plutôt que les anciens fichiers monolithiques.
  Actualisation également des fixtures des quatre phases Migrations et du
  contrôle UI/configuration pour refléter les schémas et services actuels.
- Dix-neuvième lot P3 en deux extractions sur `stream_enforcer.py` : contexte complet
  des notifications de blocage (limites, sessions, IP, appareils et variables
  traduisibles), puis mémoire de déduplication des sessions du foyer, avec les
  façades et caches historiques conservés.
- Dix-huitième lot P3 en deux extractions sur `stream_enforcer.py` : isolation
  du cache de déduplication des lectures synchronisées et du cache de grâce des
  transitions cohérentes d'IP, avec alias conservés pour la compatibilité et
  suppression des deux anciennes implémentations locales devenues mortes.
- Dix-septième lot P3 en deux extractions sur `stream_enforcer.py` : déplacement
  de l'identité et de la chronologie des endpoints dans les utilitaires de
  session, puis isolation des familles de médias et clés de transition d'IP.
- Seizième lot P3 en deux extractions sur `stream_enforcer.py` : centralisation
  des délais, fenêtres et paramètres Jellyfin, puis déplacement du diagnostic
  détaillé des sessions dans un module indépendant sans modifier les valeurs.
- Quinzième lot P3 en deux extractions sur `stream_enforcer.py` : isolation des
  règles de scope global/serveur/utilisateur et des overrides VIP, puis
  déplacement de la sélection des violations après recontrôle avec maintien de
  l'interdiction de bascule serveur pour les acteurs synthétiques.
- Quatorzième lot P3 en deux extractions sur `stream_enforcer.py` : livraison
  des notifications `stream_blocked` déplacée dans un service dédié, puis
  isolation des actions provider d'avertissement et d'arrêt avec conservation
  du fallback pour les anciennes signatures de message.
- Treizième lot P3 en deux extractions sur `stream_enforcer.py` : regroupement
  des lectures SQL de politiques, sessions, serveurs et overrides dans un
  référentiel, puis isolation du journal et de l'état persistant des actions
  d'enforcement tout en conservant les points d'appel historiques de la tâche.
- Douzième lot P3 en deux extractions sur `stream_enforcer.py` : construction
  des instantanés complets d'enforcement isolée, puis déplacement de la lecture
  des résolutions Plex/Jellyfin dans un module de métadonnées sans changer les
  formats JSON enregistrés ni les règles de détection 4K.
- Onzième lot P3 en deux extractions sur `stream_enforcer.py` : déplacement des
  utilitaires purs de politiques, acteurs, adresses et sélection de cible, puis
  isolation du pilotage du mode accéléré et de sa persistance en base.
- Dixième lot P3 en deux extractions sur `stream_enforcer.py` : traduction des
  messages de politique isolée dans un service dédié, puis déplacement des
  comparaisons de sessions, appareils, sous-réseaux et foyers probables sans
  modifier les seuils ni les fonctions internes historiques.
- Audit de non-régression du découpage P3 : ajout d'un comparateur différentiel
  ancien/nouveau bootstrap sur bases neuves et existantes. Correction associée
  du téléchargement anonymisé des logs avec les enregistrements simplifiés.
- Neuvième lot P3 de découpage du bootstrap : extraction complète du schéma et
  des migrations historiques Communications, ainsi que du catalogue
  d'amorçage des tâches. `db_bootstrap.py` repasse sous 1000 lignes.
- Huitième lot P3 de découpage du bootstrap : extraction de l'amorçage des
  modèles Communications unifiés et des anciens modèles email conservés pour
  compatibilité, sans modifier leurs contenus ni leurs délais.
- Septième lot P3 de découpage du bootstrap : extraction de l'initialisation
  des réglages de base et de la migration chiffrée des secrets Communications
  et serveurs dans deux modules indépendants.
- Sixième lot P3 de découpage du bootstrap : extraction de l'application du
  réglage CRON global et de la migration du modèle Usage Risk, avec nettoyage
  des doublons de modèles de communication strictement équivalents.
- Cinquième lot P3 de découpage du bootstrap : déplacement de l'amorçage des
  modèles d'accueil Plex/Jellyfin et de la migration versionnée des horaires de
  tâches, avec conservation des horaires personnalisés par l'administrateur.
- Quatrième lot P3 de découpage du bootstrap : extraction de la normalisation
  des anciens types de média et de la création des index applicatifs utilisés
  par les recherches, l'historique et les suppressions serveur.
- Troisième lot P3 de découpage du bootstrap : les sessions et événements
  Monitoring, ainsi que la mise à niveau de la file des jobs média et de leurs
  colonnes associées, sont déplacés dans deux modules dédiés.
- Deuxième lot P3 de découpage du bootstrap : extraction du schéma des cadeaux
  d'abonnement et du schéma d'historique Monitoring, y compris sa déduplication
  et ses agrégats quotidiens, dans deux modules dédiés et idempotents.
- Correction de la confiance 2FA locale pendant 30 jours : la page de
  connexion ne rend plus le code temporaire obligatoire lorsque le cookie de
  confiance local est encore valide.
- Nouveau lot P3 de découpage du bootstrap : le schéma des modèles d'email
  d'accueil et le schéma/migration Discord sont extraits de `db_bootstrap.py`
  dans deux modules dédiés, sans modifier leur ordre d'initialisation.
- Refactor Monitoring P3 : extraction complète des classements Libraries et
  des statistiques de l'onglet Servers hors de la route
  `monitoring_overview.py`, avec conservation des requêtes et des contrats de
  rendu existants.
- Stabilisation de la suite de tests : import tardif de l'aide DB du widget
  Now Playing et dates relatives pour la couverture des statistiques
  quotidiennes. Les fins de ligne sont désormais normalisées par
  `.gitattributes`.
- Premier découpage de `db_bootstrap.py` : création et mise à niveau des tables
  de politiques et d'enforcements de streaming déplacées dans un module dédié,
  avec test SQLite d'idempotence.
- Extraction des tables techniques Tautulli et Monitoring depuis
  `db_bootstrap.py`, avec validation SQLite des colonnes historiques et index.
- Extraction des fondations des campagnes de migration depuis
  `db_bootstrap.py` : campagnes, utilisateurs, étapes et correspondances de
  bibliothèques sont désormais initialisés par un module dédié testé.
- Migration du mode de planification des tâches extraite de
  `db_bootstrap.py`, avec validation des intervalles des workers récurrents.
- Validation et mise à niveau des tables principales extraites de
  `db_bootstrap.py`, notamment les colonnes serveur, comptes média et réglages.
- Schéma de l'historique des recommandations Usage Risk déplacé dans un module
  dédié avec contrôle SQLite de son idempotence.
- Réglages, parrainages et reconstruction de l'ancienne contrainte de statuts
  extraits de `db_bootstrap.py`, avec vérification de la conservation des
  données existantes.
- Journal des événements de parrainage extrait dans un module de bootstrap
  dédié et testé sur SQLite.
- Migration des statuts et colonnes de profil utilisateur extraite de
  `db_bootstrap.py`, avec test de reconstruction d'une ancienne table et de
  conservation des comptes.
- Schéma et amorçage initial des modèles d'abonnement extraits dans un module
  dédié ; les modèles supprimés volontairement ne sont plus recréés lors des
  initialisations suivantes.
- Colonnes obligatoires des tâches et réglages, ainsi que la table de
  protection anti-bruteforce, extraites de `db_bootstrap.py` et testées de
  manière idempotente.

## 2026-07-19 - P3 monitoring

- Optimisation du loader global de navigation : affichage differe a 180 ms,
  exclusion des interactions HTMX, fermeture defensive en fin de requete et
  suppression du flou plein ecran couteux.
- Extraction de la collecte et de la persistance des statistiques CPU/RAM
  serveur vers `core/monitoring/resource_stats.py`; le collecteur repasse sous
  1000 lignes et le parsing XML Plex est couvert par des tests unitaires.
- Extraction de la resolution et de la presentation des politiques actives du
  detail User vers `core/user_active_policies.py`, sans dependance Flask.
- Extraction de la pagination email/Discord, du tri et des libelles de
  l'historique du detail User vers `core/user_notification_history.py`.
- Extraction de l'application et du nettoyage des snapshots de templates
  d'abonnement vers `core/user_subscription_snapshots.py`.
- Extraction du contexte profil du detail User (verrou owner/admin, alias,
  parrainages, dates et options Plex) vers `core/user_profile_context.py`;
  `users_detail.py` repasse sous 1000 lignes.
- Extraction de la resolution des comptes Plex et de la synchronisation des
  identites invitees acceptees vers `core/plex_access_identity.py`.
- Extraction du nettoyage des jobs Plex, de la selection du compte media et de
  la lecture des options de partage vers `core/plex_access_jobs.py`.
- Extraction des diagnostics HTTP et des logs de payload Plex vers
  `core/plex_access_runtime.py`; suppression de trois helpers de pilotage morts
  et passage de `apply_plex_access_updates.py` sous 1000 lignes.
- Extraction de la regle du mode d'import vers `core/plex_sync_config.py`,
  mutualisation de la detection des invitations Plex en attente et suppression
  de trois helpers sans appel dans `sync_plex.py`.
- Extraction du client XML Plex.tv utilise pour le compte administrateur, les
  utilisateurs et les shared servers vers `core/plex_sync_api.py`.
- Extraction de l'orchestration globale de synchronisation des serveurs,
  bibliotheques et acces Plex vers `core/plex_sync_orchestrator.py`.
- Extraction du comptage des sections et de l'application des diffs d'acces
  aux bibliotheques vers `core/plex_library_access.py`.
- Extraction du rapprochement global et de l'upsert du proprietaire de chaque
  serveur Plex vers `core/plex_owner_sync.py`.
- Extraction de la decouverte et de la reconciliation des bibliotheques vers
  `core/plex_library_sync.py`; `sync_plex.py` repasse sous 1000 lignes.
- Centralisation de la collecte, persistance, lecture et application des
  statistiques CPU/RAM dans `core/monitoring/resource_stats.py`.
- Extraction des endpoints JSON de detail et d'historique des enforcements
  Monitoring vers `routes/monitoring_enforcements.py`, sans changement d'URL.
- Extraction du contexte serveurs Monitoring et des donnees Now Playing vers
  `core/monitoring/overview_servers.py` et `overview_live.py`.
- Extraction de l'activite recente et du contexte Usage Risk vers
  `core/monitoring/overview_activity.py` et `overview_usage_risk.py`.
- Extraction des parametres, du tri, du formatage et de la pagination de
  l'onglet Users Monitoring vers `core/monitoring/overview_users.py`.
- Restauration du helper de compatibilite Plex pour l'activation differee des
  abonnements, detectee par la passe de validation globale.
- Clarification des libelles CRON de la page Tasks : les listes regulieres
  affichent maintenant simplement leur frequence et les minutes fixes utilisent
  une formulation naturelle dans les cinq langues de l'interface.
- Extraction du comptage filtre de l'onglet Users Monitoring vers
  `core/monitoring/overview_users.py`, avec correction d'un suffixe SQL parasite
  qui pouvait casser une recherche utilisateur.
- Extraction de la requete agregee de la liste Users Monitoring vers
  `core/monitoring/overview_users.py`, avec test SQLite du filtrage, du
  dedoublonnage des lectures et du formatage.
- Extraction de la pagination des enforcements Monitoring Policies vers
  `core/monitoring/overview_policies.py`, avec bornage de la page et des tailles
  autorisees.
- Extraction du catalogue Monitoring Policies, du decodage des regles JSON et
  des compteurs systeme/verrouillage/abonnement vers
  `core/monitoring/overview_policies.py`.
- Extraction des statistiques du dashboard Monitoring Policies et des fenetres
  d'enforcement 24 heures/7 jours vers `core/monitoring/overview_policies.py`.
- Extraction des repartitions Monitoring Policies par scope, provider et type
  de regle vers `core/monitoring/overview_policies.py`.
- Extraction du classement des utilisateurs touches par les enforcements,
  avec resolution des identites Vodum/Plex, vers
  `core/monitoring/overview_policies.py`.
- Extraction de la liste paginee des enforcements recents et de la resolution
  de leur libelle utilisateur vers `core/monitoring/overview_policies.py`.
- Extraction du regroupement des enforcements par acteur et de l'etat des
  sessions suivies vers `core/monitoring/overview_policies.py`.
- Extraction de la chronologie warn/kill Monitoring Policies sur 30 jours,
  avec remplissage des jours sans evenement; l'onglet est desormais decouple
  de ses requetes metier.
- Extraction complete de l'onglet Monitoring History vers
  `core/monitoring/overview_history.py`, avec test SQLite des filtres, du tri,
  du formatage et de la pagination.
- Extraction des parametres, du tri securise et de la pagination de l'onglet
  Monitoring Libraries vers `core/monitoring/overview_libraries.py`.
- Extraction de la table agregee Monitoring Libraries, du comptage des acces
  hors proprietaire et du formatage des durees vers
  `core/monitoring/overview_libraries.py`, avec test SQLite reel.
- Extraction de la liste des utilisateurs du filtre Monitoring Libraries et de
  ses libelles de repli vers `core/monitoring/overview_libraries.py`.
- Extraction de la construction parametree des filtres de periode et
  d'utilisateur du classement Monitoring Libraries vers
  `core/monitoring/overview_libraries.py`.

## 2026-07-16 - P3 architecture, premier lot

- Finalisation du decoupage de `tasks_engine.py`, ramene sous 1000 lignes: suppression des anciennes implementations inatteignables et extraction de la configuration des taches et du cycle de vie scheduler dans `core/tasks/`.
- Suppression d'un ancien helper dashboard inutilise et de ses constantes SQL, sans changement d'URL ni de contrat de template.
- Extraction des requetes et agregations de widgets dashboard dans un service read-only dedie.
- Extraction des regles pures de validation des retours et timeouts de taches hors de `tasks_engine.py`.
- Extraction des signaux thread-safe du scheduler (execution forcee et auto-configuration) avec tests de deduplication et consommation unique.
- Extraction des decisions pures du tick scheduler: parsing des dates, compteurs, retries, occupation et echeances forcees.
- Extraction de la file FIFO des sequences de taches avec attribution thread-safe d'un worker unique.
- Remplacement du verrou et du booleen globaux du worker principal par une attribution thread-safe testee en concurrence.
- Extraction de l'orchestration des sequences de taches et de leur attente bloquante hors de `tasks_engine.py`.
- Extraction du premier noyau de regles pures d'auto-activation des taches.
- Extraction du passage complet d'auto-activation Monitoring, providers, workers d'acces, Stream Enforcer et expiry dans un service dedie.
- Extraction du cycle d'execution des taches dans un runner injectable et teste, tout en conservant `run_task` comme facade publique.
- Extraction du tick scheduler complet dans un service testable separe de la boucle de sommeil.
- Centralisation de la selection du compte Plex prefere et des jobs de resynchronisation utilisateur Plex/Jellyfin dans un service partage.
- Centralisation du contrat de pagination web et migration initiale des routes Users et Servers.
- Uniformisation des dernieres connexions SQLite applicatives directes (validation Backup et import Tautulli) via la factory commune en lecture seule.
- Retrait du widget dashboard Operations health, juge redondant et peu clair, ainsi que de son endpoint et service devenus inutiles.

## 2026-07-16 - P6 logs et diagnostic, premier lot

- Les valeurs sensibles presentes dans les tracebacks sont maintenant anonymisees hors mode debug, comme celles du message principal.
- La page Logs et le telechargement couvrent desormais le fichier actif et les cinq rotations conservees.
- Les tracebacks multilignes restent groupes avec leur evenement ERROR/CRITICAL pour le filtrage et l'affichage.
- Le telechargement anonymise force maintenant la protection des emails, tokens et IP meme lorsque le mode debug est actif.
- Les exceptions non gerees des requetes Flask et des threads Python sont maintenant capturees dans `app.log` avec traceback et contexte stable.
- Ajout des traces techniques manquantes derriere plusieurs erreurs UI Backup, Communications, Discord et Subscriptions, avec contexte non sensible.
- Les jobs d'acces Plex/Jellyfin persistes mais non demarres et les pannes de geolocalisation Monitoring sont maintenant visibles dans les logs.
- Correction du filtre initial de la page Logs qui masquait les WARNING, ERROR et CRITICAL hors mode debug; ajout du filtre CRITICAL explicite.
- Ajout de compteurs cliquables par severite sur toute la retention des logs, avec acces direct aux incidents ERROR et CRITICAL.
- Ajout d'un audit AST reproductible des handlers silencieux et couverture groupee des erreurs techniques Users, Servers, Migrations et Tasks.
- Cloture P6: erreurs de lecture visibles, configuration du handler idempotente et validation automatisee des modes normal/debug sans doublons.
- Ouverture differee du fichier de log afin qu'un volume temporairement indisponible ne bloque pas l'import des taches et du moteur de coupure.

## 2026-07-16 - P2 monitoring materialise

- Ajout de `monitoring_daily_stats`, table reconstructible d'agregats quotidiens.
- Ajout de la tache quotidienne `materialize_monitoring_daily_stats` avec backfill glissant de 31 jours.
- Lecture prioritaire des statistiques et tops utilisateurs compacts par l'overview Monitoring, avec fallback historique.
- Ajout de l'index compose Referrals valide par `EXPLAIN QUERY PLAN`; rejet documente des index Users inutilisables avec la recherche `%terme%`.
- Ajout d'une synthese d'exploitation au dashboard: providers, files de taches/jobs, incidents recents et niveau d'action.

## 2026-07-16 - Cloture P1 UI/performance

- Finalisation des fragments dashboard, paginations 20/50/100, modales chargees a la demande et skeletons stables.
- Ajout des traductions generiques de chargement, nouvelle tentative et taille de page dans les cinq langues UI.
- Validation finale de la syntaxe, des routes, templates, modales, paginations et tests de non-regression.
- Correction du dimensionnement des graphiques Monitoring sur les ecrans mobiles haute densite.
- Ajout d'un indicateur global pendant les navigations et chargements HTMX perceptibles.
- Barre laterale desktop fixee a la fenetre sur toute sa hauteur, avec defilement interne du menu.

All notable changes to Vodum will be documented in this file.

---

## Unreleased

- Complete the targeted skeleton pass with a stable Usage Risk dashboard placeholder and a viewport-sized User detail Monitoring iframe skeleton with a ten-second error fallback.

- Limit Migration campaign detail rendering to configurable 20/50/100-user pages while retaining campaign-wide eligibility, validation, rollback, and removal summary counts.

- Paginate Communications Templates server-side at 20/50/100 rows, preserving the selected editor language and current list page when opening a template.

- Make Subscriptions tab data lazy at the route level so Applications users, Gift candidates, templates, servers, and settings are queried only by consuming tabs, and add 20/50/100 pagination to Applications.

- Load full Monitoring Policy enforcement snapshots only when an event row is opened, keeping large session/IP/rule JSON payloads out of the main paginated table.

- Load sent Communications History message bodies and metadata only when opening a row, reducing table HTML and avoiding rendering every message body during page load; queued entries retain their inline transient details.

- Add configurable 20/50/100 server-side pagination to Communications History and preserve its trigger filter and sort order through every navigation link.

- Make Monitoring Policies enforcement history configurable at 20/50/100 server-paginated rows while preserving the selected size across navigation.

- Add configurable 20/50/100 server-side page sizes to Users and Referrals, preserve the choice through pagination/archive links, and avoid loading referral settings/stats or subscription setup data outside the consuming tab.

- Make User detail tab loading data-aware: communication history, access libraries and merge candidates, general referral/risk/policy data, monitoring identity, and enriched media accounts are now queried only for the tab that consumes them.

- Keep the asynchronously loaded dashboard stream/subscription summary card stretched to the same row height as the Users card without imposing a fixed mobile height.

- Move the multi-server dashboard list and seven-day peak-stream calculation out of the initial page render into a timeout-protected fragment.

- Defer the expensive dashboard Usage Risk report and trend calculation to an independent fragment so it no longer delays the initial dashboard response.

- Load the dashboard stream-enforcement and subscription summary through an independent HTMX fragment with a stable skeleton, timeout fallback, and its detail modal bundled with the fragment.

- Standardize full-screen application dialogs through the shared modal manager with a top-right close icon, backdrop-click closing, Escape handling, focus restoration, and support for dynamically loaded modals.

- Revalidate policy violations against the current session and server immediately before enforcement, and confirm actual playback disappearance after Plex and Jellyfin stop requests.

- Prevent false usage-risk upgrade emails by counting distinct blocked sessions instead of repeated enforcement rows and by sending only recommendations still present in the freshly recalculated report.

- Restore scrolling in Monitoring policy enforcement modals by constraining the complete panel to the viewport and making its content area a real flex scroll container.

- Audit long dialogs and add viewport-bounded scrolling to Monitoring IP details, Communications History, Settings security, login reset, subscription gifts, User deletion/password, and Create User modals.

- Remove the global intrinsic table width and duplicate mobile `display:block` rules that made Monitoring Policies shrink on desktop and pushed Communications History columns outside its card.

- Allow the dedicated `/login/artwork/` proxy through the authentication guard so anonymous login pages receive image bytes instead of a redirect back to HTML.

- Remove the easter-egg quote text from the login form, keep the media backdrop behind desktop login, and use only the real portrait poster behind mobile login.

- Keep the last valid login artwork visible across midnight and application startup until the daily easter-egg cache refresh completes.

- Preserve the lifetime-toggle global handler after extracting the Subscriptions editor, and keep the User email panel collapsed state stable across responsive resize changes.

- Move the final inline business script, the Subscriptions template editor, into `static/js/pages/subscriptions-template-editor.js` with translations supplied through JSON configuration.

- Move the User merge selection, preview, confirmation, and access-field synchronization into `static/js/pages/user-detail.js`, using safe DOM rendering for preview values.

- Move the Subscriptions policies table filters, pagination, bulk selection, and delete confirmation into `static/js/pages/subscriptions.js`.

- Fix the Subscriptions template editor JavaScript identifiers so translated labels can no longer alter function names and break non-English pages.

- Add an eight-second timeout and stable error fallback to the dashboard Now Playing and Next Tasks widgets.

- Move the User detail lifetime/server expiration override behavior out of the inline template into `static/js/pages/user-detail.js`.

- Move the User detail referrer picker into `static/js/pages/user-detail.js` and build candidate rows with safe DOM text nodes.

- Move the User detail Jellyfin password modal into `static/js/pages/user-detail.js` and render server responses as plain text.

- Consolidate the User access Plex, Jellyfin, and email collapsible panels in `static/js/pages/user-detail.js`.

- Centralize the User detail notification order controls in `static/js/app.js` and remove the inline partial script.

- Centralize the Users/Plex form debounce helper in `static/js/app.js` and remove the inline duplicate from the user servers partial.

- Move the Subscriptions settings expiry/stream-blocked checkbox sync out of the inline template into `static/js/pages/subscriptions.js`.

- Move the dashboard Now Playing stable-swap handler out of inline template/header blocks and keep it in `static/js/pages/dashboard.js`.

- Move Servers detail/libraries, Settings notification order, and Backup Tautulli import behavior out of inline templates into page JavaScript files.

- Move Subscriptions application/template confirmation behavior and plan summaries out of inline templates into `static/js/pages/subscriptions.js`.

- Move Users filters, referrals bulk-selection, and Create User modal behavior out of the template into `static/js/pages/users.js`.

- Fix mobile login easter egg artwork loading before authentication, and avoid repainting the dashboard sentence artwork when HTMX receives identical content.

- Add the daily easter egg visual to the login screen, using the media backdrop on desktop browsers and the poster on mobile.

- Improve mobile layouts for Subscriptions and Monitoring policy dialogs by stacking narrow action areas, relaxing dense grids, and constraining large modal content on small screens.

- Improve mobile layouts for Logs, Servers, and Communications modals by stacking action bars and constraining large dialogs on small screens.

- Add dashboard quote rotation so available easter eggs are not repeated until the eligible set has been exhausted, and allow `tv` entries to resolve as shows.

- Add French cinema easter egg quotes for Les Visiteurs, Taxi, Les Trois Fr?res, and Ast?rix & Ob?lix: Mission Cl?op?tre.

- Improve Users and User detail mobile layouts by stacking dense label/value grids and modal action rows on narrow screens.

- Make Monitoring Now Playing cards fluid on small screens so the 380px desktop card minimum no longer creates mobile overflow.

- Improve Monitoring user detail on mobile by stacking chart legends and reducing metric grids to one column on narrow screens.

- Improve the dashboard Usage Risk card on mobile by stacking the metric and chart on small screens.

- Improve mobile action, form, and modal resilience by wrapping action groups and constraining fixed-width controls only on small screens.
