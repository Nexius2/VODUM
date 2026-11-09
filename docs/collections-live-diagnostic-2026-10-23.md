# Diagnostic des collections sur l’instance réelle

Instance testée : VODUM 26.10.22 b1928. Contrôles réalisés les 22 et 23 octobre 2026 depuis l’interface authentifiée.

## Résultats observés

- L’inventaire partagé Plex fonctionne : le dernier passage affiché dure 82,283 secondes pour cinq bibliothèques, dont 28 015 films et 6 554 séries dans la bibliothèque principale. Les deux serveurs Jellyfin sont affichés hors ligne ; leurs neuf bibliothèques restent en erreur sans invalider les inventaires Plex.
- L’aperçu Spotlight lancé le 22 octobre à 20:07:54 échoue en 26 secondes. L’exécution réelle demandée ensuite démarre à 20:25:14, après les aperçus Memoria, et échoue en 16 secondes. Les logs identifient `CollectionOwnershipError` : la collection Plex 79440 a le bon type et la bonne bibliothèque, mais la comparaison sensible à la casse ne reconnaît pas le marqueur VODUM enregistré avec un V majuscule.
- L’aperçu Memoria Films termine sa sélection en 76 secondes, avec 74 médias présents et 176 absents. L’aperçu de la bibliothèque Séries atteint ensuite la limite de 15 minutes pendant l’étape inventaire. Aucun ajout ARR n’est effectué par cet aperçu.
- La programmation automatique du 23 octobre montre également un dépassement de délai en lecture des séries. Un autre passage programmé a effectué des acquisitions ARR ; il ne fait pas partie des tests manuels en aperçu.
- Une seule carte Spotlight apparaît dans l’historique, y compris après le remplacement de l’aperçu par l’exécution réelle.

## Cause de la lenteur des séries reproduite localement

`plexapi.video.Show._loadData` lit `self.childCount` pour initialiser `seasonCount`. Lorsque le XML local omet ce champ, PlexPartialObject déclenche une recharge distante pendant sa propre construction. La reconstruction de milliers de séries depuis le cache redevient alors une suite de milliers de requêtes.

Le correctif fournit les compteurs neutres nécessaires aux objets d’identité locaux. Les opérations qui ont réellement besoin de métadonnées complètes conservent leur recharge explicite. Avec PlexAPI 4.18.3, 6 554 séries ont été reconstruites en 0,824 seconde sans connexion. Le même essai avec l’ancienne construction déclenche une connexion dès le premier objet.

## Corrections locales supplémentaires

- Confirmation par relecture de l’étiquette d’une nouvelle collection avant son renommage et sa publication. Si Plex ne confirme pas cette étiquette, l’identifiant enregistré et le nom temporaire sont préservés pour permettre une reprise.
- Un refus de propriété interrompt Spotlight immédiatement, au lieu de répéter les tentatives sur chaque titre sélectionné.
- L’historique conserve les codes de propriété et de collision connus, sans exposer les messages arbitraires des services externes.

## Limites et travail restant sur le serveur

Validation locale finale : 291 tests Python réussis avec PlexAPI 4.18.3, contrôle syntaxique JavaScript et tests de l’historique réussis. Les régressions couvrent explicitement la reconstruction des séries sans connexion, le marqueur non confirmé avant renommage, la reprise d’une création temporaire et l’arrêt immédiat sur refus de propriété.

Les modifications sont dans le dépôt local. Elles ne sont pas installées automatiquement sur l’instance distante par l’interface VODUM. La publication après correctif n’est donc pas validée sur le serveur.

Le contrôle authentifié dans Plex a confirmé que la collection 79440 existe avec un seul film et porte le marqueur `Vodum:collection:07318562-c4c2-4dca-8c59-5064f72ae495`. Le code cherchait le préfixe minuscule `vodum:collection:`. La comparaison de la totalité du marqueur est désormais insensible à la casse, tout en exigeant le même UUID et la même bibliothèque. Un test utilisant un véritable objet Collection PlexAPI et ce XML vérifie le succès avec la majuscule et le rejet d’un autre UUID. Aucune étiquette ni collection Plex n’a été modifiée pour contourner le problème.

