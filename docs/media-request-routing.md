# Configuration du routage des demandes medias

Depuis Servers & libraries > fiche Sonarr/Radarr, la section Routage des demandes
medias liste les bibliotheques compatibles deja synchronisees dans VODUM. Toutes les
bibliotheques compatibles sont presentes, meme si la liste classique est paginee.

Cocher les bibliotheques a associer a cet ARR. La case unique lie et active
l'instance ; la decocher retire le lien. Un tableau montre tous les ARR lies a
chaque bibliotheque. Les fleches monter/descendre changent leur ordre ; le rang 1
est prioritaire. Le bouton Save du titre sauvegarde la fiche et l'ordre de toutes
les bibliotheques en une transaction, sans saisir de nombres ni collision.
Les criteres et activations des autres instances sont conserves. Une modification
concurrente de la liste oblige a recharger la page avant de sauvegarder.
Films : Radarr ; series : Sonarr. L'etat de connexion ne supprime pas les liens.

Pour chaque bibliotheque, les demandes peuvent etre activees ou desactivees,
la bibliotheque marquee comme preferee et une priorite de bibliotheque definie.
Plusieurs preferences peuvent coexister ; le resolver doit d'abord filtrer
les acces reels du user, puis departager par priorite et ID. Aucune preference
ne donne de droit d'acces a un utilisateur.

Sans association, la destination automatique affichee est le premier ARR compatible
par ID croissant, quelle que soit sa disponibilite actuelle. Des associations
presentes mais toutes desactivees ne doivent pas declencher ce fallback dans le
resolver. Desactiver les demandes exclura la bibliotheque de la resolution.

## Portail : recherche et demande

L'onglet Demandes de medias recherche films et series via les API lookup des
instances Radarr/Sonarr accessibles a travers les bibliotheques de l'utilisateur.
Aucune cle TMDB supplementaire n'est requise. Les resultats sont dedupliques par
TMDB ID (films) ou TVDB ID (series), jamais seulement par titre.

Le choix propose uniquement les bibliotheques reellement partagees avec cet
utilisateur. La bibliotheque preferee puis sa priorite et son ID determinent
l'ordre de resolution. VODUM choisit automatiquement la premiere bibliotheque
avec un ARR satisfaisant les criteres medias ; le user choisit seulement le media.
Une selection signee expire apres une heure ; les acces sont reverifies au POST.

Avant tout ajout :
1. Verification des bibliotheques Plex/Jellyfin accessibles du meme type avec
   les identifiants fournisseurs. Un media present est signale comme disponible.
2. Verification de tous les ARR associes actifs de la bibliotheques accessibles candidates,
   meme ceux qui ne correspondent pas aux criteres. S'il y est deja present,
   le portail indique que la recherche est deja en cours.
3. Sinon, filtrage par genres et collection, puis ajout dans le
   premier ARR correspondant selon la preference/priorite de bibliotheque puis la priorite ARR, avec recherche automatique.

Une verification en echec bloque l'ajout : elle ne prouve pas l'absence du media.
Pas de failover apres un POST incertain. Une reservation temporaire en SQLite
protege contre les soumissions concurrentes, y compris entre processus ; les
requetes suivantes reverifient Plex et les ARR. Limites par utilisateur/IP et CSRF.
Les cles API, chemins et donnees de connexion ne sont jamais envoyes au portail.

Dans la fiche admin ARR, choisir le profil qualite et la destination par defaut
parmi les valeurs existantes de l'instance. Si un seul profil ou dossier existe,
il peut etre choisi automatiquement. Plusieurs choix exigent une selection admin.
La destination requise par l'API ARR ne participe pas a la resolution d'une
bibliotheque et ne cree aucune correspondance de chemin dans VODUM.

Le suivi historique des demandes, les quotas fonctionnels et un failover avec
verification de reconciliation restent a realiser.

