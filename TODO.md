# ✅ VODUM – TODO GLOBAL REWORK

## 🧱 1. Architecture (PRIORITÉ MAX)

### 1.1 Structure générale de l’application

- [x] Sortir la création de l’app dans `app/__init__.py`
- [x] Centraliser le bootstrap Flask dans `app/app.py`
- [x] Séparer les routes en modules dédiés dans `app/routes/`
- [x] Garder le démarrage du scheduler hors de la factory Flask (`run.py`)
- [x] Réduire les imports transverses massifs hérités de l’ancien `app.py`
- [ ] Supprimer les dépendances globales encore trop couplées entre routes, tâches et providers

#### Contrôle effectué
- `app/__init__.py` est propre : il délègue à `app.app.create_app()`
- `app/app.py` délègue maintenant l’enregistrement des routes à `app/routes/__init__.py`
- `run.py` démarre le scheduler après création de l’app
- en revanche, beaucoup de fichiers de routes importent encore un gros bloc générique hérité
- certains fichiers ont déjà été nettoyés :
- [x] `app/routes/servers.py`
- [x] `app/routes/monitoring_overview.py`
- [x] `app/routes/about.py`
- [x] `app/routes/tasks_api.py`
- [x] `app/routes/logs.py`
- [x] `app/routes/auth.py`
- [x] `app/routes/backup.py`
- [x] `app/routes/monitoring_user.py`
- [x] `app/routes/dashboard.py`
- [x] `app/routes/settings.py`
- [x] `app/routes/subscriptions_page.py`
- [x] `app/routes/tasks.py`
- [x] `app/routes/users_list.py`
- [x] `app/routes/communications.py` *(import mort retiré)*
- [x] `app/routes/users_actions.py`
- [x] `app/routes/users_detail.py`
- [x] `app/routes/monitoring_api.py`
- le gros nettoyage des imports routes est fait ; le couplage restant est surtout entre la factory, le moteur de tâches et certains accès provider

#### Fichiers concernés
- `app/app.py`
- `app/routes/__init__.py`
- `app/__init__.py`
- `run.py`
- le couplage factory → routes a été réduit, mais d’autres couplages restent encore entre tâches, routes et providers

---

### 1.2 Règle d’architecture cible : GET = lecture, POST = action, Worker = exécution

- [ ] Supprimer les routes GET qui modifient la base
- [ ] Unifier les actions POST (suppression des doublons run task, toggle, etc.) *(en cours : activation + queue des tâches apply_* centralisées, auto-enable `stream_enforcer` sorti des routes/blueprints, enable/disable cohérent centralisé dans `tasks_engine`, master switch cron + tâches d’expiration sortis de `settings.py`, préparation post-restore sortie de `backup.py`, activations système `check_servers`/`update_user_status` centralisées, pilotage d’état `run_now` sorti de `tasks.py`, séquence post-création serveur centralisée, page `/tasks` séparée en GET lecture seule + POST dédié `/tasks/action`, page `/users` séparée en GET lecture seule + POST dédié `/users/referral-settings`, page `/subscriptions` séparée en GET lecture seule + POST dédié `/subscriptions/settings`, page `/settings` séparée en GET lecture seule + POST dédié `/settings/save`, page `/servers/<id>` séparée en GET lecture seule + POST dédié `/servers/<id>/save`, page `/users/<id>` séparée en GET lecture seule + POST dédié `/users/<id>/save`, page `/communications/campaigns` séparée en GET lecture seule + POST dédié `/communications/campaigns/action`, page `/communications/templates` séparée en GET lecture seule + POST dédié `/communications/templates/action`, page `/communications/configuration` séparée en GET lecture seule + POST dédié `/communications/configuration/action`, page `/backup` séparée en GET lecture seule + POST dédié `/backup/action`)*
- [ ] Supprimer les routes GET qui déclenchent des jobs
- [ ] Réserver les routes GET à la lecture DB / rendu template / API read-only
- [ ] Réserver les POST aux changements d’état
- [ ] Réserver l’exécution réelle des actions externes aux workers/tasks
- [x] suppression de la route `/tasks/run/<id>` (doublon avec POST /tasks run_now)
- [x] centralisation du lancement de tâche via une seule entrée
- [x] structure POST → enqueue → worker respectée
- [x] la déconnexion (`/logout`) n’est plus exposée en GET
- [x] centralisation de l’activation + mise en file des tâches `apply_*` via un helper unique
- [x] centralisation de l’auto-activation de `stream_enforcer` via `tasks_engine.auto_enable_stream_enforcer()`
- [x] centralisation de l’activation/désactivation cohérente des tâches via `tasks_engine` (UI tâches + mailing)
- [x] centralisation du master switch cron + sync des tâches d’expiration via `tasks_engine`
- [x] centralisation de la préparation post-restore (maintenance + désactivation cohérente des tâches) via `tasks_engine`
- [x] centralisation des activations système restantes (`check_servers`, `update_user_status`, `stream_enforcer`) via `tasks_engine`
- [x] centralisation du pilotage d’état `run_now` (queued / queue_failed) via `tasks_engine`
- [x] centralisation de la séquence post-création serveur (`check_servers` + sync provider) via `tasks_engine`

