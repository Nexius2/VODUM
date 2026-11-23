# Changelog

Les changements non publiés sont regroupés dans ce fichier. Les dates indiquent
la mise à jour du journal, sans confirmation de déploiement en production.
L’historique antérieur est conservé dans le [journal archivé](changelog-archive-2026-11-19.md).

## Non publié — mise à jour du 2026-11-21

### Portail : statut Seerr, choix 4K, saisons et suivi des demandes

- Les résultats de recherche issus de Seerr affichent le statut que Seerr
  connaît déjà (disponible, partiellement disponible, déjà demandé), pour la
  version standard et, le cas échéant, pour la version 4K
  ([aide Seerr](app/core/portal_media_requests_seerr.py), [gabarit](templates/portal/requests.html)).
- Choix 4K par demande : si l'utilisateur Seerr associé au membre possède la
  permission « demander en 4K » (ou sa variante films/séries), la fiche propose
  une case 4K préréglée sur l'option du serveur ; sinon l'option du serveur
  s'applique comme avant. Le choix est revérifié côté serveur à la soumission
  ([demandes](app/core/portal_media_requests.py)). La recherche lit l'utilisateur
  Seerr du membre en parallèle de la recherche (un appel `/api/v1/user` de plus).
- Sélection des saisons : la demande d'une série via Seerr ouvre un sélecteur
  alimenté par la nouvelle route `/portal/requests/seasons` (sélection signée,
  limitée en fréquence, [routes](app/routes/portal.py)). Les saisons non encore
  disponibles sont présélectionnées, les saisons connues de Seerr sont
  verrouillées, les épisodes spéciaux ne sont pas proposés. Sans JavaScript ou
  si la liste ne se charge pas, toute la série est demandée comme avant.
  La charge utile Seerr envoie la liste des saisons au lieu de `all`.
- Suivi après soumission : la liste « Demandes récentes » affiche les choix (4K,
  saisons) et l'état rapporté par Seerr (en attente d'approbation, approuvée,
  partiellement disponible, disponible, refusée, échouée, supprimée), lu via
  `/api/v1/request/{id}` au chargement et lors du rafraîchissement, au plus une
  fois par minute et par demande dans un délai court
  ([suivi](app/core/portal_media_request_tracking.py)). Le dernier état connu
  est conservé si Seerr ne répond pas ; le suivi s'arrête une fois la demande
  disponible, refusée ou supprimée. Le script interroge la liste toutes les
  minutes tant qu'une demande Seerr reste ouverte
  ([script](static/js/pages/portal-requests.js)).
- Migration additive au démarrage : colonnes `is_4k`, `seasons`,
  `seerr_server_id`, `seerr_request_id`, `seerr_state`, `seerr_checked_at` sur
  `portal_media_request_jobs` ([travaux](app/core/portal_media_request_jobs.py)),
  ajoutées par le bootstrap portail existant. Déployer Python, gabarit, script,
  feuille de style et traductions ensemble puis redémarrer. Traductions dans les
  cinq langues. Tests locaux uniquement (logique pure, flux de soumission et
  file de travaux simulés) ; lectures seules vérifiées contre une instance Seerr
  3.5 réelle (forme des réponses de recherche, utilisateurs, séries, demandes),
  sans validation en production. Correction : Seerr refuse les espaces encodés
  en `+` dans la recherche (HTTP 400) ; la requête est désormais encodée en
  pourcentage, ce qui corrige aussi la recherche multi-mots du service Seerr
  introduit précédemment. Seerr répond 202 « No seasons available to request »
  sans rien créer lorsque les saisons choisies sont déjà prises en charge ou
  n'ont pas encore d'épisodes : le portail l'affiche comme « plus rien à
  demander » et le sélecteur verrouille les saisons sans épisodes. Une demande
  de saisons est suivie d'après l'état de ses propres saisons (`media.seasons`),
  car l'état global de la série reste « partiel » à cause des autres saisons.
  Une demande réelle (série, une saison, au nom du membre) a été créée via le
  flux VODUM contre l'instance Seerr réelle, approuvée automatiquement, puis
  supprimée. Limites : les
  permissions Seerr sont lues à chaque recherche sans cache ; un refus 4K par
  Seerr à la soumission est rapporté comme demande refusée par le service.
- Documentation : [demandes de médias](vodum-docs/docs/media-requests.md).

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

## Non publié — mise à jour du 2026-11-22









### Portail — ignorer les instances indisponibles et poursuivre selon les priorités (2026-11-22)

- Le [traitement des demandes](app/core/portal_media_requests.py) ne bloque plus un ajout parce qu'un Sonarr/Radarr secondaire, lié ou non à la bibliothèque retenue, ne répond pas. Les contrôles défaillants restent journalisés en avertissement ; les doublons effectivement trouvés sur une instance accessible continuent de renvoyer présent/en cours sans nouvel ajout. L'indisponibilité du serveur média sélectionné ne bloque plus non plus l'envoi à un ARR accessible.
- Si l'ARR prioritaire est indisponible au contrôle d'inventaire, le traitement choisit la destination admissible suivante en conservant priorités, préférences et critères de routage. Le repli est également permis si la lecture des profils/dossiers échoue avant tout POST. Les erreurs de configuration des profils/dossiers restent explicites ; droits et accès sont revérifiés avant soumission. Aucun POST envoyé ou à réponse incertaine n'est rejoué sur une autre instance.
- Nouveau message traduit `portal_requests_no_arr_available` lorsqu'aucune destination admissible n'est disponible, sans réécrire les anciens résultats. Limite : un doublon présent uniquement sur une instance indisponible ne peut pas être détecté. Les ajouts sur les instances disponibles poursuivent leur traitement conformément au comportement demandé. [Documentation](vodum-docs/docs/media-requests.md).
- Aucune migration. Déployer module et traductions ensemble puis redémarrer application/worker. Relancer les demandes précédemment bloquées ; les anciens échecs ne sont pas relancés automatiquement. Validation locale : 54 tests passent, couvrant instances secondaires indisponibles, repli vers la priorité suivante, lecture de préparation en échec, absence de repli après POST, doublons confirmés et routes du portail. Aucun ajout réel ni validation en production.

### Diagnostics — rendre visibles les blocages Portail et les vues Monitoring en échec (2026-11-22)

- Le résumé final d'un [blocage anti-doublon ARR](app/core/portal_media_requests.py) est désormais de niveau `ERROR`, visible avec le filtre Erreur de la page Logs ; les incidents intermédiaires des appels API restent en `WARNING`. Les diagnostics ajoutés précédemment étaient masqués par ce filtre, sans être nécessairement absents du fichier.
- Le [précalcul Monitoring](app/core/monitoring/precomputed.py) journalise ses échecs en `ERROR` avec un contexte autorisé contenant la clé de vue. Le paramètre texte `snapshot_key` utilisé auparavant était ignoré par le journaliseur sécurisé. Le [résumé de tâche](app/tasks/refresh_monitoring_statistics.py) nomme désormais les vues échouées, la classe d'exception et une catégorie de cause, notamment `sql_budget_exceeded`, table ou colonne SQLite absente. Aucun message d'exception externe ni recherche utilisateur en clair n'est ajouté à ce résumé ; les résultats précédents restent conservés.
- La capture montre un Sonarr Coréen hors ligne et son conteneur arrêté : le contrôle global peut être bloqué même si les autres Sonarr fonctionnent. Les captures seules ne permettent pas d'attribuer la dernière tentative à une instance précise ni d'identifier la vue Monitoring échouée ; le journal complet actuel reste nécessaire.
- Aucune migration. Déployer les modules puis redémarrer application/worker. Ces changements améliorent les diagnostics ; ils ne réparent ni un serveur arrêté ni la cause encore inconnue de l'échec de calcul en production. Validation locale : 76 tests ciblés passent (Portail et précalcul Monitoring).