Après déploiement : relancer Spotlight sur cette collection existante, confirmer les membres et la visibilité dans Plex, puis refaire l’aperçu Memoria sur les séries et mesurer sa durée. Les serveurs Jellyfin hors ligne doivent retrouver une connexion valide pour que leur inventaire réussisse.


## Nouveau contrôle : version 26.10.23 b0929

Contrôle authentifié de VODUM et Plex le 23 octobre 2026. Aucun contenu de collection n’a été modifié pendant la comparaison.

### Erreur actuelle

Le passage films 92 termine en avertissement à 09:42:52 : 256,2 secondes, 102 présents, 266 absents, 6 acquisitions ARR, aucune erreur. Le passage séries 93 échoue à 09:45:55 après 182,3 secondes, à l’étape discovery : ConnectionError dans MemoriaSource.recent_deaths vers Wikidata. Il ne s’agit donc pas du refus de propriété Plex observé précédemment.

Corrections locales : cache de découverte partagé entre bibliothèques pendant six heures, avec une clé contenant les dates, les métiers et la langue ; absence de répétition automatique des requêtes Wikidata et délai de lecture de 30 secondes ; maintenance des hommages vérifiés encore actifs lorsque Wikidata est indisponible, avec un avertissement explicite. Sans personne connue et sans cache valide, l’échec reste visible. Les identités et décès continuent à être vérifiés dans TMDb.

### Comparaison complète de Richard Riehle

Collection VODUM 79384 : 74 films. Collection Memoria 79364 : 81 films. Relevé des 74 et 81 identifiants Plex par les listes de l’interface : 62 identifiants communs, 19 uniquement dans Memoria, 12 uniquement dans VODUM. Le solde de sept ne correspond donc pas à sept entrées simplement oubliées.

Uniquement dans Memoria : Halloween 2 (4814), À bout de souffle made in USA (4960), Le Plus Beau Cadeau du monde (67960), Boomerang (6167, 32613, 54848), Driven (7928, 45599), Hero (8394), Hindsight (21511), Des Gens Comme Nous (24378), Friend Request (36668), Dans le noir (37321), Last Call (35743), Adorables ennemies (41724), Terminal (44313), L’épreuve du feu (47281), Limbo (48354), Underground Fights (58193).

Uniquement dans VODUM : The Invisible Raptor (79418), Les Appâts Du Gain (79433), In Your Eyes (79406), Hacked: A Double Entendre of Rage Fueled Karma (79397), Fear, Inc. (36603), The Cowboy Killer (79386), Judas Kiss (79416), Ken Park (79394), Mysterious Skin (79423), Jury Duty (79398), The Last Lovecraft: Relic of Cthulhu (79395), Trop, c’est trop ! (79410).

Le code voisin memoria/app/services/plex_local_index_service.py, fonction find_local_matches_for_target, utilise une correspondance par titre sans année si la correspondance avec année échoue. Cela peut inclure des homonymes ; le nombre 81 ne constitue pas à lui seul une référence d’exactitude. L’appartenance exacte de chacun des 19 films à la filmographie n’a pas été vérifiée individuellement.

VODUM conserve la correspondance avec année et ajoute une recherche Plex ciblée acteur/réalisateur en complément du cache : le scan de section peut omettre des rôles secondaires. Aucun scan complet supplémentaire n’est lancé pendant les collections. L’effet de ce complément sur le compte réel reste à mesurer après déploiement.

### Historique corrigé localement

Une carte par configuration et par personne, fusion films/séries d’une même configuration, dernier résultat publié par bibliothèque, aucune limite arbitraire à trois personnes. Les cartes gardent la liste des titres et les statuts ARR, les compteurs et les diagnostics des dernières exécutions. Deux configurations distinctes visant la même personne restent deux cartes distinctes. Les anciennes cartes génériques d’exécution Memoria ne sont plus affichées en tête ; les aperçus et Spotlight conservent leur résultat d’exécution.

