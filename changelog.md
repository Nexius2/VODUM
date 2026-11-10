# Changelog

Les changements non publiés sont regroupés en tête de ce fichier. Les dates
indiquent la mise à jour du journal, pas une confirmation de déploiement.

## Non publié — mise à jour du 2026-11-10

### Exclusions Git et Docker

- Le [contexte Docker](.dockerignore) inclut explicitement le module Python
  des migrations masqué par le filtre des fichiers d’identifiants. Le
  [Dockerfile](Dockerfile) vérifie aussi la présence des fichiers de démarrage.
  Reconstruire l’image et recréer le conteneur. Aucune migration.
- Les [règles Git](.gitignore) excluent les tests, rapports d’audit et formats
  courants de données locales. Les tests précédemment suivis sont retirés de
  l’index et restent disponibles localement. L’historique Git est conservé.
- Le [contexte Docker](.dockerignore) est limité aux fichiers nécessaires au
  Dockerfile et exclut aussi les artefacts locaux dans les sous-dossiers
  applicatifs. Reconstruire l’image pour appliquer ces exclusions. Aucune migration.

### Déploiement de la télémétrie

- La procédure du Worker inclut la migration D1 du 2 novembre pour le schéma 4.
  Appliquer uniquement les migrations manquantes, puis déployer le Worker avant
  de mettre à jour les clients VODUM. Aucun changement au schéma SQLite local.
  Voir l'[ordre de déploiement](docs/telemetry-languages.md).

### Limites de lectures Plex

- Le [contrôle des flux](app/tasks/stream_enforcer.py) diffère la coupure
  pendant les 30 premières secondes d'une nouvelle session Plex si le
  [chevauchement](app/core/stream_sync_dedupe.py) avec une lecture du même
  contenu suffit à expliquer le dépassement de la limite par utilisateur ou
  par IP. Le serveur, le compte, l'identifiant de l'appareil et l'IP doivent
  correspondre. Un dépassement persistant est de nouveau sanctionnable après
  ce délai. Une limite à zéro reste immédiate.
- Déployer ensemble le contrôle et son module de détection. Aucune migration.

### Top streaming par pays

- Le [moteur régional](app/core/collections_country_availability.py) fusionne
  les dix premiers films de chacune des six plateformes de référence
  disponibles dans le pays choisi, puis trie les films par popularité TMDb.
  Pour les séries, il parcourt cinq pages de tendances mondiales TMDb de la
  semaine et ne garde que les titres accessibles en streaming dans ce pays.
  La disponibilité est locale, le classement des tendances reste mondial.
- Le [moteur de publication](app/core/collections_streaming.py) applique la
  limite avant de chercher les titres en bibliothèque. La clé TMDb partagée
  sert aux deux classements. Une collecte incomplète préserve la publication.
- Déployer le moteur, la [reprise de publication](app/core/collections_publication.py)
  et les libellés ensemble, puis relancer les collections. Aucune migration.

### Collections par plateforme et journaux

- Le [moteur par plateforme](app/core/collections_platforms.py) enregistre la
  reprise lorsque le budget de recherche de disponibilité est atteint.
  Le [planificateur](app/tasks/run_collections.py) conserve le code connu
  d'échec de publication et les [journaux](app/core/log_presentation.py)
  affichent la collection, la bibliothèque et l'exécution figurant dans
  les résumés d'échec. Déployer les trois fichiers ensemble. Aucune migration.

## Changements précédant la publication du 2026-11-09

### Langues et acquisition des collections

- Le [moteur](app/core/collections_streaming.py) ignore le filtre de piste
  audio en mode ARR seul et applique la limite configurée. En mode
  publication, la piste audio reste un critère pour les fichiers locaux.
  Les filtres explicites de langue originale et de pays restent actifs.
  Déployer avec les [libellés](translations/ui/fr.json) mis à jour.
  Aucune migration.

### Acquisition des titres absents avec filtre audio

- Le [moteur](app/core/collections_streaming.py) applique le filtre audio
  aux titres présents et soumet les titres absents éligibles selon le
  classement configuré. Le [popup](static/js/pages/collections.js) affiche
  le résultat ARR de chaque titre listé. Le formulaire retire le message
  permanent de demande en cours. Déployer le moteur et l’interface ensemble.
  Aucune migration.

### Liste des films absents

- Le [moteur](app/core/collections_streaming.py) relève les titres absents
  avant le filtre audio et conserve la règle d’acquisition existante.
  Le [popup](static/js/pages/collections.js) indique quand une ancienne
  exécution doit être relancée ou quand aucun titre absent n’a été confirmé.
  Déployer le moteur, le template, le script et les traductions ensemble.
  Aucune migration.

### Identifiants des comptes médias dans le portail

- [Mon profil](templates/portal/profile.html) affiche les identifiants Plex
  et Jellyfin et permet de modifier le nom Jellyfin. La sauvegarde revient
  sur le profil. [État des systèmes](templates/portal/_profile_media.html)
  affiche les accès et leur état en lecture seule. Déployer les templates
  avec la route du portail. Aucune migration.

### Titres manquants dans les collections

- Le [popup des sources](static/js/pages/collections.js) affiche les titres
  absents identifiés lors de la dernière synchronisation, à concurrence des
  places libres. La liste est calculée par le [moteur](app/core/collections_streaming.py)
  sans modifier les demandes ARR. Aucune migration. Déployer le moteur,
  l’interface et les traductions ensemble, puis relancer la collection.

### Bibliothèques Jellyfin supprimées

- La [synchronisation Jellyfin](app/tasks/sync_jellyfin.py) retire les
  bibliothèques absentes d’une réponse complète et leurs liens d’accès locaux.
  Une réponse invalide conserve les données. Les bibliothèques encore
  référencées par une configuration sont conservées et signalées.
  Aucune migration. La mise à jour intervient lors de la prochaine
  synchronisation Jellyfin, planifiée ou manuelle.

### Périmètre de l’inventaire des collections

- Le [scan partagé](app/tasks/refresh_collection_inventory.py) cible les
  bibliothèques liées à une collection configurée. Une ancienne bibliothèque
  sans collection ne peut plus provoquer d’échec du scan. Un HTTP 5xx sur
  une bibliothèque laisse les autres bibliothèques du serveur être scannées.
  Aucune migration. Déployer le moteur et les catalogues de traduction ensemble.

### Inventaire Jellyfin

- Un [inventaire incomplet ou illisible](app/core/collections_media.py) produit
  un avertissement et conserve le dernier inventaire complet. Le scan continue
  sur les autres bibliothèques. Les réponses HTTP 408 et 5xx sont également
  traitées comme des indisponibilités temporaires.
- Les [journaux](app/core/log_presentation.py) affichent le motif fourni par la
  tâche avec le nom de la bibliothèque et du serveur. Aucune migration.

### Historique et taille de la base des collections

- Le [moteur des collections](app/tasks/run_collections.py) conserve le dernier
  résultat terminé par configuration et bibliothèque, ainsi que le suivi du
  traitement actif. Les derniers compteurs disponibles et le détail de la
  dernière publication de chaque objet sont conservés séparément.
