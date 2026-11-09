# Dernières sorties par pays

`recent_releases` sélectionne uniquement des médias déjà présents dans la
bibliothèque Plex ou Jellyfin. Une configuration peut réunir une bibliothèque
films et une bibliothèque séries. Il n'existe ni collecte de titres absents,
ni acquisition Radarr/Sonarr pour ce modèle ; le serveur refuse également les
configurations Arr soumises directement à l'API.

Le pays sélectionne les **langues d'origine**, sans imposer le pays de
production. Une sélection France inclut donc les films et séries francophones
de Belgique, Suisse, Canada et de tout autre pays. Une piste audio doublée en
français ne suffit pas à rendre un titre éligible.

| Pays sélectionné | Langues d'origine |
| --- | --- |
| France | Français |
| États-Unis, Royaume-Uni | Anglais |
| Allemagne | Allemand |
| Espagne | Espagnol, catalan, basque, galicien |
| Italie | Italien |
| Canada | Anglais, français |
| Belgique | Français, néerlandais, allemand |
| Suisse | Allemand, français, italien, romanche |

Tous les titres correspondants sont éligibles par défaut, sans fenêtre de
sortie ni seuil d'ancienneté. Ils sont triés par date de sortie décroissante,
avec l'année comme secours si la date complète manque. Une limite d'affichage
facultative reste disponible dans le formulaire. Le nom est traduit et suit
le pays, par exemple **Dernières sorties France 🇫🇷**.

## Métadonnées

L'inventaire local actuel ne contient pas la langue d'origine. Le moteur la
résout via `original_language` de TMDb, à partir d'un identifiant TMDb ou d'un
identifiant IMDb/TVDb stable. Il ne rapproche pas les titres par leur seul nom,
leur langue audio, leur titre traduit ou leur pays de production.

Les langues sont mises en cache pendant 30 jours, indépendamment de la langue
d'affichage et du pays sélectionné. La clé TMDb commune aux collections est
utilisée pour cet enrichissement uniquement. La première vérification d'une
grande bibliothèque peut donc demander davantage de temps ; les métadonnées
déjà résolues restent en cache entre les exécutions.

## Erreurs et cycle de vie

Une langue ou identité non vérifiable est signalée dans les logs VODUM au
niveau ERROR. Seul le titre concerné est ignoré ; les autres continuent d'être
traités. La sélection devient partielle et les anciens membres sont conservés.
Une sélection complète et réellement vide suit le réglage commun de suppression
des collections vides.

Les aperçus ne publient rien. Désactivation et suppression retirent uniquement
la collection appartenant à VODUM. Aucun média n'est supprimé. Le nettoyage
n'interroge pas TMDb. Les arrêts et les délais du worker restent applicables.


## Bounded original-language analysis

A cold library previously required one remote lookup per title, potentially exceeding the 15-minute worker deadline. Language lookups now use a 120-second / 150-request budget per run, checking successful cached languages before fetching new details. Eligible titles are checked in release-date order; a configured limit stops scanning once enough verified titles are found. Unlimited collections may require several runs to warm the cache. Deferred titles are reported separately from lookup failures, partial runs preserve existing members, and an entirely deferred selection does not publish or empty the collection. The next manual or scheduled run continues from successful cached results.