### Portail — diagnostic du blocage anti-doublon Sonarr/Radarr (2026-11-22)

- Le [contrôle des demandes](app/core/portal_media_requests.py) journalise désormais un résumé lorsqu'une vérification ARR bloque l'ajout : bibliothèque choisie, destination, instances en échec, association à cette bibliothèque, endpoint, statut HTTP ou classe d'erreur réseau. Les clés API et URLs configurées ne sont pas ajoutées à ce diagnostic.
- Le message traduit précise qu'une instance **enregistrée dans VODUM** peut bloquer la demande : il ne prétend plus qu'elle est nécessairement liée à la bibliothèque retenue. La vérification globale des doublons et l'interdiction de rejouer un POST restent conservées. [Documentation de dépannage](vodum-docs/docs/media-requests.md).
- Le journal fourni confirme sur la tentative Broute 24 du 21 novembre un `ReadTimeout` de Sonarr 9 sur `/api/v3/series` et une erreur de connexion de Sonarr 12, alors que la bibliothèque 17 était liée aux Sonarr 8 et 9. Cette observation n'établit pas l'état de l'essai du 22 novembre à 10:57, absent de cette capture ; un voyant vert d'une autre instance ne valide pas ces appels. La connectivité/configuration de ces instances reste à corriger sur l'hôte ; aucun ajout réel n'a été envoyé.
- Aucune migration. Déployer Python et traductions ensemble puis redémarrer application/worker. Les demandes bloquées doivent être relancées après résolution de la cause. Validation locale : 50 tests ciblés du contrôle, de ses diagnostics et des routes du portail passent ; aucune résolution de production revendiquée.

### Monitoring — extension du précalcul aux autres onglets (2026-11-22)

- Le [registre des vues préparées](app/core/monitoring/precomputed_tabs.py) couvre désormais Historique, Utilisateurs, rapports Serveurs/ARR, Activité, Politiques, Usage à risque, Portail et historique de la Carte. Les recherches, tris, pages, périodes et instants personnalisés sont normalisés et préparés par la tâche existante ; les liens de pagination restent construits dans la requête courante. Les onze vues par défaut sont protégées du nettoyage.
- La [route Monitoring](app/routes/monitoring_overview.py) conserve à jour sessions, états des serveurs, CPU/RAM, derniers échantillons ARR, présence du portail, règles éditables et suivi actif des politiques. Les statistiques historiques Serveurs excluent désormais les lectures en cours, affichées séparément dans les compteurs live. La [Carte](app/core/monitoring/overview_locations.py) fusionne ses observations historiques préparées avec les sessions actuelles ; son mode live seul reste direct. La timeline attend chaque instant préparé et fixe la borne `until` pour éviter qu'une demande en attente dérive dans le temps.
- Les [graphiques historiques](app/core/monitoring/activity_statistics.py), y compris le journal quotidien d'une fiche utilisateur, sont calculés hors HTTP. Les [API](app/routes/monitoring_api.py) renvoient 202 pendant la préparation et 429 si la file bornée est pleine. Les scripts conservent le graphique précédent, affichent l'attente/date puis réessaient, avec arrêt après navigation. Les nouveaux templates distinguent résultat vide et préparation ; les variantes privées sont servies sans cache HTTP.
- Migration de données additive et idempotente : huit vues par défaut supplémentaires dans `monitoring_precomputed`, sans nouvelle table ni changement d'INFO. Déployer Python, templates et JavaScript ensemble puis redémarrer application/worker ; lancer au besoin « Actualiser les statistiques historiques du monitoring ». La cible de cinq minutes, le plafond de 128 entrées, le budget SQL de 90 secondes et le commutateur global des tâches restent en vigueur. Un nouveau filtre peut attendre le passage suivant ; les lectures individuelles de détail, la configuration et les actions opérationnelles restent directes. [Documentation](vodum-docs/docs/performance.md).
- Validation locale : 120 tests Python ciblés et deux tests JavaScript passent, couvrant vues vides/peuplées, filtres/cookies, pagination, réponses 202/200, fusion Carte et compteurs live après recalcul, borne de timeline stable et absence de SQL historique lourd dans les vues préparées testées. Pas de déploiement ni mesure de gain sur Unraid pour cette extension.

### Monitoring — statistiques historiques préparées en arrière-plan (2026-11-22)

- Nouvelle [tâche](app/tasks/refresh_monitoring_statistics.py), vérifiée chaque minute et activée par défaut, pour préparer l'aperçu Monitoring, les totaux de toutes les bibliothèques, le sélecteur d'utilisateurs et les classements des bibliothèques. Les [résultats persistants](app/core/monitoring/precomputed.py) deviennent éligibles à une actualisation après cinq minutes ; l'ancien résultat reste lisible pendant le calcul et en cas d'échec. Les classements personnalisés par période/utilisateur sont demandés puis préparés par la tâche, sans calcul historique dans la requête HTTP.
- La [route Monitoring](app/routes/monitoring_overview.py) lit les résultats préparés. Tri, pagination et choix de période de croissance utilisent la table précalculée. Les vues distinguent préparation et résultat vide, affichent la date UTC du calcul et signalent données anciennes/échec. Les compteurs live restent actuels, y compris pendant la première préparation. Le premier rendu de l'aperçu ne charge plus les événements destinés au fragment suivant.
- Migration additive et idempotente : table `monitoring_precomputed` et tâche `refresh_monitoring_statistics`. Déployer modules Python, templates, traductions et schéma ensemble puis redémarrer application/worker. Attendre le premier passage de la tâche ou la lancer depuis Tâches ; le réglage global des tâches planifiées reste respecté. Aucune modification d'INFO ni déploiement effectué ici.
- Calculs sur une connexion de lecture séparée, publication atomique par vue, budget SQL de 90 secondes par passage et maximum de 12 vues candidates. Les demandes personnalisées sont bornées à 128 entrées au total et nettoyées après sept jours d'inactivité. Limites : les calculs sont déplacés en arrière-plan, pas tous rendus incrémentaux ; la cible de cinq minutes dépend de la charge. Historique détaillé, Utilisateurs, rapports Serveurs, carte, politiques et usage à risque conservent leurs chemins existants. Voir la [documentation des performances](vodum-docs/docs/performance.md).
- Validation locale : 85 tests Python ciblés et le test JavaScript du polling passent, dont migration, persistance, premier affichage, concurrence, budget SQL, conservation après échec, filtres différés et équivalence des huit tris dans les deux sens avec pagination. Sur 50 002 lectures synthétiques : 170 ms de calcul direct des bibliothèques contre 7 ms de lecture préparée, et 1,30 s pour préparer les trois vues par défaut ; mêmes lignes. Mesures locales, sans garantie de latence ni validation sur Unraid.

### Déploiement Unraid — diagnostic des lenteurs (2026-11-22)

- Le [script de création du conteneur](create-container.sh) accepte `VODUM_PERFORMANCE_DIAGNOSTICS=1 bash create-container.sh` pour activer les mesures SQL, verrou, fournisseurs/cache et file HTTP, avec un seuil de route de 300 ms. Sans cette option, il conserve les réglages habituels. Le script affiche le chemin hôte du journal `app.log`.
- Aucune migration. Relancer le script reconstruit l'image et recrée `vodum-test` avec ses volumes existants ; relancer sans l'option retire les mesures supplémentaires. Les mesures doivent être recueillies sur l'instance pour identifier la cause des lenteurs ; aucun gain de performance n'est revendiqué par cet ajout.

### Collections — nouvelle affiche Jurassic Park / World (2026-11-22)

