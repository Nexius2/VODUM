# Connexions Sonarr et Radarr

Dans Servers & libraries, saisir l'URL de base et la
cle API (Settings > General dans le service). VODUM detecte automatiquement
Plex, Jellyfin, Sonarr ou Radarr via leur API. Plusieurs instances de chaque type
sont possibles. Un sous-chemin de reverse proxy reste dans l'URL de base, par
exemple `https://media.example/sonarr` ; ne pas ajouter `/api/v3`.

Les cles reutilisent le stockage chiffre de VODUM. Une valeur vide lors de
l'edition conserve la cle existante. La verification periodique `check_servers`
utilise `GET /api/v3/system/status` avec le header `X-Api-Key` et verifie
l'application attendue. Une mauvaise cle, une redirection, un JSON invalide ou
une connexion en echec ne sont pas affiches comme une connexion disponible.

La creation verifie la connexion avant enregistrement et refuse une instance
inaccessible. Le dashboard presente tous les serveurs dans la meme liste,
dans une carte dont toute la surface ouvre Servers & libraries. Les fiches
individuelles restent accessibles depuis cette page.

Monitoring > Servers conserve les statistiques de lecture pour Plex/Jellyfin et
ajoute des analyses Sonarr/Radarr conditionnelles : disponibilite API, latence,
file de telechargement et nombre d'alertes de sante. Les courbes de disponibilite
et de file sont calculees par jour et instance, selon la periode choisie. Les
mesures sont collectees par `check_servers`, stockees dans `arr_monitoring_samples`
et conservees 366 jours. Les valeurs manquantes sont inconnues, pas zero.
L'historique commence au deploiement ; aucun appel ARR ne se fait au rendu.

Supprimer une connexion retire sa configuration VODUM ; aucun film, serie ou
reglage n'est supprime dans Sonarr/Radarr. Les demandes du portail, profils qualite,
dossiers racine, quotas et droits par instance restent a implementer dans le lot
suivant. Aucun acces direct ni cle API n'est donne au portail.

References API officielles :
- https://sonarr.tv/docs/api/
- https://radarr.video/docs/api/
