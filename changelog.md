# Changelog

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

