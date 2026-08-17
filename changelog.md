# Changelog

- Le nom de marque affiché dans les en-têtes mobile et bureau est désormais un
  lien direct vers le tableau de bord, afin de faciliter la navigation sur les
  petits écrans.
- Amélioration de l'ergonomie du rapport des risques : le détail d'un
  utilisateur s'ouvre désormais en cliquant directement sur sa ligne, avec un
  contour visuel au survol et une navigation clavier accessible. La colonne et
  les boutons « Voir les détails » ont été supprimés.
- Correction de l'analyse des risques de partage : les indices liés aux IP et
  aux appareils fixes sont désormais évalués selon le nombre d'IP autorisé par
  le forfait courant. Plusieurs appareils fixes ne sont donc plus considérés
  comme suspects tant qu'ils restent cohérents avec cette capacité, tandis que
  les dépassements réels et les arrêts répétés continuent d'augmenter le score.
  Les forfaits sans policy active `max_ips_per_user` sont traités comme ayant
  un nombre d'IP illimité.
- Grande passe de contrôle après clôture P4 : les comptes Plex legacy possédant
  une identité acceptée mais aucune date `accepted_at` ne sont plus confondus
  avec des invitations en attente, et les métadonnées de présence survivent au
  rafraîchissement du payload Plex sans réécriture à chaque synchronisation.
- Durcissement du cycle des identifiants Jellyfin : le mot de passe temporaire
  est également purgé du payload Communications après livraison ou expiration.
  Une révélation manuelle clôt l'envoi planifié et empêche ainsi une seconde
  remise automatique. Les providers sont en outre validés avant toute mutation
  d'accès déclenchée depuis l'administration Migrations.
- Clôture du P4 côté développement : les capacités avancées déclarées par les
  providers sont désormais appliquées aux suppressions et rollbacks, l'action
  d'accès vide est explicite (`revoke` pour Plex, `sync` pour Jellyfin) et les
  imports de plans refusent immédiatement tout provider inconnu ou mapping mal
  formé. Le cycle `removed`, le registre de capacités, les migrations Jellyfin
  et leur suivi administratif sont complets dans le périmètre automatisable;
  seule la validation sur grandes instances réelles reste suivie en P0.
- Contrôle de clôture P4 : 403 tests, les 38 validateurs du projet, les audits
  de bootstrap, routes, traductions et encodage, ainsi que les smoke tests
  Docker, runtime applicatif et routes passent.
- La remise automatique des identifiants Jellyfin est maintenant réconciliée
  avec la file Communications dans l'audit Migrations : succès et canaux
  utilisés, retry planifié ou échec définitif. Après un envoi confirmé, le mot
  de passe chiffré est immédiatement purgé; il reste disponible lors des
  erreurs temporaires pour permettre les nouvelles tentatives ou une remise
  manuelle sécurisée.
- Le détail des campagnes Migrations offre désormais aux administrateurs un
  suivi complet des destinations Jellyfin : date de création du compte,
  identifiants temporaires en attente avec leur échéance, révélation ou
  expiration. Ces diagnostics n'exposent jamais le mot de passe lui-même et
  sont traduits dans les cinq catalogues de l'interface.
- Les capacités Migrations de chaque provider sont maintenant déclarées dans un
  registre typé et immuable : mode de création du compte, exigence d'email,
  gestion des bibliothèques, suppression/rollback d'accès et worker associé.
  L'analyse et la phase 3 utilisent ce contrat commun; un futur provider non
  enregistré est rejeté explicitement au lieu d'être traité comme Jellyfin.
- Le cycle de vie des comptes provider absents est désormais complet pour Plex
  comme pour Jellyfin : la synchronisation marque les comptes disparus
  `removed`, les réactive à `present` lors de leur retour et conserve leurs
  métadonnées pour l'affichage, le filtrage et la suppression locale contrôlée.
  Plex ne déduit aucune disparition d'une réponse vide, d'un serveur
  indisponible, d'un compte propriétaire ou d'une invitation encore en attente.
