# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines
sont documentes dans `changelog.md`.

Derniere mise a jour: 2026-07-22

## Principes de suivi

- Garder ici seulement les sujets encore utiles a traiter.
- Retirer une ligne quand elle est terminee et la tracer dans `changelog.md`.
- Prioriser les gains qui servent a la fois l'administration actuelle et la
  partie utilisateur exposee sur internet.
- Eviter les gros changements non valides sur la vraie base sans test terrain.

## P0 - Stabilisation et validation terrain

- [~] Valider sur une instance reelle le cycle Plex complet: invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.
- [~] Valider et renforcer la protection contre les pertes de donnees Plex sur
  instance reelle. Les garde-fous existent, il reste la validation terrain.
- [~] Valider les campagnes Migrations sur de grandes instances reelles Plex et
  Jellyfin avant d'activer davantage d'automatisations destructives.

## P3 - Architecture, routes et refactor

- [~] Reduire les dependances globales entre routes, taches et providers.
- [~] Deplacer la logique provider restante des routes et templates vers les
  services et les taches.
- [~] Continuer a decouper les fichiers de plus de 1000 lignes, notamment
  `db_bootstrap.py` et `stream_enforcer.py`. Les schemas des modeles d'accueil,
  de Discord, des cadeaux d'abonnement, du Monitoring temps reel, de son
  historique, des jobs media, de la normalisation des types et des index de
  requetes, des contenus d'accueil et des horaires versionnes sont maintenant
  extraits de `db_bootstrap.py`; le contrôle CRON global et le modèle Usage
  Risk, les réglages de base, la migration des secrets et les modèles de
  communication par défaut, leur schéma et le catalogue des tâches sont
  également isolés. `db_bootstrap.py` est maintenant repassé sous 1000 lignes.
  La traduction des politiques et l'identification des sessions/appareils ont
  aussi été sorties de `stream_enforcer.py`, avec les utilitaires de sélection
  des cibles, le pilotage temporaire de sa fréquence d'exécution, les
  instantanés d'enforcement, la lecture de la résolution des médias, les
  lectures de référentiel, la persistance de l'état d'enforcement, la livraison
  des notifications de blocage, les actions envoyées aux providers, les scopes
  de politiques et la sélection des violations après recontrôle.
  Les paramètres temporels et les diagnostics détaillés des sessions sont
  également centralisés hors de la tâche, ainsi que l'identité chronologique
  des endpoints, le regroupement des médias et les caches de grâce des
  synchronisations et transitions d'IP.
  Le contexte détaillé utilisé par les notifications de blocage est désormais
  isolé lui aussi, ainsi que la mémoire de déduplication des sessions du foyer.
- [~] Continuer la separation routes / services / providers, surtout sur les
  routes restantes de users, communications, subscriptions, migrations,
  setup wizard et servers. Le rendu de l'historique Communications et les
  opérations d'administration des modèles sont désormais isolés des routes,
  avec leurs règles de déclenchement, la persistance des pièces jointes et la
  normalisation du formulaire de configuration. Un ancien rendu local dupliqué
  de l'historique a également été supprimé. Les données des pages campagnes et
  modèles sont maintenant chargées par un service hors des routes.
  Le détail d'historique et la préparation sécurisée de la page Configuration
  utilisent désormais ce même service. Les routes de liste et détail de
  l'historique sont enregistrées dans un module séparé. `communications.py`
  est maintenant repassé sous 1000 lignes. Le calcul et le classement des
  suggestions de fusion ont été extraits de `users_list.py`. La gestion des
  instantanés de modèles d'abonnement est désormais centralisée hors de
  `subscriptions_page.py`, qui réutilise le service commun existant. La
  sélection des serveurs de migration et la préparation des correspondances
  de bibliothèques sont sorties de `migrations.py`. Les fragments SQL de
  chargement et la normalisation des types de bibliothèques sont désormais
  centralisés hors de `servers.py`, repassé sous 1000 lignes. La découverte de
  la base et du serveur Plex associé est sortie de `import_tautulli.py`. La
  sélection des modèles et fenêtres d'expiration est également centralisée
  hors de `send_expiration_emails.py`, désormais sous 1000 lignes. La fusion
  et sa prévisualisation sont sorties de `users_list.py`, maintenant largement
  sous 1000 lignes. Le blueprint Users réutilise le service commun des
  abonnements et délègue désormais l'envoi de bienvenue ainsi que le
  provisionnement Plex/Jellyfin à des services dédiés; il est lui aussi sous
  1000 lignes. Les politiques, leur validation et les modèles par défaut sont
  sortis de `subscriptions_page.py`, maintenant sous 1000 lignes. Le classement
  et la sélection des modèles Communications sont centralisés hors de
  `communications_engine.py`, lui aussi repassé sous 1000 lignes. Les appels
  HTTP de découverte utilisateur et de comptage des bibliothèques Jellyfin sont
  isolés hors de `sync_jellyfin.py`, désormais sous 1000 lignes.
