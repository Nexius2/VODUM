# In the spotlight / Sélection du moment

Le moteur est adapté du dossier fourni `Selection du moment`, sans importer son YAML, ses variables d’environnement, ses clés ni son lanceur. Seuls le cycle et les règles de découverte/scoring sont repris. Le dossier original reste intact et est exclu localement du suivi Git.

## Configuration dans VODUM

Dans Collections, cliquer sur Sélection du moment, choisir une bibliothèque de films et les options de publication. La clé TMDb est celle de l’onglet Configuration, partagée avec Memoria ; aucune autre clé n’est nécessaire. Les connexions Plex/Jellyfin proviennent des serveurs VODUM. Le moteur utilise `run_collections` et son worker dédié ; il ne lance pas de planificateur supplémentaire.

Valeurs initiales : durée de présence 30 jours calendaires, fenêtre de sorties numériques 30 jours, score minimal 65/100 et piste audio française obligatoire. Ces quatre valeurs sont modifiables. La langue des métadonnées et la langue audio sont distinctes. Tous les médias éligibles sont considérés, sans quota. L’acquisition ARR est désactivée et refusée par l’API pour ce moteur.

## Règles conservées

- Vérification TMDb des sorties numériques mondiales (type 4) pour les films récents présents dans la bibliothèque, avec la première page des tendances hebdomadaires pour le score.
- Confirmation de la sortie numérique dans la fenêtre, y compris les 30 prochains jours. La première sortie mondiale et la date du film sur le serveur doivent se situer entre le début du mois précédent et J+30. Une réédition d’un ancien film ne suffit pas.
- Note pondérée avec 100 votes de référence et moyenne 6. Profils : film événement, bons avis, franchise ou tendance.
- Score : fraîcheur 25, popularité 35, note 25, tendance 10 et franchise 5. Les seuils détaillés restent ceux du script ; le seuil global est exposé dans le formulaire.
- Identifiant TMDb local non ambigu obligatoire ; aucun rapprochement de titre n’est inventé. Parmi plusieurs éditions, une seule avec la langue audio requise est retenue. Sur Plex, chaque partie d’une même édition doit disposer de cette piste.
- Les nouveaux films automatiques sont placés en tête ; les membres existants conservent leur ordre relatif.

## Suivi et protection

Les entrées manuelles ajoutées dans la collection VODUM sont détectées au prochain passage et reçoivent leur durée complète. Les filtres de découverte ne les retirent pas. Un retrait manuel bloque la réintroduction automatique pendant 30 jours. Après expiration, un nouvel événement numérique strictement plus récent est nécessaire pour une réintroduction.

Le journal d’opérations, les dates initiales et les historiques sont conservés dans des tables VODUM isolées par configuration. L’adhésion distante est relue après ajout/retrait ; une réponse perdue reste en attente de réconciliation. Les erreurs sont visibles dans l’état et les journaux. L’historique affiche une seule carte Sélection du moment par configuration : elle est actualisée au dernier passage et conserve la liste des derniers médias dont la publication a été confirmée. Les passages successifs et les publications ne créent pas de cartes supplémentaires ; les journaux complets restent en base. Il présente le début et la durée du traitement, les compteurs et les avertissements sans exiger le debug.

Une simulation travaille dans une copie en mémoire du journal et ne modifie ni le serveur ni le suivi de production. Le nettoyage d’expiration précède les appels TMDb. Désactiver retire la seule collection appartenant à VODUM ; les films ne sont jamais supprimés. Le réglage commun des collections vides est respecté. Aucune collection externe homonyme n’est adoptée.

## Amélioration de coût

Le moteur commence par l’inventaire local : seuls les films avec un identifiant TMDb non ambigu et une date locale comprise entre le début du mois précédent et J+30 sont envoyés à TMDb. La vérification des sorties numériques, de la première sortie mondiale et du score reste celle du script. La découverte ne parcourt plus les pages du catalogue mondial. Une bibliothèque sans candidat récent ne provoque aucun appel TMDb.

Les champs facultatifs Plex (GUID, date, titre original, année) sont lus dans la réponse déjà reçue. Leur absence ne provoque aucun rechargement implicite du média. L’inventaire et les membres confirmés sont réutilisés pendant le passage ; après une mutation, les membres sont relus pour confirmation. Une réponse perdue invalide aussi le cache afin de ne pas écraser un ajout réellement appliqué.

Sur Plex, la création initiale et la mise à jour finale appliquent la configuration complète. Entre les deux, chaque ajout modifie seulement l’adhésion et le placement en tête ; chaque retrait ne touche que l’adhésion. La présence des membres et, sur Plex, le placement en tête sont vérifiés avant de confirmer l’opération. Le nettoyage d’expiration seul n’exige ni inventaire complet ni clé TMDb.