#### Contrôle effectué
- [x] `GET /tasks` est maintenant réservé à l’affichage read-only de la liste des tâches
- [x] les changements d’état des tâches (`run_now`, `toggle`) passent maintenant par une route POST dédiée `/tasks/action`
- [x] le template `tasks/tasks.html` n’utilise plus l’ancienne route supprimée `/tasks/run/<id>`
- [x] `GET /users` est maintenant réservé à l’affichage read-only (liste users / referrals / referral settings)
- [x] la sauvegarde des referral settings passe maintenant par une route POST dédiée `/users/referral-settings`
- [x] le template `users/users.html` n’utilise plus le POST direct sur `/users` pour modifier l’état
- [x] `GET /subscriptions` est maintenant réservé à l’affichage read-only des onglets subscriptions
- [x] la sauvegarde des subscription settings passe maintenant par une route POST dédiée `/subscriptions/settings`
- [x] le template `templates/subscriptions/_settings.html` n’utilise plus le POST direct sur `/subscriptions`
- [x] `GET /settings` est maintenant réservé à l’affichage read-only de la page settings
- [x] la sauvegarde des settings passe maintenant par une route POST dédiée `/settings/save`
- [x] le template `templates/settings/settings.html` n’utilise plus le POST direct sur `/settings`
- [x] `GET /servers/<id>` est maintenant réservé à l’affichage read-only de la fiche serveur
- [x] la sauvegarde d’un serveur passe maintenant par une route POST dédiée `/servers/<id>/save`
- [x] le template `templates/servers/server_detail.html` n’utilise plus le POST direct sur `/servers/<id>`
- [x] `GET /users/<id>` est maintenant réservé à l’affichage read-only de la fiche user
- [x] la sauvegarde de la fiche user passe maintenant par une route POST dédiée `/users/<id>/save`
- [x] le template `templates/users/partials/_user_general.html` n’utilise plus le POST direct sur `/users/<id>`
- [x] `GET /communications/campaigns` est maintenant réservé à l’affichage read-only de la page campagnes
- [x] les actions de campagne passent maintenant par une route POST dédiée `/communications/campaigns/action`
- [x] le template `templates/communications/communications_campaigns.html` n’utilise plus le POST direct sur `/communications/campaigns`
- [x] `GET /communications/templates` est maintenant réservé à l’affichage read-only de la page templates
- [x] les actions des templates passent maintenant par une route POST dédiée `/communications/templates/action`
- [x] le template `templates/communications/communications_templates.html` n’utilise plus le POST direct sur `/communications/templates`
- [x] `GET /communications/configuration` est maintenant réservé à l’affichage read-only de la page configuration
- [x] les actions de configuration des communications passent maintenant par une route POST dédiée `/communications/configuration/action`
- [x] le template `templates/communications/communications_configuration.html` n’utilise plus le POST direct sur `/communications/configuration`
- [x] `GET /backup` est maintenant réservé à l’affichage read-only de la page backup
- [x] les actions backup/restauration/import passent maintenant par une route POST dédiée `/backup/action`
- [x] les templates backup n’utilisent plus le POST direct sur `/backup`