- Déployer le [schéma](app/core/db_bootstrap_collections.py) avec le moteur et
  les lecteurs mis à jour. Le [nettoyage](app/core/collections_history.py)
  s'exécute au prochain passage du moteur, configuration par configuration.
  Les anciens résultats détaillés sont supprimés. L'espace libéré est
  réutilisable par SQLite. Pour réduire le fichier sur disque, prévoir un
  VACUUM séparé après sauvegarde, avec suffisamment d'espace libre.

### Profil et accès du portail

- Le [catalogue français](translations/ui/fr.json) traduit Last name par Nom.
  Les alertes du profil sont traduites dans les cinq langues.
- [Mes accès](templates/portal/system_status.html) est déplié par défaut et
  reste repliable. [Documentation](vodum-docs/docs/user-portal.md) actualisée.
- Aucune migration. Déployer le template et les catalogues ensemble.

### Inventaire des collections et incidents temporaires

- La [tâche d'inventaire](app/tasks/refresh_collection_inventory.py) signale
  les timeouts, ruptures de connexion, limitations HTTP 429 et indisponibilités
  HTTP 502/503/504 en avertissement. Elle poursuit le scan des autres serveurs
  et conserve les instantanés précédents. Le journal identifie le serveur et
  la bibliothèque concernés sans déclencher les erreurs génériques du moteur.
- Les serveurs déjà hors ligne sont ignorés et comptés dans le bilan.
  Les refus d'accès, certificats invalides, données invalides et échecs
  d'écriture restent des erreurs.
- Aucune migration. Déployer le code puis redémarrer le worker. Le prochain
  inventaire suit le rythme habituel. Les anciens journaux sont conservés.
  [Tests locaux](tests/test_collection_inventory.py), sans validation en production.

### Remplissage des collections selon le nombre demandé

- Le [moteur de publication partagé](app/core/collections_streaming.py)
  continue dans le classement après les titres absents pour remplir le
  quota de titres locaux. Les demandes ARR restent limitées aux premiers
  titres du classement. Le mode ARR seul conserve sa limite de candidats.
- [Kids](app/core/collections_kids.py) examine jusqu'à 25 pages TMDb au lieu
  de cinq. Les [classements par pays](app/core/collections_top_country.py)
  recherchent jusqu'à 250 candidats, dans leur budget de pagination.
- La [liste des collections](static/js/pages/collections.js) affiche l'écart
  si les titres locaux admissibles ne suffisent pas. Les filtres de date,
  pays, genre et langue ainsi que les limites des sources restent en vigueur.
- Aucune migration. Déployer code, template, script et traductions ensemble,
  puis relancer les collections concernées. Tests locaux, dont un cas Kids
  avec 23 titres locaux sur les cinq premières pages et 50 après pagination.

### Reprise automatique du bloc Serveurs

- Après un échec, le [bloc Serveurs](templates/dashboard/partials/_servers.html)
  conserve ses dernières données et affiche l'avertissement.
  Le [tableau de bord](static/js/pages/dashboard.js) retente le chargement
  toutes les cinq secondes sur l'onglet visible. La première réponse
  réussie remplace le bloc et retire l'avertissement.
- Aucune migration. Déployer le template et le script ensemble.

### Recherche et confirmation des fusions d'utilisateurs

- La [fenêtre de fusion](templates/users/partials/_user_servers.html) filtre
  tous les candidats par nom, identifiant ou e-mail. Afficher tout et
  revenir aux cinq suggestions utilisent une seule liste défilante.
- Le [script](static/js/pages/user-detail.js) gère les boutons directement,
  annule une sélection masquée et attend un aperçu réussi pour le compte
  choisi avant d'activer la confirmation. Le formulaire inclut son jeton CSRF.
- Les [écritures de fusion](app/core/user_merge.py) sont regroupées en une
  transaction SQLite. Un échec annule les transferts déjà effectués.
  Les règles existantes de suppression du compte absorbé s'appliquent aussi
  à ses données du portail liées par suppression en cascade.
- Aucune migration. Déployer le serveur, le template et le script ensemble.
  Vérifications locales avec des comptes de test.

### Portail : état des serveurs en un seul tableau

- La [page État des systèmes](templates/portal/system_status.html) remplace les
  cartes et explications techniques par un tableau : nom du serveur, état,
  dernier contrôle et hors ligne depuis. Les détails des accès restent dans
  une section repliée pour garder la vue principale simple.
- Les [serveurs hors ligne](app/core/portal_system_status.py) apparaissent en
  premier. La date de début de panne utilise `unavailable_since` uniquement
  pour une panne actuelle ; une date absente est indiquée comme non renseignée.
  Aucun historique de panne n'est inventé après le retour en ligne.
- [Tests de tri et d'isolation](tests/test_portal_system_status.py), de pages
  et de traductions locaux. Aucune migration. Déployer code, template et
  traductions ensemble. Données du dernier contrôle enregistré ; aucune sonde
  supplémentaire ni validation sur le serveur utilisateur.

### Bouton de fusion depuis la fiche utilisateur

- Le [bouton Merge user](templates/users/partials/_user_general.html) ouvre
  l'onglet Accès avec la fenêtre et les suggestions de fusion, au lieu de
  recharger Général où cette fenêtre n'est pas présente.
- La [route de la fiche](app/routes/users_detail.py) dirige aussi les anciennes
  URL `?merge=1` vers Accès. Le choix du compte et la confirmation finale
  restent requis ; aucune fusion n'est effectuée par cette navigation.
- Aucune migration. Déployer route et template ensemble. Vérifications locales
  du lien et de l'ouverture ; aucune fusion réelle ni validation en production.

### Avatar Plex/Jellyfin illisible dans la fiche utilisateur

- Le [composant avatar](templates/users/partials/_provider_avatar.html) affiche
  une icône de profil lorsque l'image est absente ou inaccessible, au lieu du
  texte alternatif coupé dans le cercle. Les images chargées restent cadrées
  dans un cercle de taille fixe, sans compression.
- Le [script de la fiche](static/js/pages/user-detail.js) traite aussi les
  erreurs d'image survenues avant son initialisation et après navigation HTMX.
- Aucune migration. Déployer templates et JavaScript ensemble. Cela corrige
  l'affichage de secours sans confirmer la cause d'indisponibilité de l'avatar.

### Portail utilisateur : État des systèmes

- La section Media access des [réglages du portail](templates/settings/portal.html)
  devient État des systèmes. Les [accès](templates/portal/_profile_media.html)
  quittent le profil pour un [onglet dédié](templates/portal/system_status.html)
  avec navigation et aperçu administrateur. L'ancien lien redirige vers cet onglet.
- Le [chargement des états](app/core/portal_system_status.py) reprend les statuts
  et dates de contrôle enregistrés des serveurs Plex/Jellyfin liés au compte,
  ainsi que Sonarr/Radarr via les routages activés et compatibles de ses seules
  bibliothèques autorisées. Services dédupliqués ; états en ligne, hors ligne
  et inconnu distincts. Aucun accès aux adresses, secrets ou autres utilisateurs.
- Lecture et services de demandes sont distingués. Un bouton Actualiser recharge
  la base sans sonder les serveurs. Les états reflètent le dernier contrôle,
  pas une mesure en direct. Les noms et badges sont traduits dans les cinq langues.
- [Tests d'isolation utilisateur](tests/test_portal_system_status.py), routes,
  affichage, permissions et traductions locaux ; [documentation](vodum-docs/docs/user-portal.md)
  actualisée. La suite générale du portail reste limitée par la dépendance
  locale `websocket` absente pour les sept tests de suivi global.
  Aucune migration : réutilisation de `portal_show_media_access`
  et des permissions existantes. Déployer code, templates et traductions ensemble,
  puis redémarrer l'application. Pas de validation en production.

### Allègement de la colonne des compteurs

- Suppression de la ligne Last count et de sa date dans la
  [liste des collections](static/js/pages/collections.js). La colonne voisine
  conserve les dates de dernière fin et de prochain démarrage ; les indications
  de comptage partiel ou non calculé restent affichées.
- Aucune migration ; déployer le JavaScript actualisé. Vérification locale.

### Compteurs des collections conservés hors de la limite d'historique

- La [réponse Collections](app/routes/collections.py) fournit le dernier
  [comptage exploitable](app/core/collections_diagnostics.py) de chaque
  bibliothèque indépendamment des 100 passages récents. Les aperçus,
  commandes de présentation et zéros initiaux d'un traitement en cours
  n'effacent plus le dernier comptage. Les bibliothèques retirées sont exclues
  des totaux affichés.
- La [liste](static/js/pages/collections.js) affiche la date du dernier
  comptage, un total partiel explicite si une bibliothèque n'est pas mesurée,
  ou Non calculé avec invitation à lancer Play. ARR reste toujours renseigné :
  nombre, désactivé, non applicable ou non comptabilisé pour un ancien passage
  sans cette mesure. Aucun zéro fictif n'est utilisé pour une donnée inconnue.
  Spotlight enregistre désormais explicitement son compteur ARR nul.
- [Tests des instantanés](tests/test_collections_diagnostics.py), du rendu et
  de l'API locaux. Aucune migration ; déployer backend, template, JavaScript
  et traductions ensemble. Les chiffres restent ceux du dernier traitement
  mesuré, pas un inventaire temps réel ; relancer pour les actualiser.
  Si aucun historique chiffré n'existe plus, un nouveau calcul est nécessaire.
  Pas de validation sur l'instance utilisateur.

### Journaux lisibles et incidents identifiables

- La [page Logs](templates/logs/logs.html) affiche pour les avertissements et
  erreurs un titre compréhensible, le contexte disponible, la cause connue et
  l'action conseillée. Les traces et JSON restent dans Détails techniques.
- Le [lecteur de diagnostics](app/core/log_presentation.py) couvre collections,
  présentation, inventaire, ARR, tâches, sauvegardes, communications, suivi,
  accès et serveurs. Il distingue timeout, connexion, TLS, refus d'accès et
  ajout incertain ; une cause inconnue est annoncée comme telle. Un compteur
  de relances 0/3 n'est plus expliqué comme trois tentatives épuisées.
- Les [nouveaux diagnostics](app/core/error_reporting.py) de présentation et
  de passage de collection incluent noms et identifiants autorisés. Les anciens
  messages sont expliqués sans inventer les noms absents. Aucune réponse brute
  de fournisseur ni message d'exception ajouté au contexte.
- [Guide des messages](docs/log-messages.md) et [tests de rendu et de sécurité](tests/test_log_presentation.py).
  Explications françaises et anglaises ; repli anglais explicite pour les autres
  langues. Fichiers historiques, niveaux, compteurs et export anonymisé conservés.
  La recherche reste basée sur le texte enregistré. Les incidents ne sont pas
  dédupliqués et toutes les causes ne peuvent pas être déduites d'anciens logs.
- Aucune migration. Déployer code, template et dictionnaires ensemble, puis
  redémarrer les workers pour les nouveaux contextes. Tests locaux ; pas de
  validation production ni correction de la cause réseau par ce seul affichage.

### Lecture des collections Jellyfin avec une clé API

- La [lecture des éléments Jellyfin](app/core/collections_media.py) utilise
  `/Items?Ids=...` avec les champs requis au lieu de `/Items/{id}`, route
  qui exige un contexte utilisateur. L'identifiant retourné et la marque
  de propriété restent contrôlés ; aucune collection externe n'est adoptée.
- Les réponses invalides et éléments absents disposent de messages traduits.
  Le [worker](app/tasks/run_collections.py) conserve le statut HTTP et
  l'opération en échec, sans corps de réponse ni secrets.
- [Test de lecture par clé API](tests/test_collection_inventory.py) local.
  Aucune migration ; déployer code, template et traductions ensemble puis
  redémarrer les workers. Relancer la collection Jellyfin. La capture ne
  contient pas l'exception initiale du passage 1785 : correspondance exacte
  avec ce défaut et publication sur le serveur utilisateur non confirmées.

### Premier inventaire Jellyfin et timeouts des priorités Plex

- Le [worker Collections](app/tasks/run_collections.py) autorise la création du
  [premier inventaire](app/core/collection_inventory.py) d'une bibliothèque
  avant utilisation du cache, pour Jellyfin comme Plex. La collection ne
  s'arrête plus uniquement parce qu'aucun instantané n'a encore été construit.
  Le scan conserve le heartbeat d'annulation et de renouvellement du bail.
  Un scan échoué ne devient pas un inventaire vide réussi ; les inventaires
  anciens ou invalides restent soumis au contrôle existant de rafraîchissement.
- Le [réglage des priorités Plex](app/core/collections_media.py) s'arrête au
  premier timeout ou échec de connexion pendant la vérification des objets.
  Il signale une priorité non appliquée en avertissement, sans multiplier les
  timeouts par collection ni déplacer les hubs sur la base d'un ordre incomplet.
  La commande durable reste en attente de reprise.
- Le chemin Sonarr de réponse perdue a été contrôlé : il réconcilie déjà
  l'ajout par identifiant stable, sans rejouer aveuglément le POST. Aucune
  confirmation de l'ajout particulier de la capture sans accès au serveur.
- [Tests d'inventaire](tests/test_collection_inventory.py), de
  [priorités](tests/test_collections_visibility.py) et de reprise ARR locaux.
  Aucune migration ; déployer le code puis redémarrer les workers. Relancer
  la collection Jellyfin pour initialiser sa bibliothèque. Pas de validation
  sur le serveur utilisateur ; les erreurs historiques restent conservées.

### Tri Plex et métadonnées des sorties récentes

- Le [tri Plex](app/core/collections_media.py) dispose d'une reprise unique par
  l'endpoint documenté `/library/collections/{id}/items/{id}/move` si PlexAPI
  refuse le déplacement avec une autre clé (par exemple metadata). Pas de
  recréation, de suppression ni de boucle de tentatives ; si l'endpoint canonique
  refuse aussi, l'erreur reste visible. La même protection couvre Spotlight.
- Les [sorties récentes](app/core/collections_recent_releases.py) ne demandent
  plus de résolution TVDB pour un film, combinaison non prise en charge par
  TMDB Find. Les identifiants externes malformés ne sont plus envoyés.
- Les identités ou langues inconnues deviennent des avertissements avec un
  code de raison dans les médias non résolus ; les erreurs réseau ou imprévues
  restent des erreurs. La sélection reste partielle et préserve les membres
  existants sans deviner leur langue ni leur identité.
- [Tests de tri](tests/test_collections_ordering.py) et de
  [sorties récentes](tests/test_collections_recent_releases.py) locaux.
  Aucune migration. Déployer le code puis redémarrer les workers et relancer
  les collections concernées. Sans accès au serveur de la capture, le chemin
  exact du refus Plex et sa résolution en production restent à confirmer.
  Les erreurs historiques IMDb et les résumés de tâche restent conservés.

### Audit des autres sources après le rejet IMDb

- [Contrôle documenté](docs/collections-source-validation-audit-2026-11-05.md)
  des validations TMDB, streaming, franchises, saisons et récompenses.
  Les 8 datasets de récompenses, JustWatch/Netflix France films et séries et
  une liste MDBList saisonnière passent les lectures et validations en direct.
  Une liste IMDb saisonnière répond HTTP 202 : indisponibilité constatée,
  distincte du rejet de type IMDb précédemment corrigé.
- Les [récompenses](app/core/collections_awards.py) ne présentent plus un
  échec global des identités TMDB comme un dataset inaccessible. Elles signalent
  une résolution incomplète ou une sélection vide selon le cas. Une erreur de
  dataset marque correctement le diagnostic en échec, à cette étape.
- [Tests de régression](tests/test_collections_awards.py) et suites de sources
  locaux. Pas de clé TMDB dans le processus : requêtes authentifiées et chaîne
  de publication non validées en direct. Aucun contrôle d'intégrité relâché
  sans anomalie reproduite. Aucune migration ; déployer le code puis redémarrer
  les workers. Pas de validation en production.

### IMDb : classement des films populaires contenant un téléfilm

- Le [lecteur IMDb](app/core/collections_imdb.py) accepte le type `tvMovie`
  dans le classement officiel des films populaires (`moviemeter`), en plus
  des films et courts-métrages. Le 2026-11-05, une requête réelle a renvoyé
  HTTP 200 et 100 titres dont un téléfilm : la validation locale rejetait alors
  tout le classement. Les 100 rangs sont conservés ; le filtrage des autres
  classements reste inchangé.
- Une validation de classement en échec conserve désormais le code
  `imdb_source_invalid`, au lieu d'être transformée en source inaccessible.
  La protection des collections existantes en cas d'échec reste en place.
- Les [24 tests IMDb](tests/test_collections_imdb.py) passent. Les 11 classements
  configurés ont aussi été récupérés et validés contre l'API publique IMDb
  depuis l'environnement de développement. Cela ne valide pas la résolution
  TMDB, les demandes ARR ni la publication Plex dans l'instance utilisateur.
- Aucune migration. Déployer le lecteur et redémarrer les workers, puis relancer
  la collection IMDb concernée. Les erreurs de validation ne sont pas mises en
  cache ; aucune purge n'est nécessaire. Pas de validation en production.

### Bouton Play et suivi des synchronisations de collections

- Le bouton [Play](static/js/pages/collections.js) reprend sa forme compacte
  ▷ et demande toujours une synchronisation des médias. Il ne rejoue plus
  uniquement une commande de configuration. Une synchronisation manuelle
  peut remplacer une demande de configuration en attente ; les traitements
  actifs, aperçus, suppressions et nettoyages restent protégés.
- Les [états de collection](app/core/collections_repository.py) ne comptent plus
  les changements de présentation comme des synchronisations en attente. Leur
  état reste indiqué sur la ligne Configuration. Les anciennes demandes de
  présentation déjà appliquées sont réconciliées automatiquement.
- Le résumé affiche le dernier traitement terminé, son résultat, son heure et
  sa durée si disponible, même lorsqu'un passage est plus rapide que le suivi
  toutes les deux secondes. Il n'annonce pas Running avant la prise en charge.
- [Tests HTTP](tests/test_collection_resume_api.py), de commandes, de rendu
  et de traductions locaux ; pas de validation en production. Aucune migration.
  Déployer backend, template, JavaScript et traductions ensemble puis redémarrer.
  Le lancement respecte le planificateur activé, l'activation de la collection
  et les contrôles de disponibilité du serveur.

### Reprise exploitable des demandes de collections

- La [liste](static/js/pages/collections.js) remplace le badge Queued par
  En attente, Suspendue ou Démarrage à relancer selon le diagnostic. Le résumé
  compte les demandes en attente ; les causes identiques sont regroupées entre
  bibliothèques. Suppression du message contradictoire « task is not queued ».
- Un bouton Relancer visible reprend la demande enregistrée, y compris aperçu,
  nettoyage, suppression et configuration, sans remplacer son action. Il reste
  disponible pour un nettoyage de collection désactivée. Les baux actifs restent
  protégés. La [route](app/routes/collections.py) réveille aussi les commandes
  de configuration avant de transmettre le traitement au worker.
- Le [planificateur](app/core/collections_repository.py) ne bloque plus une
  demande sur le seul statut Queued d'une tâche dont le compteur de file est nul.
  Ce cas dispose d'un test de régression ; aucune conclusion sur sa présence
  dans l'instance utilisateur n'est tirée de la capture seule.
- [Tests de reprise HTTP](tests/test_collection_resume_api.py), de demandes et
  [d'affichage](tests/test_collection_queue.js), ainsi que la suite Memoria,
  vérifiés localement. Aucune migration. Déployer backend, template, JavaScript
  et traductions ensemble puis redémarrer l'application. Le bouton ne contourne
  ni un serveur inaccessible ni la désactivation du planificateur. Pas de
  validation en production.

### Comprendre et relancer les collections en attente

- Le [backend](app/core/collections_repository.py) expose, par bibliothèque, le
  motif d'attente observé : planificateur ou tâche désactivés, serveur
  inaccessible, pause réseau, inventaire occupant le worker, traitement en cours,
  demande transmise ou demande enregistrée sans tâche en file.
- La [liste](static/js/pages/collections.js) affiche ce diagnostic et permet
  de retransmettre une synchronisation en attente. Les exécutions actives et
  demandes d'aperçu restent protégées contre leur remplacement.
- Le [template](templates/collections/collections.html) transmet désormais les
  traductions des nouveaux messages au navigateur, dont `none_running` et
  le refus de tri Plex, auparavant ajoutés aux dictionnaires seulement.
- Aucune migration. Déployer backend, template, scripts et traductions ensemble.
  Diagnostic fondé sur l'état enregistré : la cause d'un worker bloqué ne peut
  pas être confirmée par cet état seul. Tests locaux, pas de validation production.

### Visibilité des collections en cours

- La [liste](static/js/pages/collections.js) place les collections Running et
  Stopping en tête et actualise les états toutes les deux secondes. Un
  [résumé](templates/collections/collections.html) nomme les collections en cours
  et compte celles en attente, même quand les lignes sont hors écran.
- Un [bail de travail actif](app/core/collections_repository.py) prime sur un
  état stocké Queued. La phase affichée provient du membre actuellement en cours,
  plutôt que du dernier passage d'une autre bibliothèque.
- Aucune migration. Déployer backend, template, JavaScript et traductions ensemble.
  Le suivi reste périodique : un passage de moins de deux secondes peut ne pas
  être observé. Le compteur global de tâches inclut d'autres traitements.
  Vérifications locales, sans validation en production.

### Diagnostic des erreurs de collections

- Un refus Plex lors du [tri des titres](app/core/collections_media.py) affiche
  une cause traduite : ordre non garanti, publication inachevée, motif exact
  inconnu et conseils de relance et de vérification dans Plex.
- Les [logs du worker](app/tasks/run_collections.py) identifient collection,
  bibliothèque, serveur, passage, étape et code de cause. Le résumé de la tâche
  cite les collections en échec. Aucune réponse brute de Plex n'est exposée.
- Aucune migration. Déployer code et [traductions](translations/ui/fr.json)
  ensemble puis redémarrer les workers. Anciens historiques inchangés ;
  diagnostic testé localement, sans correction du refus Plex ni validation
  en production.

### Échec visible et diagnostic du rafraîchissement des serveurs

- Le [bloc Serveurs](templates/dashboard/partials/_servers.html) conserve ses
  données mais affiche un avertissement et un bouton Réessayer si son
  actualisation échoue. Les états et pics peuvent être anciens ; ce signal ne
  signifie pas que les serveurs médias sont hors ligne. Message traduit.
- Les [logs navigateur](app/core/error_reporting.py) des widgets identifient
  le bloc, la nature de l'échec, son impact et la corrélation avec le diagnostic
  HTTP. Timeout et rupture de transport deviennent des avertissements ; les
  réponses HTTP en échec et erreurs d'insertion restent des erreurs.
- Le [calcul des pics](app/core/dashboard_widgets.py) mesure le temps consacré
  au cache et à la requête, séparément du reste du bloc, pour le diagnostic HTTP. La cause d'un timeout
  n'est pas présentée comme connue sur la seule base du signal navigateur.
- Aucune migration. Déployer code, templates, traductions et JavaScript ensemble,
  puis redémarrer l'application. Anciens logs inchangés ; vérifications locales,
  sans validation en production ni confirmation de la cause du retard observé.

### Reprise des collections après une interruption réseau

- Une connexion interrompue, un délai réseau dépassé ou une réponse HTTP
  502/503/504 pendant une collection reporte son action de dix minutes.
  Les autres collections du même serveur patientent également ; les autres
  serveurs continuent. À la reprise, le contrôle hors ligne reste obligatoire.
- Avertissement explicite : connexion interrompue, redémarrage possible et
  nouvelle tentative dans dix minutes après vérification de disponibilité.
  Les erreurs TLS et les autres erreurs restent des erreurs ; aucun
  redémarrage n'est présenté comme confirmé.
- Ajout automatique de la table `collection_server_retries` au démarrage pour
  conserver la pause après redémarrage des workers. Déployer ensemble le
  [schéma](app/core/db_bootstrap_collections.py) et le
  [worker](app/tasks/run_collections.py), puis redémarrer l'application avant
  les traitements. La reprise utilise les contrôles de publication existants ;
  une écriture interrompue n'est pas immédiatement rejouée.
- [Tests de reprise](tests/test_collection_inventory.py) locaux ; pas de
  validation en production. Les acquisitions ARR hors ligne restent signalées
  séparément comme avertissements et ne sont plus considérées terminées dans
  les [lots de publication](app/core/collections_publication.py).

### Message compréhensible pour un serveur ARR hors ligne

- Lorsqu'un serveur Radarr/Sonarr est marqué hors ligne ou temporairement
  suspendu, les collections ignorent sa préparation sans appel réseau et
  indiquent : « Serveur Radarr/Sonarr hors ligne : impossible d'ajouter les
  médias pour le moment. » Le journal utilise un avertissement plutôt qu'une
  erreur pour cette situation attendue ; le serveur concerné reste identifié.
- Message traduit dans les cinq langues et disponible dans les détails et
  avertissements des collections streaming et plateformes. Les anciennes
  lignes de logs ne sont pas réécrites.
- [Code ARR](app/core/collections_arr.py),
  [tests](tests/test_collections_platforms_arr.py). Aucune migration ; déployer
  le code et redémarrer les workers. Vérification locale uniquement.

### Diagnostic des acquisitions Radarr et Sonarr

- Les erreurs ARR des collections streaming indiquent désormais le nom et
  l'identifiant de la collection, de la bibliothèque et du serveur ARR, l'étape,
  le statut HTTP et le point d'API reconnu, avec une explication de l'échec.
  L'identité du serveur est également conservée dans les détails du résultat
  lorsque la préparation des profils qualité ou dossiers racines échoue.
- Les messages bruts d'exception, tokens et réponses fournisseur ne sont pas
  journalisés. Les anciennes lignes de logs restent inchangées.
- Fichiers : [diagnostic ARR](app/core/collections_arr.py),
  [collections streaming](app/core/collections_streaming.py),
  [tests](tests/test_collections_platforms_arr.py). Aucune migration ; déployer
  le code puis redémarrer les workers. Vérification locale uniquement, sans
  confirmation de correction de la connexion ARR en production.

### Serveurs hors ligne et collections

- Le [rafraîchissement des inventaires](app/tasks/refresh_collection_inventory.py)
  ignore les serveurs marqués `down` ou en période de refroidissement, sans
  connexion, erreur ni modification des instantanés existants.
- Les [actions de collections](app/tasks/run_collections.py) sur ces serveurs
  restent en attente sans lancer de traitement. Elles redeviennent exécutables
  après confirmation du retour en ligne par le contrôle des serveurs ; les
  inventaires reprennent au prochain rafraîchissement planifié ou manuel.
- Aucune migration ; déployer le code puis redémarrer les workers. Le contrôle
  de disponibilité continue de sonder les serveurs pour détecter leur retour.
  Vérification locale dans les [tests d'inventaire](tests/test_collection_inventory.py),
  sans validation en production.

### Diagnostic des connexions d'inventaire

- Les échecs de rafraîchissement indiquent désormais la cause réseau détectée
  (DNS, connexion refusée, délai dépassé, réseau inaccessible, connexion coupée
  ou TLS), y compris lorsqu'elle est encapsulée par Requests/urllib3. Les
  messages bruts, adresses et secrets ne sont pas ajoutés aux logs.
- Fichiers : [classification](app/core/collection_inventory.py),
  [tâche](app/tasks/refresh_collection_inventory.py) et
  [tests](tests/test_collection_inventory.py). Aucune migration ; déployer le
  code puis redémarrer les workers. Ce diagnostic ne rétablit pas une connexion
  indisponible et ne constitue pas une validation en production.

### Collections

- Ajout de la gestion des collections thématiques Plex et Jellyfin, avec aperçu,
  planification, synchronisation et contrôles de publication.

### Activation et invitations Plex

- Traces détaillées du parcours d'activation et de connexion Plex, avec étapes,
  identifiants de corrélation et statuts HTTP, sans secrets ni réponses brutes
  du fournisseur.
- Distinction entre invitation en attente, accès non encore confirmés et erreur
  technique pendant la préparation des accès ; une erreur persistante renvoie
  désormais HTTP 422 avec `ok=false`.
- Bouton « Ouvrir Plex » proposé seulement lorsque l'activation de tous les
  serveurs est terminée, pour éviter une sortie prématurée du parcours.
- Analyse et limites documentées dans
  `docs/audit-activation-plex-2026-11-01.md` ; une simple connexion ne déclenche
  pas automatiquement une nouvelle autorisation de partage.

### Identité Plex et historique de lecture

- Rattachement des sessions, événements et historiques restés sans compte média
  après une synchronisation tardive, sur identifiant fournisseur non ambigu
  et sur le même serveur.
- Conservation des références de lecture lors de la déduplication des comptes
  après fusion ; une ligne encore référencée n'est pas supprimée.
- Nom transmis par Plex utilisé pour l'affichage en direct lorsqu'aucun nom de
  profil n'est encore disponible. Un nom identique ne remplace plus un
  identifiant fournisseur contradictoire lors du rapprochement.

### Coupures de lecture et diagnostic

- Tentatives compatibles GET/POST et vérifications de disparition de session,
  avec suivi d'une recréation de session identifiée pendant la coupure.
- Diagnostic structuré par tentative : identifiant de corrélation, durée,
  méthode et statut HTTP, étapes de résolution et de vérification, état du
  lecteur et évolution de la position observée.
- Distinction entre cible absente, identifiant manquant, commande refusée,
  arrêt confirmé, présence persistante et exception HTTP/réseau.
- Exceptions de coupure également conservées en `kill_failed` dans l'historique
  des règles. Les détails incluent un résumé des observations et ne contiennent
  ni tokens, ni corps de réponse, ni texte brut d'exception.
- Documentation : `docs/stream-kill-diagnostics.md`.

### Télémétrie des langues

- Schéma 4 : distinction entre configuration automatique ou imposée, préférence
  du navigateur et langue effectivement affichée, pour l'administration et le
  portail.
- Tableau des trois distributions et des parcours croisés, comptés par
  installation distincte, pour identifier les langues à examiner en vue de
  nouvelles traductions. Les anciens `unknown` ne sont pas reclassés sans preuve.
- Observations anonymes limitées à 30 jours, uniquement si la télémétrie est
  activée ; seuls des codes de langue normalisés sont collectés.
- Migration D1 `worker_telemetry/migration_20261102.sql` à appliquer avant le
  worker mis à jour, puis les clients VODUM. Procédure :
  `docs/telemetry-languages.md`.

### Communications et erreurs navigateur

- Rafraîchissements du dashboard : réglages d'affichage lus sur un snapshot
  indépendant du verrou d'écriture partagé ; aucune collecte de langue sur les
  fragments HTMX. Les observations des pages complètes utilisent une connexion
  séparée sans attente de verrou et sont ignorées si la base est occupée.
- Délais HTMX du dashboard : bloc concerné, durée observée, délai configuré et
  identifiant aléatoire de requête dans les rapports navigateur ; corrélation
  avec les requêtes lentes côté serveur et mesure des étapes de chargement,
  d'illustration et de carte de veille. Suppression du doublon console HTMX.
- Rapports navigateur enrichis avec la zone de l'interface, une opération
  prédéfinie et le statut HTTP des erreurs HTMX ; scripts HTMX locaux et
  scripts intégrés à la page distingués des sources inconnues, sans exporter
  d'URL de navigation, de paramètres ou de messages arbitraires.
- Bouton explicite d'ajout de pièces jointes dans l'éditeur de modèles ; fichiers
  enregistrés séparés des nouveaux fichiers en attente de sauvegarde.
- Sélections de fichiers successives conservées et possibilité de retirer un
  nouveau fichier avant envoi du formulaire.
- Retrait d'une pièce jointe du modèle par case à cocher, appliqué à
  l'enregistrement et limité au modèle concerné. Le retrait concerne son
  association au modèle, pas l'effacement physique du fichier stocké.
- Libellés disponibles dans les cinq langues de l'interface.
- Rapports d'erreurs navigateur : recherche d'une localisation de script
  exploitable dans les erreurs et rejets asynchrones, sans transmettre leur
  contenu ni les paramètres des URL.

### Documentation et suivi du développement

- Règle de mise à jour du changelog ajoutée à `AGENTS.md` : toute modification
  fonctionnelle ou documentaire significative doit être accompagnée de son
  entrée avant la fin du travail.

## Entrées précédentes — regroupement historique après le 2026-10-09

Les entrées ci-dessous sont conservées avec leurs résultats et limites de
validation d'origine. Ce regroupement ne constitue pas un historique exhaustif
et daté de toutes les versions publiées.

### Demarrage : detection des anciennes references de cles etrangeres

- Recherche des parents de tables legacy dans le schema SQLite au lieu d'un
  foreign_key_check global de toutes les donnees avant le bootstrap. Detection
  des suffixes _old, __rebuild et __rebuild_old, y compris tables vides et noms
  quotes ; aucun parcours des historiques necessaire pour cette detection.
- Verification complete conservee apres une reparation effective. Etapes de
  detection journalisees et sortie Python du bootstrap non tamponnee pour
  identifier un traitement lent avant le lancement de Waitress.
- Tests de detection et d'absence de lecture des donnees/ecriture valides ;
  demarrage Flask sur base temporaire valide avec 194 routes. Le blocage signale
  sur le conteneur reel n'a pas ete reproduit ; cause a confirmer avec les
  nouveaux logs ou la liste des processus du conteneur.

### Performances du suivi personnel du portail

- Statistiques personnelles chargees dans un snapshot SQLite commun aux
  periodes, historique, types de medias, serveurs, bibliotheques, courbe,
  lecteurs et IP. Lecture independante du verrou Python des ecritures.
- Requetes et regles conservees : isolation par utilisateur, deduplication,
  plafonnement des durees, pourcentages et masquage des IP. Autorisations
  de route inchangees ; aucune ecriture ajoutee.
- Comparaisons pendant transaction concurrente, utilisateur absent et
  regressions du suivi personnel validees.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 263,344 a 7,470 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --personal-monitoring`.
  Gain sur base representative toujours a mesurer.

### Performances des resumes Taches et Abonnements du dashboard

- Deux blocs de lecture isoles sur snapshots SQLite independants du verrou
  Python des ecritures. Execution des taches et gestion des abonnements inchangees.
- Ordre des prochaines taches, compteurs actifs/erreurs, exclusions des forfaits
  desactives, blocages sur sept jours et pourcentages/couleurs du graphique
  conserves. Resultats compares pendant transaction concurrente ; tables
  optionnelles absentes et absence d'ecriture testees.
- Benchmark synthetique des deux blocs, cinq repetitions avec ecriture de
  250 ms : mediane de 261,786 a 8,608 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --dashboard-summaries`.
  Gain sur base representative toujours a mesurer.

### Performances des suggestions de fusion

- Utilisateur et candidats lus dans un snapshot SQLite commun, independant du
  verrou Python des ecritures. Snapshot ferme avant le calcul des scores.
- Candidats, scores, classement et limites conserves ; action de fusion inchangee.
  Resultats compares pendant transaction concurrente, limites 0/1/sans limite
  et utilisateur absent testes, sans ecriture par le lecteur.
- Benchmark synthetique de la lecture (hors calcul des scores), cinq repetitions
  avec ecriture de 250 ms : mediane de 260,470 a 6,702 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --merge-candidates`.
  Gain sur base representative toujours a mesurer.

### Performances des politiques affichees sur la fiche utilisateur

- Identites et politiques actives de la fiche utilisateur lues dans un snapshot
  SQLite commun, independant du verrou Python des ecritures. Fonction reservee
  a l'affichage ; moteur d'application des restrictions inchange.
- Portee globale/utilisateur/serveur, filtrage du fournisseur, priorite,
  origine et valeurs affichees conserves. Comparaison pendant transaction
  concurrente et utilisateur absent testee, sans ecriture par le lecteur.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 262,339 a 6,733 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-policies`.
  Gain sur base representative toujours a mesurer.

### Performances du parrainage affiche sur la fiche utilisateur

- Contexte de parrainage et noms des comptes fusionnes charges sur snapshots
  SQLite independants du verrou Python des ecritures, pour l'affichage uniquement.
- Compteurs pending/qualified/rewarded, liste des filleuls, parrain de repli,
  tri et deduplication des noms conserves. Actions administratives inchangees.
- Comparaison pendant transaction concurrente et utilisateurs absents testees ;
  absence d'ecriture et contraintes referentielles verifiees.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 262,234 a 8,789 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-referrals`.
  Gain sur base representative toujours a mesurer.

### Message des demandes medias deja en recherche

- Message du portail reformule sans Sonarr/Radarr : le media est deja pris en
  charge par les outils de recherche et sera prochainement disponible en streaming.
  Texte harmonise dans les cinq langues et les fichiers de traduction legacy.

### Fiabilite de l'indicateur de mise a jour

- Version locale chargee par le meme mecanisme que l'application, avec prise
  en compte de VODUM_VERSION et des fichiers INFO hors conteneur.
- Comparaison numerique des formats de version reconnus ; statut invalide
  signale en erreur. Badge obsolete masque immediatement apres mise a niveau.
- Confirmation precedente conservee en cas de panne GitHub, pour la meme source,
  et recomparee avec la version installee. Erreurs visibles dans le moteur de
  taches, y compris echec de publication du statut.
- Publication atomique du JSON avec reprise bornee sous Windows et nettoyage
  des temporaires. Cache conserve, anciennete recalculee sans relecture JSON.
- Horaire personnalise de verification preserve lors de la relance au demarrage.
- Audit complet et limites de distribution documentes dans
  `docs/audit-update-badge-2026-10-20.md` ; tests de detection, erreurs, cache,
  concurrence, scheduler et rendu Jinja ajoutes.

### Performances des pages de communication

- Pages Campagnes et Modeles chargees chacune dans un snapshot SQLite en
  lecture seule, independant du verrou Python des ecritures.
- Listes, editeurs, traductions et metadonnees des pieces jointes conserves.
  Enregistrements, restauration des modeles et envois inchanges.
- Comparaisons pendant transaction concurrente, langues avec/sans traduction,
  selection absente/inexistante, modeles desactives, pagination et cas vides
  testes ; absence d'ecriture et contraintes referentielles verifiees.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 260,767 a 8,537 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --communication-pages`.
  Gain sur base representative toujours a mesurer.

### Performances du detail et de la configuration Communications

- Detail de l'historique et configuration charges sur des snapshots SQLite
  independants du verrou Python des ecritures. Lectures utilisees uniquement
  pour la consultation ; enregistrement et envois inchangees.
- Conservation du message archive et du rendu des anciens messages, des
  substitutions historiques, du masquage des trois secrets et des compteurs
  pending/error. Comparaisons pendant transaction concurrente et cas vides
  verifies, sans ecriture depuis les lecteurs.
- Benchmark synthetique des deux chargements, cinq repetitions avec ecriture
  de 250 ms : mediane de 261,966 a 9,386 ms, resultats identiques.
  Reproduction : `python tools/benchmark_dashboard_live_reads.py --communication-details`.
  Gain sur base representative toujours a mesurer.

### Performances du tableau d'acces utilisateur

- Serveurs et bibliotheques de la fiche utilisateur charges dans un meme
  snapshot SQLite, independant du verrou Python des ecritures. Aucun snapshot
  ouvert quand les deux listes sont inutiles pour l'onglet consulte.
- Selection du compte le plus renseigne par serveur et droits bibliotheques
  issus de tous les comptes lies conserves. Lectures de profil/parametres et
  autres lectures partagees avec l'enregistrement inchangees.
- Comparaison pendant transaction concurrente pour trois utilisateurs et
  trois combinaisons de chargement ; identite absente, droits et absence
  d'ecriture verifies.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 262,973 a 7,247 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-access`.
  Gain sur base representative toujours a mesurer.

### Performances de l'historique des notifications utilisateur

- Compteurs et pages email/Discord de la fiche utilisateur lus dans un snapshot
  SQLite commun, independant du verrou Python des ecritures. Aucun snapshot
  ouvert lorsque l'historique est desactive pour l'onglet consulte.
- Isolation par utilisateur/canal, pagination independante, libelles de
  modeles/campagnes et metadonnees archivees conserves. Requetes et tri inchanges.
- Comparaison pendant transaction concurrente, pages hors limites/invalides,
  utilisateur absent, envois echoues et absence d'ecriture testes.
- Benchmark synthetique, cinq repetitions avec ecriture de 250 ms : mediane
  de 260,329 a 7,423 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --user-notifications`.
  Gain sur base representative toujours a mesurer.

### Performances du dashboard : lectures en cours

- Sessions, compteurs et verification de la file de taches charges dans un meme
  snapshot SQLite en lecture seule, sans attendre le verrou Python des ecritures.
- Conservation de la limite de six sessions, des identites et du repli de
  trente minutes lorsque la file de taches est occupee.
- Tests : comparaison avec le parcours precedent, sessions absentes/anciennes,
  sessions manquantes et lecture des donnees commitees pendant une transaction.
- Benchmark synthetique local (cinq repetitions, verrou d'ecriture de 250 ms) :
  mediane de 262,767 ms a 7,179 ms, resultats identiques. Script reproductible :
  `tools/benchmark_dashboard_live_reads.py`. Gain reel a mesurer sur une base
  representative ; le prealable global de mesure du TODO reste ouvert.

### Performances du monitoring en direct

- Sessions, statistiques et serveurs des onglets Overview/Now playing lus dans
  un snapshot SQLite commun, independant du verrou Python des ecritures.
- Enrichissement et corrections des references artwork executes apres fermeture
  du lecteur, sur la connexion d'ecriture existante. Les autres onglets
  n'ouvrent pas de snapshot ; regles de repli et progression conservees.
- Comparaison des resultats, lecture pendant transaction non commitee et
  preservation des ecritures artwork testees. Benchmark synthetique local sur
  cinq repetitions avec ecriture de 250 ms : mediane de 261,163 a 6,837 ms
  pour la phase de lecture (hors artwork). Commande reproductible :
  `python tools/benchmark_dashboard_live_reads.py --monitoring`.
  Validation sur base representative toujours restante.

### Performances des evenements et filtres du monitoring

- Evenements recents Overview/Activity et utilisateurs du filtre Bibliotheques
  lus sur snapshots independants du verrou Python des ecritures.
- Requetes, ordre, limites, details JSON des series et libelles inchanges.
  Les onglets sans evenements n'ouvrent aucune connexion supplementaire.
- Comparaisons pendant transaction non commitee et regressions fonctionnelles
  validees. Benchmark synthetique local, cinq repetitions avec ecriture de
  250 ms : evenements de 262,586 a 6,379 ms ; filtre utilisateurs de 263,174
  a 6,743 ms. Resultats identiques ; mesure representative encore necessaire.
- Commandes : `python tools/benchmark_dashboard_live_reads.py --activity`
  et `python tools/benchmark_dashboard_live_reads.py --library-users`.

### Performances du rapport d'usage du portail

- Compteurs, chronologie, utilisateurs, evenements pagines et demandes medias
  charges dans un snapshot SQLite commun, independant du verrou des ecritures.
  Periodes, limites et calculs existants conserves.
- Resultats compares aux anciennes lectures pour 7/30/90 jours, valeurs de
  repli et pages hors limites ; cas vide, transactions concurrentes, compteurs
  de demandes et integrite SQLite testes. Les controles d'acces restent dans
  le parcours de route existant.
- Benchmark synthetique local avec 100 evenements, cinq repetitions et ecriture
  de 250 ms : mediane de 262,185 a 7,825 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --portal-usage`.
  Mesure sur base representative toujours necessaire.

### Performances du monitoring des politiques

- Neuf fonctions de lecture de l'onglet Politiques sur snapshots SQLite
  independants du verrou Python des ecritures. Catalogue, statistiques,
  regroupements, chronologie et pagination conservent leurs requetes et regles.
  Les actions et controles d'acces existants restent sur leur parcours actuel.
- Resultats compares aux anciennes lectures sur donnees presentes/absentes,
  identites natives, regles systeme/verrouillees et transaction concurrente ;
  absence d'ecriture par les lecteurs et integrite SQLite verifiees.
- Benchmark synthetique des neuf lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 260,858 a 23,856 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --policies`.
  Validation sur base representative toujours restante.

### Performances du monitoring Sonarr/Radarr

- Consultation des statistiques ARR sur un snapshot SQLite commun, sans attendre
  le verrou Python des ecritures. Collecte HTTP, insertion et purge conservees.
  Aucun snapshot ouvert lorsqu'aucun serveur ARR n'est fourni.
- Comparaison des six plages avec les lectures precedentes pendant transaction
  concurrente. Dernier releve (y compris egalite de date), valeurs nulles,
  serveur sans releve et exclusion Plex/Jellyfin des agregats verifies.
- Benchmark synthetique local, cinq repetitions avec ecriture de 250 ms :
  mediane de 261,492 a 7,249 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --arr`.
  Gain sur base representative toujours a mesurer.

### Performances des listes Serveurs et Bibliotheques

- Liste des serveurs, compteur et page de bibliotheques isoles sur des snapshots
  SQLite de lecture, sans attendre le verrou Python des ecritures.
- Conservation des requetes et compteurs distincts, des types normalises,
  des tris et de la pagination. Lectures de detail et actions inchangees.
- Comparaison des tris et directions (y compris valeurs de repli), pages vides,
  compteurs et resultats pendant transaction concurrente ; absence d'ecriture
  et contraintes referentielles verifiees.
- Benchmark synthetique des trois lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 262,269 a 11,078 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --server-pages`.
  Mesure representative toujours restante.

### Performances des fiches serveur

- Cinq fonctions de lecture (detail, bibliotheques, utilisateurs et compteurs)
  isolees sur snapshots SQLite independants du verrou Python des ecritures.
  Appels limites a l'affichage de la fiche ; mutations inchangees.
- Comparaison pendant transaction concurrente, isolation entre serveurs,
  deduplication des utilisateurs, pagination et serveur inexistant testees.
- Benchmark synthetique des cinq lectures, cinq repetitions avec ecriture de
  250 ms : mediane de 261,696 a 13,753 ms, resultats identiques. Reproduction :
  `python tools/benchmark_dashboard_live_reads.py --server-detail`.
  Validation representative toujours restante.
- Controle supplementaire `test_sqlite_connection_policy.py` : un echec sur les
  connexions directes deja presentes dans `app/diagnose_stream_policies.py` et
  `app/core/backup.py`, hors fichiers modifies dans ce lot ; analyse distincte
  necessaire, notamment pour respecter la sauvegarde sur connexion dediee.

### Simplification du portail utilisateur

- Accueil, Mon profil et Acces aux medias regroupes dans un seul onglet
  Mon profil, affiche a l'entree du portail.
- Informations personnelles et reglages de connexion toujours visibles en tete
  de page, sans bandeau depliable ; statut en vignette compacte coloree pres du
  titre : vert actif, jaune preavis/invitation, orange rappel, rouge acces termine
  ou suspendu, gris pour les etats inconnus.
  Acces aux bibliotheques affiches ensuite.
- Cartes Abonnement, Serveurs & bibliotheques et Activite personnelle retirees
  de Mon profil pour eviter les informations en double.
- Anciennes adresses conservees et apercu administrateur aligne sur la page
  regroupee. Options de visibilite des fonctionnalites conservees.

### Mise a jour des dependances Python

- PlexAPI : 4.18.2 -> 4.18.3.
- pytz : 2026.3.post1 -> 2026.5.
- websocket-client : 1.9.0 -> 1.9.2.
- cryptography : 50.0.1 -> 50.0.2.
- Autres dependances deja sur les dernieres versions disponibles lors de la
  verification PyPI du 2026-10-09. Validation du conteneur a effectuer.