Validation : 160 tests Python réussis, contrôles JavaScript réussis, rendu local des deux cartes vérifié dans le navigateur. Les changements de cette section sont locaux : ils ne sont pas déployés sur le serveur par une navigation dans VODUM.


## Contrôle de la version b1317 et suppression des cartes d’exécution

Le contrôle des logs de b1317 confirme que les passages 96 et 97 terminent sans erreurs, mais avec avertissements : 349 secondes pour les films, 493,6 secondes pour les séries. Il serait incorrect de présenter ces durées comme une exécution rapide. Wikidata reste indisponible ; les hommages vérifiés sont néanmoins publiés. La durée de la publication Plex reste à optimiser et à mesurer sur le serveur.

Le reliquat de cartes au-dessus des hommages provenait des anciens aperçus : le rendu précédent les conservait explicitement. Le rendu a été remplacé. L’API expose désormais les objets distants réellement créés (remote_id présent, état différent de deleted) et le dernier résultat publié pour chaque objet. L’interface ne crée de cartes qu’à partir de cette liste, y compris pour Spotlight. Les aperçus et les tentatives ne produisent aucune carte. Films et séries sont réunis uniquement lorsqu’ils appartiennent à la même configuration et à la même personne. Les listes publiées survivent à la fenêtre des 100 exécutions récentes.

Les messages de mise en attente et de programmation en français et anglais n’exposent plus le nom interne run_collections. Le message de mise en attente et l’état vide de l’historique sont également disponibles en allemand, espagnol et italien.

Contrôle Plex concret des homonymes : l’entrée 4814 de la collection Memoria est Halloween 2, 1981, réalisé par Rick Rosenthal. La distribution visible comprend notamment Jamie Lee Curtis, Donald Pleasence et Cliff Emmich (Mr. Garrett). La collection VODUM contient pour sa part l’entrée 17389, Halloween II, 2009. Le rapprochement sans année de Memoria explique donc au moins un ajout d’un autre film portant le même titre. Les 19 entrées propres à Memoria ne sont pas toutes des omissions établies de VODUM.

Corrections supplémentaires du rapprochement VODUM : espaces et ponctuation des titres normalisés, maintien du contrôle de l’année, refus qu’un titre identique écrase un TMDb différent, suppression du marquage présent fondé uniquement sur le nom d’un autre film. Les résultats enregistrent les identifiants des médias locaux pour ne pas masquer des homonymes dans les listes.

Validation locale de cette révision : 164 tests Python réussis, tests JavaScript du rendu réussis, contrôle visuel avec deux cartes et un ancien aperçu (absent du rendu). Un test de l’API vérifie l’exclusion des réservations et des objets supprimés ainsi que la conservation d’une liste publiée plus ancienne que 101 aperçus. Ces modifications restent locales jusqu’à leur déploiement ; aucun nouveau compte de films sur le serveur n’est annoncé.


### Requêtes Plex répétées sur les alias

L’inspection du code PlexAPI installé a confirmé que LibrarySection._validateFieldValueTag recharge listFilterChoices pour une valeur acteur fournie sous forme de chaîne. L’ancienne boucle person_items effectuait une recherche pour chaque alias, provoquant à la fois des téléchargements répétés de l’index des acteurs et des requêtes de médias répétées.

La révision charge les choix acteur/réalisateur une seule fois par adaptateur de bibliothèque, résout tous les alias localement et fournit directement les objets FilterChoice à une recherche par personne et par rôle. PlexAPI reconnaît ces objets et ne recharge pas l’index pour les valider. Les identifiants de médias remontés par cette recherche sont conservés.

Validation finale de cette révision : 165 tests Python réussis, dont une vérification explicite d’un seul chargement d’index pour plusieurs personnes et alias ; tests JavaScript et traductions de mise en attente vérifiés. L’amélioration des durées réelles après ce changement n’est pas encore mesurée sur le serveur.