##### Problème 1 — ancien GET historique désormais corrigé
- `app/routes/servers.py`
- route :
- [x]`/servers/<int:server_id>/sync`
- cette route n’est plus en GET :
- [x]elle est passée en POST
- le point “GET qui déclenche une action” est donc corrigé ici

##### Problème 2 — écriture monitoring sortie de la route GET
- `app/routes/monitoring_overview.py`
- route :
- [x]`/monitoring`
- la route ne fait plus d’écriture dans `monitoring_snapshots`
- [x]plus de `INSERT INTO monitoring_snapshots`
- [x]plus de `DELETE FROM monitoring_snapshots`
- l’ouverture de la page monitoring n’écrit plus en base

##### Problème 3 — appels provider live retirés de la route monitoring
- `app/routes/monitoring_overview.py`
- la page `/monitoring` ne fait plus d’appels live directs :
- [ ][x]plus de `_fetch_server_resource_stats()`
- [ ][x]plus de `_fetch_plex_resource_stats()`
- [ ][x]plus de `requests.get(... /statistics/resources ...)`
- le rendu lit désormais les données stockées en base

#### Décision cible
- `/servers/<id>/sync` doit devenir un POST
- l’écriture de `monitoring_snapshots` doit sortir de la route GET
- les stats ressources serveur doivent venir d’une tâche dédiée qui écrit en DB
- la page monitoring doit lire la DB uniquement

---

### 1.3 Monitoring : sortir définitivement le live provider du web

- [x] Supprimer les appels `requests.get()` vers Plex depuis `app/routes/monitoring_overview.py`
- [x] Déplacer la collecte CPU/RAM serveur dans une tâche dédiée
- [x] Stocker le résultat en base
- [x] Faire lire `/monitoring` uniquement depuis la base
- [x] Déplacer l’écriture des snapshots de monitoring dans une tâche dédiée ou dans le collector
- [x] Définir clairement quelles routes API ont encore le droit de proxyfier des médias distants

#### Contrôle effectué
Le gros point encore sale côté architecture, c’est ici :
- `app/routes/monitoring_api.py` conserve explicitement la seule exception autorisée pour le proxy média distant côté monitoring : `/api/monitoring/poster/<server_id>`
- la branche Plex de ce proxy a été durcie (path relatif uniquement) et le double fetch HTTP inutile a été supprimé

##### Fichier
- `app/routes/monitoring_overview.py`

##### Fonctions concernées
- `_fetch_plex_resource_stats()`
- `_fetch_server_resource_stats()`

##### Ce qu’elles font encore
- appellent Plex en direct via HTTP
- dépendent du token serveur
- sont exécutées pendant le rendu de la page

##### Pourquoi ce n’est plus acceptable
- le frontend ne doit plus dépendre du provider live
- une latence Plex ralentit la page monitoring
- un timeout Plex donne une page incohérente
- ce n’est pas compatible avec l’objectif “DB source of truth”

#### Remarque
Le collector monitoring existe déjà côté cœur :
- `app/core/monitoring/collector.py`

Donc la bonne direction n’est pas de réinventer le système, mais de :
- réutiliser ce principe
- élargir la collecte
- supprimer le live HTTP dans la route web

---

### 1.4 Task system : base correcte, mais pas encore totalement propre

