# Top streaming par pays

Le moteur par pays utilise `collections_country_availability.py`. Il généralise
la méthode de `top_hit_Movies/collector_tmdb_availability.py` et la fusion de
`top_hit_Movies/merge_top_hits_fr.py`. Le moteur Worldwide reste distinct.

## Collecte et classement

1. Charger les services TMDb disponibles pour le pays configuré (`watch_region`),
   séparément pour les films et les séries.
2. Pour chaque service, prendre les dix premiers titres en abonnement
   (`flatrate`), triés par popularité TMDb, comme dans le collecteur fourni.
3. Fusionner les identifiants TMDb sans doublons en gardant les sources et leurs
   rangs pour les diagnostics.
4. Enrichir chaque identité avec sa fiche TMDb, notamment la popularité actuelle.
5. Trier l’union par popularité TMDb décroissante, puis titre normalisé.

Le nombre de plateformes sur lesquelles un film apparaît ne change pas ce tri.
Aucun score de votes par fournisseur et aucune substitution JustWatch/FlixPatrol
ne sont utilisés pour ce modèle. Le pays est celui de la disponibilité, pas le
pays de production. Les nouveautés ne sont pas exclues par un seuil d’ancienneté.
La langue originale facultative est appliquée dès la collecte, avant le top 10.

Tous les services disponibles sont inclus, conformément au choix utilisateur.
Le script de référence n’en collecte que six : à données et services identiques,
les sélections sont équivalentes ; élargir les services élargit le résultat.
Les services uniquement location/achat ne fournissent pas de titres à la requête
`flatrate` et leurs listes vides sont acceptées.

## Publication et erreurs

La limite configurée s’applique à la liste classée ; zéro conserve toute la
sélection. Une seule édition locale est publiée par identité, comme dans le
synchroniseur fourni. Le rapprochement utilise l’identifiant TMDb, puis un titre
normalisé et une année compatibles, sans accepter un identifiant contradictoire.
Les demandes Arr suivent les routes VODUM et conservent leur mémoire persistante.

Une source en erreur ou une identité invérifiable empêche la nouvelle publication
et conserve l’existante. Il n’y a pas de classement de remplacement silencieux.
Les données et fiches sont mises en cache six heures, le catalogue des services
24 heures, avec des clés distinctes selon le pays et le type de média.

## Validation du 27 octobre 2026

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