Tables : library_arr_routes (bibliotheque, ARR, priorite, enabled) et
library_request_settings (activation, priorite, preference). Les mutations sont
transactionnelles et bornees a la bibliotheque du serveur concerne. La suppression
d'une bibliotheque ou d'un ARR nettoie les relations par cles etrangeres.

Criteres medias par association : genres et collections separes par virgules.
Chaque dimension renseignee doit correspondre (AND), au moins une valeur de chaque
dimension suffit (OR). La comparaison ignore la casse. Une dimension vide ne
restreint pas les medias ; une metadonnee absente ne satisfait pas un critere.
Exemple : genres Animation, Family + collection Disney requiert un des deux genres
ET Disney. La qualite est geree par le profil ARR choisi dans la fiche admin.

Ces criteres sont stockes dans library_arr_conditions et la fonction
route_matches_media est utilisee par le resolver du portail. Les preferences et priorites de bibliotheque sont communes
aux ARR qui s'y rattachent ; les criteres et l'activation ARR concernent uniquement
l'association courante. Les autres associations sont conservees lors de l'edition.

Contrats API verifies : [Radarr](https://radarr.video/docs/api/),
[Sonarr](https://sonarr.tv/docs/api/) et [Plex](https://developer.plex.tv/pms/).

Les ARR sans profil qualite et dossier de destination enregistres sont exclus
des recherches, du controle de presence ARR et des ajouts du portail. Une notice
rouge est affichee dans la liste et leur fiche admin. Enregistrer la fiche resout
aussi les choix uniques en identifiants explicites.

Le resolver examine les associations explicites avant les destinations de secours,
puis applique les preferences et priorites de bibliotheque dans chaque groupe.
A egalite, il privilegie les valeurs de demande enregistrees sur le premier ARR
correspondant aux criteres avant le departage par ID de bibliotheque. Les valeurs
sont ensuite verifiees aupres de cet ARR ; son rang ne change pas.
Une destination de secours reste eligible si aucun lien explicite accessible ne
correspond aux criteres du media. Le journal indique toutes les destinations
accessibles candidates et l'origine du choix, sans jetons ni chemins ARR.

Les profils qualite proposes a l'admin proviennent de /api/v3/qualityprofile
de l'instance ARR. Aucun choix qualite ou bibliotheque n'est expose au user.
Les anciennes contraintes de resolution sont ignorees pour le routage automatique ;
la qualite est definie par le profil ARR. Les affiches utilisent les URL publiques
TMDB/TVDB fournies par le lookup ; les URL internes ARR ne sont pas exposees.

La section Demandes de medias est independante de l'acces aux medias et apparait
apres l'accueil. Son activation admin exige au moins un ARR avec profil qualite
et destination enregistres. Les routes GET/POST controlent cette section.
Le monitoring du portail exploite l'audit existant pour compter les demandes,
les ajouts transmis a l'ARR, les medias deja presents, les recherches deja en
cours et les echecs. Un tableau affiche les 100 dernieres demandes de la periode,
avec utilisateur et titre. Les anciens evenements sans resultat detaille restent
dans le total sans inventer de statut d'ajout. La disponibilite apres telechargement
n'est pas mesuree par ce compteur.

## Performances des demandes

Les recherches Radarr/Sonarr (films et series) sont lancees en parallele,
avec au maximum huit appels simultanes par operation. Les resultats conservent
l'ordre des instances configurees et la deduplication par identifiant fournisseur.
Apres resolution du media et de la destination, les controles de presence
Plex/Jellyfin et ARR sont executes en parallele. Les bibliotheques d'un meme
serveur media sont verifiees en serie pour eviter de multiplier les parcours
simultanes sur ce serveur. Les profils qualite et dossiers ARR sont aussi lus
en parallele. Les lectures SQLite et le POST d'ajout restent sur le thread appelant.
Le delai global de soumission est transmis aux appels des threads de lecture.
L'ajout attend les controles et conserve les regles de blocage en cas d'echec ;
aucun cache de presence ne remplace la verification avant ajout. Le parcours
d'une grande bibliotheque Plex peut donc encore etre le principal cout.