- [x] Avoir une table `tasks` persistée en base
- [x] Avoir des statuts DB (`idle`, `queued`, `running`, `error`, `disabled`)
- [x] Avoir une queue persistée via `queued_count`
- [x] Avoir un worker dédié dans `app/tasks_engine.py`
- [x] Avoir un watchdog de récupération des tâches bloquées
- [x] Ajouter une vraie stratégie de retry standardisée par tâche
- [x] Ajouter un compteur de retry / dernière tentative / prochain retry
- [X] Sortir la connexion DB globale figée au niveau module dans `tasks_engine`
- [ ] Réduire les responsabilités trop nombreuses de `tasks_engine.py` *(en cours : `run_task()` continue d’être découpé en helpers internes, avec chargement du contexte d’exécution et post-traitement du résultat sortis dans des helpers dédiés)*

#### Contrôle effectué
- [x] l’auto-enable du worker Plex ne se base plus sur tous les `media_jobs`, mais uniquement sur les jobs réellement liés à Plex
- [x] la queue des séquences utilise maintenant son propre verrou (`sequence_lock`) au lieu de réutiliser le lock du worker principal
- [x] l’exécution complète d’une séquence ne garde plus `sequence_lock`, qui ne protège désormais que la file de séquences et son état interne
- [x] une séquence n’attend plus artificiellement 1800s sur une tâche que `enqueue_task()` a refusé de mettre en file
- [x] le doublon de définition de `_handle_task_success()` a été supprimé dans `tasks_engine.py`
- [x] le scheduler ne consomme plus `next_run` / `next_retry_at` / bootstrap `last_run` quand `enqueue_task()` refuse réellement la mise en file
- [x] le chargement du contexte d’exécution de `run_task()` est maintenant isolé dans `_load_task_execution_context()`
- [x] le post-traitement du résultat de `run_task()` est maintenant isolé dans `_process_task_result()`

##### Points déjà bons
- `app/tasks_engine.py` gère :
- [ ]queue DB
- [ ]worker
- [ ]timeout par tâche
- [ ]scheduler cron
- [ ]watchdog
- [ ]recovery au boot

##### Ce qui reste sale
- [ ] `app/tasks_engine.py` n’instancie plus `DBManager` directement au chargement du module :
- [ ]la DB est maintenant résolue en lazy-load au premier usage
- [ ] la logique auto-enable est maintenant centralisée dans un passage unique
- [ ] la logique de tick cron est maintenant isolée du `scheduler_loop()`
- [ ] ça centralise encore trop de choses dans un seul fichier :
- [ ]queue
- [ ]worker
- [ ]sequence runner
- [ ]recovery
- [ ]logs
- [x] une mécanique générique de retry/backoff existe maintenant pour les tâches scheduler
- [x] on a un `retry_count`
- [x] on a un `last_attempt_at`
- [x] on a un `next_retry_at`
- [ ] le backoff reste encore simple et pourra être affiné par type de tâche plus tard

#### Fichier concerné
- `app/tasks_engine.py`

---

### 1.5 Boot & stabilité : meilleur que prévu, mais encore à cadrer

- [x] Créer `tables.sql` uniquement si la DB est absente
- [x] Garder `db_bootstrap.py` idempotent au démarrage
- [x] Restaurer l’état maintenance au boot
- [x] Lancer un one-shot repair au démarrage
- [x] Garder le reset admin en one-shot fichier
- [x] Rendre le démarrage du scheduler idempotent
- [x] Unifier tous les “boot fixes” dans une logique lisible
- [x] Journaliser plus explicitement ce qui a été réparé ou non
- [x] Documenter clairement la chaîne de démarrage réelle

#### Contrôle effectué