- Nouvelle [affiche Jurassic v3](app/core/assets/collection_posters/universe-jurassic-v3.png) créée avec ImageGen : jungle émeraude, T. rex, portail et titre doré, en harmonie avec les autres franchises. Le [catalogue des affiches](app/core/collections_posters.py) sélectionne ce PNG pour les collections films et séries ; le JPEG précédent est conservé.
- [Provenance et prompt](docs/collections-poster-sources.md) documentés. Validation locale : contrôle visuel, format 1024 × 1536 et résolution de la clé `universe_jurassic`. Aucun envoi en production.
- Aucune migration. Déployer image et module ensemble, redémarrer application/worker puis synchroniser Jurassic : le changement de digest déclenche la republication du poster.

### Monitoring — budget du worker et page des tâches (2026-11-22)

- Le [worker média](app/tasks/media_jobs_worker.py) transmet une échéance monotone de 25 secondes au [collecteur](app/core/monitoring/collector.py). Les requêtes Plex/Jellyfin adaptent leur timeout au budget restant et refusent les nouvelles tentatives après expiration. L'attente du créneau Plex et la [collecte CPU/RAM](app/core/monitoring/resource_stats.py) respectent aussi cette échéance ; les chemins de reprise et de conservation des sessions restent actifs.
- La [page des tâches](static/js/pages/tasks.js) ne remonte plus l'annulation attendue du polling comme erreur navigateur, puis réessaie au prochain intervalle. Les autres erreurs restent signalées. Le [diagnostic de durée](app/core/tasks/result_validation.py) arrondit vers le haut pour éviter « 120s > 120s ».
- Validation locale : 40 tests Python ciblés et le test JavaScript du polling passent. Aucune validation en production. Limites : les timeouts réseau ne constituent pas une interruption forcée du SQL ou d'une réponse envoyée au compte-gouttes ; les anciennes erreurs Franchise et HTTP 502 de la capture ne sont pas déclarées résolues.
- Aucune migration. Déployer les modules Python et JavaScript ensemble, puis redémarrer application et worker. La file restante est reprise aux passages suivants ; les logs historiques sont conservés.

### Collections — reprise des nouvelles franchises dans les configurations existantes (2026-11-21)

- Le [démarrage de la base](app/core/db_bootstrap_collections.py) applique une migration de données idempotente : une ancienne sélection contenant exactement les neuf franchises historiques est étendue aux 32 listes VODUM. Le catalogue seul était enrichi auparavant, laissant les collections existantes sur leurs neuf liens. La migration s'applique aussi si les 23 listes ont déjà été ajoutées à la base par un déploiement précédent.
- Les sélections partielles ou vides sont conservées. Un marqueur dans la configuration empêche de rétablir ensuite une liste déliée ; les choix effectués dans le [formulaire](app/core/collections_repository.py) et le [gestionnaire de liens](app/core/collections_lists_admin.py) sont marqués immédiatement. Limite : une sélection historique de neuf listes ne permet pas de distinguer l'ancien choix complet par défaut d'un choix volontaire identique ; elle est traitée comme l'ancien défaut. Aucun média, objet Plex ni réglage ARR n'est modifié par la migration.
- Déployer les modules ensemble, redémarrer application et worker pour appliquer la migration, puis synchroniser Franchise pour les bibliothèques films/séries. Les seuils habituels restent deux films ou une série présents ; les conflits avec une collection externe homonyme restent protégés. Les captures d'erreurs du 20 novembre ne valident pas l'état de la dernière synchronisation. Validation locale par tests de migration, de conservation des sélections et de publication ; pas de validation en production.
- Validation : 37 tests ciblés passent. La suite élargie de 169 tests relève deux échecs hors du chemin modifié : le test de calendrier omet la liste désormais obligatoire pour le modèle `media_list`, et le test de proxy fournit les octets `JPEG`, qui ne constituent pas une image JPEG valide. Ces deux tests ne sont pas corrigés dans ce travail.

### Collections — affiches des 23 nouvelles listes (2026-11-21)

- Ajout de 23 affiches spécifiques aux listes de franchises supplémentaires : 21 créations cinématographiques ImageGen et deux affiches existantes pour Jurassic Park / World et Game of Thrones après refus de génération. Les fichiers restent [livrés localement](app/core/assets/collection_posters/) ; leurs [sources et associations](docs/collections-poster-sources.md) sont documentées.
- L'[allowlist](app/core/collections_posters.py) sélectionne les PNG dédiés et les deux JPEG de repli, pour les collections films et séries. Les anciennes versions sont conservées. Déployer les images et le module ensemble, redémarrer application/worker puis synchroniser les franchises : le contrôle de digest existant republie les visuels modifiés. Aucune migration de schéma.
- Validation : contrôle visuel de la planche des 32 franchises, signature des fichiers et test des 23 associations films/séries. Aucun envoi vers les bibliothèques de production.

### Monitoring — fiabilité de la confirmation d'un kill Plex (2026-11-21)

- Le [fournisseur Plex](app/core/providers/plex.py) refuse désormais un relevé `/status/sessions` dont le XML n'est pas un `MediaContainer` ou dont le nombre de sessions déclaré est incohérent. Une réponse XML de proxy ou un relevé tronqué ne doit pas être assimilé à la disparition du flux et à un kill réussi. Les diagnostics enregistrent le refus ; l'enforcer passe par son chemin d'échec existant.
- Validation : 67 tests ciblés passent pour les affiches, le catalogue, les franchises, la terminaison Plex et les politiques. Trois régressions couvrent un faux document XML, un relevé incomplet et le refus d'envoyer une commande depuis un relevé initial invalide.
- Le cas précis de double lecture signalé par les captures reste à confirmer avec le JSON complet de l'événement et son diagnostic de terminaison : les sessions affichées dans la fenêtre sont un instantané avant action. Cette correction n'est pas présentée comme une résolution validée de cet incident en production. Aucun kill réel n'a été envoyé pendant ce travail ; redémarrer le worker après déploiement du module, sans migration.

### Collections — suppression des listes personnelles (2026-11-21)

- Ajout d'une poubelle dans l'en-tête de l'[éditeur de liste](static/js/pages/collection-lists.js), uniquement pour les listes personnelles. Une liste encore liée affiche l'action désactivée et demande de retirer les associations ; le serveur conserve ses protections contre la suppression des listes VODUM ou utilisées.
- La confirmation réutilise la [boîte de dialogue VODUM](templates/collections/_lists.html), avec le nom de la liste, un titre spécifique et Annuler sélectionné par défaut. Les confirmations de suppression de médias conservent leur texte propre. Après suppression, le catalogue et les sélecteurs sont actualisés et une liste restante est ouverte.
- Traductions des cinq langues et styles actualisés. Aucune migration ; déployer JavaScript, template, CSS et traductions ensemble. Les fichiers médias des bibliothèques ne sont pas supprimés.
- Validation locale : 14 tests Python ciblés passent ; parcours Chromium de confirmation, annulation par Échap, suppression et protections des listes liées/VODUM vérifié. Aucune validation de production.

### Collections — 23 listes de franchises supplémentaires (2026-11-21)

