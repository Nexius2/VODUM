# Changelog

Les changements non publiés sont regroupés dans ce fichier. Les dates indiquent
la mise à jour du journal, sans confirmation de déploiement en production.
L’historique antérieur est conservé dans le [journal archivé](changelog-archive-2026-11-19.md).

## Non publié — mise à jour du 2026-11-21

### Seerr comme service de demandes du portail

- Nouveau type de serveur `seerr` (Overseerr/Jellyseerr) détecté automatiquement
  à l'ajout via `/api/v1/auth/me` ([détection](app/core/server_detection.py)),
  vérifié par la tâche de contrôle des serveurs ([connexion](app/core/seerr_connections.py)).
  La clé API est chiffrée comme les autres secrets ; aucune synchronisation.
- Les [routes de demandes](app/core/library_request_routing.py) acceptent un
  serveur Seerr pour les bibliothèques de films et de séries, avec les mêmes
  conditions (genres, collections). La fiche serveur Seerr propose uniquement
  l'option « demander les versions 4K » ; profils et dossiers restent gérés par Seerr.
- Portail : la recherche interroge Seerr (`/api/v1/search`) pour les bibliothèques
  routées vers lui et conserve l'origine de chaque résultat. La soumission
  ([Seerr](app/core/portal_media_requests_seerr.py), [demandes](app/core/portal_media_requests.py))
  associe le membre à l'utilisateur Seerr par identifiant Plex ou Jellyfin, lit le
  statut déjà connu de Seerr (disponible / en cours) et envoie la demande au nom du
  membre (`/api/v1/request`). Sans utilisateur Seerr correspondant, message
  explicite et aucune demande. Les réponses « doublon » et « quota/permission »
  de Seerr sont traduites ; une demande en attente d'approbation est signalée.
  Aucune analyse de bibliothèque par VODUM pour ces routes.
- Le réglage « Demandes de médias » du portail est activable dès qu'un ARR
  configuré ou un serveur Seerr existe ([réglages portail](app/routes/portal_admin.py)).
  Le statut système du portail inclut les Seerr routés.
- Migration additive au démarrage : colonne `portal_media_request_jobs.source`
  (`arr` par défaut) ajoutée par le [bootstrap portail](app/core/db_bootstrap_portal.py),
  index des travaux actifs recréé avec cette colonne. Déployer Python, templates,
  script et traductions ensemble puis redémarrer. Traductions dans les cinq langues ;
  tests locaux (logique de correspondance, charge utile, flux de soumission simulé)
  uniquement, sans validation en production. Limites : toutes les saisons sont
  demandées pour une série ; pas de suivi de l'approbation après la soumission.
- Documentation : [demandes de médias](vodum-docs/docs/media-requests.md) et
  [serveurs & bibliothèques](vodum-docs/docs/servers-libraries.md).
- Fiche serveur Seerr simplifiée : la section de routage ([template](templates/servers/_request_routing.html))
  n'affiche pour un Seerr qu'une case par bibliothèque (« les membres peuvent
  demander via Seerr »), sans ordre ARR, priorités ni critères, puisque Seerr
  choisit lui-même la cible, le profil et le dossier. La priorité est calculée
  automatiquement pour ne pas entrer en conflit avec un ARR déjà lié. Les fiches
  Sonarr/Radarr sont inchangées. Trois nouveaux libellés dans les cinq langues ;
  rendu et aller-retour du formulaire vérifiés par tests locaux.

## Non publié — mise à jour du 2026-11-19

### Libellés intégrés aux jauges CPU/RAM

- Les libellés des [mini-jauges](templates/dashboard/partials/_server_resource_mini_bars.html)
  se lisent désormais de bas en haut et sont superposés au remplissage.
  L'emplacement total reste de 28 pixels pour préserver l'alignement des statuts.
- Aucune migration ; déployer le template. Rendu et tests locaux vérifiés,
  sans modification des mesures ni des conditions d'affichage.