- [x] le chargement dynamique d’une tâche est maintenant isolé dans un helper dédié
- [x] l’exécution d’une tâche avec timeout réel est maintenant isolée dans un helper dédié
- [x] le traitement succès (`status`, `last_run`, `next_run`, post-check_servers) est maintenant isolé dans un helper dédié
- [x] le passage d’une tâche en `running` est maintenant isolé dans un helper dédié
- [x] le failsafe final qui corrige une tâche restée en `running` est maintenant isolé dans un helper dédié
- [x] les auto-enable `sync_plex` / `sync_jellyfin` utilisent maintenant la même logique cohérente d’activation de tâche
- [x] les auto-enable `apply_plex_access_updates` / `apply_jellyfin_access_updates` utilisent maintenant la même logique cohérente d’activation de tâche
- [x] les auto-enable des tâches de monitoring utilisent maintenant la logique centralisée d’activation
- [x] `stream_enforcer` utilise maintenant la même logique cohérente d’activation de tâche
- [x] les auto-enable périodiques n’utilisent plus les helpers “reset fort” prévus pour les actions UI/admin
- [x] un passage auto-enable préserve désormais les états runtime utiles (`running`, `queued`, `error`) au lieu de les écraser
- [x] la sortie du worker relance maintenant un contrôle DB pour éviter de laisser une file `queued_count > 0` sans worker actif
- [x] une auto-désactivation périodique n’écrase plus artificiellement l’état runtime d’une tâche déjà `running` ou `queued`
- [x] le recovery au boot n’écrase plus artificiellement les tâches en `error`, ce qui préserve la cohérence du retry après redémarrage
- [x] les boot fixes de démarrage passent maintenant par une seule séquence `_run_startup_boot_fixes(app)`
- [x] le one-shot repair retourne désormais un résultat explicite (`done` / `skipped`) exploitable par les logs de boot
- [x] les logs de boot indiquent maintenant clairement si la récupération admin, la sortie maintenance et le repair ont été exécutés, ignorés ou ont échoué
- [x] `run.py` documente maintenant explicitement la chaîne réelle : entrypoint -> create_app -> boot fixes -> scheduler
- [x] `_run_startup_boot_fixes(app)` décrit maintenant clairement son périmètre, son ordre et son rôle exact
- [x] la séparation entre bootstrap infra/DB et boot fixes applicatifs est maintenant explicitée dans le code

##### Déjà bon
- `entrypoint.sh` :
- [ ] crée la DB via `tables.sql` seulement si elle n’existe pas
- [ ] lance ensuite `db_bootstrap.py`
- `app/app.py` :
- [ ] appelle `_reset_maintenance_on_startup(app)`
- [ ] appelle `run_repair_if_needed(db, app.logger)` dans un contexte one-shot au démarrage
- `app/tasks_engine.py` :
- [x] protège désormais `start_scheduler()` contre un double démarrage
- le point “tables.sql ne doit pas tourner en boucle” est déjà globalement respecté

##### À améliorer
Le boot est devenu fonctionnel, mais dispersé :
- [ ] `entrypoint.sh`
- [ ] `db_bootstrap.py`
- [ ] `app/app.py`
- [ ] `core.repair.plex_media_users_repair`

Il faut maintenant le rendre lisible et volontaire :
- [ ] initialisation DB
- [ ] migrations
- [ ] bootstrap idempotent
- [ ] startup fixes
- [ ] one-shot repairs

---

### 1.6 Providers : la séparation existe, mais n’est pas encore imposée partout

- [x] Avoir un registre providers dans `app/core/providers/`
- [x] Avoir des modules provider dédiés Plex / Jellyfin
- [x] Avoir une base monitoring commune via `core/monitoring/collector.py`
- [ ] Empêcher toute nouvelle logique provider dans les routes web
- [ ] Empêcher toute logique provider métier dans les templates/routes
- [ ] Réserver l’accès provider aux services métier et tâches

#### Contrôle effectué
La base est déjà là :
- [ ] `app/core/providers/registry.py`
- [ ] `app/core/providers/plex.py`
- [ ] `app/core/providers/jellyfin.py`

