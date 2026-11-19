# Changelog

Les changements non publiés sont regroupés dans ce fichier. Les dates indiquent
la mise à jour du journal, sans confirmation de déploiement en production.
L’historique antérieur est conservé dans le [journal archivé](changelog-archive-2026-11-19.md).

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
