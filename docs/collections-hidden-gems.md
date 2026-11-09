# Les pépites oubliées

Le modèle `hidden_gems` est disponible dans **More ways to discover**. Il sélectionne
des films et séries très bien notés, mais peu populaires, puis utilise les mêmes
moteurs de publication Plex/Jellyfin et d'acquisition facultative Radarr/Sonarr
que les autres modèles. Une configuration peut réunir une bibliothèque films et
une bibliothèque séries, avec une route Arr indépendante pour chacune.

## Critères modifiables

- Note TMDb minimale : **7,5/10** par défaut.
- Nombre minimum de votes TMDb : **200** par défaut.
- Popularité TMDb maximale : **10** par défaut (indice, pas un pourcentage).
- Nombre de médias : **30** par défaut, modifiable ; « Tous » utilise le pool disponible.

Les trois critères doivent être remplis. Les titres adultes, non sortis, sans date
valide ou sans métriques complètes sont exclus avant toute publication/acquisition.
La source utilise les notes et votes **TMDb**, sans présenter ces valeurs comme des
notes IMDb. La [popularité TMDb](https://developer.themoviedb.org/docs/popularity-and-trending)
est un indice évolutif : une œuvre célèbre peut devenir peu populaire actuellement.

La source [Discover](https://developer.themoviedb.org/reference/discover-movie)
classe les candidats par note décroissante. Le plafond de popularité est vérifié
localement sur chaque résultat. La recherche est bornée à 50 pages, et conserve
jusqu'à 250 titres admissibles par type. Les réponses sont en cache six heures.
La limite de publication est remplie avec les titres locaux admissibles ; les
acquisitions ne concernent que les premiers titres du classement dans la limite
choisie. Une limite à zéro exploite l'ensemble du pool, comme les autres classements.

## Réglages communs

Le formulaire conserve les langues de présentation, les bibliothèques, le nombre de
médias, le tri (classement, date d'ajout, aléatoire), la priorité, la fréquence,
l'activation, les trois destinations de visibilité et les modes publié, privé ou
Arr uniquement. Les capacités et avertissements habituels de chaque fournisseur
s'appliquent : Jellyfin ne propose pas les mêmes contrôles d'accueil que Plex.

L'aperçu ne modifie pas les collections et ne lance aucun téléchargement. Une panne
de découverte conserve les publications existantes. Le moteur utilise la clé TMDb
partagée et les routes Arr existantes ; aucune migration ni nouveau secret requis.
La mise à disposition dans l'application nécessite le déploiement du code Vodum.

## Affiche

L’affiche portrait `hidden-gems-v1.png` (1024 × 1536) est embarquée et utilisée
pour les collections films et séries, sur Plex et Jellyfin. Elle est également
résolue pour les commandes de présentation et les reprises de publication.