L’accès au débit Plex partagé est ordonné par arrivée pour éviter qu’un worker repasse continuellement devant un autre. La limite globale d’une requête par seconde et par serveur est conservée ; l’arrêt et le verrou sont vérifiés pendant l’attente.

## Validation

Les tests Spotlight couvrent publication confirmée, simulation, durée stable, changement d’heure, retrait manuel, expiration, anti-réintroduction, panne de source, reprise après réponse perdue, audio multipartie, isolement des journaux, règles de dates/scoring et configuration. Les tests Memoria et planificateur sont rejoués. Les adaptateurs utilisent des serveurs simulés ; le premier essai réel reste à faire sur les serveurs de l’administrateur après reconstruction et redémarrage.

Collection names are fixed by presentation language (for example, “Sélection du moment” in French). Default daily/weekly schedules start at 15:00 for Spotlight and 05:15 for Memoria in VODUM’s time zone, with fifteen-minute offsets by library order. Legacy midnight defaults migrate on startup; custom cron expressions are preserved.


## Comprendre un passage sans collection

`Terminé sans publication` signifie qu’aucun film n’a été retenu ou qu’il ne reste aucun membre après nettoyage. Le compte rendu indique les titres lus, les identifiants TMDb disponibles, les dates manquantes, les candidats locaux récents, les fiches TMDb vérifiées et les rejets dus à la sortie initiale, à la sortie numérique, au score, à l’audio ou à une exclusion. Le moteur ne crée pas une collection vide pour masquer ce résultat.

Les aperçus affichent les titres simulés et rappellent qu’ils ne modifient pas le serveur. Les passages en cours enregistrent périodiquement leur étape et leurs compteurs dans le résultat du passage. Les interruptions conservent ce résultat partiel. La colonne de la configuration indique la dernière fin de traitement et le prochain début prévu ; l’historique précise le début du passage.

Régressions vérifiées : 1 000 vrais objets PlexAPI partiels sans rechargement caché ; cycle de 20 ajouts avec deux synchronisations complètes et 19 ajouts incrémentaux ; réponse perdue après ajout ; absence de candidat ; simulation ; nettoyage sans inventaire ; confirmation de l’adhésion distante ; progression persistée et affichage des passages sans publication. Une comparaison locale sur un catalogue simulé de 1 003 titres donne les mêmes films locaux et scores que le script fourni, avec 4 appels TMDb au lieu de 1 005. Il s’agit de nombres d’appels simulés, pas d’une mesure du serveur de production.


## Correction de lecture des GUID Plex

PlexAPI expose `guids` comme propriété calculée depuis le XML, et ne l’insère dans `vars(item)` qu’après son premier accès. L’ancienne optimisation de l’inventaire ignorait donc des GUID présents et pouvait donner une bibliothèque entière sans identifiant TMDb. L’inventaire et les membres lisent maintenant directement les nœuds `Guid` du XML déjà reçu, avec détection des identités contradictoires. Aucun rechargement par média n’est nécessaire. Une bibliothèque non vide sans aucun identifiant lisible est signalée comme erreur, plutôt que comme une sélection vide réussie.

L’inventaire est paginé par lots de 1 000 médias. Pour 28 013 médias, cela représente environ 29 pages au lieu de 281 avec des lots de 100. Les tests vérifient les identifiants effectivement extraits de vrais objets PlexAPI dont la propriété `guids` n’a pas été calculée, puis leur passage dans le moteur jusqu’à la création de collection. Un test qui se contente de compter les médias sans vérifier leurs identifiants ne couvre pas ce défaut.


## Inventaire partagé

Les moteurs utilisent désormais l’inventaire local partagé, alimenté par `refresh_collection_inventory`, et ne relisent plus toute la bibliothèque distante à chaque passage. Voir [Inventaire des collections](collections-inventory.md) pour le premier remplissage, les durées, le planning à 12 heures après la fin et la gestion des pannes.


## Plafond de médias

« Tous les médias » reste le réglage par défaut. Il peut être décoché pour fixer
un nombre maximal de membres, appliqué aussi dans l’aperçu. Le plafond inclut les
ajouts manuels. S’il est réduit, les membres excédentaires sont retirés à partir
de la fin de l’ordre actuel, sans supprimer les fichiers. Les places libres sont
remplies par les candidats admissibles, dans l’ordre du score. Les membres déjà
présents conservent leur durée de présence tant que le plafond ne les écarte pas.
Un retrait dû au plafond n’est pas traité comme une suppression manuelle ou une
expiration ; le titre peut être retenu à nouveau si le plafond augmente.