### Jauges de ressources verticales et alignement des statuts

- Les [jauges CPU/RAM](templates/dashboard/partials/_server_resource_mini_bars.html)
  sont désormais verticales, avec leurs libellés écrits verticalement et un
  remplissage de bas en haut. Leur emplacement occupe seulement 28 pixels et
  reste réservé sans données, pour aligner les badges Online/Offline de toutes
  les cartes. Aucun pourcentage n'est affiché.
- Aucune migration ; déployer les templates de la carte Serveurs. Rendu et
  tests du dashboard vérifiés localement ; collecte des mesures inchangée.

### Barres CPU et RAM dans la carte Serveurs du dashboard

- La [carte Serveurs](templates/dashboard/partials/_servers.html) affiche à
  droite du statut deux [mini-barres CPU/RAM](templates/dashboard/partials/_server_resource_mini_bars.html),
  sans pourcentages visibles. Chaque barre apparaît uniquement si sa mesure
  est disponible ; une charge nulle reste une mesure valide.
- Le [chargement des mesures](app/core/dashboard_servers.py) réutilise les
  données du monitoring de moins de dix minutes, pour les serveurs affichés,
  au premier rendu et lors des actualisations. Aucun appel réseau ni nouvelle
  collecte ; mesures absentes, périmées, invalides ou serveur hors ligne :
  aucune barre trompeuse à zéro. Les fournisseurs sans métriques compatibles
  conservent leur carte habituelle.
- Aucune migration ; déployer les modules Python et les deux templates ensemble.
  Les 34 tests locaux du dashboard passent, dont disponibilité partielle, zéro,
  fraîcheur, absence de table et rendu sans nombres visibles. Pas de validation
  en production.

### Icônes du tableau des bibliothèques

- Les flèches de tri du [tableau Monitoring / Bibliothèques](templates/monitoring/tabs/libraries.html)
  utilisent des entités HTML à la place des caractères corrompus. Les symboles
  de taille minimale et de valeur absente du même tableau sont également réparés.
  L'état du tri est annoncé aux lecteurs d'écran ; les liens de tri sont conservés.
- Aucune migration ; déployer le template. Rendu vérifié localement pour les
  deux sens de tri et les colonnes inactives, sans validation en production.

### Information sur la collecte initiale

- Le [tableau de bord](templates/dashboard/dashboard.html) affiche pendant les
  24 premières heures de l’instance un message indiquant que les synchronisations
  et collectes peuvent prendre plusieurs heures et que les données apparaissent
  progressivement. Le bandeau disparaît aussi si la page reste ouverte.
- La [date persistante](app/core/initial_sync_notice.py) ne repart pas à zéro lors
  d’un redémarrage ou d’une relance de l’assistant. Sur une base existante, la
  date historique la plus ancienne des marqueurs d’initialisation ou des
  utilisateurs est reprise. Sans date exploitable, une ancienne base ne reçoit
  pas artificiellement une nouvelle période de 24 heures.
- Migration additive au démarrage : colonne `settings.instance_started_at`,
  ajoutée par le [bootstrap](app/core/db_bootstrap_settings.py) et initialisée
  pour les nouvelles instances par les [réglages initiaux](app/core/db_bootstrap_base_settings.py).
  Déployer Python, schéma, template, script et traductions ensemble, puis
  redémarrer avant de consulter le dashboard. Message traduit dans les cinq
  langues ; vérifications locales uniquement.

### Nettoyage après publication

- Le [TODO](TODO.md) ne conserve plus les éléments cochés comme terminés ; les
  objectifs et validations encore ouverts sont préservés.
- Le journal précédent a été archivé puis ce fichier réinitialisé à la demande
  de l’administrateur après publication. Aucune version ni date de publication
  n’a été ajoutée, et INFO n’a pas été modifié par ce nettoyage.