Mais l’architecture n’est pas encore totalement respectée, car on a encore des appels directs côté route web, surtout dans :
- [ ] `app/routes/monitoring_overview.py`

---

### 1.7 Routes à corriger en priorité absolue

- [x] Passer `/servers/<int:server_id>/sync` en POST
- [ ] Sortir la création des `media_jobs` de cette route GET historique
- [x] Sortir l’écriture `monitoring_snapshots` hors de `/monitoring`
- [x] Sortir les appels live Plex CPU/RAM hors de `/monitoring`
- [ ] Vérifier toutes les routes GET qui modifient DB/session/provider et les recenser proprement
- [ ] Lister explicitement les exceptions volontaires autorisées

#### Contrôle effectué — priorité immédiate
1. `app/routes/servers.py`
- [x] `/servers/<int:server_id>/sync`
- [x] actionnelle en POST

2. `app/routes/monitoring_overview.py`
- [x] `/monitoring`
- [x] n’écrit plus dans `monitoring_snapshots`
- [x] n’appelle plus Plex en direct

3. `app/routes/monitoring_api.py`
- [ ] endpoints de proxy image/poster
- [ ] à garder éventuellement, mais à classer comme **exception technique**
- [ ] ils ne doivent pas servir de précédent pour remettre du provider live partout

---

### 1.8 Découpage concret du chantier architecture

#### Sprint A — verrouiller les règles
- [x] Transformer `/servers/<id>/sync` en POST
- [x] Retirer toute écriture DB de la page `/monitoring`
- [x] Retirer les appels Plex live CPU/RAM de `/monitoring`
- [ ] Définir noir sur blanc les exceptions GET autorisées

#### Sprint B — nettoyer le moteur de tâches
- [x] Isoler la logique queue/worker du scheduling cron
- [x] Isoler la logique auto-enable
- [x] Préparer un vrai retry standardisé
- [ ] Réduire la taille et les responsabilités de `app/tasks_engine.py`

#### Sprint C — imposer la séparation provider
- [ ] Faire passer toute collecte provider par tâches/services
- [ ] Interdire les appels provider dans les routes HTML
- [ ] Garder les routes API “proxy média” uniquement comme exceptions documentées

---

### 1.9 Statut réel de la section Architecture

- [x] La refonte a déjà commencé
- [x] L’app n’est plus un monolithe unique
- [x] Le système de tâches DB existe
- [x] Le boot est déjà largement meilleur qu’avant
- [ ] L’architecture n’est pas encore propre tant que des GET modifient l’état
- [x] L’architecture n’est pas encore propre tant que `/monitoring` appelle Plex en direct
- [x] L’architecture n’est pas encore propre tant que `/monitoring` écrit en base pendant le rendu
- [ ] L’architecture n’est pas encore propre tant que `tasks_engine.py` reste trop central et trop global
---

## 📊 2. Monitoring (CRITIQUE)

### Source de vérité = DB uniquement
- [ ] Supprimer tout appel live Plex dans dashboard / monitoring
- [ ] Implémenter fallback sur dernier snapshot si tâche lente

### Sync Plex fiable
- [ ] Corriger `sync_plex` :
- [ ]matching robuste (name + type + server)
- [ ]éviter pertes de données
- [ ] Nettoyer les données héritées de Tautulli (thumbs incohérents)

### Performance
- [ ] Découper les traitements lourds (overview, users, libraries)
- [ ] Mettre en cache les résultats complexes
- [ ] Limiter fréquence des appels Plex (1 req/sec/server)
- [ ] enregistrer les poster dans films et serie jouer pour les resortir plus facilement a l'appel d'apres.

---

## 📬 3. Communications & Campaigns

### Fiabilité
- [ ] Garantir qu’une campagne ne reste jamais bloquée en “disabled”
- [ ] Reprise automatique après redémarrage
- [ ] Envoi des emails manqués (logique “rattrapage”)