- Fiabilisation du suivi Plex en temps réel : les rafraîchissements websocket
  répétitifs sans changement passent en niveau debug, tandis que le démarrage,
  les changements de nombre de sessions et les événements de lecture restent
  visibles en information.
- Les indisponibilités temporaires d'un serveur Plex sont désormais consignées
  comme avertissements sans traceback dans les logs normaux, avec le détail
  complet conservé lorsque le mode debug est actif.
- Renforcement de l'arrêt des lectures Plex : lorsqu'une première demande de
  terminaison est acceptée mais que la session reste visible pendant une
  transition, VODUM réessaie la commande et ne considère l'arrêt réussi
  qu'après la disparition effective de la session.
- Mémorisation des arrêts récents par policy, serveur et utilisateur afin de
  gérer correctement les sessions automatiquement recréées par un lecteur et
  de réévaluer immédiatement une récidive sans accorder un nouveau délai
  complet d'avertissement.
- Correction du comptage des flux Plex lors du remplacement d'une session :
  plusieurs sessions cohérentes correspondant au même appareil, endpoint et
  contenu restent comptées comme une seule lecture pendant tout leur
  chevauchement, au lieu de devenir artificiellement plusieurs flux après deux
  cycles.
- Conservation de la détection des usages réels : deux contenus différents sur
  un endpoint faiblement identifié ne sont pas fusionnés indéfiniment et
  continuent à compter comme des lectures distinctes après la grâce prévue.
- Correction des recommandations d'abonnement : l'absence de policy active
  `max_ips_per_user` signifie désormais que le forfait possède un nombre d'IP
  illimité, au lieu d'être interprétée comme une capacité de zéro IP.
- Les policies IP désactivées sont maintenant réellement ignorées pendant le
  calcul des abonnements suggérés; une limite IP explicitement activée reste
  pleinement appliquée.
- Les forfaits supérieurs sans plafond IP, notamment le forfait Famille,
  peuvent ainsi être suggérés aux utilisateurs dépassant les capacités IP des
  forfaits Base ou Plus, sous réserve des seuils d'arrêts, de flux, de valeur et
  de cooldown déjà configurés.
- Clôture de l'uniformisation des accès SQLite applicatifs après audit : toutes
  les ouvertures directes restantes dans `app` passent désormais par le helper
  commun, à l'exception de l'implémentation centrale elle-même.
- Première passe outillée de nettoyage du code mort : suppression de 31 imports
  inutilisés dans les pages principales, services Plex/Jellyfin, helpers web,
  sauvegarde et assistant de configuration, sans retirer les alias de
  compatibilité encore consommés par les tests et intégrations historiques.
- Finalisation de la passe de code mort avec 25 imports supplémentaires et sept
  variables sans effet retirés des tâches de synchronisation, d'expiration, de
  monitoring et de création utilisateur. Les façades historiques de
  `stream_enforcer` sont désormais annotées explicitement et l'audit Ruff des
  imports, symboles et variables inutilisés ne remonte plus aucune erreur.
- Centralisation de l'application des restrictions de dossiers Jellyfin dans le
  service provider commun : le worker d'accès conserve son contexte HTTP, ses
  timeouts et son fallback POST vers PUT sans maintenir une seconde logique
  active de mise à jour des policies.
- Première étape du cycle de vie des comptes Jellyfin supprimés : le marquage
  `removed` est centralisé dans le référentiel de synchronisation et les comptes
  retrouvés lors d'un sync repassent explicitement à l'état `present`, avec
  identifiant provider et date de contrôle actualisés.
- Affichage de l'état provider dans l'onglet Accès utilisateur : les comptes
  Jellyfin disparus portent désormais un badge `Removed from provider`, leur
  dernière date de contrôle est visible et les cartes peuvent être filtrées
  entre comptes présents et supprimés.
- Ajout d'une suppression locale contrôlée des comptes provider absents :
  l'action POST vérifie l'appartenance à l'utilisateur et exige l'état
  `removed`, protège les rôles owner/admin et s'appuie sur les clés étrangères
  existantes pour conserver les événements et historiques en les détachant du
  compte local supprimé.
