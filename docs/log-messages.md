# Comprendre les journaux VODUM

La page Logs affiche d'abord une explication pour les avertissements et erreurs :

- le traitement concerné ;
- les noms disponibles (collection, bibliothèque, serveur) ou identifiants ;
- la cause connue et une action conseillée ;
- les détails techniques dépliables pour une investigation complémentaire.

Les explications sont disponibles en français et anglais. Les autres langues
utilisent actuellement l'anglais pour ces nouvelles explications. Les messages
métiers existants conservent leurs traductions.

## Causes et actions

| Signal | Signification | Vérification utile |
| --- | --- | --- |
| Délai dépassé | Pas de réponse dans le temps imparti ; ne prouve pas que le serveur est hors ligne | Accessibilité et charge du serveur ; résultat distant avant de rejouer une modification |
| Connexion interrompue | Transport réseau en échec | Adresse, service et réseau |
| Certificat refusé | Connexion TLS impossible | Adresse et certificat configurés |
| Accès refusé (401/403 explicite) | Authentification ou droits refusés | Clé API et autorisations |
| Ajout ARR non confirmé | Le POST a pu aboutir sans que VODUM reçoive sa réponse | Présence du média dans ARR avant toute nouvelle demande |
| Aucune relance, compteur 0 | Pas de nouvelle tentative effectuée | Dernier résultat et configuration de la tâche ; ne pas interpréter 0/3 comme trois échecs |
| Cause inconnue | L'entrée ne précise pas la cause | Détails techniques et contexte ; aucune cause supposée |

Les familles couvertes sont les collections (dont présentation et inventaire),
ARR, tâches, sauvegardes, communications, suivi, accès et serveurs. Les autres
avertissements et erreurs ont une présentation générique avec cause inconnue.
Les événements INFO/DEBUG gardent leur texte habituel. Il ne s'agit pas d'un
regroupement d'incidents : plusieurs lignes peuvent concerner le même passage.

## Exemple du 5 novembre 2026, 18 h 11

L'ancien message `collections.visibility.object`, `ReadTimeout` indique une
présentation de collection dont l’application n’est pas confirmée : l'appel n'a pas
répondu à temps. Cette ancienne entrée ne précise ni le nom de la collection
ni le serveur ; l'interface signale donc ce manque. Il faut vérifier le résultat
sur le serveur et l'état Configuration de la collection. On ne peut pas conclure
que les médias ont disparu ou que le serveur est hors ligne.

Les nouveaux diagnostics de présentation et de traitement de collection
conservent les noms et identifiants autorisés, sans recopier les réponses brutes
ni les messages d'exception susceptibles de contenir des secrets.

## Conservation

Les fichiers historiques, niveaux de log, compteurs, filtres et export anonymisé
restent inchangés. L'explication est calculée à l'affichage pour les lignes de
la page ; elle ne prouve pas qu'une ancienne erreur est toujours active.
La recherche continue de porter sur les textes techniques enregistrés.