### Logique métier
- [ ] Unifier :
- [ ]expiration emails
- [ ]campaigns
- [ ]scheduled communications
- [ ] Empêcher doublons (trigger + target + subscription)

### Améliorations
- [ ] Ajouter retry sur `comm_scheduled` en erreur
- [ ] Ajouter logs détaillés d’envoi
- [ ] Ajouter résumé global (Discord/email optionnel)

---

## 👤 4. Gestion des utilisateurs & accès

### Plex access
- [ ] Corriger définitivement :
- [ ]états “already invited”
- [ ]“request sent” incohérents
- [ ] Conserver les droits même si utilisateur non accepté
- [ ] Décaler expiration tant que compte non utilisé

### Actions globales
- [ ] Bouton “Grant access to all users” par serveur
- [ ] Bouton “Remove access from all users” (sauf owner)

### DB & cohérence
- [ ] Nettoyage automatique des états incohérents
- [ ] Ajouter colonne “nombre d’utilisateurs par library”

---

## 🧩 5. Libraries & Media

- [ ] Corriger association library ↔ media
- [ ] Utiliser les posters Plex (prioritaires sur Tautulli)
- [ ] Corriger affichage :
- [ ]séries → poster série (pas épisode)
- [ ] Ajouter “Top played” fiable par library
- [ ] Masquer automatiquement libraries sans activité

---

## 🧠 6. UI / UX (IMPORTANT)

### Tables
- [ ] Pagination standard (20 lignes + next/prev/first/last)
- [ ] Sauvegarde des filtres (localStorage)
- [ ] Indicateur visuel de tri (flèche + couleur)
- [ ] Click ligne → ouverture modal (pas bouton “view”)

### Cohérence UI
- [ ] Uniformiser tous les modals
- [ ] Supprimer éléments inutiles / bruit visuel
- [ ] Améliorer design global (cards, spacing, lisibilité)

### Interactions
- [ ] Supprimer boutons inutiles
- [ ] Ajouter actions bulk (select all / actions groupées)
- [ ] dans la partie user, la fonction search doit pouvoir rechercher parmis tous les status, selectionné ou pas.
- [ ] check everything is multilanguage

---

## ⚙️ 7. Settings & Configuration

- [ ] Ajouter toggle `VODUM_TRUST_PROXY`
- [ ] Implémenter système multilangue (JSON)
- [ ] Sauvegarde/restauration DB via UI
- [ ] Configuration SMTP :
- [ ]mode simple
- [ ]mode OAuth

---

## 🔄 8. Automatisation & tâches

- [ ] Script quotidien envoi emails
- [ ] Script désactivation utilisateurs expirés (toutes les 12h)
- [ ] Script vérification serveurs (cron horaire)
- [ ] Ajouter mode `--summary-only` pour scripts

---

## 🧪 9. Data quality & repair

- [ ] Ajouter script de réparation DB (exécution unique au boot)
- [ ] Nettoyage :
- [ ]entrées invalides
- [ ]incohérences users/libraries
- [ ] Vérification intégrité régulière (optionnelle)

---

## 🧱 10. Refactor code (STRUCTURE)

- [ ] Découper les fichiers >1000 lignes
- [ ] Séparer clairement :
- [ ]routes
- [ ]services métier
- [ ]providers (plex/jellyfin)
- [ ] Uniformiser les accès DB (db_manager uniquement)
- [ ] Supprimer code mort / legacy

---

## 🚀 11. Bonus / Futur

- [ ] Support Jellyfin complet
- [ ] Notifications Discord enrichies
- [ ] Dashboard avancé (charts usage)
- [ ] API publique (lecture seule)

---

# 🧭 Progression recommandée

1. Architecture
2. Monitoring
3. Communications
4. Users / Access
5. UI
6. Refactor code