- Traduction complète en français, anglais, allemand, espagnol et italien des
  nouveaux filtres, statuts, confirmations et retours d'action du cycle de vie
  des comptes provider supprimés.
- Passe de contrôle après refactor : suppression de l'ancienne implémentation
  Jellyfin restée en doublon derrière le service provider commun, avec
  conservation d'un simple alias de compatibilité pour les intégrations
  historiques.
- Correction des imports de fusion utilisateur après le nettoyage du code
  mort : les routes d'action et de détail importent maintenant directement les
  services `user_merge` et `user_merge_suggestions`. Un smoke test reproduisant
  la disposition Python plate de l'image Docker protège désormais le démarrage
  Waitress contre ce type de rupture.
- Deux premiers lots de finalisation P3 sur les abonnements : la recherche et
  la pagination des utilisateurs auxquels appliquer un forfait, puis le
  chargement et la préparation des policies pour la liste et l'éditeur, sont
  sortis de `subscriptions_page.py` vers un service de données testé. Les
  bornes de pagination et les payloads JSON non objets sont traités de façon
  déterministe.
- Deux lots P3 supplémentaires sur les abonnements : les données communes des
  onglets (réglages, serveurs, utilisateurs cadeaux et catalogue des forfaits)
  sont chargées par le service de page, tandis que la duplication, l'activation
  et la suppression des modèles sont centralisées dans un service
  d'administration testé, avec désaffectation des utilisateurs avant
  suppression conservée.
- Deux lots P3 Users : la validation, la persistance JSON et la mise en file des
  options de partage Plex unitaires sont centralisées dans le service des
  options utilisateur. Le toggle d'une bibliothèque est sorti de la route vers
  un service d'accès commun Plex/Jellyfin qui conserve le blocage des comptes
  expirés, le scope strict au serveur, les actions grant/sync/revoke, la
  déduplication des jobs et le réveil tolérant des workers.
- Deux lots P3 Migrations : la relance manuelle de la réconciliation des
  invitations et la validation d'une destination sont sorties de la route. Les
  suppressions/restaurations d'accès source et le rollback destination partagent
  maintenant une orchestration testée qui valide le nom de campagne, interdit
  la suppression en mode copie, choisit le worker du provider et réveille
  ensuite le worker Migrations dans l'ordre historique.
- Deux lots P3 Setup : la lecture, le décodage et la persistance bornée de
  l'état de l'assistant sont centralisés dans un service. La validation puis la
  création chiffrée des serveurs Plex/Jellyfin, l'activation des tâches, le
  lancement de la découverte et le comptage strict des serveurs validés par
  l'assistant sont également sortis de la route et couverts par des tests.
- Deux derniers lots P3 Setup : les règles de navigation et de saut des étapes
  optionnelles, puis le chargement complet des données de rendu sont extraits
  de la route. Les secrets SMTP, OAuth et Discord restent masqués dans le
  contexte du template, avec couverture des transitions et du marquage des
  serveurs validés. Cette série de six lots P3 est terminée.
- Contrôle fonctionnel global après les extractions P3 : 396 tests, tous les
  validateurs métier, le bootstrap et l'intégrité d'une base neuve, les routes,
  l'authentification, les protections CSRF, les traductions, la compilation et
  les imports Docker sont validés. Le contrôle de création serveur a été mis à
  jour pour suivre la nouvelle frontière route/service et éviter un faux échec
  de CI.
- Audit approfondi en exécution réelle : parcours de l'assistant Setup, du
  Dashboard, des abonnements, utilisateurs, migrations et policies, puis test
  du cycle duplication/suppression d'une formule sur une base isolée. Correction
  des dernières chaînes UTF-8 corrompues dans les abonnements, citations et
  messages de bootstrap, ainsi que de statuts restés en anglais dans plusieurs
  catalogues. Un audit d'encodage permanent empêche désormais leur retour.
