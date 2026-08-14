# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines
sont documentes dans `changelog.md`.

Derniere mise a jour: 2026-08-02

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
  services et les taches. Le worker d'acces Jellyfin reutilise maintenant le
  service provider commun pour lire et mettre a jour les policies de dossiers.
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
  de bibliothèques sont sorties de `migrations.py`. Le chargement des campagnes
  récentes et l'agrégation de leurs compteurs sont maintenant dans le même
  service de page, tout comme l'enrichissement des utilisateurs et le résumé
  de la page de détail, la normalisation des options de campagne et la
  pagination des utilisateurs. Les lectures des utilisateurs, mappings et
  bibliothèques destination de cette page y sont également centralisées. La
  construction sécurisée du rapport de campagne est isolée dans un service
  dédié. Les colonnes et lectures de campagne partagées avec ce rapport sont
  regroupées dans un référentiel Migrations. Les fragments SQL de
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
  isolés hors de `sync_jellyfin.py`, désormais sous 1000 lignes. La réplication
  des options Plex entre serveurs de même propriétaire est sortie de
  `users_detail.py` vers un service utilisateur testé. La lecture du formulaire,
  la persistance de ces options et la création dédupliquée des jobs de
  synchronisation Plex utilisent désormais ce même service. La modification
  administrative des parrains et la normalisation des overrides de profil
  sont également isolées de `users_detail.py` dans des services testés. Les
  lectures partagées du profil/réglages/providers ainsi que les requêtes des
  comptes serveur et bibliothèques accessibles sont regroupées dans un
  référentiel dédié. Dans la tâche d'accès Plex, le parsing XML des sections et
  partages ainsi que l'identification robuste du partage utilisateur sont
  maintenant isolés dans des services provider testés. La construction des
  requêtes HTTP Jellyfin, leur authentification, la découverte des serveurs et
  la sélection de leur URL sont également sorties de `sync_jellyfin.py`. La
  normalisation du rôle, de la date de création et de l'avatar utilisateur,
  puis la persistance du payload Jellyfin complet, sont centralisées dans un
  service de métadonnées. L'initialisation de l'expiration au premier accès et
  le matching des profils VODUM/placeholder par username sont aussi isolés de
  la tâche dans des services testés. Les écritures des bibliothèques, de l'état
  des comptes média et de leurs accès par serveur sont regroupées dans un
  référentiel de synchronisation Jellyfin.
  La suppression serveur utilise désormais un service dédié pour ses lots SQL,
  son garde de concurrence atomique, la lecture de sa cible et le lancement
  normalisé de son thread. L'ordre complet des suppressions directes et des
  relations jusqu'au commit final est également sorti du traitement de fond;
  leur orchestration et la fermeture sûre de la connexion sont centralisées.
  L'ouverture configurée et l'ordre des compteurs de journal sont aussi dans le
  service. Les journaux, erreurs, fermeture et libération du garde sont enfin
  orchestrés par le worker dédié; la route ne garde qu'un adaptateur de thread.
  Les listes Serveurs et Bibliothèques délèguent maintenant leurs requêtes,
  agrégats et tris validés au service de page commun. Le détail serveur lui
  délègue aussi le comptage et le chargement paginé de ses bibliothèques et
  utilisateurs média, ainsi que le chargement de son enregistrement principal.
  Le comptage global de la liste Bibliothèques est également centralisé.
  Le workflow de synchronisation serveur délègue désormais la lecture de la
  cible, la sélection des utilisateurs Plex éligibles, la construction des
  contrats de jobs, leur insertion dédupliquée, le réveil tolérant du worker et
  le résultat métier à un service dédié; la route ne conserve que le flux HTTP.
  La création serveur délègue maintenant la résolution du type de formulaire et
  la normalisation de l'URL Plex/Jellyfin à des fonctions pures testées. La
  sauvegarde réutilise la même résolution du type et la création délègue aussi
  la forme optionnelle de ses paramètres Tautulli. La sérialisation/chiffrement
  des secrets et l'insertion SQL complète de la création sont centralisés dans
  un service d'administration serveur. Le commit de compatibilité et la mise en
  file tolérante de la découverte y sont également isolés. L'activation avant
  commit, les signaux après commit et le résultat UI de création sont désormais
  centralisés tout en conservant leur ordre transactionnel. La sauvegarde
  délègue maintenant la lecture des secrets existants et son UPDATE complet au
  même service d'administration. Le décodage tolérant des paramètres et leur
  fusion Tautulli/`verify_tls` avec conservation des secrets y sont aussi isolés.
  Leur sérialisation/chiffrement final et les signaux post-UPDATE sont désormais
  centralisés; la route de sauvegarde ne conserve que le flux HTTP.
  Les routes d'accès en masse délèguent aussi le réveil tolérant du worker Plex
  et leurs journaux contextualisés au service de bibliothèques existant.
  Les types supportés et les erreurs d'URL de création sont enfin validés par le
  service de formulaire commun à la création et à la sauvegarde.
  La lecture complète des champs de création et de sauvegarde y est également
  centralisée, avec nettoyage des imports de route devenus inutiles. Côté
  abonnements, la recherche/pagination des utilisateurs ainsi que le chargement
  et la préparation des policies sont maintenant isolés dans le service de
  données de page. Les données communes des onglets et le cycle
  duplication/activation/suppression des modèles sont également sortis de la
  route. Dans les routes Users, les mises à jour unitaires des options de
  partage Plex et le toggle d'accès aux bibliothèques Plex/Jellyfin sont
  désormais portés par des services dédiés. Dans Migrations, la validation
  manuelle et la réconciliation d'invitations, puis l'orchestration des trois
  opérations d'accès de phase 3, sont également sorties de la route. Dans
  l'assistant Setup, la persistance de la progression et le workflow de
  validation/création des serveurs sont maintenant centralisés hors de la
  couche HTTP. Sa navigation conditionnelle et la préparation sécurisée des
  données de rendu sont également extraites, ce qui termine les six lots P3
  planifiés sur Subscriptions, Users, Migrations et Setup.
  Contrôle global effectué après clôture : les 396 tests, tous les validateurs
  métier, le bootstrap d'une base neuve avec intégrité/FK, les contrats des
  routes et protections CSRF, les catalogues de traduction, la compilation et
  les imports dans la disposition Docker passent. Le validateur historique de
  création serveur a été adapté à la nouvelle frontière route/service afin que
  la CI protège réellement cette extraction.
  Une seconde passe en exécution réelle a couvert le parcours Setup, les pages
  Dashboard, Subscriptions, Users, Migrations et Monitoring Policies, ainsi que
  la duplication et la suppression d'une formule sur une base temporaire. Elle
  a permis de corriger les dernières chaînes mojibake et plusieurs statuts non
  traduits; un audit UTF-8 reproductible est maintenant inclus au projet.
### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>`: proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## P4 - Migrations et providers

- [ ] Definir le cycle de vie complet des comptes provider marques `removed`:
  affichage et filtres dans l'interface, restauration/reassociation si le compte
  reapparait, conservation de l'historique et suppression locale controlee.
  Le cycle Jellyfin couvre maintenant le marquage centralise, le retour a
  `present`, l'affichage et le filtre dans l'onglet Acces, ainsi que la
  suppression locale reservee aux comptes confirmes absents avec conservation
  de l'historique. Il reste a appliquer le meme contrat aux comptes Plex.
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