- Ajout dans le [catalogue livré](app/data/franchise_lists.json) de Jurassic Park / World, Terminator, Matrix / Animatrix, James Bond, Mission: Impossible, Conjuring, Indiana Jones, Pirates of the Caribbean, Planet of the Apes, Ghostbusters, Transformers, Rocky / Creed, John Wick, Resident Evil, Godzilla / Kong, Narnia, Dune, Shrek / Puss in Boots, Walking Dead, Game of Thrones, Yellowstone, Doctor Who et Dragon Ball. Le catalogue passe de 9 à 32 listes, avec 307 nouvelles identités IMDb typées, titres et années vérifiés directement auprès d'IMDb le 2026-11-21.
- Les films, séries, principaux spin-offs et courts retenus sont décrits dans le [périmètre détaillé](docs/collections-franchise-expansion-2026-11-21.md). Jeux vidéo, documentaires de fabrication, podcasts et projets postérieurs à la date de vérification sont exclus. Les variantes de continuité et adaptations anciennes sont explicitées ; il ne s'agit pas d'un inventaire exhaustif de tous les contenus promotionnels.
- Le [chargement initial](app/core/collections_franchise_lists.py) ajoute aussi les années des nouvelles entrées. Insertion additive et idempotente, sans modification des noms personnalisés, activations/exclusions, ajouts personnels ou associations explicites existantes. Les listes supplémentaires sont disponibles dans la gestion des liens Franchise ; elles ne sont pas ajoutées automatiquement à une sélection explicite déjà enregistrée. [Documentation des sources](vodum-docs/docs/collection-sources.md) actualisée.
- Aucune migration de schéma. Déployer le JSON et son module de chargement ensemble puis redémarrer pour ajouter les listes en base. Les lier aux configurations souhaitées, puis lancer leur synchronisation. Les correspondances TMDB et les bibliothèques locales continuent de déterminer les collections effectivement publiées. Aucun déploiement ni contrôle sur l'instance de production.
- Validation locale : 80 tests ciblés passent ; vérification en direct des 307 identifiants et de leur type/année/date de sortie ; tests du catalogue, du classement films/séries, de l'ajout sur une ancienne base, du second démarrage et de la conservation des personnalisations et associations.

### Collections — listes liées et gestion des associations (2026-11-21)

- L'[éditeur Franchise](static/js/pages/collections.js) affiche uniquement les listes liées à sa configuration, dans une zone de hauteur limitée. Les listes personnelles non liées, comme « test », restent accessibles dans l'onglet Listes mais ne sont plus ajoutées au formulaire Franchise. Le formulaire conserve les sélections explicites et accepte une sélection vide après déliaison de la dernière liste.
- Dans [Collections et bibliothèques associées](static/js/pages/collection-lists.js), ajout de « Gérer les liens Franchise » avec recherche par collection/bibliothèque et huit configurations par page. Les actions [API](app/routes/collection_lists.py) lient ou délient la liste pour toutes les bibliothèques d'une configuration dans une transaction ; une configuration occupée est refusée. L'interface des collections est rafraîchie après modification.
- Les [configurations historiques sans sélection explicite](app/core/collections_franchises.py) utilisent désormais uniquement les listes VODUM par défaut : une nouvelle liste personnelle ne rejoint plus implicitement toutes les franchises. Les liens explicites existants sont préservés. Les collections du modèle « Liste de médias » conservent leur source unique, modifiable dans leur propre éditeur.
- Aucune migration de schéma. Déployer backend, [template](templates/collections/collections.html), CSS, JavaScript et traductions ensemble, puis redémarrer. Les associations prennent effet à la prochaine synchronisation ; délier retire alors uniquement les collections VODUM concernées, sans supprimer les médias. [Documentation](vodum-docs/docs/collections.md) et traductions des cinq langues actualisées.
- Validation : 77 tests Python ciblés passent, plus le test JavaScript du sélecteur. Parcours Chromium ordinateur/mobile avec 1 009 listes : seuls les liens choisis apparaissent dans l'éditeur, liaison/déliaison et rafraîchissement vérifiés. Aucun changement exécuté sur l'instance de production.

### Collections — nouvelles affiches Stargate et Terre du Milieu (2026-11-21)

- Remplacement de l'affiche du film Stargate et du visuel minimaliste Middle-earth par deux illustrations cinématographiques dédiées aux franchises films/séries, cohérentes avec Harry Potter / Fantastic Beasts. Les [associations d'affiches](app/core/collections_posters.py) et leur [provenance](docs/collections-poster-sources.md) sont actualisées ; les anciennes images sont conservées.
- Déployer les deux nouveaux PNG et le module d'association ensemble. Aucune migration ; le contrôle de digest existant appliquera les affiches aux collections VODUM à leur prochaine synchronisation. Visuels et sélection locale vérifiés, sans validation dans Plex en production.

### Sécurité web — en-têtes du reverse proxy sous Waitress (2026-11-21)