- [~] Uniformiser les acces DB applicatifs restants. Les connexions SQLite de
  bootstrap, config, logs, restauration et suppression serveur passent deja
  par `open_sqlite_connection`.
- [~] Supprimer le code mort apres une passe outillee dediee.

### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>`: proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## P4 - Migrations et providers

- [ ] Definir le cycle de vie complet des comptes provider marques `removed`:
  affichage et filtres dans l'interface, restauration/reassociation si le compte
  reapparait, conservation de l'historique et suppression locale controlee.
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

## P8 - Partie utilisateur et ouverture externe

- [ ] Permettre au compte admin de se connecter via un compte Plex.
- [ ] Dans l'ajout d'un serveur Plex, proposer la recherche des serveurs lies
  au compte Plex selectionne comme methode de connexion.
- [ ] Creer un acces web utilisateur configurable depuis un nouveau menu admin.
  - Login possible via compte admin, Plex, Jellyfin ou email standard.
  - Donner a l'utilisateur acces a son profil, son abonnement, les informations
    liees a son compte et son propre monitoring.
  - Gerer les roles et autorisations: admin, utilisateur et roles futurs.
  - Configurer le domaine ou lien d'acces.
  - Definir les regles d'acces, mots de passe, validations et zone support.
- [ ] Ajouter les possibilites Plex et Jellyfin encore manquantes, notamment
  l'edition du profil.
- [ ] Ajouter un mecanisme ou un lien de paiement aux profils utilisateurs.
- [ ] Ajouter une API publique apres cadrage: donnees exposees, objectifs,
  securite, quotas et authentification.
- [ ] Ameliorer la creation d'utilisateur et les emails d'invitation depuis
  l'espace web VODUM:
  - creation automatique, assistee ou controlee des comptes Plex/Jellyfin;
  - liens de telechargement des lecteurs media;
  - aide a la configuration du lecteur.

### Securite des acces publics

- [ ] Integrer Cloudflare Turnstile comme protection anti-automatisation
  optionnelle des formulaires publics.
  - Ajouter la configuration dans la modale de securite Settings, sous la 2FA,
    tout en gardant Turnstile independant de la 2FA.
  - Prevoir les modes compact et invisible, avec choix des formulaires
    proteges: connexion admin, reinitialisation du mot de passe et futurs acces
    utilisateurs.
  - Demander une Site Key et une Secret Key; masquer et chiffrer la Secret Key
    avec le mecanisme de secrets existant.
  - N'autoriser l'activation que lorsque la configuration est complete et
    proposer un test affichant clairement son etat de validite.
  - Valider chaque jeton cote serveur via l'endpoint Cloudflare `siteverify`,
    avec timeout court, controle du hostname et journalisation sans secret.
  - Definir explicitement le comportement en cas d'indisponibilite Cloudflare
    afin de ne pas verrouiller accidentellement toute l'administration.
  - Conserver les protections anti-bruteforce et 2FA existantes: Turnstile les
    complete et ne les remplace pas.
  - Prevoir un moyen de recuperation locale/admin en cas de cle ou de widget
    mal configure, ainsi que les traductions et ajustements CSP necessaires.

## Notes de prudence

- Ne pas supprimer le cache artwork existant: il est utile et deja raccorde
  aux headers HTTP.
- Ne pas remplacer `sync` par `revoke` partout cote provider: Plex a
  volontairement un garde-fou contre sync vide.
- Les optimisations SQL doivent etre validees avec la vraie base et
  `EXPLAIN QUERY PLAN`; ajouter trop d'index peut ralentir les ecritures et le
  bootstrap.
- Les modifications de fichiers contenant du texte corrige doivent rester
  ciblees pour eviter de recreer du mojibake.
