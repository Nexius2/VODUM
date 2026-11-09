# Contrôle des validations de sources — 2026-11-05

Objectif : rechercher le rejet global d'une réponse valide, comme le type
`tvMovie` dans le classement IMDb populaire, et les erreurs de diagnostic.
Contrôles depuis le poste de développement, sans publication ni demande ARR.

## Vérifications en direct

| Source | Contrôle | Résultat |
| --- | --- | --- |
| Récompenses | Téléchargement des 8 datasets configurés et extraction de la dernière édition pour chaque type configuré | Tous acceptés : Oscars 1, BAFTA 1, Golden Globes 4 films/3 séries, Emmy 3, Cannes 1, César 1, Berlinale 2, Venise 1 |
| JustWatch France | Catalogue des fournisseurs | 132 fournisseurs acceptés |
| JustWatch Netflix France | Classements films et séries via GraphQL | 10 titres acceptés pour chacun |
| Netflix Tudum France | Pages officielles et lecteur de classement | 10 films et 10 séries acceptés, sans recours au repli JustWatch |
| MDBList saisonnier | Liste Christmas Extravaganza configurée, lecture JSON puis validation | 641 films acceptés |
| Letterboxd saisonnier | Téléchargement de la page configurée Black Is Beautiful | Page accessible ; résolution complète des identités non testée en direct |
| Listes IMDb saisonnières | Liste New Year configurée | HTTP 202, refusé correctement comme réponse incomplète ; ce n'est pas le rejet d'un type de titre |

Ces observations valent pour les sources, régions et listes citées à l'instant
du contrôle ; elles ne valident pas toutes les régions ni toutes les listes.

## Code et tests

Les lecteurs TMDB (classements, pays, pépites, plateformes, enfants),
les listes de franchises, les sources saisonnières, Memoria et Spotlight ont
été examinés, puis leurs suites locales exécutées. Les listes de franchises
acceptaient déjà `tvMovie` pour les films ; les validations TMDB ne distinguent
pas films de cinéma et téléfilms par ce type IMDb. Les types restent contrôlés
pour ne pas confondre films, séries et épisodes. Aucune raison établie de
supprimer les contrôles d'intégrité, d'identité ou de complétude.

Défaut corrigé dans les récompenses : après lecture réussie du dataset,
l'échec de toutes les résolutions TMDB était annoncé comme source indisponible.
Il devient `streaming_incomplete`. Des lauréats appartenant uniquement à
l'autre type de média donnent `streaming_empty`. Un dataset invalide conserve
son erreur et le diagnostic indique maintenant l'étape dataset en échec.
La publication existante est préservée dans ces cas.

## Limites

Pas de clé TMDB dans l'environnement du processus : API TMDB authentifiée,
résolution des identités et disponibilité par plateforme vérifiées par tests
locaux uniquement. Aucun serveur Plex/Jellyfin ni ARR sollicité. Aucun résultat
présenté comme validé en production.

Références de contrat : [TMDB Find](https://developer.themoviedb.org/reference/find-by-id)
et [TMDB Trending Movies](https://developer.themoviedb.org/reference/trending-movies).
