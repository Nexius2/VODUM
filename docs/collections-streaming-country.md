# Top streaming par pays

Le moteur par pays utilise `collections_country_availability.py`. Films et
séries suivent la même méthode : le top de chaque grande plateforme par
abonnement du pays, cumulé. Le moteur Worldwide (tendances mondiales) est
distinct et n'est pas concerné.

## Collecte et classement

1. Charger les services TMDb du pays (`/watch/providers/{type}`, `watch_region`),
   triés selon leur ordre d'affichage TMDb dans ce pays (`display_priorities`).
   Les chaînes revendues (« … Amazon Channel », « … Apple TV Channel »…) sont
   ignorées et les offres d'un même service sont regroupées (Netflix et Netflix
   avec pub forment une seule plateforme).
2. Garder les 10 premières plateformes qui proposent réellement des titres en
   abonnement (`flatrate`) ; les boutiques de location/achat, vides, sont sautées
   (30 services examinés au plus).
3. Classement de chaque plateforme :
   - Netflix : le Top 10 officiel hebdomadaire du pays (Tudum), rapproché d'un
     titre TMDb disponible sur Netflix dans ce pays, puis la suite TMDb. Tudum
     publie les titres en anglais : la recherche TMDb se fait en anglais, puis le
     titre est affiché dans la langue de la collection. Un titre non rapproché
     (aucun ou plusieurs candidats) est ignoré sans erreur et mis en cache 24 h ;
   - toutes les plateformes ensuite : le classement de popularité JustWatch dans
     le pays (`apis.justwatch.com/graphql`, `popularTitles`, filtre `packages`
     et `objectTypes`, tri `POPULAR`), qui donne l'identifiant TMDb de chaque
     titre. Les identifiants de packages JustWatch sont ceux des services TMDb ;
   - repli par plateforme : si JustWatch ne répond pas, renvoie une erreur ou ne
     classe rien, la popularité TMDb des titres de la plateforme dans le pays
     (`/discover`, `with_watch_providers`, `flatrate`, `popularity.desc`) est
     utilisée, avec un avertissement (loggé en warning, jamais en erreur).
4. Cumul rang par rang : tous les n°1, puis tous les n°2, etc. À rang égal, un
   titre présent sur plusieurs plateformes passe devant, puis l'ordre des
   plateformes du pays. Les doublons sont fusionnés.
5. La profondeur par plateforme augmente (pages de 20, 100 titres au plus) jusqu'à
   obtenir le « Nombre de médias affichés » sans doublon, même si les plateformes
   se recoupent. « Tous les médias » prend les 20 premiers de chaque plateforme.

Limites : JustWatch classe selon l'activité de ses utilisateurs dans le pays.
Son API GraphQL publique est gratuite, sans compte ni clé, mais non officielle
(l'API officielle est réservée aux partenaires) : elle peut changer ou être
bloquée, d'où le repli TMDb, dont la popularité est mondiale. Les résultats
JustWatch sont mis en cache six heures (packages : 24 heures). FlixPatrol
(API payante) n'est pas utilisé. Les services gratuits avec
publicité (sans abonnement) ne sont pas inclus.

La langue originale facultative est appliquée dès la collecte, y compris au Top
10 Netflix.

## Publication et erreurs

La limite configurée s’applique à la liste classée ; zéro conserve toute la
sélection. Une seule édition locale est publiée par identité, comme dans le
synchroniseur fourni. Le rapprochement utilise l’identifiant TMDb, puis un titre
normalisé et une année compatibles, sans accepter un identifiant contradictoire.
Les demandes Arr suivent les routes VODUM et conservent leur mémoire persistante.

Une plateforme TMDb en erreur empêche la nouvelle publication et conserve
l’existante. Si la page Netflix Top 10 est illisible ou qu’un titre n’est pas
rapproché, le classement TMDb de Netflix est utilisé et un avertissement est
affiché.
Les données et fiches sont mises en cache six heures, le catalogue des services
24 heures, avec des clés distinctes selon le pays et le type de média.

## Validation du 27 octobre 2026 (ancienne méthode films, remplacée le 26 novembre 2026)

- Tests comparatifs exécutant le véritable collecteur et la fusion de référence
  avec les mêmes réponses : identités, popularités et ordre identiques en FR,
  DE, IN et US.
- Rejeu des fichiers utilisateur `top_hit_Movies/data/*_fr.json` et de la sortie
  `top_hits_movies_fr.json` : les mêmes 52 films dans le même ordre.
- Collecte réelle France avec tous les services : 94 services interrogés,
  599 titres distincts, environ 74 secondes sans cache. Il s’agit d’une validation
  de collecte ; la publication sur l’instance nécessite le déploiement du code.

Références TMDb :
- [Services par pays](https://developer.themoviedb.org/reference/watch-providers-movie-list)
- [Disponibilité et popularité Discover](https://developer.themoviedb.org/reference/discover-movie)
