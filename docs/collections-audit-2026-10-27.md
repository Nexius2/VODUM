# Contrôle des collections — 27 octobre 2026

Mise à jour : le modèle par pays a depuis été remplacé par la méthode du moteur
`top_hit_Movies`, généralisée au pays configuré. Voir
[Top streaming par pays](collections-streaming-country.md). Les constats ci-dessous
décrivent le comportement antérieur observé sur l’instance.


## Constats sur l’instance

- Worldwide : les six classements FlixPatrol renvoient HTTP 403. Le passage films ne récupère que huit tendances TMDb ayant une offre d’abonnement. Ce nombre vient de la collecte, avant le rapprochement avec Plex.
- France : les classements directs sont principalement remplacés par les listes de popularité JustWatch. Tous les services nationaux sont conservés à la demande de l’utilisateur. Les scripts fournis ont un autre périmètre : six plateformes, disponibilité régionale et popularité TMDb ; leurs résultats ne sont donc pas censés être identiques.
- Le pipeline France n’exclut pas les nouveautés par date. Le bonus de popularité TMDb du mélange est borné ; les identités JustWatch reçoivent zéro bonus. Il ne s’agit pas d’un filtre de nouveautés.
- Le titre d’une recommandation Plex est distinct de celui de la collection. Renommer la collection ne suffit pas à corriger un ancien titre de recommandation.

## Corrections

- Memoria : les nouvelles premières détections remplacent les plus anciennes à la limite configurée. La popularité départage les détections simultanées. Une nouvelle personnalité sans média local ne déloge pas un hommage publié. Le même ordre est utilisé par le moteur et la liste des personnalités.
- Publication Plex commune : une recommandation VODUM au titre périmé est recréée et retrouve les destinations et la priorité configurées. La collection et ses médias ne sont pas supprimés.
- Worldwide : recherche bornée à cinq pages de tendances pour obtenir jusqu’à vingt titres disponibles en streaming, plutôt que filtrer uniquement les vingt premiers titres. Les erreurs des pages suivantes préservent les résultats vérifiés.
- France : les variantes d’abonnement Netflix et Paramount ne multiplient plus leurs votes. Les autres services et chaînes restent présents.
- France et Worldwide : couverture affichée hors des détails, distinguant classements directs, popularité et sources indisponibles. Une sélection uniquement de repli est explicitement signalée. Les classements IMDb/TMDb, récompenses, collections locales et saisonnières ne sont pas remplacés par ce classement.

## Limites

Ces modifications sont locales. Les refus HTTP 403 des fournisseurs restent extérieurs à ces corrections. Aucun classement manquant n’est inventé. Une synchronisation après déploiement est nécessaire pour vérifier les recommandations Plex et la nouvelle collecte dans l’environnement de production.