- Correction du problème décrit dans la [PR #8](https://github.com/Nexius2/VODUM/pull/8) : le [serveur de production](app/serve.py) conserve désormais les en-têtes transférés sans les interpréter. Le middleware VODUM reste seul responsable de vérifier le pair direct contre `VODUM_TRUSTED_PROXY_NETS`, puis de résoudre HTTPS, le nom d'hôte et l'adresse du client. Cette correction couvre aussi l'activation depuis les réglages en base et les deux modes de mesure de la file Waitress.
- Le choix `trusted_proxy="*"` proposé dans la PR n'est pas repris : Waitress réécrirait l'adresse du pair avant son contrôle par VODUM. Aucun nouveau paramètre d'environnement n'est nécessaire ; le HTTP local et le rejet des en-têtes des pairs non autorisés sont conservés. [Documentation](vodum-docs/docs/security.md) complétée.
- Validation : 13 tests ciblés passent, dont des requêtes HTTP réelles sous Waitress 3.0.2, avec et sans mesure de file. Cookies `Secure`, HSTS, adresses clients distinctes, usurpation d'une adresse de proxy, désactivation et changement de réseaux à chaud, dernier saut transféré et HTTP direct vérifiés. Aucune validation en production.
- Aucune migration. Déployer le serveur Python puis redémarrer VODUM pour appliquer les ajustements Waitress ; les réseaux autorisés et la configuration du reverse proxy restent à adapter à chaque installation.

### Collections — cache des affiches et récupération des franchises (2026-11-21)

- Correction du 502 sur certaines affiches IMDb : les originaux, dont « Meet Walter », dépassaient la limite de 2 Mo. Le [proxy](app/core/collections_portraits.py) demande désormais des miniatures adaptées et conserve les images sur disque dans `collection_posters` à côté de la base (`/appdata/collection_posters` par défaut, configurable avec `VODUM_COLLECTION_POSTER_CACHE_DIR`). Réutilisation pendant 30 jours, conservation d'une image périmée en cas de panne amont, écritures atomiques et nettoyage périodique vers un plafond de 256 Mio. Le cache se remplit à la consultation et couvre aussi les listes personnalisées.
- L'[éditeur des listes](static/js/pages/collection-lists.js) retente brièvement une image en échec sans la masquer pour toute la session. Les médias déjà marqués comme résolus mais sans affiche sont à nouveau enrichissables ; les informations partielles restent relançables. [Documentation du cache](vodum-docs/docs/collections.md) actualisée.
- Le [moteur Franchise](app/core/collections_franchises.py) conserve l'identifiant et le marqueur de propriété d'une ancienne collection de la même configuration lors d'un changement de clé, même si un précédent échec a réservé la nouvelle clé sans créer de collection distante. L'aperçu ne modifie pas ces références. La propriété distante reste vérifiée ; une collection externe de même nom n'est ni adoptée ni écrasée.
- Les collisions traitées restent des avertissements avec le détail disponible des identifiants en conflit, sans être réintroduites comme erreurs de tâche par un résultat enfant ou une [reprise de publication](app/core/collections_publication.py). Stargate séries est déjà présent dans les listes ; le log fourni signalait une collision de titre et non l'absence de sa source.
- Association d'[affiches spécifiques](app/core/collections_posters.py) à Stargate, Harry Potter / Fantastic Beasts et Terre du Milieu au lieu du visuel générique. [Provenance des visuels](docs/collections-poster-sources.md) documentée ; les versions précédentes sont conservées. Une génération ImageGen refusée a été remplacée par une affiche Stargate existante, sans contournement du filtre.
- Aucune migration de schéma. Déployer modules, JavaScript et fichiers d'affiches, puis redémarrer application et worker. Garder le répertoire de cache sur le volume persistant. Les nouvelles affiches de franchises sont appliquées lors de leur prochaine synchronisation ; aucun changement n'a été exécuté sur l'instance Plex de production.
- Validation : 72 tests Python ciblés passent, plus le test JavaScript de pagination des listes. « Meet Walter » vérifié en direct avec une miniature JPEG de 5 519 octets puis une relecture locale ; couverture du cache concurrent, de la panne amont, de son nettoyage, des références de collections et des états partiels. L'identité exacte de la collection distante qui bloque Stargate en production reste à vérifier sur l'instance.

### Collections — collection issue d'une liste de médias (2026-11-21)

- Ajout du modèle « Liste de médias » dans « More ways to discover » au [catalogue](app/core/collection_catalog.py). Une configuration choisit une liste VODUM ou personnelle et reprend son nom ; bibliothèques films/séries ou paire de bibliothèques, limite, tri, fréquence, visibilité, priorité et acquisition Arr utilisent les réglages habituels.
- Le [sélecteur de liste](static/js/pages/collections.js) propose une recherche insensible aux accents, huit résultats par page dans une zone de hauteur limitée et un rappel permanent de la sélection. Une recherche ou un changement de page conserve le choix. [Interface](templates/collections/collections.html), [styles](static/css/collections.css), traductions des cinq langues et compteur du catalogue actualisés.
- Le [moteur](app/core/collections_media_list.py) publie une seule liste par bibliothèque, avec uniquement ses entrées activées du type correspondant, sans minimum de deux films présents. Aperçu, acquisitions, suppressions et protections de propriété réutilisent le moteur partagé. Les listes utilisées apparaissent dans les [collections associées](app/core/collections_lists_admin.py) et ne peuvent pas être supprimées.
- Les correspondances TMDB restent nécessaires pour la publication ; un titre affichable grâce à IMDb ne garantit pas sa présence dans une nouvelle collection. En cas d'identification partielle, les membres existants sont préservés. Les modifications de contenu prennent effet à la prochaine exécution ; les listes absentes ou désactivées sont refusées. [Documentation utilisateur](vodum-docs/docs/collections.md) et [sources](vodum-docs/docs/collection-sources.md) complétées.
- Aucune migration de schéma : configuration stockée dans le JSON existant. Déployer modules, worker, template, JavaScript, CSS et traductions ensemble, puis redémarrer application et worker avant de créer ce modèle.
- Validation : 63 tests Python ciblés passent, plus le test JavaScript du sélecteur avec 1 000 listes. Parcours Chromium ordinateur/mobile avec 1 009 listes, recherche, pagination, choix, enregistrement et réouverture vérifiés localement. La suite streaming élargie conserve 3 échecs et 10 erreurs identiques avec ou sans la modification du moteur partagé ; un ancien test JavaScript Continents échoue aussi sur un helper absent de son contexte simulé. Aucune validation en production.

### Collections — navigation des listes plus compacte (2026-11-21)

- Dans l'[éditeur de listes](static/js/pages/collection-lists.js), retrait de l'origine « VODUM / Custom » sous les noms dans la navigation pour afficher davantage de listes. L'origine apparaît désormais sous le titre du contenu, avant le libellé et le nombre de médias. L'indication des listes désactivées reste visible.
- Aucune migration ; mise à jour du JavaScript uniquement. Syntaxe et rendu HTML généré vérifiés localement, sans validation en production.

### Collections — métadonnées IMDb et recherche par identifiants (2026-11-21)

- Ajout d'un [recours direct à IMDb](app/core/collections_list_metadata.py) par identifiant exact lorsque TMDB n'a pas de correspondance : titre, année et affiche sans remplacer l'identité d'origine ni rechercher un titre approximatif. Les titres vérifiés du catalogue VODUM servent de secours si IMDb est indisponible ; cet état partiel reste relançable sans inventer d'année ou d'affiche.
- L'[éditeur](static/js/pages/collection-lists.js) retente automatiquement les anciens échecs IMDb une fois avec ce nouveau mécanisme. Les nouveaux échecs restent relançables manuellement. Les titres personnalisés, activations et origines sont préservés par l'[API](app/routes/collection_lists.py).
- Le [proxy d'affiches](app/core/collections_portraits.py) accepte aussi les images IMDb sur un hôte fixe, sans redirection, avec validation du chemin, du type et de la taille. Aucun accès à une URL arbitraire.
- Recherche par titre, `tt123` ou `imdb:tt123`, `tvdb:123`, `tmdb:123`, ainsi que `tmdb:movie:123` / `tmdb:tv:123`. Un numéro TMDB sans type vérifie films et séries ; TVDB passe par la correspondance TMDB des séries. Les numéros seuls restent des recherches de titre pour éviter de deviner le fournisseur. Libellés actualisés dans les cinq langues.
- Aucune migration de schéma ; déployer modules, API, JavaScript et traductions ensemble puis redémarrer. Les métadonnées sont conservées dans les colonnes existantes à l'ouverture des listes. IMDb reste une dépendance externe susceptible d'être indisponible.
- Validation : dix tests locaux ciblés (recherche, identité, secours, persistance et proxy), vérification directe des huit identifiants de la capture avec titre/année/affiche et chargement réel d'une affiche via le proxy. Aucune validation de l'instance de production.

### Collections — activation et suppression des médias (2026-11-21)

- Dans l'[éditeur de listes](static/js/pages/collection-lists.js), la colonne d'activation porte désormais le titre « Activé » et utilise un interrupteur accessible au clavier. La poubelle occupe une colonne réservée sur toutes les lignes, y compris celles des médias VODUM non supprimables, pour conserver l'alignement.
- La confirmation native est remplacée par une [boîte de dialogue](templates/collections/_lists.html) utilisant les [styles VODUM](static/css/collections.css), le titre du média et l'avertissement sur la conservation dans les bibliothèques. Annulation sélectionnée par défaut ; Échap annule. Une navigation vers une autre liste annule l'action en attente.
- Aucune migration ; déployer template, JavaScript et CSS ensemble. Vérifications locales, sans validation en production.

### Collections — recherche unifiée et affiches (2026-11-21)

- L'[ajout de médias](static/js/pages/collection-lists.js) recherche films et séries ensemble sans sélecteur de type ; chaque résultat garde son type pour permettre le choix en cas d'ambiguïté. Les identifiants IMDb recherchent aussi les deux catégories ; les personnes sont exclues.
- L'[API de recherche](app/routes/collection_lists.py) transmet désormais le chemin validé des affiches TMDB, qui manquait dans ses résultats. Le proxy d'images existant est conservé, avec une vignette de remplacement en l'absence d'affiche.
- Aucune migration. Déployer API, JavaScript et [CSS](static/css/collections.css) ensemble. Validation locale avec réponses TMDB simulées ; pas de validation en production.

### Collections — retrait des paramètres de liste (2026-11-21)

- Suppression du bloc « List settings » dans l'[éditeur de listes](static/js/pages/collection-lists.js), avec ses champs de nom et d'activation, son bouton Enregistrer et la suppression des listes personnalisées qui y figurait. Les commandes de contenu des médias sont conservées.
- Retrait des styles associés dans la [feuille Collections](static/css/collections.css). Aucune migration nécessaire ; déployer les deux fichiers statiques ensemble. Vérification syntaxique JavaScript locale, sans validation en production.

### Collections — tableaux de contenu et identification des médias (2026-11-21)

- Réorganisation de l'[éditeur de listes](static/js/pages/collection-lists.js) : les
  collections associées sont affichées en haut dans un petit tableau lorsqu'il y
  en a plusieurs, ou sur une ligne sans tableau pour une seule. Une configuration
  regroupant films et séries est comptée une seule fois, avec ses bibliothèques.
  Le contenu apparaît en dessous dans un tableau avec mini-affiche, titre, type,
  origine et activation. La navigation de gauche est conservée.
- L'ajout de média dispose de son encadré avec recherche et résultats ; le filtre
  du contenu est séparé. Les réglages de nom/activation de la liste sont repliables.
  Adaptation mobile et traductions des cinq langues actualisées.
- Correction du chargement des titres : le premier identifiant sans correspondance
  interrompait la boucle et empêchait le traitement des suivants. Deux requêtes au
  maximum sont maintenant traitées en parallèle ; une absence de correspondance
  est conservée et affichée sur sa ligne avec identifiant, type et action Réessayer.
  Le bandeau générique sans média concerné n'est plus utilisé pour ce traitement.
  Les pannes réseau restent visibles sur les lignes traitées et un arrêt après
  erreurs répétées évite de solliciter inutilement TMDB.
- Les [métadonnées](app/routes/collection_lists.py) enrichissent aussi les entrées
  possédant déjà un titre pour récupérer leur affiche, sans écraser leur titre ni
  leur activation/origine. Les affiches utilisent le proxy TMDB existant, avec
  remplacement discret lorsqu'une image manque. Aucune recherche par titre
  approximative ne remplace une identité introuvable.
- Migration additive au [démarrage](app/core/db_bootstrap_collections.py) de la table
  `franchise_list_items` : `poster_path`, `metadata_state`, `metadata_error` et
  `metadata_checked_at`. Déployer schéma, modules, templates, CSS, JavaScript et
  traductions ensemble, puis redémarrer avant de rouvrir les listes. Le chargement
  reprend à l'ouverture de la liste ; il ne s'agit pas d'un traitement en arrière-plan.
- Validation : 228 tests ciblés passent, dont migration répétée sur ancien schéma,
  conservation des personnalisations, absence de correspondance suivie d'une entrée
  valide, cache des métadonnées et regroupement des bibliothèques. Parcours Chromium
  vérifié sur ordinateur/mobile, avec une ou plusieurs collections liées et reprise
  après identifiant introuvable. Réponses TMDB simulées ; aucune validation sur
  l'instance de production ni promesse de résoudre les identifiants absents de TMDB.


### Développement — rangement des fichiers de travail des agents (2026-11-21)

- Déplacement des trois logs de diagnostic présents à la racine dans
  `tools/codex/logs/`. Les fichiers sont conservés ; aucune donnée d'exécution
  utilisée par VODUM n'est déplacée.
- Ajout d'une [consigne persistante](AGENTS.md) pour placer les prochains logs,
  audits, rapports et fichiers temporaires des agents sous `tools/codex/`.
  Les exclusions Git et Docker existantes de `tools/` suffisent ; aucune règle
  supplémentaire ajoutée à `.gitignore`. Les sources et documents du projet
  conservent leurs emplacements. Aucune migration ni déploiement nécessaire.


### Dashboard — jauges CPU/RAM à gauche du statut (2026-11-21)

- Dans la [carte Serveurs](templates/dashboard/partials/_servers.html), les jauges
  CPU/RAM passent à gauche du statut Online/Offline. L'heure ou la date reste sous
  le statut ; les valeurs et leurs conditions d'affichage sont conservées.
- Aucune migration ni changement du JavaScript ; déployer le template actualisé.


### Collections — reprise Franchise bloquée par une collision de nom (2026-11-21)

- Un refus de publication pour nom déjà utilisé ne reste plus dans les
  [plans de publication](app/core/collection_inventory.py). Il ne sera donc pas
  rejoué comme une mise à jour d'adhésion inachevée lors d'une reprise.
- Les [reprises des anciens lots Franchise](app/core/collections_publication.py)
  traitent également ces collisions par franchise : avertissement avec son nom,
  suppression de son seul plan bloqué, puis poursuite des autres publications.
  La collection bloquée n'est pas marquée synchronisée et aucune collection distante
  non reconnue comme appartenant à VODUM n'est adoptée, modifiée ou supprimée.
- Une véritable collision reste à résoudre en renommant la liste ou la collection
  existante concernée. Les échecs de vérification de propriété restent bloquants ;
  leurs plans sont conservés pour diagnostic/reprise. Aucune nouvelle migration ni
  purge manuelle requise : déployer les deux modules puis redémarrer le worker.
- Régression reproduite dans les [tests de plans](tests/test_collection_publication_plans.py),
  avec un ancien lot de deux franchises dont la première rencontre une collision,
  la poursuite de la seconde, et l'absence de rejeu du plan rejeté. Contrôles locaux
  sur adaptateurs simulés : 224 tests ciblés passent. Aucune validation de publication
  sur l'instance réelle.


### Collections — onglet Listes générique et navigation compacte

- Les textes de l'[onglet Listes](templates/collections/_lists.html) parlent de
  listes de films et séries et de collections associées, sans les limiter au modèle
  Franchise. Ce changement de présentation ne crée pas le futur modèle permettant
  de sélectionner une liste librement ; le raccordement actuel reste inchangé.
- Le [panneau de navigation](static/js/pages/collection-lists.js) utilise des lignes
  compactes dans un cadre unique, une sélection mise en évidence, des compteurs
  alignés et une recherche par nom. La création d'une liste est regroupée dans
  un volet dépliable. Le filtrage conserve la liste ouverte et affiche un état vide.
- Traductions adaptées dans les cinq langues et révision des ressources actualisée.
  Aucune migration ; déployer templates, CSS, JavaScript et traductions ensemble.
  Rendu et parcours contrôlés dans Chromium sur grand écran et mobile, avec recherche,
  création et suppression personnelle ; template vérifié dans les cinq langues et
  syntaxe JavaScript contrôlée. Les métadonnées sont simulées pour ces contrôles.


### Collections — sélection des franchises en grille

- Dans la [configuration Franchise](templates/collections/collections.html), les
  listes sont présentées dans une grille de cases encadrées, comme les événements
  Seasonal : deux colonnes sur grand écran et une sur mobile. Chaque case contient
  uniquement la sélection et le nom de la liste, sans date ni emoji ajouté.
- Le même rendu est conservé après création ou modification d'une liste dans
  l'éditeur. Sélection et enregistrement restent inchangés. Aucune migration ;
  déployer le template et le [JavaScript](static/js/pages/collections.js) ensemble.
  Rendu vérifié dans Chromium sur grand écran et mobile, cases à cocher contrôlées ;
  validation du template dans les cinq langues et syntaxe JavaScript vérifiées.


### Collections — Stargate, Harry Potter et Terre du Milieu

- Ajout de trois [listes locales](app/data/franchise_lists.json) sélectionnables
  dans Franchise : Stargate (4 films, 5 séries), Harry Potter & Fantastic Beasts
  (11 films), The Lord of the Rings & The Hobbit (10 films, 1 série).
  Les adaptations animées et séries dérivées sont incluses ; les épisodes
  individuels, documentaires et projets non sortis ne sont pas ajoutés.
- Les titres des nouvelles entrées sont conservés en base pour la future édition.
  L'identifiant du film Stargate Origins: Catherine est distinct de la série :
  [correction publiée par IMDb](https://community-imdb.sprinklr.com/conversations/data-issues-policy-discussions/incorrectly-merged-stargate-origins-catherine-movie-with-tv-series/683e9a3840333655d36a376b).
- Ces trois univers utilisent provisoirement l'[affiche Franchise commune](app/core/assets/collection_posters/franchises-v1.png).
  Aucune nouvelle table : déployer données et code ensemble, puis redémarrer
  pour initialiser les ajouts sans écraser les personnalisations. Une sélection
  déjà enregistrée reste inchangée : cocher les nouvelles listes pour l'étendre.
  Validation : 174 tests ciblés passent ; formulaire vérifié dans Chromium.
  Aucune validation en production.

### Collections — onglet Listes et édition du contenu

- Ajout de l'[onglet Listes](templates/collections/_lists.html) : consultation et
  filtrage des films/séries, création et renommage de listes, activation des listes
  et médias, recherche par titre ou identifiant IMDb, puis ajout d'un média vérifié.
  Les nouvelles listes sont proposées dans la configuration Franchise sans recharger
  la page et sont utilisables par le moteur existant.
- La [gestion des listes](app/core/collections_lists_admin.py) distingue les éléments
  fournis par VODUM des ajouts personnels. Les listes et médias VODUM peuvent être
  désactivés mais pas supprimés, y compris par requête directe. Seuls les ajouts
  personnels sont supprimables ; une liste personnelle utilisée doit d'abord être
  retirée des configurations associées. Aucun fichier média n'est supprimé.
- Chaque liste affiche les configurations Franchise qui la sélectionnent et leurs
  serveurs/bibliothèques, y compris les configurations désactivées. Un lien ouvre
  leur configuration. Les changements de contenu prennent effet lors d'une prochaine
  synchronisation ; aucune exécution automatique n'est ajoutée par l'éditeur.
- Les [routes d'administration](app/routes/collection_lists.py) utilisent les contrôles
  administrateur et CSRF existants. Les titres manquants sont chargés progressivement
  via TMDB, enregistrés sans modifier les activations et peuvent être relancés en cas
  d'échec. Recherche, ajout et identification nécessitent la clé TMDB configurée ;
  les titres déjà enregistrés et les changements d'activation restent accessibles
  sans appel réseau. Aucune liste publique n'est téléchargée.
- Retrait de l'encadré technique « Local VODUM lists… » de la configuration Franchise
  et de son récapitulatif, à la demande de l'utilisateur. Traductions de l'éditeur
  dans les cinq langues ; affichage adapté aux petits écrans. Les listes personnelles
  utilisent l'affiche Franchise commune.
- Aucune nouvelle migration : réutilisation des deux tables de listes déjà créées.
  Déployer ensemble routes, moteur, templates, CSS, JavaScript et traductions, puis
  redémarrer. Validation : 188 tests ciblés, contrôle de syntaxe JavaScript et parcours
  Chromium sur base temporaire (création, recherche/ajout, suppression personnelle,
  désactivation, associations, mise à jour de la configuration et format mobile).
  Les réponses TMDB sont simulées dans ces contrôles ; aucune validation sur serveur
  Plex/Jellyfin réel ni en production.

### Collections — listes locales pour Franchise

- Franchise utilise désormais six [listes intégrées à VODUM](app/data/franchise_lists.json)
  plutôt que de télécharger le contenu de listes publiques. Dans sa
  [configuration](templates/collections/collections.html), seuls leurs noms sont
  affichés avec des cases à cocher, ainsi que dans le récapitulatif.
- Une liste peut contenir films et séries ; chaque bibliothèque utilise les entrées
  de son type. La sélection accepte une bibliothèque ou une paire films/séries.
  Les configurations existantes sélectionnent les six listes par défaut et
  conservent leurs identifiants de publication.
- Deux tables additives sont initialisées au démarrage par le
  [bootstrap](app/core/db_bootstrap_collections.py). L'initialisation répétée préserve
  les noms modifiés et les désactivations. Les listes et entrées fournies portent
  un indicateur VODUM ; leur interface d'édition et de désactivation reste à faire
  dans un futur onglet, sans action de suppression exposée ici.
- Le contenu initial provient du catalogue déjà embarqué, arrêté au 2026-10-29.
  TMDB reste utilisé pour résoudre les identités et les métadonnées ; cette
  modification ne constitue pas une validation actuelle de chaque titre.
- Déployer ensemble code, données JSON, traductions, templates et JavaScript,
  puis redémarrer pour créer les tables et initialiser les listes. Pas de migration
  destructive. Validation : 172 tests ciblés passent, syntaxe JavaScript vérifiée
  et formulaire contrôlé dans Chromium. Aucune validation en production.

### Dashboard — date compacte et libellés CPU/RAM lisibles

- Dans la [carte Serveurs](templates/dashboard/partials/_servers.html), le dernier
  contrôle affiche uniquement l'heure lorsqu'il date d'aujourd'hui, sinon uniquement
  la date, selon le jour local du navigateur. L'horodatage complet reste en infobulle.
  Ce format est limité à cette carte ; les autres dates gardent leur affichage.
- Les libellés [CPU et RAM](templates/dashboard/partials/_server_resource_mini_bars.html)
  passent sous leurs barres verticales, à côté du statut et de son horodatage.
  Les valeurs absentes ou les serveurs hors ligne ne reçoivent pas de jauge fictive.
- Mise à jour de la [révision du JavaScript](templates/base.html) pour charger le
  nouveau [formatage](static/js/app.js). Aucune migration ; déployer templates et
  JavaScript ensemble. Rendu vérifié dans Chromium avec le CSS de l'application,
  date locale et passage de minuit contrôlés ; aucune validation en production.

### Annulation des développements Collections du 2026-11-20

- Retrait des ajouts Lists, préparation/migration de catalogue, nettoyage et
  multi-cibles réalisés depuis 7 h ; retour des fichiers concernés à leur état
  antérieur, en conservant les travaux plus anciens. Les changements annulés ne
  sont plus annoncés comme disponibles. Aucune migration de base réelle exécutée
  par ce travail ; une copie de l'état annulé est conservée hors du dépôt.

### Planification — gestionnaire de listes internes Collections

- Ajout du chantier au [TODO](TODO.md), avant Configuration Manager, avec
  audit, conception, catalogue officiel, personnalisations, interface Lists,
  intégration, migration idempotente et validation.
- Conservation du [cahier des charges complet](docs/collections-internal-lists.md).
  Cette mise à jour documentaire ne modifie pas le moteur Collections et
  n'exécute aucune migration.

### P0 — fiche utilisateur moins dépendante des écritures SQLite

- Les lectures initiales de la [fiche utilisateur](app/routes/users_detail.py)
  passent par un [snapshot indépendant](app/core/user_detail_repository.py) :
  profil, abonnement, réglages et informations propres à chaque onglet peuvent
  être lus pendant qu'une écriture utilise la connexion partagée. Les lectures
  d'enregistrement restent inchangées, sans cache.
- [Mesure locale et limites](docs/performance-user-profile-header-2026-11-19.md) :
  avec une écriture simulée de 250 ms, ce bloc passe d'environ 250 ms à 2–6 ms,
  avec des résultats identiques sur les cinq onglets. Cette mesure ne représente
  pas le temps HTTP complet ; validation réelle conservée au [TODO](TODO.md).
- 50 tests passent et Flask démarre avec 220 routes sur base temporaire.
  Aucune migration ; déployer ensemble la route et le repository, puis
  redémarrer. Aucune validation en production.

### P0 — supprimer les écritures optionnelles sans changement sur les pages

- Les [observations de langues](app/core/language_telemetry.py) vérifient l'état
  enregistré avant de prendre le verrou d'écriture SQLite. Une combinaison déjà
  connue aujourd'hui, ou une journée ayant atteint sa limite, ne déclenche plus
  de transaction tant qu'aucune donnée ancienne n'est à purger.
- Consentement, champs anonymes, exclusion HTMX, normalisation, rétention,
  déduplication et plafond de 32 restent inchangés. Les écritures nécessaires
  gardent leur vérification atomique ; aucun cache ni donnée collectée n'est
  ajouté. Les contrôles d'autorisation ne sont pas modifiés.
- [Mesure et limites](docs/performance-language-observations-2026-11-19.md) : sur
  100 visites répétées, 100 transactions et 200 instructions DELETE/INSERT passent
  à zéro, pour la même observation finale. Les timings locaux variables ne
  permettent pas d'annoncer un gain stable de latence ; la lecture préalable et
  l'ouverture de connexion restent présentes. Mesure sous charge réelle au
  [TODO](TODO.md).
- Aucune migration ; déployer le module et redémarrer. Neuf tests de télémétrie,
  cinq tests des réglages par requête et six tests de résolution de langue
  passent localement ; aucune validation en production.

### P0 — suivi Collections sans transaction d'écriture inutile

- Le [suivi Collections](app/routes/collections.py) charge ses données dans un
  snapshot SQLite indépendant et récupère les publications par jointure. Sur
  500 cartes avec snapshots, les SELECT passent de 519 à 19 ; les réponses JSON
  complètes restent identiques. Détail individuel, mode compact et repli des
  anciennes publications sont conservés.
- La [récupération des runs](app/core/collections_repository.py) contrôle d'abord
  en lecture isolée si une réparation est nécessaire. Elle évite la transaction
  d'écriture à vide ; les réparations effectives conservent leur transaction et
  revérifient les leases et commandes avant modification.
- [Mesure et limites](docs/performance-collections-poll-2026-11-19.md) : avec un
  écrivain maintenu artificiellement 250 ms, médiane Flask locale de 267 à 13 ms
  sur cinq mesures. Ce résultat n'est pas une mesure de production ; si une
  réparation est requise, l'attente du verrou reste possible. Le
  [TODO](TODO.md) conserve la validation sur l'instance réelle et le coût du
  repli historique comme travaux ouverts.
- Aucune migration ni nouvel index ; déployer route et dépôt Collections
  ensemble, puis redémarrer. Tests locaux du payload, des lectures concurrentes,
  des reprises et des moteurs Collections/Memoria ; pas de changement visuel.

### P0 — calcul des suggestions de fusion d'utilisateurs

- Le [scoreur](app/core/user_merge_suggestions.py) prépare une seule fois les
  identités et tokens du compte source et réutilise les champs normalisés des
  candidats. Poids, similarités, scores entiers, ordre des ex æquo et limites
  restent identiques ; les comptes ne sont pas modifiés. Les calculs restent
  après fermeture du snapshot SQLite.
- [Mesure locale et limites](docs/performance-merge-ranking-2026-11-19.md) :
  classement de 5 000 candidats de 315 à 212 ms, médianes de cinq exécutions,
  soit environ 33 % de temps CPU en moins. Le
  [benchmark](tools/benchmark_merge_suggestions.py) vérifie les résultats complets.
  Les 288 scores de référence et différentes limites conservent leurs résultats.
- Le [TODO](TODO.md) conserve l'audit des autres calculs CPU redondants comme
  travail ouvert. Aucune migration ni modification d'interface ; déployer le
  module Python et redémarrer. Aucun gain HTTP ou global en production n'est
  déduit de ce benchmark CPU synthétique.

### P0 — réutilisation des filtres de recherche des logs

- Le [lecteur de logs](app/logging_utils.py) réutilise un filtre par niveau et
  recherche entre les pages d'un même snapshot stable. Le cache supplémentaire
  est limité à 512 Kio et ne duplique pas les messages. Les résultats ne sont
  jamais tronqués pour respecter ce budget.
- Ajout, rotation, remplacement, purge et erreurs de lecture invalident le filtre.
  Recherche sur les traces multilignes, casse, compteurs, pagination, export et
  copies défensives sont conservés. Le filtrage initial reste hors du verrou
  partagé des caches.
- [Mesure locale et limites](docs/performance-log-search-2026-11-19.md) : sur
  5 000 événements, recherche répétée de 3,50 à 0,62 ms, médiane de dix mesures.
  La première recherche reste à environ 3,57 ms ; aucun gain HTTP ou en production
  n'est annoncé. Le [TODO](TODO.md) conserve les recherches initiales, fichiers
  changeant continuellement et gros volumes comme travaux ouverts.
- Aucune migration ; déployer le module Python et redémarrer. Vérifications
  locales de régression, d'invalidation et de concurrence uniquement.

### P0 — recherches simples du monitoring utilisateurs

- La [recherche utilisateurs](app/core/monitoring/overview_users.py) utilise les
  identités des comptes ayant un historique pour les requêtes sans espace ni
  joker SQL. Elle évite de répéter les identités pour chaque lecture. Les listes
  n'agrègent plus l'historique des utilisateurs exclus par ce filtre ; les tris
  non agrégés sélectionnent d'abord la page. Comptes liés, déduplication, durées,
  classement et pagination conservent leurs résultats.
- Les recherches avec espaces, `%` ou `_` conservent leur parcours exact.
  Les tris Lectures/Durée sans recherche et la matérialisation des totaux restent
  dans le [TODO](TODO.md), mis à jour sans y réintroduire de lots terminés.
- [Mesure locale](docs/performance-monitoring-users-2026-11-19.md) : sur 100 082
  lectures et une recherche correspondant à dix groupes, liste par dernière
  lecture de 384 à 18 ms, compteur de 77 à 2,5 ms (médianes de cinq mesures).
  Le [benchmark](tools/benchmark_monitoring_users_page.py) accepte `--search`.
  Résultats SQL comparés, plans indexés et lectures concurrentes vérifiés.
- Aucune migration ni nouvel index ; déployer le module Python et redémarrer.
  Ces chiffres ne sont pas des temps HTTP ni une validation sur l'instance
  de production ; les recherches très larges restent proportionnelles au volume
  de sessions des groupes retenus.

### Planification du Configuration Manager & Compliance

- Ajout au [TODO](TODO.md) du chantier en cinq phases : audit et consultation,
  profils/groupes, conformité et intégration à `check_servers`, déploiement,
  puis correction des écarts. Les contraintes de sécurité, compatibilité,
  performance, traduction et tests sont conservées.
- Le [cahier des charges complet](docs/configuration-manager-compliance.md) est
  conservé dans le dépôt. Ajout documentaire uniquement : aucune implémentation,
  migration ou modification de comportement ; faisabilité des API à vérifier
  lors de l'audit prévu. Liens locaux vérifiés.

### Nettoyage du dossier de développement

- Retrait du projet des temporaires `.tmp`, caches Ruff/Python, dépendances
  Node et cache pnpm régénérables, journaux de diagnostic, anciens rapports
  d'audit déjà retirés des sources versionnées et deux anciens scripts de
  diagnostic. 4 571 fichiers, environ 230 Mo, déplacés dans une quarantaine
  locale hors du projet : `C:\Users\sylva\AppData\Local\Temp\vodum-cleanup-20261119`.
  Le manifeste de ce dossier permet de retrouver leurs emplacements initiaux.
  La suppression définitive a été refusée par le contrôle automatique ; aucun
  fichier n'a été détruit pour contourner ce refus.
- Tests de régression, outils de validation/benchmark, environnement Python,
  `.env.example`, manifestes Node, sources, assets, migrations, traductions et
  documentation utile conservés pour le fonctionnement et la maintenance.
  Une reconstruction du CSS nécessite de réinstaller les dépendances Node
  depuis les manifestes conservés ; les assets déjà construits restent présents.
- Le [TODO](TODO.md) et une note technique ne pointent plus vers les rapports
  retirés. La [documentation de configuration](vodum-docs/docs/configuration.md)
  couvre aussi les variables de compression et de budget du snapshot de sauvegarde.
- Aucune migration, aucune modification d'INFO ni des données de production.
  Démarrage réel local sur base temporaire : 220 routes et contrôles HTTP de base
  vérifiés. Documentation vérifiée ; le validateur des traductions signale des
  écarts de clés préexistants, sans modification des catalogues par ce nettoyage.

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
