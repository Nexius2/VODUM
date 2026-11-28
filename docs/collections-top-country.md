# Top Country Media

Le modèle `streaming_country` s’affiche désormais **Top Streaming by Country**. Son identifiant, ses configurations existantes et sa sélection par marché de streaming restent compatibles.

**Top Country Media** est une nouvelle bulle disponible dans **More ways to discover**. Son moteur `top_country` crée des collections de films et/ou de séries originaires du pays choisi.

## Classement et origine

La source est TMDb Discover : [films](https://developer.themoviedb.org/reference/discover-movie) et [séries](https://developer.themoviedb.org/reference/discover-tv). Les requêtes utilisent `with_origin_country`, sans filtre de marché ou de disponibilité en streaming. Deux classements sont proposés : mieux notés (`vote_average.desc`) et plus populaires (`popularity.desc`). Le minimum de votes est réglable, avec 100 par défaut, et s’applique aux deux classements.

Avant toute correspondance locale ou acquisition Arr, le moteur vérifie également la fiche TMDb du titre : `production_countries` pour les films et `origin_country` pour les séries. Le pays choisi doit être présent. Les coproductions associées à ce pays sont donc incluses ; un film simplement disponible au Japon, ou doublé en japonais, ne devient pas un film japonais. Une origine inconnue est exclue avec un diagnostic, et le titre n’est pas envoyé à Arr.

Les œuvres adultes et les titres non encore sortis sont exclus. La pagination déduplique les identifiants et collecte jusqu’à 250 titres vérifiés par classement. La limite configurée permet un classement plus court. Les résultats de découverte sont en cache six heures et les pays vérifiés trente jours.

## Paramètres et publication

Le modèle propose les réglages communs : présentation localisée, pays d’origine, langue originale facultative, langue audio locale obligatoire facultative, limite, classement/date d’ajout/aléatoire, priorité, fréquence, activation et destinations d’accueil indépendantes. Une paire films/séries utilise des collections séparées et peut choisir Radarr/Sonarr séparément.

Les titres présents sont publiés via le moteur partagé. Les titres vérifiés absents peuvent être demandés à Arr. Comme pour les autres modèles, une contrainte audio locale ne peut pas être garantie avant acquisition : les titres absents ne sont pas acquis dans ce mode. Les erreurs Arr restent des avertissements avec les détails dans les logs et n’invalident pas une publication réussie.

Un aperçu ne modifie pas Plex/Jellyfin et ne soumet aucune acquisition. Une source indisponible conserve la publication existante. Lors d’un changement de pays ou de classement, un résultat partiel ne fusionne pas les anciens membres avec la nouvelle sélection. L’édition conserve l’accès aux bibliothèques déjà attachées, y compris hors ligne ; les nouvelles cibles suivent la restriction habituelle aux serveurs en ligne.

## Déploiement

Le moteur et le formulaire sont livrés dans le code. Aucune modification de l’instance distante n’est nécessaire avant le déploiement Docker. Aucun nouveau secret ni nouvelle migration de base n’est requis : le modèle utilise la clé TMDb et les routes Arr existantes. Les classements sont ensuite accessibles depuis la nouvelle bulle.
